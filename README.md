# 出張計画アシスタント

出張条件の整理、利用者が追加した資料の検索、計画書の作成、メール下書きの編集を行う日本語 Web アプリです。

## 主な機能

- 会話または条件欄から出発地、目的地、日程、目的などを整理します。アップロード資料から読み取れる条件も下書きに反映し、会話・フォームで明示した値を優先します。
- PDF、DOCX、Markdown、画像を読み取り、OCR と資料内検索に使います。回答・計画書には検索で得た根拠を示します。根拠がない内容や規程の適用可否は推測しません。
- 交通・宿泊の比較画面には二つの模擬案を表示します。実在する便、施設、料金、空席ではありません。入力された予算上限を超える場合は画面で警告します。
- 模擬案と資料根拠を使った計画書を日本語で作成し、確認・保存できます。
- メール文を編集可能な下書きとして作成し、コピーできます。メールは送信しません。
- OrcaRouter が利用できない場合も、条件抽出、模擬案、計画書のひな形、メールのひな形を利用できます。AI による会話回答は利用できない場合があります。

## 流れ

```text
条件を入力または資料を追加
  → 条件を確認
  → 二つの模擬案と資料根拠を確認
  → 計画書を保存
  → メール下書きを編集・コピー
```

## ローカル起動

Python 3.12 が必要です。初回の資料索引作成時には FastEmbed のモデル（約 220 MB）がダウンロードされます。

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

ブラウザーで <http://127.0.0.1:8765/> を開きます。ローカル起動ではアクセスコードは不要です。パスワードなしでインターネットに公開しないでください。

## OrcaRouter の設定

AI 会話・翻訳にはサーバー側の `ORCAROUTER_API_KEY` が必要です。Web サイトの利用者が個別に API キーを用意する必要はありません。公開環境では管理者が Render の環境変数に設定します。キーをソースコードや Git に登録しないでください。

| 環境変数 | 用途 |
| --- | --- |
| `APP_BIND_HOST` | 待ち受け先。ローカル既定値は `127.0.0.1`、Render は `0.0.0.0`。 |
| `PORT` | HTTP ポート。既定値は `8765`、Render Blueprint は `10000`。 |
| `APP_DATA_DIR` | 資料、索引、出力の保存先。Render 設定は `/var/data`。 |
| `APP_ACCESS_PASSWORD` | 公開環境で必要なチーム共有アクセスコード。 |
| `APP_TRUSTED_HOSTS` | Render 以外で公開するときに許可する完全一致ホスト名。 |
| `RENDER_EXTERNAL_HOSTNAME` | Render が設定するホスト名。 |
| `ORCAROUTER_API_KEY` | 任意のサーバー側 AI 接続キー。未設定時はひな形等に縮退。 |
| `ORCAROUTER_MODEL` | モデルルート。既定値は `orcarouter/free`。 |

## Render

[`render.yaml`](render.yaml) は Docker Web Service、ヘルスチェック、ポート `10000` を設定します。初回同期時に `APP_ACCESS_PASSWORD` を設定し、AI 機能を使う場合は `ORCAROUTER_API_KEY` も Render の環境変数に登録します。無料サービスのローカル保存データは再起動・再デプロイ後に失われる場合があります。詳細は [`DEPLOY_RENDER.md`](DEPLOY_RENDER.md) を参照してください。

## 新しいクローンでテスト

テストには公開サンプル資料をローカルに取り込みます。資料と索引は Git に登録されません。

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe scripts/download_sources.py
.\.venv\Scripts\python.exe scripts/import_demo.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

macOS / Linux：

```bash
./.venv/bin/python scripts/download_sources.py
./.venv/bin/python scripts/import_demo.py
./.venv/bin/python -m unittest discover -s tests -v
```

## 制約と安全性

- 交通、宿泊、空席、天気、カレンダーの値は模擬データです。実際の予約・購入には使えません。
- 会社規程との適合や、規程上の承認要否を自動確定しません。原文と適用範囲を利用者が確認してください。
- メール送信、承認、決済は行いません。
- アップロード資料、索引、実行記録、API キーは Git に含めません。`.gitignore` で実行時データを除外しています。
- 公開 API はアクセスコード、Host/Origin 検証、リクエスト制限で保護されます。アクセスコードはチーム共有で、個人別権限ではありません。

詳細設計は [`docs/AGENT_ARCHITECTURE.md`](docs/AGENT_ARCHITECTURE.md)、公開前の確認事項は [`docs/RELEASE_READINESS.md`](docs/RELEASE_READINESS.md) を参照してください。
