---
name: spec-reviewer
description: 実装前に技術仕様書の不足、矛盾、曖昧さ、過剰設計を read-only で洗い出すレビューガイド。
license: See repository LICENSE
---

# Spec Reviewer

## トリガ

- `specs/*.md` を作成 / 更新した直後
- 実装前に仕様の抜け漏れを確認したいとき

## 運用フロー

1. active spec を `specs/` に 1 件だけ置いたうえで `make spec-review` を実行する
2. 返ってきた GAP / FIX をもとに spec を修正する
3. 重要な曖昧さや不足が消えるまで繰り返す

## runner 前提

- review prompt は `scripts/spec_review_runner.sh` に焼き込まれている。
- runner は `specs/TEMPLATE.md` を除く `.md` が 1 件だけ存在する前提で動く。
- 0 件または複数件ある場合は fail-fast する。

## チェックポイント

- 変更対象ファイルが具体的か
- 自動テストと手動チェックの線引きが明確か
- `make post-change` と必要な `make manual-*` が定義されているか
- docs 更新箇所まで spec に含まれているか
- 完了後に spec を削除する前提が明記されているか
