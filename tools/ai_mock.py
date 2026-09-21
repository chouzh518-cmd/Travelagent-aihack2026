import json
import re
from datetime import datetime
from llama_index.core.llms import ChatMessage
from llm.orcarouter import create_llm

def generate_smart_plans(trip_data):
    # 將 Pydantic 模型轉為字典
    trip_dict = trip_data.model_dump() if hasattr(trip_data, "model_dump") else trip_data
    
    prompt = f"""
    あなたは出張手配APIのモックサーバーです。
    以下の出張リクエストを読み取り、現実的な「新幹線プラン」と「飛行機プラン」の2つの見積りを生成し、指定のJSON配列のみを出力してください。

    【出張リクエスト】
    {json.dumps(trip_dict, ensure_ascii=False)}

    【厳格な要件】
    1. リクエストの出発地(origin)、目的地(destination)、日時(departure_at)に合わせた現実的なデータを作ること。
    2. 宿泊が必要(lodging_required: true)な場合は、ホテルの費用も含めること。
    3. Markdownタグ(```json等)は一切使わず、純粋なJSON配列 [{{...}}, {{...}}] のみを出力すること。

    【JSON構造のテンプレート】
    [
      {{
        "schema_version": "1.0",
        "plan_id": "ai_plan_01",
        "trip_id": "{trip_dict.get('trip_id', 'trip_001')}",
        "version": "v1.0",
        "data_kind": "simulation",
        "available": true,
        "valid_until": "2026-12-31T23:59:59+09:00",
        "source": "ai_mock_api",
        "queried_at": "2026-09-21T12:00:00+09:00",
        "legs": [
          {{ "direction": "outbound", "mode": "Shinkansen", "origin": "{trip_dict.get('origin', 'Tokyo')}", "destination": "{trip_dict.get('destination', 'Osaka')}", "departure_at": "2026-09-30T09:00:00+09:00", "arrival_at": "2026-09-30T11:30:00+09:00", "source": "train_api" }},
          {{ "direction": "return", "mode": "Shinkansen", "origin": "{trip_dict.get('destination', 'Osaka')}", "destination": "{trip_dict.get('origin', 'Tokyo')}", "departure_at": "2026-09-30T17:00:00+09:00", "arrival_at": "2026-09-30T19:30:00+09:00", "source": "train_api" }}
        ],
        "costs": [
          {{ "description": "新幹線チケット", "category": "transport", "currency": "JPY", "unit_amount": 14500, "quantity": 2, "unit": "ticket", "taxes_included": true, "source": "train_api", "queried_at": "2026-09-21T12:00:00+09:00" }}
        ],
        "zero_cost_reasons": {{ "transfer": "徒歩圏内", "per_diem": "日当なし", "hotel": "宿泊不要", "transport": "特になし" }}
      }}
    ]
    """
    
    try:
        llm = create_llm()
        response = llm.chat([ChatMessage(role="user", content=prompt)])
        match = re.search(r'\[.*\]', response.message.content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return []
    except Exception as e:
        print(f"AI Mock Generation Error: {e}")
        return []