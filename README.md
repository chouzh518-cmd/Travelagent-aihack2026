# 出張計画アシスタント

Python 製の出張計画支援デモです。登録済みプロジェクトの資料と利用者が入力した条件をもとに、規程根拠を検索し、模擬プランを比較して、計画書とメール下書きを作成します。画面、生成文、配布用説明は日本語です。

交通・宿泊・天気・カレンダーのサンプルは実際の照会結果ではありません。予約、承認、メール送信、規程適合の最終判断は行わず、利用者の確認が必要です。

## 主な機能

- `data/projects/catalog.json` からプロジェクトと関連資料を読み込みます。
- PDF、DOCX、Markdown、画像の資料をローカルで抽出/OCRし、Chroma/FastEmbed で検索します。
- 会話内容から場所、日付、時刻、予算、宿泊条件をローカルルールで抽出します。後から明示された値は今回の条件案に反映されます。
- 資料検索と OrcaRouter（任意）による質問応答を提供します。利用できない場合はルール処理とテンプレートへ縮退します。
- 交通・費用の模擬プランを 2 件表示し、利用者が選択したプランで計画書と編集可能なメール下書きを作成します。
- サーバー側で行程・費用・資料根拠を検証します。証拠不足や規程適用範囲が不明な場合、自動で適合と判定しません。

## 処理の流れ

```text
プロジェクト選択・資料追加
  → 日本語で条件を補足
  → 条件を確認して計画書を作成
  → 模擬プランと根拠を確認し、プランを選択
  → メール下書きを編集・コピー
```

## 構成

| パス | 用途 |
| --- | --- |
| `app.py` | HTTP サーバー、API、入力検証、アクセス制御 |
| `templates/`、`static/` | 日本語画面とブラウザー側の処理 |
| `agents/`、`rag/`、`llm/` | 資料に基づく質問応答と任意のモデル接続 |
| `core/` | 条件抽出、費用計算、行程検証 |
| `policy_import/` | 資料抽出、OCR、索引、引用根拠 |
| `tools/` | ローカル模擬データと外部連携の境界 |
| `data/projects/`、`data/offers/` | 公開用プロジェクト資料と見積りサンプル |
| `config/`、`schemas/` | 設定、API・データ形式 |
| `tests/` | 単体・HTTP API テスト |
| `docs/` | アーキテクチャ、データ登録、デモ、リリース確認 |

## 動作環境とローカル起動

Python 3.12 が必要です。初回のセマンティック検索時に FastEmbed モデル（約 220 MB）をダウンロードします。依存関係は [`requirements.txt`](requirements.txt) を参照してください。

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

macOS / Linux：

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python app.py
```

既定の URL は <http://127.0.0.1:8765/>、ヘルスチェックは `/healthz` です。ローカルではログインを要求しません。パスワードなしの状態でインターネットに公開しないでください。

## 環境変数

| 変数 | 用途 |
| --- | --- |
| `APP_BIND_HOST` | 待ち受け先。ローカル既定値は `127.0.0.1`、Render は `0.0.0.0`。 |
| `PORT` | HTTP ポート。ローカル既定値は `8765`、Render Blueprint は `10000`。 |
| `APP_DATA_DIR` | 実行時資料・索引・出力の保存先。Render 設定は `/var/data`。 |
| `APP_ACCESS_PASSWORD` | 公開環境で必須のチーム共有アクセスパスワード。 |
| `APP_TRUSTED_HOSTS` | 許可する正確なホスト名をカンマ区切りで指定。公開時に必要。 |
| `RENDER_EXTERNAL_HOSTNAME` | Render が設定するホスト名。 |
| `ORCAROUTER_API_KEY` | 任意。設定しない場合、モデル機能は縮退動作。 |
| `ORCAROUTER_MODEL` | モデルルート。既定値は `orcarouter/free`。 |
| `ORCAROUTER_ALLOW_PAID` | `true` のときだけ有料ルートを許可。既定では無効。 |

秘密情報は Render の Environment Variables に登録し、ソースコードや Git に保存しないでください。

## Render へのデプロイ

リポジトリの [`render.yaml`](render.yaml) は Docker Web Service、`/healthz`、ポート `10000` を設定します。Blueprint の初回同期では `APP_ACCESS_PASSWORD` を設定してください。モデルを使用する場合は、デプロイ後に `ORCAROUTER_API_KEY` を Render の環境変数へ登録します。

無料 Web Service のファイルシステムは一時的で、永続ディスクを利用できません。アップロード資料や索引は再起動・再デプロイ・スリープ後に失われる可能性があります。永続保存が必要な運用には無料プランを使用しないでください。詳細は [`DEPLOY_RENDER.md`](DEPLOY_RENDER.md) を参照してください。

## テスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

macOS / Linux：

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

テストには公開サンプル資料のローカルスナップショットが必要です。空の環境では `scripts/download_sources.py` と `scripts/import_demo.py` を実行して用意します。実行時データは Git に追加しないでください。

## API の概要

- `GET /api/projects`、`GET /api/snapshots`：プロジェクトと資料
- `POST /api/agent/chat`：資料に基づく質問応答
- `POST /api/intent/extract`：ローカルルールによる条件抽出
- `POST /api/simulation/offers`、`POST /api/travel-context`：模擬プラン・模擬状況
- `POST /api/run`：行程、費用、規程根拠の検証
- `POST /api/email/generate`：メール下書き
- `POST /api/import`、`DELETE /api/documents/{snapshot_id}`：資料の追加・セッション内アップロードの削除
- `GET /healthz`：ヘルスチェック

## セキュリティと制約

- `data/projects/` の資料は、公開許可と匿名化を確認してから配布してください。
- アップロード資料、抽出結果、索引、実行記録、メール下書き、API Key は Git に含めないでください。
- 公開 API はアクセスパスワード、Host/Origin 検証、リクエスト制限を使用します。アクセスパスワードはチーム共有で、個人別権限や企業 ID 管理ではありません。
- モデルが構造化条件や規程の根拠を推測で補うことはありません。未確認事項は利用者が確認してください。
- 鉄道、航空、宿泊、在庫、天気、カレンダーの本番 API やメール送信は接続されていません。

## 関連資料

- [`docs/AGENT_ARCHITECTURE.md`](docs/AGENT_ARCHITECTURE.md)：構成と責任範囲
- [`docs/PROJECT_DATA_REGISTRATION.md`](docs/PROJECT_DATA_REGISTRATION.md)：プロジェクト資料の登録方法
- [`docs/RELEASE_READINESS.md`](docs/RELEASE_READINESS.md)：検証状況と公開前の確認

## ライセンスと資料の出所

本リポジトリに個別のオープンソースライセンス宣言はありません。第三者資料、提供資料、OCR 結果の著作権・利用条件・再配布許可は個別に確認してください。
