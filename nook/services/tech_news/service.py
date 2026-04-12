import inspect
import os
import re
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

from nook.services.collector_storage import CollectorStorage
from nook.services.config import load_service_toml
from nook.services.llm_client import create_client
from nook.services.storage import build_storage_backend

_MARKDOWN_FORMAT = """
# {title}

[View on {feed_name}]({url})

{summary}
"""


class FeedConfig(BaseModel):
    name: str
    url: str
    feed_name_display: str
    keywords: list[str] | None = None


class Config:
    max_entries_per_feed = 10
    summary_index_s3_key_format = "tech_news/{date}.md"
    threshold_days = 1
    max_chars = 25000

    @classmethod
    def load_feeds(cls) -> list[FeedConfig]:
        feed_data = load_service_toml("tech_news", "feed.toml")
        feeds = [FeedConfig.model_validate(feed) for feed in feed_data.get("feeds", [])]
        if not feeds:
            raise ValueError(
                "configs/tech_news/feed.toml must define at least one feed"
            )
        return feeds


@dataclass
class Article:
    feed_name: str
    title: str
    url: str
    text: str
    soup: BeautifulSoup
    category: str | None = field(default=None)
    summary: str = field(init=False)


class TechNews:
    def __init__(self) -> None:
        self._client = create_client()
        self._storage = CollectorStorage(
            service_name="tech_news",
            backend=build_storage_backend(os.environ),
        )
        self._threshold = datetime.now() - timedelta(days=Config.threshold_days)
        self._feeds = Config.load_feeds()

    def __call__(self) -> None:
        markdowns = []
        processed_urls = set()
        for feed_config in self._feeds:
            print(f"Processing feed: {feed_config.name} ({feed_config.url})")
            feed_parser: feedparser.FeedParserDict = feedparser.parse(
                feed_config.url,
            )
            entries = self._filter_entries(feed_parser, feed_config.keywords)

            # feedparserで取得できなかった場合、手動パースにフォールバック
            if len(entries) == 0 and len(feed_parser.entries) == 0:
                print(
                    f"Feedparser returned no entries for {feed_config.name}, trying manual parsing..."
                )
                entries = self._manual_parse_feed(feed_config.url, feed_config.keywords)
                if len(entries) > 0:
                    print(
                        f"Manual parsing found {len(entries)} entries for {feed_config.name}"
                    )

            if len(entries) > Config.max_entries_per_feed:
                print(
                    f"Limiting entries for {feed_config.name} from {len(entries)} to {Config.max_entries_per_feed}",
                )
                entries = entries[: Config.max_entries_per_feed]

            print(f"Found {len(entries)} relevant entries for {feed_config.name}.")
            for entry in entries:
                try:
                    url = entry.get("link", "").split("?")[0]
                    if url in processed_urls:
                        print(f"Skipping already processed article: {url}")
                        continue

                    article = self._retrieve_article(
                        entry,
                        feed_name=feed_config.feed_name_display,
                    )
                    if not article:
                        continue

                    processed_urls.add(article.url)

                    article.summary = self._summarize_article(article)
                    markdowns.append(self._stylize_article(article))
                    time.sleep(2)
                except Exception as e:
                    print(f"Error processing entry {entry.get('link', 'N/A')}: {e}")
                    traceback.print_exc()

        self._store_summaries(markdowns)

    def _filter_entries(
        self,
        feed_parser: feedparser.FeedParserDict,
        keywords: list[str] | None,
    ) -> list[dict[str, Any]]:
        filtered_entries = []
        keywords_pattern = self._compile_keywords_pattern(keywords)
        for entry in feed_parser["entries"]:
            date_ = entry.get("date_parsed") or entry.get("published_parsed")
            if not date_:
                print(f"Skipping entry due to missing date: {entry.get('link', 'N/A')}")
                continue
            try:
                published_dt = datetime.fromtimestamp(time.mktime(date_))
            except Exception:
                print(f"Error converting date for entry: {entry.get('link', 'N/A')}")
                traceback.print_exc()
                continue

            if published_dt <= self._threshold:
                continue

            if keywords_pattern:
                if not keywords_pattern.search(self._search_text(entry)):
                    continue
                print(f"Keyword match found for: {entry.get('title', '')}")

            filtered_entries.append(entry)

        return filtered_entries

    def _manual_parse_feed(
        self, url: str, keywords: list[str] | None
    ) -> list[dict[str, Any]]:
        """feedparserが失敗した場合の手動パース"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; NewsCrawler/1.0)",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            # BeautifulSoupでXMLパース
            soup = BeautifulSoup(response.text, "xml")
            items = soup.find_all("item")

            print(f"Manual parsing found {len(items)} raw items")

            filtered_entries = []
            keywords_pattern = self._compile_keywords_pattern(keywords)

            for item in items:
                # feedparser互換のエントリー構造を作成
                entry = {}

                # 基本フィールド
                title_elem = item.find("title")
                entry["title"] = title_elem.text if title_elem else ""

                link_elem = item.find("link")
                entry["link"] = link_elem.text if link_elem else ""

                # 日付処理
                pubDate_elem = item.find("pubDate")
                if pubDate_elem and pubDate_elem.text:
                    entry["published"] = pubDate_elem.text
                    try:
                        published_dt = parsedate_to_datetime(pubDate_elem.text)
                        # 閾値チェック
                        if published_dt.replace(tzinfo=None) <= self._threshold.replace(
                            tzinfo=None
                        ):
                            continue
                    except Exception as e:
                        print(f"Date parse error: {e}")
                        continue
                else:
                    # 日付がない場合はスキップ
                    continue

                # コンテンツフィールド
                desc_elem = item.find("description")
                entry["summary_detail"] = {"value": desc_elem.text if desc_elem else ""}

                # content:encodedまたはcontent要素を探す
                content_elem = item.find("encoded") or item.find("content")
                if content_elem:
                    entry["content"] = [{"value": content_elem.text}]
                else:
                    entry["content"] = [{"value": entry["summary_detail"]["value"]}]

                # キーワードフィルタリング
                if keywords_pattern:
                    if not keywords_pattern.search(self._search_text(entry)):
                        continue
                    print(
                        f"Keyword match found in manual parse: {entry.get('title', '')[:50]}"
                    )

                filtered_entries.append(entry)

            return filtered_entries

        except requests.exceptions.RequestException as e:
            print(f"HTTP error in manual feed fetch for {url}: {e}")
            return []
        except Exception as e:
            print(f"Error in manual feed parse for {url}: {e}")
            traceback.print_exc()
            return []

    def _retrieve_article(
        self,
        entry: dict[str, Any],
        feed_name: str,
    ) -> Article | None:
        try:
            url = entry.get("link", "").split("?")[0]
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            response.encoding = response.apparent_encoding or "utf-8"

            soup = BeautifulSoup(response.text, "html.parser")

            body_content = soup.find("body")
            text = ""
            if body_content:
                # VietnamNews専用の処理を優先
                detail_content = soup.find("div", class_="detail__content")
                if detail_content:
                    # detail__content内の段落を取得
                    paragraphs = detail_content.find_all("p")
                    if paragraphs:
                        text = "\n".join(
                            [
                                p.get_text(strip=True)
                                for p in paragraphs
                                if p.get_text(strip=True)
                            ]
                        )

                # 通常の処理
                if not text:
                    article_tag = body_content.find("article")
                    if article_tag:
                        text = "\n".join(
                            [
                                p.get_text(separator="\n", strip=True)
                                for p in article_tag.find_all(
                                    ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"],
                                    recursive=True,
                                )
                            ],
                        )
                    else:
                        main_content = body_content.find(
                            [
                                "main",
                                {"role": "main"},
                                {"class": "content"},
                                {"id": "content"},
                            ],
                        )
                        if main_content:
                            text = "\n".join(
                                [
                                    p.get_text(separator="\n", strip=True)
                                    for p in main_content.find_all(
                                        ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"],
                                        recursive=True,
                                    )
                                ],
                            )
                        else:
                            text = "\n".join(
                                [
                                    p.get_text(separator="\n", strip=True)
                                    for p in body_content.find_all("p")
                                ],
                            )

            text = "\n".join(line for line in text.splitlines() if line.strip())

            if not text or text.isspace():
                # determine whether entry.content has content
                if (
                    len(rss_content := entry.get("summary_detail", {}).get("value", ""))
                    > 0
                ):
                    text = BeautifulSoup(rss_content, "html.parser").get_text()
                else:
                    print(f"Extracted empty content for: {url}")
                    return None

            return Article(
                feed_name=feed_name,
                title=entry.get("title", "Unknown Title"),
                url=url,
                text=text,
                soup=soup,
            )
        except requests.exceptions.RequestException as e:
            print(f"HTTP Error retrieving article {entry.get('link', 'N/A')}: {e}")
            return None
        except Exception as e:
            print(
                f"Error retrieving or parsing article {entry.get('link', 'N/A')}: {e}",
            )
            traceback.print_exc()
            return None

    def _store_summaries(self, summaries: list[str]) -> None:
        if not self._storage.write_daily_markdown(summaries):
            print("No summaries generated, skipping S3 storage.")
            return

        print(f"Stored {len(summaries)} tech news summaries.")

    @staticmethod
    def _compile_keywords_pattern(
        keywords: list[str] | None,
    ) -> re.Pattern[str] | None:
        if not keywords:
            return None
        escaped_keywords = [re.escape(keyword) for keyword in keywords]
        return re.compile("|".join(escaped_keywords), re.IGNORECASE)

    @staticmethod
    def _search_text(entry: dict[str, Any]) -> str:
        title = entry.get("title", "")
        summary = entry.get("summary_detail", {}).get("value", "")
        content = entry.get("content", [{}])[0].get("value", "")
        return f"{title} {summary} {content}".lower()

    def _stylize_article(self, article: Article) -> str:
        summary_text = (
            article.summary
            if isinstance(article.summary, str)
            else "Summary not available"
        )
        return _MARKDOWN_FORMAT.format(
            title=article.title,
            feed_name=article.feed_name,
            url=article.url,
            summary=summary_text,
        )

    def _summarize_article(self, article: Article) -> str:
        if not article.text or article.text.isspace():
            print(f"Skipping summarization for {article.url} due to empty content.")
            return "Content could not be retrieved or was empty."
        try:
            truncated_text = article.text[: Config.max_chars]
            if len(article.text) > Config.max_chars:
                print(
                    f"Truncating content for {article.url} from {len(article.text)} to {Config.max_chars} chars.",
                )

            print(
                f"Sending {len(truncated_text)} chars to LLM for summarization: {article.url}",
            )
            summary = self._client.generate_content(
                contents=self._contents_format.format(
                    title=article.title,
                    text=truncated_text,
                ),
                system_instruction=self._system_instruction,
            )
            print(f"Summarization successful for: {article.url}")
            return summary
        except Exception as e:
            print(f"Error during summarization for {article.url}: {e}")
            traceback.print_exc()
            return f"Error summarizing content: {e}"

    @property
    def _system_instruction(self) -> str:
        return inspect.cleandoc(
            """
            ユーザーから与えられた記事のタイトルと本文を注意深く読み、以下の指示に従って日本語で詳細な要約を作成してください。

            1.  **客観性:** 個人的な意見や解釈を避け、記事の内容に基づいて客観的に要約してください。
            2.  **網羅性:** 記事の主要なポイント、結論、重要な情報（例：企業名、技術名、資金調達額など）を可能な限り含めてください。
            3.  **構造:** 要約は自然な日本語の文章として、論理的な流れを持つように構成してください。
            4.  **簡潔さ:** 元の記事よりも大幅に短く、かつ重要な情報が失われないようにしてください。
            5.  **言語:** 要約は必ず日本語で記述してください。
            6.  **HTMLタグ:** 提供される本文にはHTMLタグの残骸や不要なテキストが含まれる場合がありますが、それらは無視し、意味のある情報のみを抽出して要約に使用してください。
            7.  **出力形式:** 要約文のみを出力し、それ以外のテキスト（例：「要約：」のような接頭辞）は含めないでください。
            """,
        )

    @property
    def _contents_format(self) -> str:
        return inspect.cleandoc(
            """
            # 記事タイトル
            {title}

            # 記事本文
            {text}

            **念押しですが、要約は必ず"日本語で"記述してください。**
            """,
        )
