import json
from pathlib import Path
from core.contracts import PlanInput, ToolResult
from policy_import.store import now


def unavailable(name):
    return ToolResult(status="not_configured", source=None, queried_at=now(), data=[],
                      issues=[f"{name}：動作確認済みの API、認証情報、応答項目の対応表が未設定です。"])


def load_plans(path: str | Path):
    """Load user-supplied internal-contract records, never guess provider mappings."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("見積りファイルは PlanInput 形式の JSON 配列にしてください。")
        plans = [PlanInput.model_validate(item) for item in raw]
        if len({p.plan_id for p in plans}) != len(plans):
            raise ValueError("plan_id が重複しています。各見積りに異なる ID を指定してください。")
        return ToolResult(status="success" if plans else "no_results", source=str(path), queried_at=now(),
                          data=[p.model_dump() for p in plans], issues=[])
    except (ValueError, OSError) as exc:
        return ToolResult(status="invalid_input", source=str(path), queried_at=now(), data=[], issues=[str(exc)])
