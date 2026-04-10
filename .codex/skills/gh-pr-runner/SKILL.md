---
name: gh-pr-runner
description: "`gh` CLI を用いたブランチ作成、PR 作成、レビュー確認、コメント返信、マージの流れを簡潔に再利用するガイド。"
license: See repository LICENSE
---

# gh PR Flow

## トリガ

- 変更を PR にまとめるとき
- レビュー指摘に対応するとき

## Quickstart

1. ブランチ作成: `git checkout -b <branch>`
2. 差分確認: `git status`, `git diff`
3. 検証: `make post-change`
4. PR 作成: `gh pr create --title "..." --body "..."`
5. レビュー確認: `gh pr view` / `gh pr view --web`
6. コメント返信: `gh pr comment <PR#> --body "..."`
7. マージ: `gh pr merge --squash`

## ベストプラクティス

- PR 本文には目的、主要変更点、テスト結果、既知の注意点を書く
- 中規模以上の変更なら `specs/` の技術仕様書要約も添える
- force push や amend はリポジトリ方針と合意がある場合のみ行う
