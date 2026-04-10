from __future__ import annotations

from pydantic import BaseModel, Field


class RedditPostSummary(BaseModel):
    post_summary: list[str] = Field(default_factory=list)
    interesting_comments: list[str] = Field(default_factory=list)


def render_reddit_post_markdown(
    *,
    title: str,
    upvotes: int,
    media_markdown: str,
    permalink: str,
    summary: RedditPostSummary,
) -> str:
    parts = [
        f"# {title}",
        f"**Upvotes**: {upvotes}",
    ]
    if media_markdown.strip():
        parts.append(media_markdown.strip())
    parts.append(f"[View on Reddit]({permalink})")
    parts.append("### 1. このポストの内容")
    parts.append(
        _render_bullet_list(
            summary.post_summary,
            empty_message="ポスト内容は抽出できなかった。",
        )
    )
    parts.append("### 2. 特に興味深いコメント")
    parts.append(
        _render_bullet_list(
            summary.interesting_comments,
            empty_message="特に興味深いコメントは抽出できなかった。",
        )
    )
    return "\n\n".join(parts)


def _render_bullet_list(items: list[str], *, empty_message: str) -> str:
    normalized_items = [item.strip() for item in items if item.strip()]
    if not normalized_items:
        normalized_items = [empty_message]
    return "\n".join(f"- {item}" for item in normalized_items)
