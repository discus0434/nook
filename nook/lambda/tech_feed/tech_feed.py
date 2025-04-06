import inspect
import os
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
import json
import base64

import boto3
import feedparser
import requests
import tomllib
from botocore.exceptions import ClientError
from bs4 import BeautifulSoup
from gemini_client import create_client

_MARKDOWN_FORMAT = """
# {title}

[View on {feed_name}]({url})

{summary}
"""


class Config:
    tech_feed_max_entries_per_day = 10
    summary_index_s3_key_format = "tech_feed/{date}.md"
    threshold_days = 1

    @classmethod
    def load_feeds(cls) -> dict[str, str]:
        """Load feed URLs from feed.toml file."""
        feed_toml_path = os.path.join(os.path.dirname(__file__), "feed.toml")
        with open(feed_toml_path, "rb") as f:
            feed_data = tomllib.load(f)

        # Create a dictionary mapping feed names to URLs
        feeds = {}
        for feed in feed_data.get("feeds", []):
            feeds[feed["name"]] = feed["url"]

        return feeds


@dataclass
class Article:
    feed_name: str
    title: str
    url: str
    text: str
    soup: BeautifulSoup
    category: str | None = field(default=None)
    summary: list[str] = field(init=False)


class TechFeed:
    def __init__(self) -> None:
        self._client = create_client()
        self._s3 = boto3.client("s3")
        self._bucket_name = os.environ["BUCKET_NAME"]
        self._tech_feed_urls = Config.load_feeds()
        self._threshold = datetime.now() - timedelta(days=Config.threshold_days)

    def __call__(self) -> None:
        markdowns = []
        for feed_name, feed_url in self._tech_feed_urls.items():
            feed_parser: feedparser.FeedParserDict = feedparser.parse(feed_url)
            entries = self._filter_entries(feed_parser)
            if len(entries) > Config.tech_feed_max_entries_per_day:
                entries = entries[: Config.tech_feed_max_entries_per_day]

            for entry in entries:
                article = self._retrieve_article(entry, feed_name=feed_name)
                article.summary = self._summarize_article(article)
                markdowns.append(self._stylize_article(article))
                time.sleep(2)
        self._store_summaries(markdowns)

    def _filter_entries(
        self, feed_parser: feedparser.FeedParserDict
    ) -> list[dict[str, Any]]:
        filtered_entries = []
        for entry in feed_parser["entries"]:
            date_ = entry.get("date_parsed") or entry.get("published_parsed")
            if not date_:
                print(f"date_ is None: {entry.link}")
                print(entry)
                continue
            try:
                published_dt = datetime.fromtimestamp(time.mktime(date_))
            except Exception as e:
                print(f"Error converting date: {e}")
                traceback.print_exc()
                print(f"entry: {entry.link}")
                print(entry)
                continue
            if published_dt > self._threshold:
                filtered_entries.append(entry)
        return filtered_entries

    def _retrieve_article(self, entry: dict[str, Any], feed_name: str) -> Article:
        try:
            response = requests.get(entry.link)
            soup = BeautifulSoup(response.text, "html.parser")
            text = "\n".join(
                [
                    p.get_text()
                    for p in soup.find_all(
                        ["p", "code", "ul", "h1", "h2", "h3", "h4", "h5", "h6"]
                    )
                ]
            )
            return Article(
                feed_name=feed_name,
                title=entry.title,
                url=entry.link,
                text=text,
                soup=soup,
            )
        except Exception as e:
            raise Exception(f"Error raised while retrieving article: {e}") from e

    def _store_summaries(self, summaries: list[str]) -> None:
        date_str = date.today().strftime("%Y-%m-%d")
        key = Config.summary_index_s3_key_format.format(date=date_str)
        content = "\n---\n".join(summaries)
        try:
            self._s3.put_object(
                Bucket=self._bucket_name,
                Key=key,
                Body=content,
            )
        except ClientError as e:
            print(f"Error putting object {key} into bucket {self._bucket_name}.")
            print(e)

    def _stylize_article(self, article: Article) -> str:
        return _MARKDOWN_FORMAT.format(
            title=article.title,
            feed_name=article.feed_name,
            url=article.url,
            summary=article.summary,
        )

    def _summarize_article(self, article: Article) -> str:
        if not article.text or article.text.isspace():
             print(f"Skipping summarization for {article.url} due to empty content.")
             return "Content could not be retrieved or was empty."
        try:
            return self._client.generate_content(
                contents=self._contents_format.format(
                    title=article.title, text=article.text[:20000]
                ),
                system_instruction=self._system_instruction,
            )
        except Exception as e:
            print(f"Error during summarization for {article.url}: {e}")
            return f"Error summarizing content: {e}"

    @property
    def _system_instruction(self) -> str:
        return inspect.cleandoc(
            """
            ユーザーから記事のタイトルと文章が与えられるので、内容をよく読み、日本語でとても詳細な要約を作成してください。
            与えられる文章はHTMLから抽出された文章なので、一部情報が欠落していたり、数式、コード、不必要な文章などが含まれている場合があります。
            要約以外の出力は不要です。
            """
        )

    @property
    def _contents_format(self) -> str:
        return inspect.cleandoc(
            """
            {title}

            本文:
            {text}
            """
        )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    print(event)
    is_trigger_event = False

    try:
        if event.get("source") == "aws.events":
            is_trigger_event = True
            print("Invocation source: EventBridge")
        elif "requestContext" in event and event.get("requestContext", {}).get("http", {}).get("method") == "POST":
            print("Invocation source: Function URL (POST)")
            body_str = event.get("body", "{}")
            if event.get("isBase64Encoded", False):
                print("Decoding Base64 body")
                try:
                    body_str = base64.b64decode(body_str).decode('utf-8')
                except (base64.binascii.Error, UnicodeDecodeError) as e:
                    print(f"Failed to decode Base64 body: {e}")
                    body_str = "{}"

            print(f"Parsed body string: {body_str[:200]}...")

            try:
                body_json = json.loads(body_str)
                if body_json.get("source") == "aws.events":
                    print("Found 'source: aws.events' in request body.")
                    is_trigger_event = True
                else:
                    print("Request body did not contain 'source: aws.events'.")
            except json.JSONDecodeError as e:
                print(f"Failed to decode JSON body: {e}")
                print(f"Body content was: {body_str}")

        if is_trigger_event:
            print("Triggering TechFeed job...")
            tech_feed_ = TechFeed()
            tech_feed_()
            print("TechFeed job finished.")
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": "TechFeed triggered successfully"})
            }
        else:
            print("Invocation source not recognized or payload mismatch. No action taken.")
            if "requestContext" in event:
                return {
                    "statusCode": 400,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"message": "Invalid request: Expected 'source: aws.events' in POST body"})
                }
            else:
                print("Returning 400 for unrecognized non-HTTP invocation.")
                return {"statusCode": 400}

    except Exception as e:
        print("An error occurred during execution:")
        print(traceback.format_exc())
        if "requestContext" in event:
             return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": f"Internal server error: {e}"})
            }
        else:
            return {"statusCode": 500}
