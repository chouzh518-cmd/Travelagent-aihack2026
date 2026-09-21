"""Bounded deterministic workflow. Does not pretend to be a configured ReAct agent."""
import time
import uuid
from pathlib import Path

from policy_import.store import atomic_json, now
from .calculator import compare
from .intent_parser import validate_request
from .rule_matcher import extract_verified_rules
import json
import re
from llama_index.core.llms import ChatMessage
from llm.orcarouter import create_llm

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
            
            if policy and policy.get("evidence"):
                event("policy", "reviewing", "AI が規程と見積り金額を照合しています...")
                # 將檢索到的規程原文組合成一個 Context 字串
                policy_text = "\n".join([hit["text"] for hit in policy["evidence"]])
                
                try:
                    llm = create_llm()
                    for item in comparison["results"]:
                        # 整理每個方案的花費明細
                        plan_costs = "\n".join([f"{c['description']}: ¥{c.get('amount', c.get('unit_amount', 0) * c['quantity'])}" for c in item["cost_breakdown"]])
                        
                        prompt = (
                            "以下の出張規程に基づき、この見積りが規程に適合しているか判定してください。\n\n"
                            f"【出張規程】\n{policy_text}\n\n"
                            f"【見積り費用】\n{plan_costs}\n\n"
                            "判定結果を以下のJSON形式でのみ出力してください。それ以外のテキストは含めないでください：\n"
                            '{"compliant": trueまたはfalse, "issue": "違反している場合はその理由。適合している場合は空文字"}'
                        )
                        
                        response = llm.chat([ChatMessage(role="user", content=prompt)])
                        
                        # 解析 AI 回傳的 JSON
                        match = re.search(r'\{.*\}', response.message.content, re.DOTALL)
                        if match:
                            res_json = json.loads(match.group(0))
                            item["compliant"] = res_json.get("compliant", False)
                            if not item["compliant"] and res_json.get("issue"):
                                item["issues"].append(res_json.get("issue"))
                        else:
                            item["compliant"] = False
                            item["issues"].append("AIによる判定結果のフォーマットエラーです。")
                            
                    stop = "completed"
                    event("policy", "completed", "規程への適合判定が完了しました。")
                    
                except Exception as e:
                    event("policy", "failed", f"AI判定中にエラーが発生しました: {str(e)}")
                    stop = "needs_rule_review"
            else:
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
