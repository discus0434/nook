---
name: template-bootstrapper
description: テンプレート由来の初期化手順メモ。`my-nook` では通常実行しないが、初期 bootstrap 時に何を揃える想定だったかを参照できる。
license: See repository LICENSE
---

# Template Bootstrapper

## 注意

- この skill は新規リポジトリ向けの bootstrap 参考情報であり、既に稼働中の `my-nook` へそのまま適用する用途ではない。
- `my-nook` では、初期 bootstrap 相当の内容はすでに反映済みである。

## 参考にする項目

- `.codex/config.toml`
- repo-local `.codex/skills/`
- `AGENTS.md`
- `docs/`, `specs/`
- `Makefile` の `post-change` / spec review ターゲット
- `pyproject.toml` と `uv.lock`
- `.github/workflows/ci.yml`
- spec は作業中のみ保持し、完了後に削除する
