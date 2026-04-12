---
name: spec-implementation-reviewer
description: 実装完了後、技術仕様書とコード / テストの乖離を read-only で洗い出すレビューガイド。
license: See repository LICENSE
---

# Spec Implementation Reviewer

## トリガ

- 実装が終わり、docs 更新に入る直前
- 技術仕様書どおりに実装できているか確認したいとき

## 運用フロー

1. active spec を `specs/` に 1 件だけ置いたうえで `make spec-implementation-review` を実行する
2. GAP / FIX をもとにコードやテストを修正する
3. Critical / Major がなくなるまで繰り返す

## runner 前提

- review prompt は `scripts/spec_implementation_review_runner.sh` に焼き込まれている。
- runner は `specs/TEMPLATE.md` を除く `.md` が 1 件だけ存在する前提で動く。
- 0 件または複数件ある場合は fail-fast する。

## 注意

- spec 自体の誤りや、合意が必要な仕様変更が見つかったら実装修正前にユーザー確認を取る
- レビュー前に `make post-change` を通しておく
- docs 更新後は対象 spec を削除する
