# Design Doc

## アーキテクチャ概要

Nook は collector 群と viewer を `nook/services/` 配下のマイクロサービス package として持ち、実行面だけを adapter で切り替える構成になった。AWS では CDK + Lambda + EventBridge + S3、local では Ubuntu `systemd --user` または macOS `launchd` + filesystem storage を使う。viewer はどちらの runtime でも FastAPI を使うが、storage と job trigger は runtime ごとに差し替える。

## 実行モード

- AWS:
  - `nook/deploy/aws/stack.py` が Lambda 群、viewer Function URL、日次 EventBridge を定義する。
  - `nook/deploy/aws/cli.py` は repo root の `.env` と process env を merge し、その env で Secrets Manager secret bootstrap と CDK 実行を行う。
  - collector handler は `nook/deploy/aws/handlers/` の薄い wrapper で、core logic は `nook/services/` に置く。
  - Lambda environment には `BUCKET_NAME`、`LLM_MODEL`、`NOOK_RUNTIME_MODE`、`NOOK_STORAGE_BACKEND`、`NOOK_AWS_SECRET_ID` を渡す。runtime credential は Secrets Manager から読む。
  - Markdown と補助 state は S3 に保存する。
- Local:
  - `nook/deploy/local/cli.py` が service 登録、削除、viewer 起動、collector 単発起動を担当する。
  - Ubuntu は `~/.config/systemd/user/`、macOS は `~/Library/LaunchAgents/` に manifest を生成し、manifest には absolute `uv` path を埋め込む。
  - systemd collector unit は `TimeoutStartSec=15min` を持つ。
  - Markdown は `NOOK_DATA_DIR` 配下、未指定なら `~/.local/share/my-nook/data` に保存する。

## モジュール構成

- `app.py`
  - CDK 用の最小 entrypoint。`nook.deploy.aws.app` を呼ぶ。
- `nook/services/catalog.py`
  - 全サービス名、種別、日次スケジュールを定義する。
- `nook/services/storage.py`
  - `S3StorageBackend` と `FilesystemStorageBackend` を持ち、viewer retry 用に Markdown の更新時刻も返す。
- `nook/services/collector_storage.py`
  - collector から daily markdown / state を service 名付きで扱う thin helper。
- `nook/services/config.py`
  - repo root から `configs/<service>/...` を解決し、TOML を読む helper。
- `nook/services/runtime.py`
  - runtime mode、repo root、viewer listen address、job invoker を解決する。
- `nook/services/runtime_secrets.py`
  - local env と AWS Secrets Manager から runtime credential を解決する。fixed app secret に加えて `*_API_KEY` を runtime secret として扱い、AWS runtime では process env へ注入する。
- `nook/services/llm_client.py`
  - PydanticAI client の thin wrapper。必須 env `LLM_MODEL` を既定モデルとして解決し、transient な network timeout / connection error と retryable HTTP status を retry する。
  - `google-gla` / `google-vertex` では thread / Lambda runtime での event loop conflict を避けるため、呼び出しごとに dedicated `httpx.AsyncClient` と concrete Google model を組み立て、実行後に close する。
  - 既に running event loop がある call site では `Agent.run_sync()` を直接叩かず、worker thread へ退避して同期 API を維持する。
  - text output、structured output、viewer chat 用 prompt を共通化する。viewer chat search は provider が対応している場合のみ built-in `WebSearchTool` を使う。
- `nook/services/viewer/app.py`
  - storage / job invoker 注入型の FastAPI app factory を提供し、初期表示用の server-render context も template へ渡す。chat request では `app_name + date + article_id` から対象 article instance を再解決する。
- `nook/services/viewer/content.py`
  - viewer の対象 service 一覧、初期表示用 tab / article list / TOC の組み立て、Markdown 読み出し、article 解決、retry 実行を担当する。Markdown API payload に `articles` と `updated_at` を含め、`previous_updated_at` が一致する stale record は 404 にする。retry payload には `started_at` を含める。
