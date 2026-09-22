# 出張プロジェクト情報の登録

社員向け画面のプロジェクト選択肢は `data/projects/catalog.json` から読み込みます。各プロジェクトは ID、表示名、Markdown 資料の一覧で登録します。

Markdown 資料は `data/projects/` 配下に置き、カタログの `path` に正確な相対パスを記載します。選択時に原文が読み込まれ、次の全角ラベルを含む箇条書きから登録値を抽出します。

| Markdown ラベル | 抽出先 |
| --- | --- |
| `出張プロジェクト` | project_name |
| `出発地` | origin |
| `目的地` | destination |
| `予算上限` | budget_jpy |
| `出張期間` | duration_limit_days |
| `顧客到着期限` | arrival_deadline |
| `出張目的` | purpose |
| `出発日時` | departure_at |
| `到着期限` | arrive_by |
| `帰着期限` | return_by |
| `宿泊` | lodging_required |

書式は `- 出発地：東京` のように、ハイフン、ラベル、全角コロン、値の順です。金額は円、期間は「1日以内」の形で記載します。未確定値は `未入力` または `未確認` とし、計画書では不足条件として表示します。
