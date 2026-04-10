from nook.services.paper_summarizer.summary_schema import (
    PaperReference,
    PaperSummarySections,
    render_paper_summary_markdown,
)
from nook.services.reddit_explorer.summary_schema import (
    RedditPostSummary,
    render_reddit_post_markdown,
)


def test_render_paper_summary_markdown_formats_structured_sections() -> None:
    markdown = render_paper_summary_markdown(
        title="Structured Paper",
        url="https://arxiv.org/abs/1234.56789",
        summary=PaperSummarySections(
            approach=["新しい encoder を導入した。"],
            results=["既存手法より精度が上がった。"],
            limitations=["長文入力では遅い。"],
            references=[
                PaperReference(
                    title="Baseline Paper",
                    url="https://example.com/baseline",
                    rationale="比較対象として重要。",
                ),
            ],
        ),
    )

    assert markdown == (
        "# Structured Paper\n\n"
        "[View Paper](https://arxiv.org/abs/1234.56789)\n\n"
        "### 1. どのようなアプローチで課題を解決しようとしたか\n\n"
        "- 新しい encoder を導入した。\n\n"
        "### 2. 結果、何が達成できたのか\n\n"
        "- 既存手法より精度が上がった。\n\n"
        "### 3. Limitationや問題点は何か\n\n"
        "- 長文入力では遅い。\n\n"
        "### 4. 参考文献のうち、特に参照すべきもの\n\n"
        "- [Baseline Paper](https://example.com/baseline): 比較対象として重要。"
    )


def test_render_paper_summary_markdown_handles_empty_references() -> None:
    markdown = render_paper_summary_markdown(
        title="Structured Paper",
        url="https://arxiv.org/abs/1234.56789",
        summary=PaperSummarySections(
            approach=["a"],
            results=["b"],
            limitations=["c"],
            references=[],
        ),
    )

    assert "- 特に参照すべき文献は抽出できなかった。" in markdown


def test_render_reddit_post_markdown_formats_structured_sections() -> None:
    markdown = render_reddit_post_markdown(
        title="Interesting Post",
        upvotes=123,
        media_markdown="![Image](https://example.com/image.png)",
        permalink="https://reddit.com/r/test/post",
        summary=RedditPostSummary(
            post_summary=["新機能の実装報告。", "背景には既存 API の制約がある。"],
            interesting_comments=["互換性の懸念が指摘された。"],
        ),
    )

    assert markdown == (
        "# Interesting Post\n\n"
        "**Upvotes**: 123\n\n"
        "![Image](https://example.com/image.png)\n\n"
        "[View on Reddit](https://reddit.com/r/test/post)\n\n"
        "### 1. このポストの内容\n\n"
        "- 新機能の実装報告。\n"
        "- 背景には既存 API の制約がある。\n\n"
        "### 2. 特に興味深いコメント\n\n"
        "- 互換性の懸念が指摘された。"
    )


def test_render_reddit_post_markdown_handles_empty_comment_section() -> None:
    markdown = render_reddit_post_markdown(
        title="Interesting Post",
        upvotes=123,
        media_markdown="",
        permalink="https://reddit.com/r/test/post",
        summary=RedditPostSummary(
            post_summary=["新機能の実装報告。"],
            interesting_comments=[],
        ),
    )

    assert "- 特に興味深いコメントは抽出できなかった。" in markdown
