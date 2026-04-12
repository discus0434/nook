import asyncio
import os
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta

from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

from nook.services.collector_storage import CollectorStorage
from nook.services.llm_client import create_client
from nook.services.runtime_secrets import require_runtime_secret
from nook.services.storage import build_storage_backend

_MARKDOWN_FORMAT = """
# {name}

**Votes**: {votes_count} | **Tagline**: {tagline}

{thumbnail}

[View Link]({website})

{description}
"""


class Config:
    product_hunt_api_url = "https://api.producthunt.com/v2/api/graphql"
    product_hunt_oauth_url = "https://api.producthunt.com/v2/oauth/token"  # OAuth URL
    summary_index_s3_key_format = "product_hunt/{date}.md"
    min_votes_threshold: int = 20
    llm_api_sleep_seconds: float = 2.0
    product_hunt_api_sleep_seconds: float = 0.5
    graphql_fetch_limit: int = 50
    summary_max_chars: int = 50
    summary_input_max_chars: int = 10000


@dataclass
class Product:
    """
    Product Hunt の製品を表すデータクラス。

    Attributes
    ----------
    id : str
        製品のID。
    name : str
        製品名。
    tagline : str
        製品のキャッチフレーズ。
    description : str | None
        製品の説明（LLM による要約）。
    website : str
        Product Hunt上の製品ページURL。
    votes_count : int
        投票数。
    thumbnail_url : str | None
        サムネイル画像のURL。
    """

    id: str
    name: str
    tagline: str
    description: str | None
    website: str
    votes_count: int
    thumbnail_url: str | None = None


