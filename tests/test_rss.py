import os
import sys
import time
import tomllib
from dataclasses import dataclass

import feedparser

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@dataclass
class FeedInfo:
    """情報をまとめるためのデータクラス

    Parameters
    ----------
    key : str
        フィードのキー
    name : str
        フィードの名前
    url : str
        フィードのURL
    status : str
        フィードの取得状態 (success/error)
    error_message : Optional[str]
        エラーメッセージ (エラー時のみ)
    entries_count : Optional[int]
        取得できたエントリーの数 (成功時のみ)
    """

    key: str
    name: str
    url: str
    status: str = "unknown"
    error_message: str | None = None
    entries_count: int | None = None


def load_feeds() -> list[FeedInfo]:
    """feed.tomlファイルからフィード情報を読み込む

    Returns
    -------
    List[FeedInfo]
        フィード情報のリスト
    """
    # configs/tech_feed/feed.tomlのパスを取得
    feed_toml_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "configs", "tech_feed", "feed.toml"
        )
    )

    # ファイルが存在するか確認
    if not os.path.exists(feed_toml_path):
        raise FileNotFoundError(f"feed.tomlファイルが見つかりません: {feed_toml_path}")

    # TOMLファイルを読み込む
    with open(feed_toml_path, "rb") as f:
        feed_data = tomllib.load(f)

    # FeedInfoのリストに変換
    feeds = []
    for feed in feed_data.get("feeds", []):
        feeds.append(FeedInfo(key=feed["key"], name=feed["name"], url=feed["url"]))

    return feeds


def test_feeds(feeds: list[FeedInfo]) -> tuple[list[FeedInfo], list[FeedInfo]]:
    """各フィードにリクエストを送り、成功・失敗を記録する

    Parameters
    ----------
    feeds : List[FeedInfo]
        テスト対象のフィードリスト

    Returns
    -------
    Tuple[List[FeedInfo], List[FeedInfo]]
        (成功したフィード, 失敗したフィード)のタプル
    """
    success_feeds = []
    failed_feeds = []

    for feed in feeds:
        try:
            print(f"テスト中: {feed.name} ({feed.url})")
            feed_parser = feedparser.parse(feed.url)

            # フィードの取得に成功したかを確認
            if feed_parser.get("bozo_exception"):
                # フィードの解析中にエラーが発生した場合
                feed.status = "error"
                feed.error_message = str(feed_parser.get("bozo_exception"))
                failed_feeds.append(feed)
            elif not feed_parser.get("entries"):
                # エントリーが空の場合
                feed.status = "error"
                feed.error_message = "フィードにエントリーがありません"
                failed_feeds.append(feed)
            else:
                # 成功
                feed.status = "success"
                feed.entries_count = len(feed_parser.get("entries", []))
                success_feeds.append(feed)

            # リクエスト間に少し待機
            time.sleep(1)

        except Exception as e:
            feed.status = "error"
            feed.error_message = str(e)
            failed_feeds.append(feed)

    return success_feeds, failed_feeds


def print_results(success_feeds: list[FeedInfo], failed_feeds: list[FeedInfo]) -> None:
    """テスト結果を表示する

    Parameters
    ----------
    success_feeds : List[FeedInfo]
        成功したフィードのリスト
    failed_feeds : List[FeedInfo]
        失敗したフィードのリスト
    """
    total = len(success_feeds) + len(failed_feeds)
    success_rate = (len(success_feeds) / total) * 100 if total > 0 else 0

    print("\n" + "=" * 80)
    print(
        f"RSS/Atomフィードテスト結果 - 合計: {total}、成功: {len(success_feeds)}、失敗: {len(failed_feeds)}"
    )
    print(f"成功率: {success_rate:.1f}%")
    print("=" * 80)

    if success_feeds:
        print("\n✅ 正常に取得できたフィード:")
        print("-" * 80)
        for feed in success_feeds:
            print(f"  • {feed.name} - エントリー数: {feed.entries_count}")
            print(f"    URL: {feed.url}")

    if failed_feeds:
        print("\n❌ 取得に失敗したフィード:")
        print("-" * 80)
        for feed in failed_feeds:
            print(f"  • {feed.name}")
            print(f"    URL: {feed.url}")
            print(f"    エラー: {feed.error_message}")


def main() -> None:
    """メイン実行関数"""
    try:
        # フィード情報を読み込む
        feeds = load_feeds()
        print(f"{len(feeds)}件のフィードを読み込みました\n")

        # 各フィードをテスト
        success_feeds, failed_feeds = test_feeds(feeds)

        # 結果を表示
        print_results(success_feeds, failed_feeds)

    except Exception as e:
        print(f"エラーが発生しました: {e}")
        raise


if __name__ == "__main__":
    main()
