from datetime import datetime

from .base import unavailable
from policy_import.store import now
from core.contracts import ToolResult

def query(request):
    """Return an explicitly synthetic calendar check until an account is configured."""
    departure = request.get("departure_at") if isinstance(request, dict) else None
    destination = request.get("destination") if isinstance(request, dict) else None
    if not departure or not destination:
        return unavailable("カレンダー連携")
    date_text = datetime.fromisoformat(departure).date().isoformat()
    return ToolResult(
        status="success", data_kind="simulation", source="ローカル模擬カレンダー",
        queried_at=now(),
        data=[{"date": date_text, "status": "no_conflict", "title": "社内予定との重複は模擬上確認されませんでした。",
               "destination": destination}],
        issues=["実際の社内カレンダーには接続していません。予定の空き状況は必ず本人が確認してください。"],
    )
