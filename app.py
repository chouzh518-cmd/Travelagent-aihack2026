"""Local-only desktop interface. Run: python app.py"""
from __future__ import annotations
import json
import argparse
import hashlib
import hmac
import json
import os
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import Field, ValidationError

from agents.rag_agent import AgentRequest, answer as answer_agent, status as agent_status
from core.contracts import NaturalLanguageInput, PlanInput, TripRequest
from core.emailer import build_draft, save_draft
from core.intent_parser import parse_text, validate_request
from core.planner import run
from core.rule_matcher import RuleRequest, extract_verified_rules
from policy_import.models import Binding, ImportSpec, Model, SearchRequest, Source
from policy_import.store import PolicyStore

ROOT = Path(__file__).resolve().parent


class WorkflowInput(Model):
    trip: TripRequest
    plans: list[PlanInput] = Field(max_length=30)
    policy: RuleRequest | None = None


class DraftInput(Model):
    trip: TripRequest
    plan: PlanInput
    recipient: str


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root=ROOT):
        self.root = Path(root)
        self.store = PolicyStore(root)
        self.store_lock = threading.Lock()
        super().__init__(address, Handler)


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
        return True

    def do_GET(self):
        if not self.local_request():
            return
        url = urlsplit(self.path)
        assets = {"/": ("templates/plan_compare.html", "text/html; charset=utf-8"),
                  "/static/app.css": ("static/app.css", "text/css; charset=utf-8"),
                  "/static/app.js": ("static/app.js", "text/javascript; charset=utf-8")}
        try:
            if url.path == "/healthz":
                self.reply(200, {"status": "ok"})
            elif url.path in assets:
                name, kind = assets[url.path]
                self.reply(200, (ROOT / name).read_bytes(), kind)
            elif url.path == "/api/plan-schema":
                self.reply(200, (ROOT / "schemas/PlanInput.json").read_bytes(), "application/schema+json; charset=utf-8", "PlanInput.schema.json")
            elif url.path == "/api/demo-plans":
                import json
                self.reply(200, json.loads((ROOT / "plans_only.json").read_bytes()))
            elif url.path == "/api/snapshots":
                with self.server.store_lock:
                    store = self.server.store
                    allowed = {b.snapshot_id for b in store.bindings() if b.usage_mode == "demo" and b.company_id is None}
                    records = [record for record in store.list_snapshots() if record.snapshot_id in allowed]
                self.reply(200, [{"snapshot_id": r.snapshot_id, "document_id": r.document_id,
                                "title": r.title, "document_kind": r.document_kind,
                                "revision_date": r.revision_date, "source": r.source.model_dump(),
                                "extraction_status": r.extraction_status, "chunk_count": len(r.chunks),
                                "issues": [issue.model_dump() for issue in r.issues]} for r in records])
            elif url.path == "/api/agent/status":
                with self.server.store_lock:
                    result = agent_status(self.server.store)
                self.reply(200, result)
            elif url.path == "/api/source":
                sid = parse_qs(url.query).get("snapshot_id", [""])[0]
                with self.server.store_lock:
                    record = self.server.store.load(sid)
                    permitted = any(b.snapshot_id == sid and b.usage_mode == "demo" and b.company_id is None for b in self.server.store.bindings())
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
                supported = {"pdf", "docx", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
                if suffix not in supported:
                    return self.reply(400, {"status": "invalid_input", "message": "対応形式は PDF、DOCX、PNG、JPG、TIFF、BMP、WebP です。"})
                data = self.rfile.read(size)
                if len(data) != size:
                    return self.reply(400, {"status": "invalid_input", "message": "ファイルを最後までアップロードできませんでした。再試行してください。"})
                if suffix == "pdf" and not data.startswith(b"%PDF-"):
                    return self.reply(400, {"status": "invalid_input", "message": "有効な PDF ファイルではありません。"})
                title = Path(filename).stem[:160] or "手動アップロード資料"
                document_id = "upload_" + hashlib.sha256(filename.encode("utf-8")).hexdigest()[:20]
                source_type = "jpg" if suffix == "jpeg" else suffix
                spec = ImportSpec(document_id=document_id, title=title, document_kind="policy",
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
            elif self.path == "/api/search":
                request = SearchRequest.model_validate(payload)
                if request.usage_mode != "demo" or request.company_id is not None:
                    return self.reply(403, {"status": "blocked", "message": "この画面では公開資料のデモ用途のみを利用できます。"})
                with self.server.store_lock:
                    result = self.server.store.search(request).model_dump()
            elif self.path == "/api/trip":
                trip = TripRequest.model_validate(payload)
                result = {"trip": trip.model_dump(), **validate_request(trip)}
            elif self.path == "/api/intent":
                request = NaturalLanguageInput.model_validate(payload)
                result = parse_text(request.text, base_time=datetime.fromisoformat(request.base_time))
            elif self.path == "/api/rules":
                request = RuleRequest.model_validate(payload)
                if request.usage_mode != "demo" or request.company_id is not None:
                    return self.reply(403, {"status": "blocked", "message": "この画面では公開資料のデモ用途のみを利用できます。"})
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
                    bindings = [b for b in self.server.store.bindings() if b.usage_mode == "demo" and b.company_id is None]
                    allowed = {b.snapshot_id for b in bindings}
                    records = [record for record in self.server.store.list_snapshots() if record.snapshot_id in allowed]
                    query_parts = [request.trip.origin, request.trip.destination, request.trip.purpose,
                                   "交通費 宿泊費 出張規程 承認条件",
                                   "宿泊" if request.trip.lodging_required else None]
                    policy_request = RuleRequest(company_id=None, employee_scope=None,
                        document_ids=list(dict.fromkeys(r.document_id for r in records)),
                        snapshot_ids=[r.snapshot_id for r in records], usage_mode="demo",
                        query=" ".join(part for part in query_parts if part)) if records else None
                    result = run(request.trip, request.plans, self.server.root / "output/runs",
                                 policy_request, self.server.store if policy_request else None)
            elif self.path in ("/api/draft", "/api/draft/export"):
                request = DraftInput.model_validate(payload)
                result = build_draft(request.trip, request.plan, request.recipient)
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
