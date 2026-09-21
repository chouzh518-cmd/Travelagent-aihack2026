"""Bounded deterministic workflow. Does not pretend to be a configured ReAct agent."""
import time
import uuid
from pathlib import Path

from policy_import.store import atomic_json, now
from .calculator import compare
from .intent_parser import validate_request
from .rule_matcher import extract_verified_rules


def run(trip, plans, output_dir, policy_request=None, store=None):
    started = time.monotonic()
    execution_id = uuid.uuid4().hex
    events = []

    def event(step, status, message):
        events.append({"queried_at": now(), "step": step, "status": status, "message": message})

    validation = validate_request(trip)
    event("requirements", validation["status"], validation["question"])
    comparison = None
    policy = None
    if validation["status"] != "ready":
        stop = validation["status"]
    elif policy_request is not None and store is None:
        stop = "policy_store_unavailable"
        event("policy", "failed", "規程データベースが設定されていません。")
    elif policy_request is not None:
        policy = extract_verified_rules(store, policy_request)
        event("policy", policy["status"], "規程原文と抽出可能なルールを読み込みました。適用範囲と規程適合は未判定です。")
        if policy["status"] in ("blocked", "failed"):
            stop = "policy_scope_blocked"
        elif not plans:
            event("offers", "not_configured", "確認済みの見積りがありません。便名や料金を生成せず処理を停止しました。")
            stop = "needs_offers"
        else:
            comparison = compare(plans, trip)
            event("calculation", "completed", "費用と往復の所要時間を計算し、行程条件を確認しました。")
            stop = "needs_rule_review"
    elif not plans:
        event("offers", "not_configured", "確認済みの見積りがありません。便名や料金を生成せず処理を停止しました。")
        stop = "needs_offers"
    else:
        comparison = compare(plans, trip)
        event("calculation", "completed", "費用と往復の所要時間を計算し、行程条件を確認しました。")
        event("policy", "needs_rule_review", "確認済みの規程ルールがないため、規程適合は未判定です。")
        stop = "needs_rule_review"
    result = {"execution_id": execution_id, "trip_id": trip.trip_id, "status": stop,
              "elapsed_seconds": round(time.monotonic()-started, 3), "events": events,
              "comparison": comparison, "validation": validation, "policy": policy}
    atomic_json(Path(output_dir) / (execution_id + ".json"), result)
    return result
