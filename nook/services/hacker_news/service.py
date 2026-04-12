import inspect
import json
import os
import time
import traceback
from dataclasses import dataclass
from typing import Any

import requests
from bs4 import BeautifulSoup

from nook.services.collector_storage import CollectorStorage
from nook.services.llm_client import create_client
from nook.services.storage import build_storage_backend

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
    threshold_days = 1


@dataclass
class Story:
    """
    Hacker News のストーリーを表すデータクラス。

    Attributes
    ----------
    title : str
        ストーリーのタイトル。
    score : int
        ストーリーのスコア。
    url : str | None, optional
        ストーリーのURL。テキストベースの投稿の場合は None。
    text : str | None, optional
        ストーリーの本文または要約。URLベースの投稿の場合は本文の要約、
        テキストベースの投稿の場合は元のテキストまたはその要約。
    """

    title: str
    score: int
    url: str | None = None
    text: str | None = None


class HackerNewsRetriever:
    """
    Hacker News からトップストーリーを取得し、必要に応じて要約してS3に保存するクラス。
    """

    def __init__(self):
        """
        HackerNewsRetriever の初期化。

        LLM クライアント、storage backend を設定します。
        """
        self._client = create_client()
        self._storage = CollectorStorage(
            service_name="hacker_news",
            backend=build_storage_backend(os.environ),
        )

    def __call__(self) -> None:
        """
        Hacker News のトップストーリーを取得し、処理してS3に保存するメイン処理。
        """
        stories = self._get_top_stories()
        if not stories:
            print("No suitable stories found on Hacker News.")
            return
        # スコアで降順ソート
        stories.sort(key=lambda s: s.score, reverse=True)
        styled_attachments = [self._stylize_story(story) for story in stories]
        self._store_summaries(styled_attachments)

    def _get_top_stories(self) -> list[Story]:
        """
        Hacker News のトップストーリーを取得し、フィルタリングして返す。

        スコアが20未満のストーリーは除外します。
        テキストを持つストーリーはそれを要約（長すぎる/短すぎる場合はクレンジングのみ）。
        URLのみを持つストーリーはその先の記事を要約します。

        Returns
        -------
        list[Story]
            処理されたストーリーのリスト。
        """
        top_story_ids = self._get_top_storie_ids()[: Config.hacker_news_num_top_stories]

        stories: list[Story] = []
        for story_id in top_story_ids:
            story_data = self._get_story(story_id)
            # story_dataがNoneの場合や"score"がない場合はスキップ
            if not story_data or "score" not in story_data:
                print(f"Skipping story {story_id}: Invalid data")
                continue

            if story_data["score"] < 20:
                continue

            title = story_data.get("title", "No Title")
            score = story_data["score"]
            url = story_data.get("url")
            hn_text = story_data.get("text")
            summary = None

            if hn_text:
                # HN自体にテキストがある場合
                cleaned_text = self._cleanse_text(hn_text)
                if (
                    100 < len(cleaned_text) < 10000
                ):  # 長すぎる/短すぎるテキストは要約しない
                    print(f"Summarizing HN text for story {story_id}: {title[:50]}...")
                    summary = self._summarize_content(title, cleaned_text)
                else:
                    summary = cleaned_text  # 要約せず、クレンジングしたテキストを使用
            elif url:
                # URLのみの場合、リンク先の記事を要約
                print(f"Retrieving and summarizing URL for story {story_id}: {url}")
                summary = self._retrieve_and_summarize_url(url, title)
                time.sleep(2)  # LLM API のレート制限対策

            # summaryがNoneのままの場合（テキストもURLもなく要約できなかった、またはエラー発生）はスキップしない
            # textフィールドには要約結果 or クレンジングされたHNテキスト or Noneが入る
            stories.append(
                Story(
                    title=title,
                    score=score,
                    url=url,
                    text=summary,  # HNテキストがあった場合はその要約orクレンジング結果、URLの場合は記事の要約
                )
            )
            # 処理の間に短い待機を入れる（API制限回避）
            time.sleep(0.5)

        return stories

    def _retrieve_and_summarize_url(self, url: str, title: str) -> str | None:
        """
        指定されたURLから記事の内容を取得し、要約する。

        Parameters
        ----------
        url : str
            記事のURL。
        title : str
            記事のタイトル（要約のコンテキスト用）。

        Returns
        -------
        str | None
            記事の要約。取得または要約に失敗した場合はNone。
        """
        try:
            response = requests.get(url, timeout=15)  # タイムアウト設定
            response.raise_for_status()  # HTTPエラーチェック
            content_type = response.headers.get("content-type", "").lower()

            # HTMLコンテンツのみ処理
            if "html" not in content_type:
                print(f"Skipping non-HTML content at {url}: {content_type}")
                return f"Skipping non-HTML content ({content_type})"  # 要約できない理由を返す

            soup = BeautifulSoup(response.text, "html.parser")
            # 主要なテキストコンテンツを抽出する試み (より堅牢な方法)
            main_content = soup.find("article") or soup.find("main") or soup.body
            if main_content:
                text = "\n".join(
                    p.get_text()
                    for p in main_content.find_all(
                        [
                            "p",
                            "h1",
                            "h2",
                            "h3",
                            "h4",
                            "h5",
                            "h6",
                            "li",
                        ],  # リスト項目も追加
                        recursive=False,  # 主要コンテナ直下のみを対象にする場合
                    )
                    if p.get_text(strip=True)  # 空のタグを除外
                )
                # それでも取れない場合、body全体から取得
                if not text.strip():
                    text = main_content.get_text(
                        separator="\\n", strip=True
                    )  # エスケープ修正
            else:
                text = soup.get_text(
                    separator="\\n", strip=True
                )  # エスケープ修正 # フォールバック

            cleaned_text = self._cleanse_text(text)

            if not cleaned_text or cleaned_text.isspace():
                print(
                    f"Skipping summarization for {url} due to empty content after cleaning."
                )
                return "Content could not be retrieved or was empty after cleaning."

            if len(cleaned_text) < 100:  # 短すぎるコンテンツは要約しない
                print(f"Skipping summarization for {url} due to short content.")
                return cleaned_text  # 短い場合はそのまま返す

            print(f"Summarizing content from URL: {url}")
            return self._summarize_content(
                title, cleaned_text[:20000]
            )  # 長すぎる場合は切り詰める

        except requests.exceptions.RequestException as e:
            print(f"Error retrieving URL {url}: {e}")
            return f"Error retrieving URL: {e}"
        except Exception as e:
            print(f"Error processing content from {url}: {e}")
            traceback.print_exc()
            return f"Error processing content: {e}"

    def _summarize_content(self, title: str, text: str) -> str:
        """
        与えられたタイトルとテキストを LLM で要約する。

        Parameters
        ----------
        title : str
            記事のタイトル。
        text : str
            要約対象のテキスト本文。

        Returns
        -------
        str
            要約結果のテキスト。エラー時はエラーメッセージ。
        """
        try:
            return self._client.generate_content(
                contents=self._contents_format.format(title=title, text=text),
                system_instruction=self._system_instruction_for_articles,  # 記事要約用のプロンプトを使用
            )
        except Exception as e:
            print(f"Error during summarization for title '{title[:50]}...': {e}")
            return f"Error summarizing content: {e}"

    def _get_top_storie_ids(self) -> list[int]:
        """Hacker News のトップストーリーIDリストを取得する。"""
        try:
            response = requests.get(
                Config.hacker_news_top_stories_url,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching top story IDs: {e}")
            return []

    def _get_story(self, story_id: int) -> dict[str, Any] | None:
        """指定されたIDのストーリー詳細を取得する。"""
        try:
            response = requests.get(
                Config.hacker_news_item_url.format(story_id=story_id),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching story {story_id}: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON for story {story_id}: {e}")
            return None

    def _cleanse_text(self, text: str | None) -> str:
        """
        HTMLタグを除去し、テキストをクレンジングする。

        Parameters
        ----------
        text : str | None
            クレンジング対象のテキスト。Noneの場合は空文字列を返す。

        Returns
        -------
        str
            クレンジングされたテキスト。
        """
        # Added check for None or empty string
        if not text:
            return ""
        # `get_text` は基本的なタグ除去を行う
        soup = BeautifulSoup(text, "html.parser")
        # separatorに改行を指定し、strip=Trueで前後の空白を除去
        return soup.get_text(separator="\n", strip=True)

    def _store_summaries(self, summaries: list[str]) -> None:
        """
        要約リストを結合し、MarkdownファイルとしてS3に保存する。

        Parameters
        ----------
        summaries : list[str]
            Markdown形式の要約文字列のリスト。
        """
        if not self._storage.write_daily_markdown(summaries, separator="\n---\n"):
            print("No summaries to store.")
            return
        print("Successfully stored Hacker News summaries.")

    def _stylize_story(self, story: Story) -> str:
        """
        StoryオブジェクトをMarkdown形式の文字列に整形する。

        Parameters
        ----------
        story : Story
            整形対象のStoryオブジェクト。

        Returns
        -------
        str
            Markdown形式の文字列。
        """
        # textがNoneの場合や空の場合のフォールバックを追加
        summary_text = (
            story.text
            if story.text and story.text.strip()
            else "Summary not available."
        )

        # URLがある場合はリンクを表示、ない場合は要約テキストを直接表示
        if story.url:
            url_or_text = f"[View Link]({story.url})\n\n{summary_text}"
        else:
            # URLがなく、HNのテキストを要約した場合 or そのまま表示した場合
            url_or_text = summary_text

        return _MARKDOWN_FORMAT.format(
            title=story.title,
            score=story.score,
            url_or_text=url_or_text,
        )

    @property
    def _system_instruction_for_articles(self) -> str:
        return inspect.cleandoc(
            """
            あなたは、与えられた記事のタイトルと本文を読んで日本語で要約を作成するアシスタントです。
            本文はHTMLから抽出されたもので、不完全な場合や不要な情報が含まれる場合があります。
            記事の主要なポイントを捉え、簡潔かつ分かりやすい要約を作成してください。
            要約以外の余計な文章は含めないでください。
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
