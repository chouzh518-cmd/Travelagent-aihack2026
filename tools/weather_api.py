from datetime import datetime

from .base import unavailable
from policy_import.store import now
from core.contracts import ToolResult

def query(request):
    """Return deterministic weather simulation for the demo; never claim live forecast data."""
    departure = request.get("departure_at") if isinstance(request, dict) else None
    destination = request.get("destination") if isinstance(request, dict) else None
    if not departure or not destination:
        return unavailable("天気検索")
    date_value = datetime.fromisoformat(departure).date()
    # The example route/date can demonstrate the warning path deterministically.
    severe = ("大阪" in destination and date_value.isoformat() == "2026-10-10") or date_value.day % 7 == 0
    if severe:
        item = {"date": date_value.isoformat(), "destination": destination, "severity": "severe",
                "condition": "大雨・強風（模擬）", "transport_risk": "高",
                "advice": "天候が安定する日へ変更し、出発前に交通機関の運行情報を再確認してください。"}
    else:
        item = {"date": date_value.isoformat(), "destination": destination, "severity": "normal",
                "condition": "大きな荒天なし（模擬）", "transport_risk": "低",
                "advice": "出発前に最新の予報と交通機関の運行情報を確認してください。"}
    return ToolResult(
        status="success", data_kind="simulation", source="ローカル模擬天気プロバイダー",
        queried_at=now(), data=[item],
        issues=["実際の天気 API には接続していません。出発前に最新予報を確認してください。"],
    )
