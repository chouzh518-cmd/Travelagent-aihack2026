"""LlamaIndex LLM adapter for OrcaRouter's free chat model router."""
from __future__ import annotations

import os


API_BASE = "https://api.orcarouter.ai/v1"
DEFAULT_MODEL = "orcarouter/free"


def configured():
    return bool(os.environ.get("ORCAROUTER_API_KEY", "").strip())


def selected_model():
    return os.environ.get("ORCAROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def create_llm():
    api_key = os.environ.get("ORCAROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("尚未配置 OrcaRouter API Key。请在服务环境中设置 ORCAROUTER_API_KEY。")
    try:
        from llama_index.llms.openai_like import OpenAILike
    except ImportError as exc:
        raise RuntimeError("LlamaIndex OrcaRouter 适配依赖未安装，请重新安装 requirements.txt。") from exc
    return OpenAILike(
        model=selected_model(),
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
    if status_code == 429:
        return "OrcaRouter 免费模型请求过于频繁，请稍后重试。"
    if status_code in (401, 403):
        return "OrcaRouter API Key 无效或没有调用权限。"
    if status_code:
        return f"OrcaRouter 请求失败（HTTP {status_code}）。"
    return "暂时无法连接 OrcaRouter，请稍后重试。"