- `nook/services/viewer/chat.py`
  - link 抽出、追加コンテキスト収集、chat prompt 構築を担当する。
- `nook/services/viewer/fetch.py`
  - 外部 URL の本文抽出を担当する。
- `nook/services/viewer/weather.py`
  - viewer の天気表示用データを取得する。
- `nook/services/viewer/static/`
  - viewer の CSS / JavaScript asset を置く。
- `nook/services/<collector>/service.py`
  - collector の core logic を持つ package。Lambda handler は置かず、設定は `configs/` から読む。
  - `paper_summarizer` は論文本文が大きいため、他 collector より長い LLM request timeout を使う。
  - `paper_summarizer` は Hugging Face papers API の `upvotes` を使って新着 paper を降順に並べ、既読 ID を除いた順で処理する。
  - `reddit_explorer` は設定された subreddit 群から集めた post を一度集約し、`upvotes` 降順で markdown 化する。
- `nook/services/registry.py`
  - service 名から collector runner / class を解決する。
- `nook/deploy/aws/handlers/`
  - Lambda handler 群。EventBridge / Lambda invoke を受けて core service を呼ぶ唯一の entrypoint。
- `nook/deploy/aws/runtime_config.py`
  - AWS stack config、runtime environment、requirements path、bundle に含める source dir を定義する。
  - `paper_summarizer` は 2048 MB、それ以外の LLM-heavy collector (`product_hunt`, `hacker_news`, `github_trending`, `reddit_explorer`, `tech_feed`, `google_alerts`, `tech_news`) と `viewer` は 512 MB を使う。
- `nook/deploy/aws/secret_bootstrap.py`
  - deploy 前の Secrets Manager upsert を担当する。
- `nook/deploy/aws/requirements/`
  - Lambda runtime dependency manifest 群を置く。
- `nook/deploy/local/manifests.py`
  - systemd unit / timer と launchd plist を生成する。`NOOK_UV_EXECUTABLE` と collector timeout を manifest に反映する。
- `Makefile`
  - AWS 系ターゲットの前に `cdk.out` を掃除し、stale asset が残らないようにする。

## データフロー

### AWS

1. `make cdk-deploy` は repo root の `.env` と process env を merge した credential を Secrets Manager secret へ upsert してから CDK deploy を実行する。
2. EventBridge が collector Lambda を日次で起動する。
3. collector handler が `nook/services/registry.py` 経由で core service を実行する。
4. collector / viewer は runtime で Secrets Manager から credential を取得し、`StorageBackend` 越しに S3 へ Markdown / state を読み書きしながら外部 API / RSS / LLM を使う。
   collector config の TOML は bundle された `configs/` から読む。
5. viewer Lambda は S3 から Markdown を読み、Function URL 経由で UI と chat API を提供する。
6. viewer の retry API は collector Lambda を非同期 invoke する。

### Local

1. `local-register` が viewer 常駐 service と collector scheduled service を user 領域に登録する。
2. collector service は `uv run python -m nook.deploy.local.cli run-job <service>` を実行する。手動発火は `make local-trigger SERVICE=<service>` を使う。
3. local CLI は filesystem backend を選び、collector / viewer は同じ `StorageBackend` abstraction で local filesystem を直接読み書きする。viewer からの retry は manifest が埋め込んだ `NOOK_UV_EXECUTABLE` か repo `.venv/bin/uv` を使って collector command を組み立てる。
   collector config の TOML は repo root の `configs/` から読む。
4. viewer service は filesystem backend から Markdown を読み、retry API では local subprocess で collector を再起動する。

## Viewer 構成

