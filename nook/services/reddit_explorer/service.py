import inspect
import os
import time
from dataclasses import dataclass, field
from typing import Literal

import praw

from nook.services.collector_storage import CollectorStorage
from nook.services.config import load_service_toml
from nook.services.llm_client import create_client
from nook.services.reddit_explorer.summary_schema import (
    RedditPostSummary,
    render_reddit_post_markdown,
)
from nook.services.runtime_secrets import require_runtime_secret
from nook.services.storage import build_storage_backend


class Config:
    reddit_top_posts_limit = 10
    reddit_top_comments_limit = 3
    summary_index_s3_key_format = "reddit_explorer/{date}.md"

    @classmethod
    def load_subreddits(cls) -> list[str]:
        """Load subreddits from subreddits.toml file."""
        subreddits_data = load_service_toml("reddit_explorer", "subreddits.toml")

        # Create a list of subreddit names
        subreddits = []
        for subreddit in subreddits_data.get("subreddits", []):
            subreddits.append(subreddit["name"])

        return subreddits


@dataclass
class RedditPost:
    type: Literal["image", "gallery", "video", "poll", "crosspost", "text", "link"]
    id: str
    title: str
    url: str | None
    upvotes: int
    text: str
    permalink: str = ""
    comments: list[dict[str, str | int]] = field(init=False)
    summary: RedditPostSummary = field(init=False)
    thumbnail: str = "self"


class RedditExplorer:
    def __init__(self):
        self._reddit = praw.Reddit(
            client_id=require_runtime_secret("REDDIT_CLIENT_ID"),
            client_secret=require_runtime_secret("REDDIT_CLIENT_SECRET"),
            user_agent=require_runtime_secret("REDDIT_USER_AGENT"),
        )
        self._client = create_client()
        self._storage = CollectorStorage(
            service_name="reddit_explorer",
            backend=build_storage_backend(os.environ),
        )
        self._subreddits = Config.load_subreddits()

    def __call__(self) -> None:
        markdowns = []
        posts = self._collect_posts()
        for post in self._sort_posts_by_upvotes(posts):
            post.comments = self._retrieve_top_comments_of_post(post.id)
            post.summary = self._summarize_reddit_post(post)
            markdowns.append(self._stylize_post(post))
            time.sleep(5)

        self._store_summaries(markdowns)

    def _collect_posts(self) -> list[RedditPost]:
        posts: list[RedditPost] = []
        for subreddit in self._subreddits:
            posts.extend(self._retrieve_hot_posts(subreddit))
        return posts

    def _sort_posts_by_upvotes(self, posts: list[RedditPost]) -> list[RedditPost]:
        return sorted(posts, key=lambda post: post.upvotes, reverse=True)

    def _store_summaries(self, summaries: list[str]) -> None:
        wrote = self._storage.write_daily_markdown(summaries, separator="\n---\n")
        if not wrote:
            print("No summaries to store.")

    def _retrieve_hot_posts(
        self, subreddit: str, limit: int | None = None
    ) -> list[RedditPost]:
        if limit is None:
            limit = Config.reddit_top_posts_limit

        posts = []
        for post in self._reddit.subreddit(subreddit).hot(limit=limit):
            post_type = self.__judge_post_type(post)

            url = self._get_video_url(post) if post_type == "video" else post.url

            # filter out undesired posts
            if post.author.name == "AutoModerator":
                continue
            if "megathread" in post.title.lower():
                continue
            if post.upvote_ratio < 0.7:
                continue
            if ["gallery", "poll", "crosspost"].__contains__(post_type):
                continue
            posts.append(
                RedditPost(
                    type=post_type,
                    id=post.id,
                    title=post.title,
                    url=url,
                    upvotes=post.ups,
                    text=post.selftext,
                    thumbnail=post.thumbnail,
                )
            )
            posts[-1].permalink = f"https://www.reddit.com{post.permalink}"
        return posts

    def _retrieve_top_comments_of_post(
        self,
        post_id: str,
        limit: int | None = None,
    ) -> list[dict[str, str | int]]:
        if limit is None:
            limit = Config.reddit_top_comments_limit

        submission = self._reddit.submission(id=post_id)
        submission.comments.replace_more(limit=0)
        return [
            {
                "text": comment.body,
                "upvotes": comment.ups,
            }
            for comment in submission.comments.list()[:limit]
        ]

    def _summarize_reddit_post(self, post: RedditPost) -> RedditPostSummary:
        comments_text = "\n".join(
            [
                f"{comment['upvotes']} upvotes: {comment['text']}"
                for comment in post.comments
            ]
        )

        return self._client.generate_structured_content(
            contents=self._contents,
            system_instruction=self._system_instruction_format(
                title=post.title,
                comments=comments_text,
                selftext=post.text,
            ),
            response_schema=RedditPostSummary,
        )

    def __judge_post_type(
        self, post: praw.models.Submission
    ) -> Literal["image", "gallery", "video", "poll", "crosspost", "text", "link"]:
        if getattr(post, "post_hint", "") == "image":
            return "image"
        elif getattr(post, "is_gallery", False):
            return "gallery"
        elif getattr(post, "is_video", False):
            return "video"
        elif hasattr(post, "poll_data"):
            return "poll"
        elif hasattr(post, "crosspost_parent"):
            return "crosspost"
        elif post.is_self:
            return "text"
        return "link"

    def _get_video_url(self, post: praw.models.Submission) -> str | None:
        if hasattr(post, "media"):
            return post.media.get("reddit_video", {}).get("fallback_url", None)
        elif hasattr(post, "secure_media"):
            return post.secure_media.get("reddit_video", {}).get("fallback_url", None)
        else:
            return None

    def _stylize_post(self, post: RedditPost) -> str:
        return render_reddit_post_markdown(
            title=post.title,
            upvotes=post.upvotes,
            media_markdown=(
                f"![Image]({post.url})"
                if post.type == "image"
                else f'<video src="{post.url}" controls controls style="width: 100%; height: auto; max-height: 500px;"></video>'
                if post.type == "video" and post.url is not None
                else ""
            ),
            permalink=post.permalink,
            summary=post.summary,
        )

    def _system_instruction_format(
        self, title: str, comments: str, selftext: str
    ) -> str:
        self_text = inspect.cleandoc(
            f"""
            投稿文
            '''
            {selftext}
            '''
            """
        )
        return inspect.cleandoc(
            f"""
            以下のテキストは、Redditのあるポストのタイトルと{"投稿文、そして" if selftext else ""}当ポストに対する主なコメントです。
            よく読んで、ユーザーの質問に答えてください。

            タイトル
            '''
            {title}
            '''

            {self_text if selftext else ""}

            コメント
            '''
            {comments}
            '''
            """
        )

    @property
    def _contents(self) -> str:
        return inspect.cleandoc(
            """
            以下の structured output schema に従って、各 field を日本語で埋めてください。

            - `post_summary`: このポストの内容を説明する箇条書き
            - `interesting_comments`: 特に興味深いコメントの要点
            """
        )