class ProductHuntRetriever:
    """
    Product Hunt からデイリートップ製品を取得し、要約してS3に保存するクラス。
    """

    def __init__(self):
        """
        ProductHuntRetriever の初期化。
        """
        self._developer_token = require_runtime_secret("PRODUCT_HUNT_DEVELOPER_TOKEN")
        self._llm_client = create_client()
        self._storage = CollectorStorage(
            service_name="product_hunt",
            backend=build_storage_backend(os.environ),
        )

        headers = {
            "Authorization": f"Bearer {self._developer_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
            ),
        }
        self._gql_transport = AIOHTTPTransport(
            url=Config.product_hunt_api_url,
            headers=headers,
        )
        self._gql_client = Client(
            transport=self._gql_transport,
            fetch_schema_from_transport=False,
        )
        print("Initialized GQL client with Product Hunt Developer Token.")

    def __call__(self) -> None:
        """
        Product Hunt のトップ製品を取得し、処理してS3に保存するメイン処理。
        """
        try:
            # Run the async function synchronously
            asyncio.run(self._fetch_and_process_products())
        except Exception as e:
            print(f"An error occurred during async execution: {e}")
            traceback.print_exc()

    async def _fetch_and_process_products(self):  # Make this async
        """Internal async method to fetch and process products"""
        products_data = await self._get_daily_top_products()  # Use await
        if not products_data:
            print("No products found on Product Hunt today or error fetching.")
            return

        products: list[Product] = []
        # Correctly access the list of edges
        edges = products_data.get("posts", {}).get(
            "edges", []
        )  # Direct access after execute
        if not edges:
            print("No product edges found in the response.")
            return

        for post_edge in edges:
            node = post_edge.get("node")
            if not node:
                continue

            # 投票数が一定数以上のものだけフィルタリング
            if node.get("votesCount", 0) < Config.min_votes_threshold:
                continue

            print(
                f"Processing product: {node.get('name')} (Votes: {node.get('votesCount')})"
            )

            # LLM で説明文を生成
            # Use description if available, otherwise fallback to tagline
            content_to_summarize = node.get("description") or node.get("tagline")
            if not content_to_summarize:
                summary = "No description or tagline provided."
            else:
                # _summarize_product is synchronous and uses the shared LLM client.
                summary = self._summarize_product(
                    node.get("name", "No Name"), content_to_summarize
                )
                await asyncio.sleep(Config.llm_api_sleep_seconds)  # Use config value

            products.append(
                Product(
                    id=node.get("id"),
                    name=node.get("name", "N/A"),
                    tagline=node.get("tagline", "N/A"),
                    description=summary,  # 生成した要約
                    website=node.get("website", "#"),  # Use website URL if available
                    votes_count=node.get("votesCount", 0),
                    thumbnail_url=node.get("thumbnail", {}).get("url")
                    if node.get("thumbnail")
                    else None,
                )
            )
            await asyncio.sleep(
                Config.product_hunt_api_sleep_seconds
            )  # Use config value

        # 投票数で降順ソート
        products.sort(key=lambda p: p.votes_count, reverse=True)

        styled_products = [self._stylize_product(product) for product in products]
        self._store_summaries(styled_products)

    # Make this method async as it uses the async client
    async def _get_daily_top_products(self) -> dict | None:
        """
        Product Hunt API v2 (GraphQL) を使用して今日のトップ製品を取得する。
        """
        # Use gql function to parse the query string
        # Reference Config.graphql_fetch_limit in the query string
        query_string = f"""
            query DailyPosts($postedBefore: DateTime, $postedAfter: DateTime) {{
              posts(order: VOTES, postedBefore: $postedBefore, postedAfter: $postedAfter, first: {Config.graphql_fetch_limit}) {{ # Use config value
                edges {{
                  node {{
                    id
                    name
                    tagline
                    description # Fetch description
                    website # Fetch website URL
                    url # Fetch PH URL
                    votesCount
                    thumbnail {{
                      url
                    }}
                  }}
                }}
                totalCount
              }}
            }}
        """
        query = gql(query_string)
        now_utc = datetime.utcnow()
        # Calculate start and end of the *previous* UTC day
        today_start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start_utc = today_start_utc - timedelta(days=1)
        yesterday_end_utc = today_start_utc - timedelta(
            microseconds=1
        )  # End of previous day

        variables = {
            "postedAfter": yesterday_start_utc.isoformat() + "Z",
            "postedBefore": yesterday_end_utc.isoformat() + "Z",
        }

        try:
            print(
                f"Fetching daily top products from Product Hunt API (since {yesterday_start_utc.isoformat()}Z)..."
            )
            # Use await to execute the async query, passing query as positional arg
            data = await self._gql_client.execute_async(
                query, variable_values=variables
            )
            print("Successfully fetched data from Product Hunt.")
            return data
        except Exception as e:  # Catch potential TransportQueryError or others
            print(f"Error fetching data from Product Hunt API: {e}")
            traceback.print_exc()
            return None

    def _summarize_product(self, name: str, text_to_summarize: str) -> str:
        """
        製品名と説明/タグラインから簡単な説明を生成する。
        """
        # Use Config values for prompt constraints
        prompt = f"""製品名「{name}」について、以下の情報を元にどのような製品か日本語で{Config.summary_max_chars}字程度で簡潔に説明してください。

情報:
```
{text_to_summarize[: Config.summary_input_max_chars]}
```
"""  # Limit input length using config
        try:
            return self._llm_client.generate_content(
                contents=prompt,
                # Update system instruction for clarity
                system_instruction=f"あなたはProduct Huntのランキングに登録された製品の概要を簡潔に説明するアシスタントです。説明は{Config.summary_max_chars}字程度に収めてください。",
            )
        except Exception as e:
            print(f"Error during summarization for '{name}': {e}")
            return f"Error summarizing product: {e}"

    def _stylize_product(self, product: Product) -> str:
        """
        Product オブジェクトを Markdown 形式の文字列に整形する。
        """
        # description が None の場合のフォールバック
        desc = (
            product.description if product.description else "No description available."
        )

        # Use PH url (node.url) if website is not present or prefer PH link
        link = product.website  # Default to website
        # Assuming node.url was fetched in GraphQL if needed
        # if not link or link == '#':
        #     link = product.ph_url if hasattr(product, 'ph_url') else '#'

        # Add class="product-thumbnail" to the img tag
        thumbnail_md = (
            f'<img src="{product.thumbnail_url}" alt="{product.name} Thumbnail" class="product-thumbnail">'
            if product.thumbnail_url
            else ""
        )

        return _MARKDOWN_FORMAT.format(
            name=product.name,
            votes_count=product.votes_count,
            tagline=product.tagline,
            website=link,
            description=desc,
            thumbnail=thumbnail_md,
        )

    def _store_summaries(self, summaries: list[str]) -> None:
        """
        要約リストを結合し、Markdown ファイルとして S3 に保存する。
        """
        if not self._storage.write_daily_markdown(summaries, separator="\n---\n"):
            print("No product summaries to store.")
            return
        print("Successfully stored Product Hunt summaries.")
