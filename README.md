# nook

nook は、日々公開される技術ニュース、論文、OSS、プロダクト情報を収集して日本語で要約し、Web でまとめて読めるようにするアプリです。ローカル環境でも AWS でも動かせます。

## できること

- Hacker News、Product Hunt、GitHub Trending、Reddit、RSS、Google Alerts、論文情報をまとめて収集する
- 各記事や論文を日本語で要約する
- 日付ごとに情報を整理して Web で読む
- 各記事に対して追加の質問を送る
- ローカル環境と AWS のどちらでも同じ構成で動かす

対応している主な情報源は次のとおりです。

- Hacker News
- Product Hunt
- GitHub Trending
- Reddit
- 技術ブログなどの RSS
- Google Alerts の RSS
- Hugging Face Daily Papers 経由の論文情報
- `configs/tech_news/feed.toml` に定義した任意の RSS 一覧

補足として、`reddit_explorer` は取得した投稿全体を upvote の多い順に並べて出力し、`paper_summarizer` は Hugging Face Daily Papers の upvote が多い論文から順に処理します。`tech_news` は複数の RSS を横断して集約でき、feed ごとに任意の `keywords` フィルタを付けられます。

## 前提環境

- Python 3.11
- `uv`
- 利用する LLM の API キー
  - 例: `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`
- Reddit API の認証情報
- Product Hunt API Key と Developer Token
- Google Alerts を使う場合は Google アカウント
- AWS にデプロイする場合だけ `aws` CLI と AWS CDK

## はじめ方

1. リポジトリを取得します。

   ```bash
   git clone https://github.com/discus0434/nook.git
   cd nook
   ```

2. `.env` を作成します。

   ```bash
   cp .env.example .env
   ```

3. `.env` に必要な値を設定します。

   ```dotenv
   LLM_MODEL=openai:gpt-5.2
   OPENAI_API_KEY=your_openai_api_key
   REDDIT_CLIENT_ID=your_reddit_client_id
   REDDIT_CLIENT_SECRET=your_reddit_client_secret
   REDDIT_USER_AGENT=your_reddit_user_agent
   PRODUCT_HUNT_API_KEY=your_product_hunt_api_key
   PRODUCT_HUNT_DEVELOPER_TOKEN=your_product_hunt_developer_token

   # 利用する provider に合わせて必要なキーを設定してください
   # GOOGLE_API_KEY=your_google_api_key
   # ANTHROPIC_API_KEY=your_anthropic_api_key
   # OPENROUTER_API_KEY=your_openrouter_api_key

   # AWS で独自の Secrets Manager 名を使う場合だけ設定
   # NOOK_AWS_SECRET_ID=nook/runtime-secrets
   ```

   `LLM_MODEL` には `openai:gpt-5.2` のような provider/model 形式の文字列を指定します。viewer の追加質問では、対応している provider の場合だけ組み込みの Web 検索を使います。非対応 provider では通常のチャットとして動きます。

4. 依存関係をインストールします。

   ```bash
   uv sync --dev
   ```

## ローカルで使う

Ubuntu では `systemd --user`、macOS では `launchd` を使って viewer と収集ジョブを登録できます。

```bash
make local-register
```

登録後は次の URL で viewer を開けます。

```text
http://127.0.0.1:8080
```

個別の収集ジョブを単発で実行したいときは `SERVICE` を指定します。

```bash
make local-trigger SERVICE=reddit_explorer
```

登録を外す場合は次を実行します。

```bash
make local-unregister
```

## AWS にデプロイする

AWS CLI と AWS CDK の設定が済んでいれば、次のコマンドでデプロイできます。

```bash
make cdk-deploy
```

このコマンドは `.env` と現在の環境変数を読み込み、`NOOK_AWS_SECRET_ID` で指定した Secrets Manager secret に必要な認証情報を反映したうえで CDK deploy を実行します。完了後に viewer の Function URL が表示されます。

## 設定ファイル

このリポジトリに含まれている `configs/*.toml` はサンプルです。公開版に同梱されている内容をそのまま使うのではなく、自分の監視対象に合わせて編集してください。

- `configs/reddit_explorer/subreddits.toml`
  - 収集対象の subreddit を定義します。
- `configs/github_trending/languages.toml`
  - 追跡する言語を定義します。
- `configs/tech_feed/feed.toml`
  - 技術ブログなどの RSS を定義します。
- `configs/tech_news/feed.toml`
  - 複数 RSS を横断して集約する feed 一覧を定義します。
  - 各 feed は `name`、`url`、`feed_name_display` を持ち、`keywords` は任意です。
  - `keywords` を指定した場合は title、summary、content に一致した記事だけを残します。
  - 同じ URL は 1 件にまとめ、各 feed からは 1 日あたり最大 10 件まで処理します。
- `configs/google_alerts/google_alerts.toml`
  - Google Alerts の RSS を定義します。
  - 同梱している URL はサンプルなので、実際に使う前に自分の RSS URL に置き換えてください。

## ディレクトリ構成

- `nook/services/`
  - collector と viewer の本体です。
- `nook/deploy/aws/`
  - CDK、Lambda handler、AWS 向けの deploy 処理です。
- `nook/deploy/local/`
  - ローカル実行と service 登録まわりです。
- `configs/`
  - 各 collector が参照するサンプル設定ファイルです。
- `docs/DESIGN.md`
  - 現在の設計をまとめたドキュメントです。

## 画面例

PC 画面:

![PC 画面](assets/screenshots/web-screenshot.webp)

モバイル画面:

![モバイル画面](assets/screenshots/mobile-screenshot.webp)

チャット画面:

![チャット画面](assets/screenshots/chat-screenshot.webp)

## ライセンス

このプロジェクトは GNU Affero General Public License v3.0 のもとで公開しています。詳細は [LICENSE](LICENSE) を参照してください。

## 連絡先

- GitHub Issues
- X: [@IMG_5955](https://x.com/IMG_5955)
