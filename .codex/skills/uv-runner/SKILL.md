---
name: uv-runner
description: "`uv` を使った依存管理、実行、ロック更新、トラブルシュートの手順集。"
license: See repository LICENSE
---

# uv Runner

## Quickstart

- 環境構築: `uv sync --dev`
- 品質確認: `make post-change`
- 単発実行: `uv run python path/to/script.py`

## よく使うコマンド

- `uv run pytest`
- `uv run pytest -k "<pattern>"`
- `uv run ruff check .`
- `uv run ruff format .`
- `uv lock`

## 運用ルール

- ルート依存は `pyproject.toml` と `uv.lock` に集約する
- `cdk.json` は `uv run python app.py` 前提で動く
- Lambda 配布依存は各関数配下の `requirements.txt` に残す

## トラブルシュート

- venv が崩れたら: `rm -rf .venv && uv sync --dev`
- ロック差分を更新したら: `uv lock`
- 実行環境差分を避けたいときは `uv sync --frozen --dev`
