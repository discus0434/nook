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

1. `make spec-review PROMPT="<prompt>"` を実行する
2. 返ってきた GAP / FIX をもとに spec を修正する
3. 重要な曖昧さや不足が消えるまで繰り返す

## プロンプト例

```markdown
You are a read-only spec-review agent. Do not modify files.
1. Read the target spec in specs/.
2. Check whether the goal, scope, files, modules, tests, docs updates, and verification steps are concrete enough to implement.
3. Identify missing requirements, contradictions, risky assumptions, and over-engineering.
4. Output OK / GAP / FIX with severity (Critical/Major/Minor/Info).
5. Cite specific spec sections when possible.
```

## チェックポイント

- 変更対象ファイルが具体的か
- 自動テストと手動チェックの線引きが明確か
- `make post-change` と必要な `make manual-*` が定義されているか
- docs 更新箇所まで spec に含まれているか
- 完了後に spec を削除する前提が明記されているか
