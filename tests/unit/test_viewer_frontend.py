import json
import subprocess
from pathlib import Path


def test_viewer_retry_polling_uses_previous_updated_at_contract() -> None:
    viewer_js_path = (
        Path(__file__).resolve().parents[2]
        / "nook"
        / "services"
        / "viewer"
        / "static"
        / "viewer.js"
    )
    script = f"""
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync({json.dumps(str(viewer_js_path))}, "utf8");
const window = {{}};
const document = {{ addEventListener() {{}} }};
const sandbox = {{ window, document, URLSearchParams }};
vm.runInNewContext(source, sandbox, {{ filename: "viewer.js" }});

const hooks = window.__myNookViewerTestHooks;
assert.ok(hooks);
assert.equal(
  hooks.resolveInitialApp(["tech_news", "tech_feed"]),
  "tech_news",
);
assert.equal(hooks.resolveInitialApp([]), null);
assert.equal(
  hooks.buildMarkdownRequestPath(
    "tech_feed",
    "2026-04-08",
    "2026-04-08T00:01:00+00:00",
  ),
  "/api/markdown/tech_feed?date=2026-04-08&previous_updated_at=2026-04-08T00%3A01%3A00%2B00%3A00",
);
assert.equal(
  JSON.stringify(
    hooks.buildRetryPollRequestOptions(true, "2026-04-08T00:01:00+00:00"),
  ),
  JSON.stringify({{
    preserveCurrentContentOn404: true,
    previousUpdatedAt: "2026-04-08T00:01:00+00:00",
  }}),
);
assert.equal(
  JSON.stringify(hooks.buildRetryPollRequestOptions(false, null)),
  JSON.stringify({{
    preserveCurrentContentOn404: false,
    previousUpdatedAt: null,
  }}),
);
assert.equal(
  JSON.stringify(
    hooks.buildChatRequestPayload(
      "article-tech_feed-a1b2c3d4",
      "2026-04-08",
      "assistant: previous answer",
      "what changed?",
    ),
  ),
  JSON.stringify({{
    article_id: "article-tech_feed-a1b2c3d4",
    date: "2026-04-08",
    chat_history: "assistant: previous answer",
    message: "what changed?",
  }}),
);
assert.equal(hooks.slugify("- Foo -", 0), "foo");
assert.equal(
  JSON.stringify(
    hooks.cloneArticles([
      {{
        article_id: "article-tech_feed-a1b2c3d4",
        title: "First Article",
        html: '<h1 id="heading-article-tech_feed-a1b2c3d4-0-first-article">First Article</h1>',
        headings: [
          {{
            text: "First Article",
            anchor: "heading-article-tech_feed-a1b2c3d4-0-first-article",
            level: 1,
          }},
        ],
      }},
    ]),
  ),
  JSON.stringify([
    {{
      article_id: "article-tech_feed-a1b2c3d4",
      title: "First Article",
      html: '<h1 id="heading-article-tech_feed-a1b2c3d4-0-first-article">First Article</h1>',
      headings: [
        {{
          text: "First Article",
          anchor: "heading-article-tech_feed-a1b2c3d4-0-first-article",
          level: 1,
        }},
      ],
    }},
  ]),
);
assert.equal(
  JSON.stringify(
    hooks.flattenArticleHeadings([
      {{
        article_id: "article-tech_feed-a1b2c3d4",
        headings: [
          {{
            text: "First Article",
            anchor: "heading-article-tech_feed-a1b2c3d4-0-first-article",
            level: 1,
          }},
        ],
      }},
    ]),
  ),
  JSON.stringify([
    {{
      text: "First Article",
      anchor: "heading-article-tech_feed-a1b2c3d4-0-first-article",
      level: 1,
    }},
  ]),
);
assert.equal(
  JSON.stringify(
    hooks.reconcileChatHistory(
      {{
        "article-tech_feed-second": [{{ role: "assistant", content: "keep second" }}],
        "article-tech_feed-first": [{{ role: "assistant", content: "keep first" }}],
        "article-tech_feed-stale": [{{ role: "assistant", content: "drop" }}],
      }},
      [
        {{ article_id: "article-tech_feed-second" }},
        {{ article_id: "article-tech_feed-new" }},
        {{ article_id: "article-tech_feed-first" }},
      ],
    ),
  ),
  JSON.stringify({{
    "article-tech_feed-second": [{{ role: "assistant", content: "keep second" }}],
    "article-tech_feed-new": [],
    "article-tech_feed-first": [{{ role: "assistant", content: "keep first" }}],
  }}),
);
"""

    subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        text=True,
    )


def test_viewer_styles_fix_product_hunt_thumbnail_width() -> None:
    viewer_css_path = (
        Path(__file__).resolve().parents[2]
        / "nook"
        / "services"
        / "viewer"
        / "static"
        / "viewer.css"
    )
    source = viewer_css_path.read_text(encoding="utf-8")

    assert ".product-thumbnail" in source
    assert "width: 8%;" in source
