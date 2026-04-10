from __future__ import annotations

import re
from typing import Callable

ContentFetcher = Callable[[str], str | None]

_PROMPT_TEMPLATE = """
以下の記事に関連して、検索エンジンを用いて事実を確認しながら、ユーザーからの質問に対してできるだけ詳細に答えてください。
なお、回答はMarkdown形式で記述してください。

[記事]

{markdown}

{additional_context}

[チャット履歴]

'''
{chat_history}
'''

[ユーザーからの新しい質問]

'''
{message}
'''

それでは、回答をお願いします。
"""


def build_chat_prompt(
    *,
    markdown: str,
    additional_context: str,
    chat_history: str,
    message: str,
) -> str:
    context_block = ""
    if additional_context:
        context_block = (
            "\n\n[記事またはユーザーからの質問に含まれるリンクの内容]"
            "(うまく取得できていない可能性があります)\n\n"
            f"{additional_context}"
        )

    return _PROMPT_TEMPLATE.format(
        markdown=markdown,
        additional_context=context_block,
        chat_history=chat_history,
        message=message,
    )


def collect_additional_context(
    *,
    markdown: str,
    message: str,
    content_fetcher: ContentFetcher,
) -> str:
    links = list(dict.fromkeys([*extract_links(markdown), *extract_links(message)]))
    additional_context_parts = []
    for url in links:
        content = content_fetcher(url)
        if content:
            additional_context_parts.append(f"- Content from {url}:\n\n'''{content}'''")

    if not additional_context_parts:
        return ""

    return "\n\n".join(additional_context_parts)


def extract_links(text: str) -> list[str]:
    markdown_links = re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", text)
    urls = re.findall(r"(?<![\(\[])(https?://[^\s\)]+)", text)

    resolved_markdown_links = []
    for label, url in markdown_links:
        normalized_label = label.strip().lower()
        if normalized_label.startswith("image") or normalized_label.startswith("video"):
            continue
        resolved_markdown_links.append(url)

    return [*resolved_markdown_links, *urls]
