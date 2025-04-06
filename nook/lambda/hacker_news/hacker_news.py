import inspect
import os
import traceback
from dataclasses import dataclass
from datetime import date
from pprint import pprint
from typing import Any
import json
import base64

import boto3
import requests
from botocore.exceptions import ClientError
from bs4 import BeautifulSoup
from gemini_client import create_client

_MARKDOWN_FORMAT = """
# {title}

**Score**: {score}

{url_or_text}
"""


class Config:
    hacker_news_top_stories_url = (
        "https://hacker-news.firebaseio.com/v0/topstories.json"
    )
    hacker_news_item_url = "https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
    hacker_news_num_top_stories = 30
    summary_index_s3_key_format = "hacker_news/{date}.md"


@dataclass
class Story:
    title: str
    score: int
    url: str | None = None
    text: str | None = None


class HackerNewsRetriever:
    def __init__(self):
        self._client = create_client()
        self._s3 = boto3.client("s3")
        self._bucket_name = os.environ["BUCKET_NAME"]

    def __call__(self) -> None:
        stories = self._get_top_stories()
        if not stories:
            print("No suitable stories found on Hacker News.")
            return
        styled_attachments = [self._stylize_story(story) for story in stories]
        self._store_summaries(styled_attachments)

    def _get_top_stories(self) -> list[Story]:
        """
        Gets the top stories from Hacker News and returns.

        1. Get the top stories from Hacker News.
        2. For each story, get the title and text.
        3. If the score is less than 20, ignore the story.
        4. If the story has text, summarize it.
        5. Return the stories.

        Returns
        -------
        list[Story]
            The list of stories.
        """
        # 1. Get the top stories from Hacker News.
        top_stories = self._get_top_storie_ids()[: Config.hacker_news_num_top_stories]

        stories = []
        for story_id in top_stories:
            # 2. For each story, get the title and text.
            story = self._get_story(story_id)

            # 3. If the score is less than 20, ignore the story.
            if story["score"] < 20:
                continue

            # 4. If the story has text, summarize it.
            summary = None
            if story.get("text"):
                if 100 < len(story["text"]) < 10000:
                    summary = self._summarize_story(story)
                else:
                    summary = self._cleanse_text(story["text"])

            stories.append(
                Story(
                    title=story["title"],
                    score=story["score"],
                    url=story.get("url"),
                    text=story.get("text") if summary is None else summary,
                )
            )

        # 5. Return the stories.
        return stories

    def _summarize_story(self, story: dict[str, str | int]) -> str:
        return self._client.generate_content(
            contents=self._contents_format.format(
                title=story["title"], text=self._cleanse_text(story["text"])
            ),
            system_instruction=self._system_instruction,
        )

    def _get_top_storie_ids(self) -> list[int]:
        return requests.get(
            Config.hacker_news_top_stories_url,
            headers={"Content-Type": "application/json"},
        ).json()

    def _get_story(self, story_id: int) -> dict[str, str]:
        return requests.get(
            Config.hacker_news_item_url.format(story_id=story_id),
            headers={"Content-Type": "application/json"},
        ).json()

    def _cleanse_text(self, text: str) -> str:
        # Added check for None or empty string
        if not text:
            return ""
        return BeautifulSoup(text, "html.parser").get_text()

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

    def _stylize_story(self, story: Story) -> str:
        url_or_text = f"[View Link]({story.url})" if story.url else story.text
        return _MARKDOWN_FORMAT.format(
            title=story.title,
            score=story.score,
            url_or_text=url_or_text,
        )

    @property
    def _system_instruction(self) -> str:
        return inspect.cleandoc(
            """
            あなたは、Hacker Newsの最新の記事を要約するアシスタントです。
            ユーザーからHacker Newsの記事のタイトルと本文を与えられるので、あなたはその記事を日本語で要約してください。
            なお、要約以外の出力は不要です。
            """
        )

    @property
    def _contents_format(self) -> str:
        return inspect.cleandoc(
            """
            タイトル
            ```
            {title}
            ```

            本文
            ```
            {text}
            ```
            """
        )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    pprint(event)
    is_trigger_event = False

    try:
        # Check for EventBridge trigger
        if event.get("source") == "aws.events":
            is_trigger_event = True
            print("Invocation source: EventBridge")
        # Check for Function URL trigger (or API Gateway)
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
            print("Triggering HackerNewsRetriever job...")
            retriever = HackerNewsRetriever()
            retriever()
            print("HackerNewsRetriever job finished.")
            # Return success response compatible with Function URL
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": "HackerNewsRetriever triggered successfully"})
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
                return {"statusCode": 400}

    except Exception as e:
        print("An error occurred during execution:")
        pprint(traceback.format_exc())
        if "requestContext" in event:
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": f"Internal server error: {e}"})
            }
        else:
            return {"statusCode": 500}
