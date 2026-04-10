---
name: pytest-driver
description: "`tests/unit/` で失敗テスト先行の TDD を進め、手動チェックと自動テストを混ぜないためのガイド。"
license: See repository LICENSE
---

# Pytest Driver

## トリガ

- 非テストコードを変更する前
- 条件分岐や例外を追加するとき
- バグ再現を自動テストで固定したいとき

## 原則

- 自動テストは `tests/unit/` に置く
- ネットワーク、認証情報、外部 API 依存の確認は `make manual-*` に分離する
- 正常 / 異常 / 境界の少なくとも 3 系統を意識する

## Quickstart

1. 期待する挙動を 1 ケース書いてまず失敗させる
2. 異常系 / 境界系を追加する
3. 最小実装でグリーンにする
4. `make post-change` で format / lint / pytest をまとめて確認する

## よく使う確認観点

- 例外型とメッセージが正しいか
- 設定ファイルやディレクトリ構成などの smoke test を書けないか
- 外部 API を呼ぶ前段の整形ロジックだけでも分離してテストできないか
