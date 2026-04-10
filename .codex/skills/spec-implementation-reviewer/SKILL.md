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

1. `make spec-implementation-review PROMPT="<prompt>"` を実行する
2. GAP / FIX をもとにコードやテストを修正する
3. Critical / Major がなくなるまで繰り返す

## プロンプト例

```markdown
You are a read-only spec-implementation-review agent. Do not modify files.
1. Read the target spec in specs/.
2. Extract promised behaviors, touched files, tests, and docs updates.
3. Compare them with the current repository.
4. Output OK / GAP / FIX with severity (Critical/Major/Minor/Info).
5. Cite concrete file paths and missing tests when possible.
```

## 注意

- spec 自体の誤りや、合意が必要な仕様変更が見つかったら実装修正前にユーザー確認を取る
- レビュー前に `make post-change` を通しておく
- docs 更新後は対象 spec を削除する
