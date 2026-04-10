"""
Tech News RSS フィードとコンテンツ取得の動作確認スクリプト
各フィードのRSS取得と記事コンテンツ取得をテストします。
"""

import sys
import time
import traceback
from datetime import datetime
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup

# tech_news.pyのConfigクラスから設定を読み込む
sys.path.append("../nook/lambda/tech_news")

# フィード設定
FEEDS = [
    {
        "name": "VietnamNews-Society",
        "url": "https://vietnamnews.vn/rss/society.rss",
        "feed_name_display": "VietnamNews Society",
    }
]


class FeedTester:
    def __init__(self):
        self.results = []

    def test_rss_feed(self, feed_config: dict[str, Any]) -> dict[str, Any]:
        """RSSフィードの取得をテスト"""
        result = {
            "name": feed_config["name"],
            "url": feed_config["url"],
            "rss_status": "FAILED",
            "rss_error": None,
            "entry_count": 0,
            "first_entry_title": None,
            "first_entry_url": None,
        }

        try:
            print(f"\n[{feed_config['name']}] RSS フィードをテスト中...")
            print(f"  URL: {feed_config['url']}")

            # feedparserで取得
            feed_parser = feedparser.parse(feed_config["url"])

            # エラーチェック
            if hasattr(feed_parser, "bozo_exception") and feed_parser.bozo_exception:
                print(f"  ⚠️ Feedparser警告: {feed_parser.bozo_exception}")

            # エントリー数確認
            entry_count = len(feed_parser.entries)
            result["entry_count"] = entry_count

            if entry_count == 0:
                # 手動パースを試みる
                print(
                    "  Feedparserでエントリーが取得できませんでした。手動パースを試行..."
                )
                entries = self._manual_parse_feed(feed_config["url"])
                entry_count = len(entries)
                result["entry_count"] = entry_count

                if entry_count > 0:
                    result["rss_status"] = "OK (manual parse)"
                    result["first_entry_title"] = entries[0].get("title", "N/A")
                    result["first_entry_url"] = entries[0].get("link", "N/A")
                    print(f"  ✅ 手動パースで{entry_count}件のエントリーを取得")
                else:
                    result["rss_status"] = "FAILED"
                    result["rss_error"] = (
                        "No entries found (both feedparser and manual parse failed)"
                    )
                    print("  ❌ 手動パースでもエントリーが取得できませんでした")
            else:
                result["rss_status"] = "OK"
                first_entry = feed_parser.entries[0]
                result["first_entry_title"] = first_entry.get("title", "N/A")
                result["first_entry_url"] = first_entry.get("link", "N/A")
                print(f"  ✅ {entry_count}件のエントリーを取得")

        except Exception as e:
            result["rss_error"] = str(e)
            print(f"  ❌ エラー: {e}")

        return result

    def _manual_parse_feed(self, url: str) -> list[dict[str, Any]]:
        """feedparserが失敗した場合の手動パース"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; NewsCrawler/1.0)",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "xml")
            items = soup.find_all("item")

            entries = []
            for item in items[:5]:  # 最初の5件だけテスト
                entry = {}

                title_elem = item.find("title")
                entry["title"] = title_elem.text if title_elem else ""

                link_elem = item.find("link")
                entry["link"] = link_elem.text if link_elem else ""

                if entry["title"] or entry["link"]:
                    entries.append(entry)

            return entries

        except Exception as e:
            print(f"    手動パースエラー: {e}")
            return []

    def test_article_content(self, url: str, feed_name: str) -> dict[str, Any]:
        """記事コンテンツの取得をテスト"""
        result = {
            "content_status": "FAILED",
            "content_error": None,
            "content_length": 0,
            "has_text": False,
        }

        if not url or url == "N/A":
            result["content_error"] = "Invalid URL"
            return result

        try:
            print(f"  記事コンテンツをテスト中: {url[:80]}...")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # 記事本文を探す
            text = ""
            body_content = soup.find("body")

            if body_content:
                # VietnamNews専用の処理を優先
                detail_content = soup.find("div", class_="detail__content")
                if detail_content:
                    # detail__content内の段落を取得
                    paragraphs = detail_content.find_all("p")
                    if paragraphs:
                        text = "\n".join(
                            [
                                p.get_text(strip=True)
                                for p in paragraphs
                                if p.get_text(strip=True)
                            ]
                        )

                # 通常の処理
                if not text:
                    article_tag = body_content.find("article")
                    if article_tag:
                        text = "\n".join(
                            [
                                p.get_text(separator="\n", strip=True)
                                for p in article_tag.find_all(
                                    ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"],
                                    recursive=True,
                                )
                            ]
                        )
                    else:
                        # articleタグがない場合の代替処理
                        main_content = body_content.find(
                            [
                                "main",
                                {"role": "main"},
                                {"class": "content"},
                                {"id": "content"},
                            ]
                        )
                        if main_content:
                            text = "\n".join(
                                [
                                    p.get_text(separator="\n", strip=True)
                                    for p in main_content.find_all(
                                        ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"],
                                        recursive=True,
                                    )
                                ]
                            )
                        else:
                            text = "\n".join(
                                [
                                    p.get_text(separator="\n", strip=True)
                                    for p in body_content.find_all("p")
                                ]
                            )

            text = "\n".join(line for line in text.splitlines() if line.strip())

            result["content_length"] = len(text)
            result["has_text"] = len(text) > 100  # 100文字以上あれば有効とする

            if result["has_text"]:
                result["content_status"] = "OK"
                print(f"    ✅ {len(text)}文字のコンテンツを取得")
            else:
                result["content_status"] = "FAILED"
                result["content_error"] = f"Content too short ({len(text)} chars)"
                print(f"    ❌ コンテンツが短すぎます ({len(text)}文字)")

        except requests.exceptions.RequestException as e:
            result["content_error"] = f"HTTP Error: {e}"
            print(f"    ❌ HTTPエラー: {e}")
        except Exception as e:
            result["content_error"] = str(e)
            print(f"    ❌ エラー: {e}")

        return result

    def run_tests(self):
        """全フィードをテスト"""
        print("=" * 80)
        print("Tech News フィード動作確認テスト")
        print("=" * 80)
        print(f"テスト開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"フィード数: {len(FEEDS)}")

        for feed_config in FEEDS:
            # RSSフィードテスト
            feed_result = self.test_rss_feed(feed_config)

            # 最初の記事のコンテンツ取得テスト
            if (
                feed_result["first_entry_url"]
                and feed_result["first_entry_url"] != "N/A"
            ):
                content_result = self.test_article_content(
                    feed_result["first_entry_url"], feed_config["name"]
                )
                feed_result.update(content_result)
            else:
                feed_result.update(
                    {
                        "content_status": "SKIPPED",
                        "content_error": "No article URL available",
                        "content_length": 0,
                        "has_text": False,
                    }
                )
                print("  記事コンテンツテストをスキップ（URLなし）")

            self.results.append(feed_result)

            # レート制限対策
            time.sleep(1)

        # 結果サマリー
        self.print_summary()

    def print_summary(self):
        """テスト結果のサマリーを表示"""
        print("\n" + "=" * 80)
        print("テスト結果サマリー")
        print("=" * 80)

        # 統計情報
        total = len(self.results)
        rss_ok = sum(1 for r in self.results if "OK" in r["rss_status"])
        content_ok = sum(1 for r in self.results if r["content_status"] == "OK")
        both_ok = sum(
            1
            for r in self.results
            if "OK" in r["rss_status"] and r["content_status"] == "OK"
        )

        print("\n📊 統計:")
        print(f"  総フィード数: {total}")
        print(f"  RSS取得成功: {rss_ok}/{total} ({rss_ok / total * 100:.1f}%)")
        print(
            f"  コンテンツ取得成功: {content_ok}/{total} ({content_ok / total * 100:.1f}%)"
        )
        print(f"  両方成功: {both_ok}/{total} ({both_ok / total * 100:.1f}%)")

        # 問題のあるフィード
        print("\n⚠️ 問題のあるフィード:")
        problem_feeds = [
            r
            for r in self.results
            if r["rss_status"] == "FAILED" or r["content_status"] == "FAILED"
        ]

        if problem_feeds:
            for feed in problem_feeds:
                print(f"\n  [{feed['name']}]")
                if feed["rss_status"] == "FAILED":
                    print(f"    RSS: ❌ {feed['rss_error']}")
                else:
                    print(f"    RSS: ✅ ({feed['entry_count']}件)")

                if feed["content_status"] == "FAILED":
                    print(f"    コンテンツ: ❌ {feed['content_error']}")
                elif feed["content_status"] == "OK":
                    print(f"    コンテンツ: ✅ ({feed['content_length']}文字)")
        else:
            print("  なし（全フィード正常）")

        # 正常なフィード
        print("\n✅ 正常に動作しているフィード:")
        working_feeds = [
            r
            for r in self.results
            if "OK" in r["rss_status"] and r["content_status"] == "OK"
        ]

        if working_feeds:
            for feed in working_feeds:
                print(
                    f"  - {feed['name']}: RSS {feed['entry_count']}件, コンテンツ {feed['content_length']}文字"
                )
        else:
            print("  なし")

        print("\n" + "=" * 80)
        print(f"テスト完了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)


def main():
    """メイン関数"""
    tester = FeedTester()
    try:
        tester.run_tests()
    except KeyboardInterrupt:
        print("\n\nテストを中断しました")
    except Exception as e:
        print(f"\n予期しないエラー: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
