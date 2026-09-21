import hashlib
import html
import json
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

from .calculator import calculate
from .contracts import PlanInput, TripRequest
from .intent_parser import validate_request


def build_draft(trip: TripRequest, plan: PlanInput, recipient: str):
    if "\r" in recipient or "\n" in recipient or parseaddr(recipient)[1] != recipient or recipient.count("@") != 1:
        raise ValueError("有効な承認者メールアドレスを 1 件入力してください。")
    if validate_request(trip)["status"] != "ready":
        raise ValueError("出張申請の必須項目が未入力、または未確認です。")
    result = calculate(plan, trip)
    amount = f"¥{result['total_cost']:,}" if result["total_cost"] is not None else f"未確定（既知の小計 ¥{result['known_subtotal']:,}）"
    subject = "出張承認申請（下書き）"
    lines = ["このメールは下書きです。まだ送信されていません。", f"データ区分：{'シミュレーション' if plan.data_kind == 'simulation' else '入力データ'}",
             f"出張目的：{trip.purpose or '未入力'}", f"行程：{trip.origin} → {trip.destination} → {trip.origin}",
             f"出発日時：{trip.departure_at}", f"帰着期限：{trip.return_by}",
             f"見積り：{plan.plan_id}、版：{plan.version}", f"費用：{amount}", "費用内訳："]
    for row in result["cost_breakdown"]:
        item_amount = f"¥{row['amount']:,}" if row["amount"] is not None else "未確定"
        lines.append(f"- {row['description']}：{item_amount}；出典：{row['source']}")
    lines += ["移動区間："]
    for leg in plan.legs:
        lines.append(f"- {leg.mode}：{leg.origin} → {leg.destination}；{leg.departure_at} ～ {leg.arrival_at}；出典：{leg.source}")
    lines += ["規程上の根拠：適用が確認された条文は添付されていません。規程適合の承認済みを示すものではありません。", "確認事項："] + ["- " + issue for issue in result["issues"]]
    body = "\n".join(lines)
    identity = json.dumps({"trip": trip.model_dump(), "plan": plan.model_dump(), "recipient": recipient,
                           "subject": subject, "body": body}, ensure_ascii=False, sort_keys=True)
    return {"status": "draft", "sent": False, "recipient": recipient, "subject": subject,
            "body": body, "html": "<pre>" + html.escape(body) + "</pre>",
            "confirmation_fingerprint": hashlib.sha256(identity.encode()).hexdigest()}


def save_draft(draft, directory):
    from policy_import.store import atomic_json
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = draft["confirmation_fingerprint"]
    atomic_json(directory / (name + ".json"), draft)
    message = EmailMessage()
    message["To"] = draft["recipient"]
    message["Subject"] = draft["subject"]
    message.set_content(draft["body"])
    (directory / (name + ".eml")).write_bytes(message.as_bytes())
    return str(directory / (name + ".eml"))