- template は `nook/services/viewer/templates/index.html` で nav / 初期本文 / TOC まで server-side render する。これにより `viewer.js` が走らないブラウザでも最低限の閲覧は成立する。
- active service を開くと、その service の article section を `---` 区切りで分解して縦積み表示する。各 article section には独立した chat log / form を持つ。
- 画面 state は server から JSON でも渡し、`nook/services/viewer/static/viewer.js` が hydrate 後の tab 切り替え、retry polling、article 単位 chat、weather refresh を担当する。
- article 本文と TOC 用 heading は backend で HTML / anchor まで確定させ、browser 側はその server-render 済み payload をそのまま使う。TOC は active service 内の全 article heading をフラットに列挙する。retry polling は Markdown の存在ではなく `updated_at` の変化を見て完了判定し、backend は `previous_updated_at` と一致する stale record を返さない。
- article chat は client が `article_id` と `date` を送り、backend が storage から該当 article markdown を再抽出して prompt を組む。`article_id` は article content fingerprint を種にした per-instance ID で、service/date ごとの state へ `canonical_markdown` とともに保存し、reload / retry 後も既存 article instance の ID を可能な限り維持する。
- backend は app, content, chat, fetch, weather に責務分割し、unit test で個別検証できる構造にしている。

## 設定 / データモデル

- runtime env:
  - `LLM_MODEL`: 必須の provider/model string
  - `NOOK_RUNTIME_MODE`: `aws` または `local`
  - `NOOK_REPO_ROOT`: config path と local runtime path 解決の基準 repo root
  - `NOOK_STORAGE_BACKEND`: `s3` または `filesystem`
  - `NOOK_DATA_DIR`: local storage root
  - `NOOK_LOCAL_HOST`, `NOOK_LOCAL_PORT`: local viewer bind 設定
  - `NOOK_UV_EXECUTABLE`: local viewer が retry 用 collector command を組み立てるときの absolute `uv` path
- `NOOK_AWS_SECRET_ID`: AWS runtime が参照する Secrets Manager secret name / ARN
- local / deploy bootstrap 用 env:
  - `LLM_MODEL` (required)
  - `*_API_KEY` (`OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` など)
  - `REDDIT_CLIENT_ID`
  - `REDDIT_CLIENT_SECRET`
  - `REDDIT_USER_AGENT`
  - `PRODUCT_HUNT_API_KEY`
  - `PRODUCT_HUNT_DEVELOPER_TOKEN`
- AWS secret JSON keys:
  - `*_API_KEY`
  - `REDDIT_CLIENT_ID`
  - `REDDIT_CLIENT_SECRET`
  - `REDDIT_USER_AGENT`
  - `PRODUCT_HUNT_API_KEY`
  - `PRODUCT_HUNT_DEVELOPER_TOKEN`
- local storage layout:
  - Markdown: `<data_dir>/<service>/<YYYY-MM-DD>.md`
  - 補助 state: `<data_dir>/_state/<service>/<key>`
- collector config layout:
  - `configs/tech_feed/feed.toml`
  - `configs/tech_news/feed.toml`
  - `configs/google_alerts/google_alerts.toml`
  - `configs/github_trending/languages.toml`
  - `configs/reddit_explorer/subreddits.toml`
- viewer markdown payload:
  - `markdown`
  - `articles[]`
  - `articles[].article_id`
  - `articles[].title`
  - `articles[].html`
  - `articles[].headings[]`
  - `articles[].headings[].text`
  - `articles[].headings[].anchor`
  - `articles[].headings[].level`
  - `updated_at`
- viewer chat payload:
  - `article_id`
  - `date`
  - `chat_history`
  - `message`
- viewer retry payload:
  - `message`
  - `started_at`
- paper_summarizer state key:
  - `arxiv_ids-<YYYY-MM-DD>.txt`

## 開発フロー設計

1. `uv sync --dev` でルート環境を構築する。
2. 中規模以上の変更では `specs/TEMPLATE.md` をコピーして技術仕様書を作る。
3. `tests/unit/` に失敗テストを先に追加し、最小実装で通す。
4. `make post-change` で `ruff format` / `ruff check` / `pytest` を実行する。
5. AWS 変更は `make cdk-synth`, `make cdk-diff`, `make cdk-deploy` で検証する。これらのターゲットは実行前に `cdk.out` を削除する。
6. local service 変更は `make local-register`, `make local-unregister`, `make local-viewer`, `make local-trigger SERVICE=<service>` で確認する。
