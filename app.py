"""Local-only desktop interface. Run: python app.py"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import Field, ValidationError

from agents.rag_agent import AgentRequest, answer as answer_agent, status as agent_status
from agents.email_writer import generate as generate_email
from agents.intent_router import interpret as interpret_intent, translate_plan_items
from agents.trace_log import error_code as trace_error_code, new_trace_id, record as record_trace
from core.contracts import NaturalLanguageInput, PlanInput, TripRequest
from core.emailer import build_draft, save_draft
from core.intent_parser import parse_text, validate_request
from core.planner import run
from core.rule_matcher import RuleRequest, extract_verified_rules
from tools.calendar_api import query as query_calendar
from tools.simulation_provider import create_simulated_offers
from tools.weather_api import query as query_weather
from policy_import.models import Binding, ImportSpec, Model, SearchRequest, Source
from policy_import.store import PolicyStore

ROOT = Path(__file__).resolve().parent


class WorkflowInput(Model):
    trip: TripRequest
    plans: list[PlanInput] = Field(max_length=30)
    policy: RuleRequest | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    snapshot_ids: list[str] = Field(default_factory=list, max_length=100)


class DraftInput(Model):
    trip: TripRequest
    plan: PlanInput
    recipient: str


class EmailGenerateInput(Model):
    plan_title: str = Field(default="出張計画", min_length=1, max_length=160)
    recipient: str = Field(default="", max_length=200)
    purpose: str = Field(default="出張計画の共有・確認依頼", max_length=1200)
    document_context: str = Field(default="", max_length=12000)
    plan_context: str = Field(default="", max_length=12000)
    conversation_context: str = Field(default="", max_length=12000)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root=ROOT):
        self.root = Path(root)
        self.store = PolicyStore(root)
        self.store_lock = threading.Lock()
        self.rate_lock = threading.Lock()
        self.rate_buckets = {}
        super().__init__(address, Handler)


def record_routing(trace_id, routing, *, stage="complexity_routing"):
    if not routing:
        return
    record_trace(trace_id, stage, "local_complexity_router", "scored",
                 model_route=routing.get("model_route"), tier=routing.get("tier"),
                 score=routing.get("score"), features=routing.get("features"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Do not log request payloads or email recipients.
        pass

    def reply(self, status, value, content_type="application/json; charset=utf-8", download=None):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        request_host = self.headers.get("Host", "")
        local = request_host in hosts
        trusted_hosts = {host.strip() for host in os.environ.get("APP_TRUSTED_HOSTS", "").split(",") if host.strip()}
        render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
        if render_host:
            trusted_hosts.add(render_host)
        if not local and request_host not in trusted_hosts:
            self.reply(403, {"status": "blocked", "message": "この画面は許可されたホストからのみ利用できます。"})
            return False
        origin = self.headers.get("Origin")
        if local and origin and origin not in {f"http://{host}" for host in hosts}:
            self.reply(403, {"status": "blocked", "message": "許可されていない接続元からの要求です。"})
            return False
        if not local and origin:
            parsed_origin = urlsplit(origin)
            if parsed_origin.scheme != "https" or parsed_origin.netloc != request_host:
                self.reply(403, {"status": "blocked", "message": "許可されていない接続元からの要求です。"})
                return False
        if not local and self.path != "/api/login" and self.path.startswith("/api/"):
            password = os.environ.get("APP_ACCESS_PASSWORD", "")
            if not password:
                self.reply(503, {"status": "failed", "message": "アクセスコードが設定されていません。"})
                return False
            authorization = self.headers.get("Authorization", "")
            token = authorization.removeprefix("Bearer ")
            if not authorization.startswith("Bearer ") or not hmac.compare_digest(token, password):
                self.reply(401, {"status": "unauthorized", "message": "チームアクセスコードを入力してください。"})
                return False
        path = urlsplit(self.path).path
        if path == "/api/login" or path.startswith("/api/documents/") or path in {"/api/import", "/api/agent/chat", "/api/agent/translate-plan", "/api/intent", "/api/intent/extract",
                                            "/api/search", "/api/rules", "/api/simulation/offers", "/api/travel-context", "/api/run", "/api/email/generate"}:
            client_ip = self.client_address[0] if self.client_address else "unknown"
            key = (client_ip, path)
            now = time.monotonic()
            limit = 10 if path == "/api/login" else 30
            with self.server.rate_lock:
                if len(self.server.rate_buckets) > 10000:
                    self.server.rate_buckets = {
                        bucket_key: stamps for bucket_key, stamps in self.server.rate_buckets.items()
                        if stamps and now - max(stamps) < 60
                    }
                recent = [stamp for stamp in self.server.rate_buckets.get(key, []) if now - stamp < 60]
                if len(recent) >= limit:
                    self.server.rate_buckets[key] = recent
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Retry-After", "60")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "rate_limited", "message": "リクエストが多すぎます。しばらく待ってから再試行してください。"}, ensure_ascii=False).encode("utf-8"))
                    return False
                recent.append(now)
                self.server.rate_buckets[key] = recent
        return True

    def do_GET(self):
        if not self.local_request():
            return
        url = urlsplit(self.path)
        assets = {"/": ("templates/plan_compare.html", "text/html; charset=utf-8"),
                  "/static/app.css": ("static/app.css", "text/css; charset=utf-8"),
                  "/static/workspace-theme.css": ("static/workspace-theme.css", "text/css; charset=utf-8"),
                  "/static/workspace.js": ("static/workspace.js", "text/javascript; charset=utf-8")}
        try:
            if url.path == "/healthz":
                self.reply(200, {"status": "ok"})
            elif url.path in assets:
                name, kind = assets[url.path]
                self.reply(200, (ROOT / name).read_bytes(), kind)
            elif url.path == "/api/plan-schema":
                self.reply(200, (ROOT / "schemas/PlanInput.json").read_bytes(), "application/schema+json; charset=utf-8", "PlanInput.schema.json")
            elif url.path == "/api/snapshots":
                with self.server.store_lock:
                    store = self.server.store
                    allowed = {b.snapshot_id for b in store.bindings() if b.usage_mode == "demo" and b.company_id is None}
                    records = [record for record in store.list_snapshots()
                               if record.snapshot_id in allowed and record.document_id.startswith("upload_")]
                self.reply(200, [{"snapshot_id": r.snapshot_id, "document_id": r.document_id,
                                "title": r.title, "document_kind": r.document_kind,
                                "revision_date": r.revision_date, "source": r.source.model_dump(),
                                "extraction_status": r.extraction_status, "chunk_count": len(r.chunks),
                                "issues": [issue.model_dump() for issue in r.issues]} for r in records])
            elif url.path == "/api/agent/status":
                with self.server.store_lock:
                    agent_state = agent_status(self.server.store)
                result = {"source_count": agent_state["source_count"],
                          "model_configured": agent_state["model_configured"]}
                self.reply(200, result)
            elif url.path == "/api/source":
                sid = parse_qs(url.query).get("snapshot_id", [""])[0]
                with self.server.store_lock:
                    record = self.server.store.load(sid)
                    permitted = record.document_id.startswith("upload_") and any(
                        b.snapshot_id == sid and b.usage_mode == "demo" and b.company_id is None
                        for b in self.server.store.bindings())
                if not permitted:
                    return self.reply(403, {"status": "blocked", "message": "この資料はデモ用途として登録されていません。"})
                data = (self.server.store.folder(sid) / ("source." + record.source.type)).read_bytes()
                # HTML is downloaded as inert bytes, never rendered on this app's origin.
                self.reply(200, data, "application/octet-stream", "source." + record.source.type)
            elif url.path.startswith("/api/drafts/"):
                filename = url.path.removeprefix("/api/drafts/")
                if not re.fullmatch(r"[a-f0-9]{64}\.eml", filename):
                    raise ValueError("下書き ID が無効です。")
                data = (self.server.root / "output/drafts" / filename).read_bytes()
                self.reply(200, data, "message/rfc822", "approval-draft.eml")
            else:
                self.reply(404, {"status": "not_found", "message": "指定されたページまたは機能が見つかりません。"})
        except (ValueError, OSError) as exc:
            self.reply(400, {"status": "failed", "message": str(exc)})

    def do_POST(self):
        if not self.local_request():
            return
        if self.path == "/api/import":
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 25 * 1024 * 1024:
                    return self.reply(413, {"status": "invalid_input", "message": "ファイルサイズは 1 バイト以上、25 MiB 以下にしてください。"})
                filename = unquote(self.headers.get("X-File-Name", ""))
                filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
                suffix = Path(filename).suffix.lower().removeprefix(".")
                supported = {"pdf", "docx", "md", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
                if suffix not in supported:
                    return self.reply(400, {"status": "invalid_input", "message": "対応形式は Markdown、PDF、DOCX、PNG、JPG、TIFF、BMP、WebP です。"})
                data = self.rfile.read(size)
                if len(data) != size:
                    return self.reply(400, {"status": "invalid_input", "message": "ファイルを最後までアップロードできませんでした。再試行してください。"})
                if suffix == "pdf" and not data.startswith(b"%PDF-"):
                    return self.reply(400, {"status": "invalid_input", "message": "有効な PDF ファイルではありません。"})
                title = Path(filename).stem[:160] or "手動アップロード資料"
                upload_identity = filename.encode("utf-8") + b"\0" + hashlib.sha256(data).digest()
                document_id = "upload_" + hashlib.sha256(upload_identity).hexdigest()[:32]
                source_type = "jpg" if suffix == "jpeg" else suffix
                # User-provided files are the only source library in the workspace.
                document_kind = "policy"
                spec = ImportSpec(document_id=document_id, title=title, document_kind=document_kind,
                                  issuer_name=None, policy_version=None, revision_date=None,
                                  source=Source(type=source_type, url=None, file_path=f"uploaded/{filename}"))
                with self.server.store_lock:
                    record = self.server.store.ingest(spec, data)
                    self.server.store.bind(Binding(company_id=None, document_id=record.document_id,
                                                   snapshot_id=record.snapshot_id, usage_mode="demo",
                                                   approval_evidence=None))
                preview = "\n\n".join(chunk.text for chunk in record.chunks)[:12000]
                return self.reply(200, {"status": "success", "snapshot_id": record.snapshot_id,
                                        "document_id": record.document_id, "title": record.title,
                                        "extraction_status": record.extraction_status,
                                        "chunk_count": len(record.chunks), "preview": preview,
                                        "issues": [issue.model_dump() for issue in record.issues]})
            except (ValueError, OSError) as exc:
                return self.reply(400, {"status": "failed", "message": str(exc)})
            except Exception as exc:
                diagnostic = str(exc).lower()
                if "fastembed" in diagnostic or "huggingface" in diagnostic or "embedding" in diagnostic:
                    return self.reply(503, {"status": "not_configured", "message": "資料検索モデルを準備できません。会話への手入力は利用できます。モデルを準備してから資料を再アップロードしてください。"})
                message = "ファイルを読み取れませんでした。OCR の依存関係を確認し、内容が鮮明であることを確認して再試行してください。"
                return self.reply(500, {"status": "failed", "message": message})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.reply(415, {"status": "invalid_input", "message": "JSON 形式で送信してください。"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2 * 1024 * 1024:
                return self.reply(413, {"status": "invalid_input", "message": "データは 1 バイト以上、2 MiB 以下にしてください。"})
            payload = json.loads(self.rfile.read(size))
            if self.path == "/api/login":
                expected = os.environ.get("APP_ACCESS_PASSWORD", "")
                supplied = payload.get("password", "") if isinstance(payload, dict) else ""
                if not expected or not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
                    return self.reply(401, {"status": "unauthorized", "message": "アクセスコードが正しくありません。"})
                result = {"status": "success", "token": expected}
            elif self.path == "/api/agent/chat":
                request = AgentRequest.model_validate(payload)
                with self.server.store_lock:
                    result = answer_agent(self.server.store, request)
                trace_id = new_trace_id()
                routing = result.get("routing") or {}
                record_routing(trace_id, routing)
                understanding = result.get("intent_understanding") or {}
                intent_route = understanding.get("routing") or routing
                record_trace(trace_id, "intent_understanding", "OrcaRouter",
                             understanding.get("status", "not_configured" if result.get("status") == "not_configured" else "not_attempted"),
                             model_route=intent_route.get("model_route"),
                             tier=intent_route.get("tier"), score=intent_route.get("score"),
                             error_code=trace_error_code(understanding.get("message")))
                if result.get("retrieval_method") or result.get("status") in ("no_sources", "no_evidence", "retrieval_error"):
                    record_trace(trace_id, "document_retrieval", "local_policy_store",
                                 result.get("status", "completed"),
                                 evidence_count=len(result.get("citations", [])),
                                 retrieval_method=result.get("retrieval_method"))
                generated = result.get("status") == "success"
                record_trace(trace_id, "grounded_answer_generation", "OrcaRouter",
                             "completed" if generated else "not_run" if result.get("status") in ("no_sources", "no_evidence", "not_configured", "dependency_missing") else "failed",
                             model_route=routing.get("model_route"), tier=routing.get("tier"),
                             score=routing.get("score"),
                             error_code=trace_error_code(result.get("diagnostic_error") or result.get("answer")))
                for internal_field in ("model", "routing", "intent_understanding", "diagnostic_error"):
                    result.pop(internal_field, None)
                result["citations"] = [{key: citation[key] for key in ("reference", "title", "location", "text", "cited") if key in citation}
                                       for citation in result.get("citations", [])]
                result["status"] = "success" if generated else "needs_attention"
            elif self.path == "/api/agent/translate-plan":
                items = payload.get("items") if isinstance(payload, dict) else None
                if (not isinstance(items, list) or
                        any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
                            or not isinstance(item.get("text"), str) for item in items)):
                    return self.reply(400, {"status": "invalid_input", "message": "日本語化する項目を確認してください。"})
                try:
                    result = {"status": "success", "translations": translate_plan_items(items)}
                except (ValueError, RuntimeError) as exc:
                    return self.reply(503, {"status": "translation_failed", "message": str(exc)})
            elif self.path == "/api/search":
                request = SearchRequest.model_validate(payload)
                if request.usage_mode != "demo" or request.company_id is not None:
                    return self.reply(403, {"status": "blocked", "message": "この画面では公開資料のデモ用途のみを利用できます。"})
                if not request.document_ids or any(not document_id.startswith("upload_") for document_id in request.document_ids):
                    return self.reply(403, {"status": "blocked", "message": "今回追加された資料だけを検索できます。"})
                with self.server.store_lock:
                    result = self.server.store.search(request).model_dump()
            elif self.path == "/api/trip":
                trip = TripRequest.model_validate(payload)
                result = {"trip": trip.model_dump(), **validate_request(trip)}
            elif self.path == "/api/intent":
                request = NaturalLanguageInput.model_validate(payload)
                result = parse_text(request.text, base_time=datetime.fromisoformat(request.base_time))
                extracted = result.get("trip")
                fields = ({key: extracted.get(key) for key in
                           ("origin", "destination", "departure_at", "arrive_by", "return_by", "purpose", "lodging_required")}
                          if extracted else {})
                understanding = interpret_intent(request.text, fields=fields)
                result["model_api_status"] = understanding["status"]
                result["llm_understanding"] = understanding
                trace_id = new_trace_id()
                routing = understanding.get("routing") or {}
                record_trace(trace_id, "structured_field_extraction", "local_rule_parser",
                             "completed" if extracted else "needs_information",
                             detail=f"extracted_fields={len(fields)}; missing_fields={len(result.get('missing_fields', []))}")
                record_routing(trace_id, routing)
                record_trace(trace_id, "intent_understanding", "OrcaRouter", understanding["status"],
                             model_route=routing.get("model_route"), tier=routing.get("tier"),
                             score=routing.get("score"),
                             error_code=trace_error_code(understanding.get("message")))
                result.pop("model_api_status", None)
                result["llm_understanding"] = {"summary": understanding.get("summary"),
                                               "questions": understanding.get("questions", [])}
            elif self.path == "/api/intent/extract":
                request = NaturalLanguageInput.model_validate(payload)
                result = parse_text(request.text, base_time=datetime.fromisoformat(request.base_time))
                result.pop("model_api_status", None)
            elif self.path == "/api/simulation/offers":
                trip = TripRequest.model_validate(payload)
                validation = validate_request(trip)
                if validation["status"] != "ready":
                    return self.reply(400, {"status": validation["status"], "message": validation["question"],
                                            "missing_fields": validation["missing_fields"]})
                result = create_simulated_offers(trip)
                trace_id = new_trace_id()
                for provider_event in result.get("provider_events", []):
                    record_trace(trace_id, "offer_data_generation", provider_event["provider"],
                                 provider_event["status"], data_kind="simulation",
                                 source=provider_event.get("source"), detail="Synthetic data; no live provider request was made.")
                result.pop("provider_events", None)
                result.pop("references", None)
            elif self.path == "/api/travel-context":
                trip = TripRequest.model_validate(payload)
                context = trip.model_dump()
                calendar_result = query_calendar(context).model_dump()
                weather_result = query_weather(context).model_dump()
                result = {"status": "simulation", "data_kind": "simulation", "queried_at": datetime.now().astimezone().isoformat(),
                          "calendar": calendar_result, "weather": weather_result,
                          "issues": [*calendar_result.get("issues", []), *weather_result.get("issues", [])]}
            elif self.path == "/api/rules":
                request = RuleRequest.model_validate(payload)
                if request.usage_mode != "demo" or request.company_id is not None:
                    return self.reply(403, {"status": "blocked", "message": "この画面では公開資料のデモ用途のみを利用できます。"})
                if any(not document_id.startswith("upload_") for document_id in request.document_ids):
                    return self.reply(403, {"status": "blocked", "message": "今回追加された資料だけを検索できます。"})
                with self.server.store_lock:
                    result = extract_verified_rules(self.server.store, request)
            elif self.path == "/api/plans":
                if not isinstance(payload, list) or len(payload) > 30:
                    raise ValueError("見積りファイルは PlanInput 形式の JSON 配列（最大 30 件）にしてください。")
                plans = [PlanInput.model_validate(item) for item in payload]
                if len({p.plan_id for p in plans}) != len(plans):
                    raise ValueError("plan_id が重複しています。各見積りに異なる ID を指定してください。")
                result = {"status": "success" if plans else "no_results", "plans": [p.model_dump() for p in plans]}
            elif self.path == "/api/run":
                request = WorkflowInput.model_validate(payload)
                if request.policy and (request.policy.usage_mode != "demo" or request.policy.company_id is not None):
                    return self.reply(403, {"status": "blocked", "message": "この画面では公開資料のデモ用途のみ利用できます。"})
                with self.server.store_lock:
                    requested_ids = set(request.policy.document_ids if request.policy else request.document_ids)
                    requested_snapshots = set(request.policy.snapshot_ids if request.policy else request.snapshot_ids)
                    bindings = [b for b in self.server.store.bindings()
                                if b.usage_mode == "demo" and b.company_id is None
                                and b.document_id.startswith("upload_")
                                and b.document_id in requested_ids
                                and b.snapshot_id in requested_snapshots]
                    allowed = {b.snapshot_id for b in bindings}
                    records = [record for record in self.server.store.list_snapshots() if record.snapshot_id in allowed]
                    policy_records = [record for record in records if record.document_kind == "policy"]
                    query_parts = [request.trip.origin, request.trip.destination, request.trip.purpose,
                                   "交通費 宿泊費 出張規程 承認条件",
                                   "宿泊" if request.trip.lodging_required else None]
                    policy_request = RuleRequest(company_id=None, employee_scope=None,
                        document_ids=list(dict.fromkeys(r.document_id for r in policy_records)),
                        snapshot_ids=[r.snapshot_id for r in policy_records], usage_mode="demo",
                        query=(request.policy.query if request.policy else " ".join(part for part in query_parts if part))) if policy_records else None
                result = run(request.trip, request.plans, self.server.root / "output/runs",
                             policy_request, self.server.store if policy_request else None)
                trace_id = new_trace_id()
                data_kind = "simulation" if request.plans and all(plan.data_kind == "simulation" for plan in request.plans) else "input"
                for workflow_event in result.get("events", []):
                    record_trace(trace_id, workflow_event["step"], "local_workflow",
                                 workflow_event["status"], data_kind=data_kind,
                                 detail=workflow_event["message"])
                result.pop("events", None)
                result.pop("execution_id", None)
                result.pop("elapsed_seconds", None)
            elif self.path == "/api/email/generate":
                request = EmailGenerateInput.model_validate(payload)
                result = generate_email(**request.model_dump())
            elif self.path in ("/api/draft", "/api/draft/export"):
                request = DraftInput.model_validate(payload)
                result = build_draft(request.trip, request.plan, request.recipient)
                record_trace(new_trace_id(), "approval_email_draft", "local_template", "created",
                             data_kind=request.plan.data_kind)
                if self.path.endswith("/export"):
                    save_draft(result, self.server.root / "output/drafts")
                    result["download_url"] = "/api/drafts/" + result["confirmation_fingerprint"] + ".eml"
            else:
                return self.reply(404, {"status": "not_found", "message": "指定されたページまたは機能が見つかりません。"})
            self.reply(200, result)
        except ValidationError as exc:
            messages = {"missing": "必須項目を入力してください。", "int_parsing": "整数で入力してください。",
                        "int_type": "整数で入力してください。", "string_type": "文字列で入力してください。",
                        "string_too_short": "文字数が不足しています。", "string_too_long": "文字数の上限を超えています。",
                        "extra_forbidden": "定義されていない項目です。", "literal_error": "指定された選択肢から入力してください。"}
            errors = [{"field": ".".join(str(v) for v in error["loc"]),
                       "message": (error["msg"].removeprefix("Value error, ") if error["type"] == "value_error"
                                   else messages.get(error["type"], "入力形式を確認してください。"))}
                      for error in exc.errors(include_input=False, include_context=False)]
            self.reply(400, {"status": "invalid_input", "message": "入力データを確認してください。", "errors": errors})
        except (ValueError, OSError) as exc:
            self.reply(400, {"status": "failed", "message": str(exc)})
        except Exception:
            self.reply(500, {"status": "failed", "message": "内部処理に失敗しました。データと依存パッケージを確認してください。"})

    def do_DELETE(self):
        if not self.local_request():
            return
        match = re.fullmatch(r"/api/documents/([0-9a-f]{64})", urlsplit(self.path).path)
        if not match:
            return self.reply(400, {"status": "invalid_input", "message": "資料 ID が無効です。"})
        try:
            snapshot_id = match.group(1)
            with self.server.store_lock:
                permitted = any(b.snapshot_id == snapshot_id and b.usage_mode == "demo" and b.company_id is None
                                for b in self.server.store.bindings())
                if not permitted:
                    return self.reply(404, {"status": "not_found", "message": "資料が見つかりません。"})
                record = self.server.store.load(snapshot_id)
                if not record.document_id.startswith("upload_"):
                    return self.reply(403, {"status": "blocked", "message": "登録済みの資料はこの画面から削除できません。"})
                record = self.server.store.delete(snapshot_id)
            self.reply(200, {"status": "deleted", "snapshot_id": record.snapshot_id})
        except (ValueError, OSError) as exc:
            self.reply(400, {"status": "failed", "message": str(exc)})
        except Exception:
            self.reply(500, {"status": "failed", "message": "資料の削除に失敗しました。"})


def main():
    parser = argparse.ArgumentParser(description="ローカル出張アシスタント")
    parser.add_argument("--host", default=os.environ.get("APP_BIND_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        if not os.environ.get("APP_ACCESS_PASSWORD"):
            parser.error("APP_ACCESS_PASSWORD must be set when binding to a public interface")
        if not (os.environ.get("APP_TRUSTED_HOSTS") or os.environ.get("RENDER_EXTERNAL_HOSTNAME")):
            parser.error("Set APP_TRUSTED_HOSTS to the exact public host name")
    data_root = Path(os.environ.get("APP_DATA_DIR", str(ROOT))).resolve()
    server = LocalServer((args.host, args.port), root=data_root)
    print(f"出張アシスタント：http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
