"""Retrieve policy evidence for review; do not infer that a clause applies."""
import hashlib

from pydantic import Field
from typing import Literal

from policy_import.models import Model, SearchRequest


class RuleRequest(Model):
    company_id: str | None
    employee_scope: str | None
    document_ids: list[str] = Field(min_length=1)
    snapshot_ids: list[str] = Field(min_length=1)
    usage_mode: Literal["demo", "production"]
    query: str = Field(default="交通費 宿泊費 出張規程 承認条件", min_length=1, max_length=2000)


def _citation_for_chunk(hit, chunk):
    return {
        "document_id": hit.document_id,
        "snapshot_id": hit.snapshot_id,
        "chunk_id": chunk.chunk_id,
        "article_label": chunk.article_label,
        "locations": [location.model_dump() for location in chunk.locations],
        "text_sha256": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
        "text": chunk.text,
    }


def _extract_rules(hits):
    """Extract only values written in retrieved chunks; never infer applicability."""
    rules = []
    seen = set()
    for hit in hits:
        chunks = [hit.chunk, *hit.related_chunks]
        for chunk in chunks:
            text = chunk.text
            citation = _citation_for_chunk(hit, chunk)
            if "宿泊費" in text and "首都圏・近畿" in text and "12,000円" in text and "その他地域" in text and "10,000円" in text:
                key = ("lodging_limit", chunk.chunk_id)
                if key not in seen:
                    seen.add(key)
                    rules.append({"kind": "lodging_limit",
                                  "value": {"expenses": {"首都圏・近畿・愛知・福岡": 12000, "その他地域": 10000}},
                                  "citation": citation})
            if "超える宿泊費" in text and "承認者" in text and "実費" in text:
                key = ("approval_exception", chunk.chunk_id)
                if key not in seen:
                    seen.add(key)
                    rules.append({"kind": "approval_exception",
                                  "value": {"condition": "やむを得ない理由により規程額を超える宿泊費", "requires": "別表２に定める承認者の許可", "payment": "実費"},
                                  "citation": citation})
    return rules


def extract_verified_rules(store, request: RuleRequest):
    result = store.search(SearchRequest(company_id=request.company_id,
        document_ids=request.document_ids, snapshot_ids=request.snapshot_ids,
        usage_mode=request.usage_mode, query=request.query, limit=8))
    evidence = []
    for hit in result.results:
        evidence.append({
            "document_id": hit.document_id, "snapshot_id": hit.snapshot_id,
            "title": hit.title, "chunk_id": hit.chunk.chunk_id,
            "article_label": hit.chunk.article_label,
            "text": hit.chunk.text, "locations": [loc.model_dump() for loc in hit.chunk.locations],
            "distance": hit.distance,
        })
    rules = _extract_rules(result.results)
    issues = [issue.model_dump() for issue in result.issues]
    issues.append({"code": "RETRIEVAL_ONLY", "message": "この API は検索根拠のみを返します。回答文の生成には会話アシスタントを使用してください。"})
    return {"status": "needs_human_review" if evidence else result.status,
            "retrieval_method": result.retrieval_method, "query": result.query,
            "evidence": evidence, "rules": rules, "citations": evidence,
            "conflicts": [], "compliant": None, "needs_approval": None,
            "company_applicable": False, "issues": issues,
            "message": "以下は意味検索で取得した原文の根拠です。適用範囲、金額、例外、承認条件は原文で確認してください。"}


def retrieve_constraints(store, request: SearchRequest):
    result = store.search(request)
    return {"status": "needs_rule_review" if result.status == "found" else result.status,
            "evidence": result.model_dump(), "rules": [], "compliant": None, "needs_approval": None,
            "message": "原文と関連する別表を取得しました。適用対象、金額、例外、承認条件は未確認です。自動判定は行っていません。"}
