---
name: utility-helper
description: "`rg` / `fd` / `bat` / `jq` / `yq` / `delta` など、ローカル探索と差分確認を高速化する補助ツールの短縮ガイド。"
license: See repository LICENSE
---

# Utility Helper

## トリガ

- コード検索が遅い / ノイズが多い
- JSON / YAML / TOML から値を抜きたい
- 差分が読みにくい

## 速習コマンド

- `rg "pattern" nook tests docs`
- `rg --files nook tests docs`
- `fd feed.toml nook`
- `bat -n pyproject.toml`
- `jq '.watch.exclude' cdk.json`
- `git diff | delta`

## 運用メモ

- まず `rg` を優先し、`grep` は必要時のみ使う
- README / docs / spec の参照先確認にも `rg` を使う
