from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ViewerPage:
    date: str
    app_names: list[str]
    contents: dict[str, str]
    articles: dict[str, list["ViewerRenderedArticle"]]
    markdown_exists: dict[str, bool]
    markdown_updated_at: dict[str, str | None]
    weather_data: dict[str, str]

    def to_state(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "app_names": self.app_names,
            "contents": self.contents,
            "articles": {
                app_name: [article.to_state() for article in articles]
                for app_name, articles in self.articles.items()
            },
            "markdown_exists": self.markdown_exists,
            "markdown_updated_at": self.markdown_updated_at,
            "weather_data": self.weather_data,
        }


@dataclass(frozen=True, slots=True)
class ViewerArticleState:
    article_id: str
    title: str
    markdown: str

    def to_state(self) -> dict[str, str]:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "markdown": self.markdown,
        }


@dataclass(frozen=True, slots=True)
class ViewerTab:
    app_name: str
    label: str
    is_active: bool
    has_markdown: bool


@dataclass(frozen=True, slots=True)
class ViewerHeading:
    text: str
    anchor: str
    level: int

    def to_state(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "anchor": self.anchor,
            "level": self.level,
        }


@dataclass(frozen=True, slots=True)
class ViewerRenderedArticle:
    article_id: str
    title: str
    html: str
    headings: list[ViewerHeading]

    def to_state(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "html": self.html,
            "headings": [heading.to_state() for heading in self.headings],
        }


@dataclass(frozen=True, slots=True)
class ViewerInitialRender:
    current_app: str | None
    tabs: list[ViewerTab]
    article_title: str
    article_meta: str
    articles: list[ViewerRenderedArticle]
    missing_message: str | None
    headings: list[ViewerHeading]
    has_markdown: bool
