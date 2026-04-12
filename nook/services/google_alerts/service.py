import inspect
import os
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from nook.services.collector_storage import CollectorStorage
from nook.services.config import load_service_toml
from nook.services.llm_client import create_client
from nook.services.storage import build_storage_backend

_MARKDOWN_FORMAT = """
# {title}

[View Original Alert Result]({url}) (Alert: {alert_name})

{summary}
"""


class Config:
    google_alerts_max_entries_per_day = 20  # Limit entries per alert per day
    summary_index_s3_key_format = "google_alerts/{date}.md"
    threshold_days = 1

    @classmethod
    def load_alerts(cls) -> list[dict[str, str]]:
        """Load alert names and feed URLs from google_alerts.toml file."""
        alert_data = load_service_toml("google_alerts", "google_alerts.toml")
        return alert_data.get("alerts", [])


@dataclass
class Article:
    alert_name: str  # Changed from feed_name
    title: str
    url: str
    text: str
    soup: BeautifulSoup
    category: str | None = field(default=None)
    summary: str = field(
        init=False,
    )  # Changed type to str, expecting single summary string


class GoogleAlerts:  # Changed class name
    def __init__(self) -> None:
        self._client = create_client()
        self._storage = CollectorStorage(
            service_name="google_alerts",
            backend=build_storage_backend(os.environ),
        )
        self._alerts = Config.load_alerts()  # Changed variable name and loading method
        self._threshold = datetime.now() - timedelta(days=Config.threshold_days)

    def __call__(self) -> None:
        all_markdowns = []
        for alert in self._alerts:
            alert_name = alert.get("name", "Unknown Alert")
            alert_url = alert.get("url")
            if not alert_url:
                print(f"Skipping alert '{alert_name}' due to missing URL.")
                continue

            print(f"Processing alert: {alert_name} ({alert_url})")
            try:
                feed_parser: feedparser.FeedParserDict = feedparser.parse(alert_url)
                if feed_parser.bozo:
                    print(
                        f"Warning: Feed for '{alert_name}' may be ill-formed. Bozo exception: {feed_parser.bozo_exception}",
                    )

                entries = self._filter_entries(feed_parser)
                if len(entries) > Config.google_alerts_max_entries_per_day:
                    print(
                        f"Limiting entries for '{alert_name}' from {len(entries)} to {Config.google_alerts_max_entries_per_day}",
                    )
                    entries = entries[: Config.google_alerts_max_entries_per_day]

                alert_markdowns = []
                for entry in entries:
                    redirect_url = entry.get("link")
                    if not redirect_url:
                        print(f"Skipping entry in '{alert_name}' due to missing link.")
                        continue

                    # Extract the actual article URL from the redirect URL's 'url' query parameter
                    try:
                        parsed_url = urlparse(redirect_url)
                        query_params = parse_qs(parsed_url.query)
                        article_url = query_params.get("url", [None])[0]
                        if not article_url:
                            print(
                                f"Could not extract actual URL from redirect link: {redirect_url}",
                            )
                            continue
                    except Exception as parse_e:
                        print(f"Error parsing redirect URL {redirect_url}: {parse_e}")
                        continue

                    # Sometimes the title might be missing or empty
                    title = entry.get("title", "No Title Provided")

                    try:
                        article = self._retrieve_article(
                            article_url,
                            alert_name=alert_name,
                            title=title,
                        )
                        article.summary = self._summarize_article(article)
                        alert_markdowns.append(self._stylize_article(article))
                    except Exception as e:
                        print(
                            f"Failed to process entry '{title}' ({article_url}) for alert '{alert_name}': {e}",
                        )
                    time.sleep(2)  # Keep delay between API calls

                all_markdowns.extend(alert_markdowns)

            except Exception as e:
                print(f"Error processing feed for alert '{alert_name}': {e}")
                traceback.print_exc()

        if all_markdowns:
            self._store_summaries(all_markdowns)
        else:
            print("No new alert entries found to store.")

    def _filter_entries(
        self,
        feed_parser: feedparser.FeedParserDict,
    ) -> list[dict[str, Any]]:
        filtered_entries = []
        for entry in feed_parser.get("entries", []):  # Use .get for safety
            # Google Alerts uses 'published_parsed' or sometimes 'updated_parsed'
            date_ = entry.get("published_parsed") or entry.get("updated_parsed")
            if not date_:
                link = entry.get("link", "N/A")
                print(f"date_ is None for entry. Link: {link}")
                # print(entry) # Avoid printing potentially large entry object unless debugging
                continue
            try:
                # Ensure date_ is a time.struct_time
                if isinstance(date_, time.struct_time):
                    published_dt = datetime.fromtimestamp(time.mktime(date_))
                else:
                    # Attempt to parse if it's a string (less common for parsed feeds)
                    # This part might need adjustment based on actual date string formats if encountered
                    print(
                        f"Unexpected date format for entry {entry.get('link', 'N/A')}: {date_}. Skipping.",
                    )
                    continue

            except Exception as e:
                print(
                    f"Error converting date for entry {entry.get('link', 'N/A')}: {e}",
                )
                traceback.print_exc()
                continue

            if published_dt > self._threshold:
                filtered_entries.append(entry)
            # else:
            #     print(f"Skipping old entry: {entry.get('title', 'N/A')} published on {published_dt}")

        # Sort by published date, newest first
        filtered_entries.sort(
            key=lambda x: x.get("published_parsed") or x.get("updated_parsed"),
            reverse=True,
        )
        return filtered_entries

    def _retrieve_article(
        self,
        url: str,
        alert_name: str,
        title: str,
    ) -> Article:  # Added url, title params
        try:
            # Use a timeout and handle potential redirects explicitly
            response = requests.get(url, timeout=15, allow_redirects=True)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

            # Check content type to avoid parsing non-HTML content
            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type:
                print(
                    f"Skipping non-HTML content at {response.url} (Content-Type: {content_type})",
                )
                # Return an Article with a note indicating content couldn't be parsed
                return Article(
                    alert_name=alert_name,
                    title=title,
                    url=response.url,  # Use the final URL after redirects
                    text="Content is not HTML.",
                    soup=BeautifulSoup("", "html.parser"),  # Empty soup
                )

            soup = BeautifulSoup(response.text, "html.parser")
            # Improved text extraction: focus on main content areas if possible,
            # otherwise fall back to paragraphs, etc. This is highly site-dependent.
            main_content = soup.find("article") or soup.find(
                "main",
            )  # Common tags for main content
            if main_content:
                text = "\n".join(
                    [
                        p.get_text(strip=True)
                        for p in main_content.find_all(
                            ["p", "li", "h1", "h2", "h3", "h4"],
                        )
                    ],
                )
            else:
                # Fallback to common text elements if specific main content tag not found
                text = "\n".join(
                    [
                        p.get_text(strip=True)
                        for p in soup.find_all(
                            [
                                "p",
                                "code",
                                "ul",
                                "ol",
                                "li",
                                "h1",
                                "h2",
                                "h3",
                                "h4",
                                "h5",
                                "h6",
                            ],
                        )
                    ],
                )

            # Handle cases where text extraction yields minimal or no meaningful content
            if not text or text.strip().isspace():
                print(f"Warning: Could not extract meaningful text from {response.url}")
                text = "Could not extract text content."

            return Article(
                alert_name=alert_name,  # Use alert_name
                title=title,  # Use provided title
                url=response.url,  # Use final URL after redirects
                text=text.strip(),
                soup=soup,  # Pass the soup object
            )
        except requests.exceptions.RequestException as e:
            print(f"Request failed for {url}: {e}")
            # Reraise as a generic exception or handle specifically
            raise Exception(f"Error retrieving article content from {url}: {e}") from e
        except Exception as e:
            print(f"Error parsing HTML for {url}: {e}")
            raise Exception(
                f"Error raised while retrieving/parsing article from {url}: {e}",
            ) from e

    def _store_summaries(self, summaries: list[str]) -> None:
        if not self._storage.write_daily_markdown(summaries, separator="\n---\n"):
            print("No summaries to store.")
            return

        print(f"Successfully stored {len(summaries)} Google Alert summaries.")

    def _stylize_article(self, article: Article) -> str:
        # Ensure summary is a string, provide default if None or empty
        summary_text = (
            article.summary
            if article.summary and not article.summary.isspace()
            else "Summary could not be generated."
        )
        return _MARKDOWN_FORMAT.format(
            title=article.title,
            alert_name=article.alert_name,  # Changed from feed_name
            url=article.url,
            summary=summary_text,  # Use the processed summary_text
        )

    def _summarize_article(self, article: Article) -> str:
        # Check if text is meaningful before sending it to the LLM.
        if (
            not article.text
            or article.text.isspace()
            or article.text == "Content is not HTML."
            or article.text == "Could not extract text content."
        ):
            print(
                f"Skipping summarization for '{article.title}' ({article.url}) due to inadequate content.",
            )
            return "Content could not be retrieved or was inadequate for summarization."

        # Limit text length to avoid exceeding API limits (adjust limit as needed)
        max_len = 25000
        text_to_summarize = article.text[:max_len]
        if len(article.text) > max_len:
            print(
                f"Warning: Truncating text for summarization for '{article.title}' ({article.url})",
            )

        print(f"Summarizing article: '{article.title}'")
        try:
            # Assuming generate_content returns the summary string directly
            summary = self._client.generate_content(
                # Use the same prompt format as tech_feed
                contents=self._contents_format.format(
                    title=article.title,
                    text=text_to_summarize,
                ),
                system_instruction=self._system_instruction,
            )
            print(f"Successfully summarized: '{article.title}'")
            return summary.strip() if summary else "Summary generation returned empty."
        except Exception as e:
            print(
                f"Error during summarization for '{article.title}' ({article.url}): {e}",
            )
            # Optionally log traceback for detailed debugging
            # traceback.print_exc()
            return f"Error summarizing content: {e}"

    @property
    def _system_instruction(self) -> str:
        # Using the same system instruction as tech_feed
        return inspect.cleandoc(
            """
            ユーザーから記事のタイトルと文章が与えられるので、内容をよく読み、日本語でとても詳細な要約を作成してください。
            与えられる文章はHTMLから抽出された文章なので、一部情報が欠落していたり、数式、コード、不必要な文章などが含まれている場合があります。
            要約以外の出力は一切不要です。
            """,
        )

    @property
    def _contents_format(self) -> str:
        # Using the same contents format as tech_feed
        return inspect.cleandoc(
            """
            {title}

            本文:
            {text}
            """,
        )
