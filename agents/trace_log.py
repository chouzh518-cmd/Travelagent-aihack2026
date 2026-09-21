"""Private, content-minimized execution records for developer diagnostics."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.Lock()


def new_trace_id() -> str:
    return uuid.uuid4().hex


def record(trace_id: str, stage: str, provider: str, status: str, *,
           model_route: str | None = None, tier: str | None = None,
           score: int | None = None, features: dict | None = None,
           data_kind: str | None = None, source: str | None = None,
           evidence_count: int | None = None, retrieval_method: str | None = None,
           error_code: str | None = None, detail: str | None = None) -> None:
    """Append one safe-to-share diagnostic event; never persist prompts or API keys."""
    item = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trace_id": trace_id,
        "stage": stage,
        "provider": provider,
        "status": status,
        "model_route": model_route,
        "tier": tier,
        "score": score,
        "features": features,
        "data_kind": data_kind,
        "source": source,
        "evidence_count": evidence_count,
        "retrieval_method": retrieval_method,
        "error_code": error_code,
        "detail": detail,
    }
    path = ROOT / "output" / "agent-traces" / "agent-trace.jsonl"
    line = json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(line)
    except OSError:
        # Diagnostics must never interrupt the user's workflow.
        return


def error_code(message: str | None) -> str | None:
    """Return a recognized provider error identifier without storing its message."""
    if not message:
        return None
    known = ("err_free_access_denied", "free_rate_limited")
    return next((value for value in known if value in message), None)
