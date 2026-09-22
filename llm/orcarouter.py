"""LlamaIndex LLM adapter for OrcaRouter's free chat model router."""
from __future__ import annotations

import os
import json
from pathlib import Path


API_BASE = "https://api.orcarouter.ai/v1"
DEFAULT_MODEL = "orcarouter/free"


def configured():
    return bool(os.environ.get("ORCAROUTER_API_KEY", "").strip())


def selected_model():
    return os.environ.get("ORCAROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def tier_model(tier: str) -> str:
    config_path = Path(__file__).resolve().parents[1] / "config" / "llm_tiers.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return config["model_routes"][tier]


def effective_model(requested_model: str | None = None) -> str:
    """Resolve the actual model under the default cost safety gate."""
    requested = requested_model or selected_model()
    allow_paid = os.environ.get("ORCAROUTER_ALLOW_PAID", "").strip().lower() == "true"
    return requested if allow_paid else DEFAULT_MODEL


def create_llm(model: str | None = None):
    api_key = os.environ.get("ORCAROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OrcaRouter API キーが設定されていません。サービス環境に ORCAROUTER_API_KEY を設定してください。")
    try:
        from llama_index.llms.openai_like import OpenAILike
    except ImportError as exc:
        raise RuntimeError("LlamaIndex の OrcaRouter アダプターがありません。requirements.txt の依存関係を再インストールしてください。") from exc
    # Paid or automatic tier routes are opt-in. The default keeps the demo on
    # the free route even when the complexity scorer selects A/B/C.
    actual_model = effective_model(model)
    return OpenAILike(
        model=actual_model,
        api_base=API_BASE,
        api_key=api_key,
        context_window=65536,
        is_chat_model=True,
        is_function_calling_model=False,
        timeout=90,
        max_retries=0,
    )


def safe_error_message(error: Exception):
    status_code = getattr(error, "status_code", None)
    error_code = None
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        nested = body.get("error", body)
        if isinstance(nested, dict):
            error_code = nested.get("error_reason") or nested.get("code")
    response = getattr(error, "response", None)
    if error_code is None and response is not None:
        try:
            response_body = response.json()
            nested = response_body.get("error", response_body) if isinstance(response_body, dict) else {}
            if isinstance(nested, dict):
                error_code = nested.get("error_reason") or nested.get("code")
        except Exception:
            pass
    if error_code == "err_free_access_denied":
        return "OrcaRouter 無料ルートがワークスペースの利用条件により拒否されました（err_free_access_denied）。有料ルートへの切替や再試行は行っていません。"
    if status_code == 429:
        return "OrcaRouter がリクエストを制限しました（HTTP 429）。料金のあるモデルへの切替は行っていません。"
    if status_code in (401, 403):
        return "OrcaRouter API キーが無効か、呼び出し権限がありません。"
    if status_code:
        return f"OrcaRouter の呼び出しに失敗しました（HTTP {status_code}）。"
    return "OrcaRouter に接続できませんでした。ネットワークと API 状態を確認してください。"
