"""Technical boundary tests. No invented offers are saved to demo data.

Source ingestion assertions use only the two approved public documents.
Arithmetic cases are isolated in-memory test inputs, not market quotes or employee records.
"""
import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from app import LocalServer
from core.calculator import calculate, compare
from core.contracts import CostItem, Leg, PlanInput, TripRequest
from core.emailer import build_draft, save_draft
from core.intent_parser import parse_text, validate_request
from core.planner import run
from core.rule_matcher import RuleRequest, extract_verified_rules
from policy_import.extract import ExtractionError, chunk_blocks, extract
from policy_import.models import Binding, ExtractionOptions, ImportSpec, SearchRequest, Source
from policy_import.store import PolicyStore
from tools.base import load_plans
from tools.email_api import send

ROOT = Path(__file__).resolve().parents[1]


def trip():
    # Isolated technical test values, never displayed as a real employee itinerary.
    return TripRequest(trip_id="unit-test", company_id=None, employee_id=None,
                       origin="起点", destination="终点", departure_at="2026-09-20T08:00:00+09:00",
                       arrive_by="2026-09-20T12:00:00+09:00", return_by="2026-09-21T20:00:00+09:00",
                       purpose="技術境界テスト", lodging_required=True, confirmed=True)


def plan():
    return PlanInput(plan_id="unit-test", trip_id="unit-test", version="1", data_kind="simulation",
                     available=True, valid_until="2099-01-01T00:00:00+09:00", source="unit-test only",
                     queried_at="2026-09-20T07:00:00+09:00",
                     legs=[Leg(direction="outbound", mode="test", origin="起点", destination="终点",
                               departure_at="2026-09-20T08:00:00+09:00", arrival_at="2026-09-20T10:00:00+09:00", source="unit-test only"),
                           Leg(direction="return", mode="test", origin="终点", destination="起点",
                               departure_at="2026-09-21T16:00:00+09:00", arrival_at="2026-09-21T18:00:00+09:00", source="unit-test only")],
                     costs=[CostItem(description="test room-night", category="hotel", currency="JPY", unit_amount=12000,
                                     quantity=2, unit="room-night", taxes_included=True, source="unit-test only", queried_at="2026-09-20T07:00:00+09:00")],
                     zero_cost_reasons={"transport":"arithmetic test", "transfer":"arithmetic test", "per_diem":"arithmetic test"})


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PolicyStore(ROOT)
        cls.records = {r.document_id: r for r in cls.store.list_snapshots()}
        cls.pdf = cls.records["jrfu_domestic_travel"]
        cls.web = cls.records["michibiku_travel_template"]

    def request(self, record, query="宿泊費", **changes):
        raw = dict(company_id=None, document_ids=[record.document_id], snapshot_ids=[record.snapshot_id], usage_mode="demo", query=query)
        raw.update(changes)
        return SearchRequest(**raw)

    def test_expected_public_document_counts(self):
        self.assertEqual(sum(c.chunk_type == "article" for c in self.pdf.chunks), 8)
        self.assertEqual(sum(c.chunk_type == "article" for c in self.web.chunks), 24)

    def test_pdf_cross_page_article_preserved(self):
        chunk = next(c for c in self.pdf.chunks if c.article_label == "第４条")
        self.assertEqual({l.page_number for l in chunk.locations}, {1, 2})
        self.assertIn("の利用を認めるものとし、その運賃を支給する。", chunk.text)

    def test_table_grid_and_continuation_preserved(self):
        chunk = next(c for c in self.pdf.chunks if c.article_label == "別表３")
        self.assertEqual(len(chunk.tables), 2)
        self.assertEqual(chunk.tables[0].rows[8][2], "12,000円")
        self.assertEqual(chunk.tables[0].rows[9][2], "10,000円")
        self.assertIn("車中泊", chunk.tables[1].rows[0])
        self.assertIsNone(chunk.tables[0].rows[0][1])

    def test_references_resolve_exactly(self):
        chunk = next(c for c in self.pdf.chunks if c.article_label == "第４条")
        table = next(c for c in self.pdf.chunks if c.article_label == "別表３")
        ref = next(r for r in chunk.references if r.label == "別表３")
        self.assertEqual(ref.target_chunk_ids, [table.chunk_id])

    def test_template_placeholders_flagged(self):
        chunk = next(c for c in self.web.chunks if c.article_label == "第14条")
        self.assertIn("UNFILLED_PLACEHOLDER", [i.code for i in chunk.issues])

    def test_marketing_excluded(self):
        self.assertNotIn("プラットフォーム", "\n".join(c.text for c in self.web.chunks))

    def test_template_not_company_policy(self):
        with self.assertRaises(ValueError):
            self.store.bind(Binding(company_id="unit-test", document_id=self.web.document_id,
                                   snapshot_id=self.web.snapshot_id, usage_mode="production", approval_evidence="unit-test"))

    def test_rules_keep_exact_values_citations_and_nonapplicability(self):
        request = RuleRequest(company_id=None, employee_scope=None, document_ids=[self.pdf.document_id],
                              snapshot_ids=[self.pdf.snapshot_id], usage_mode="demo")
        result = extract_verified_rules(self.store, request)
        self.assertEqual(result["status"], "needs_human_review")
        self.assertFalse(result["company_applicable"])
        self.assertIsNone(result["compliant"])
        by_kind = {rule["kind"]: rule for rule in result["rules"]}
        self.assertEqual(by_kind["lodging_limit"]["value"]["expenses"],
                         {"首都圏・近畿・愛知・福岡":12000, "その他地域":10000})
        self.assertIn("approval_exception", by_kind)
        self.assertTrue(all(rule["citation"]["locations"] and rule["citation"]["text_sha256"]
                            for rule in result["rules"]))

    def test_company_scope_is_not_wildcard(self):
        result = self.store.search(self.request(self.pdf, company_id="unbound-test-scope"))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.results, [])

    def test_document_scope_is_exact(self):
        result = self.store.search(self.request(self.pdf, document_ids=[self.web.document_id]))
        self.assertEqual(result.status, "blocked")

    def test_production_without_company_blocked(self):
        self.assertEqual(self.store.search(self.request(self.pdf, usage_mode="production")).status, "blocked")

    def test_search_has_citations_and_related_tables(self):
        result = self.store.search(self.request(self.pdf))
        self.assertEqual(result.status, "found")
        self.assertTrue(all(h.snapshot_id == self.pdf.snapshot_id for h in result.results))
        self.assertTrue(any(c.article_label == "別表３" for h in result.results for c in h.related_chunks))
        self.assertTrue(all(h.source.url and h.chunk.locations for h in result.results))

    def test_missing_is_not_fabricated(self):
        result = self.store.search(self.request(self.pdf, "不存在的测试关键词"))
        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.results, [])

    def test_identifier_case_not_coerced(self):
        raw = self.request(self.pdf).model_dump()
        raw["Company_id"] = raw.pop("company_id")
        with self.assertRaises(ValidationError):
            SearchRequest.model_validate(raw)

    def test_reimport_is_idempotent(self):
        spec = ImportSpec.model_validate_json((ROOT / "config/import_jrfu.json").read_text(encoding="utf-8"))
        again = self.store.ingest(spec)
        self.assertEqual(again.snapshot_id, self.pdf.snapshot_id)
        self.assertEqual(again.queried_at, self.pdf.queried_at)

    def test_invalid_pdf_fails_explicitly(self):
        with self.assertRaises(ExtractionError):
            extract(b"", "pdf", ExtractionOptions())

    def test_image_without_text_is_kept_without_search_error(self):
        from PIL import Image

        image_data = BytesIO()
        Image.new("RGB", (80, 80), "white").save(image_data, format="JPEG")
        spec = ImportSpec(document_id="empty-text-image", title="文字なし画像", document_kind="policy",
                          issuer_name=None, policy_version=None, revision_date=None,
                          source=Source(type="jpg", url=None, file_path="uploaded/no-text.jpg"))
        with tempfile.TemporaryDirectory() as directory, patch("policy_import.extract.recognize_image", return_value=[]):
            store = PolicyStore(directory)
            record = store.ingest(spec, image_data.getvalue())
            store.bind(Binding(company_id=None, document_id=record.document_id,
                               snapshot_id=record.snapshot_id, usage_mode="demo", approval_evidence=None))
            response = store.search(SearchRequest(company_id=None, document_ids=[record.document_id],
                                      snapshot_ids=[record.snapshot_id], usage_mode="demo", query="画像の内容"))

        self.assertEqual(record.extraction_status, "partial")
        self.assertEqual(record.chunks, [])
        self.assertEqual(response.status, "not_found")
        self.assertNotIn("PARTIAL_EXTRACTION", [issue.code for issue in response.issues])

    def test_html_needs_exact_selector(self):
        data = (ROOT / "data/policies/sources/michibiku_travel_template.html").read_bytes()
        with self.assertRaises(ExtractionError):
            extract(data, "html", ExtractionOptions())

    def test_word_extraction_on_existing_plan(self):
        source = Path(r"C:\Users\chouz\OneDrive\Desktop\9.19meet.docx")
        if not source.exists():
            self.skipTest("Original user plan is not available on this machine")
        blocks, _ = extract(source.read_bytes(), "docx", ExtractionOptions())
        self.assertTrue(any("模块 1" in b.text for b in blocks))
        with self.assertRaises(ExtractionError):
            chunk_blocks(blocks, "plan-is-not-policy")


class BusinessTests(unittest.TestCase):
    def test_missing_slots_are_requested(self):
        value = trip().model_copy(update={"origin": "  ", "lodging_required": None})
        self.assertEqual(validate_request(value)["missing_fields"], ["origin", "lodging_required"])

    def test_false_is_not_missing(self):
        self.assertEqual(validate_request(trip().model_copy(update={"lodging_required": False}))["status"], "ready")

    def test_confirmation_required(self):
        self.assertEqual(validate_request(trip().model_copy(update={"confirmed": False}))["status"], "needs_confirmation")

    def test_relative_date_uses_explicit_base_time_and_missing_slots(self):
        result = parse_text("下周三去大阪当天回，见客户",
                            base_time=datetime.fromisoformat("2026-09-21T12:00:00+09:00"))
        self.assertEqual(result["status"], "needs_information")
        self.assertEqual(result["trip"]["destination"], "大阪")
        self.assertEqual(result["date_context"]["departure_date"], "2026-09-30")
        self.assertEqual(result["trip"]["departure_at"], None)
        self.assertEqual(result["trip"]["lodging_required"], False)

    def test_japanese_intent_extracts_route_date_time_and_day_return(self):
        result = parse_text("来週水曜日に東京から大阪へ9時出発、18時に帰着、日帰りで顧客訪問",
                            base_time=datetime.fromisoformat("2026-09-21T12:00:00+09:00"))
        self.assertEqual(result["trip"]["origin"], "東京")
        self.assertEqual(result["trip"]["destination"], "大阪")
        self.assertEqual(result["date_context"]["departure_date"], "2026-09-30")
        self.assertEqual(result["date_context"]["return_date"], "2026-09-30")
        self.assertEqual(result["trip"]["departure_at"], "2026-09-30T09:00:00+09:00")
        self.assertEqual(result["trip"]["return_by"], "2026-09-30T18:00:00+09:00")
        self.assertIn("arrive_by", result["missing_fields"])

    def test_japanese_request_extracts_next_week_stay_and_conference_without_inventing_times(self):
        result = parse_text("来週の金曜から2泊3日で、東京の〇〇学会に参加したい",
                            base_time=datetime.fromisoformat("2026-09-22T12:00:00+09:00"))
        self.assertEqual(result["trip"]["destination"], "東京")
        self.assertEqual(result["trip"]["purpose"], "〇〇学会への参加")
        self.assertIsNone(result["trip"]["departure_at"])
        self.assertIsNone(result["trip"]["return_by"])
        self.assertTrue(result["trip"]["lodging_required"])
        self.assertEqual(result["duration_limit_days"], 3)
        self.assertEqual(result["date_context"]["departure_date"], "2026-10-02")
        self.assertEqual(result["date_context"]["return_date"], "2026-10-04")

    def test_duration_does_not_guess_return_date(self):
        result = parse_text("2026-09-23去大阪出差3天",
                            base_time=datetime.fromisoformat("2026-09-21T12:00:00+09:00"))
        self.assertIsNone(result["date_context"]["return_date"])
        self.assertIsNone(result["trip"]["return_by"])

    def test_follow_up_can_set_return_date_and_budget(self):
        result = parse_text("2026年10月10日に東京から大阪へ8時出発、2026年10月11日に18時帰着、予算30,000円、宿泊",
                            base_time=datetime.fromisoformat("2026-09-21T12:00:00+09:00"))
        self.assertEqual(result["trip"]["departure_at"], "2026-10-10T08:00:00+09:00")
        self.assertEqual(result["trip"]["return_by"], "2026-10-11T18:00:00+09:00")
        self.assertEqual(result["budget_jpy"], 30000)

    def test_naive_datetime_rejected(self):
        raw = trip().model_dump()
        raw["departure_at"] = "2026-09-20T08:00:00"
        with self.assertRaises(ValidationError):
            TripRequest.model_validate(raw)

    def test_currency_and_amount_types_strict(self):
        for key, value in (("currency", "USD"), ("unit_amount", 1.5), ("unit_amount", True), ("quantity", "2")):
            raw = plan().costs[0].model_dump()
            raw[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                CostItem.model_validate(raw)

    def test_cost_uses_units_not_llm(self):
        result = calculate(plan(), trip())
        self.assertEqual(result["total_cost"], 24000)
        self.assertIsNone(result["compliant"])
        self.assertIsNone(result["needs_approval"])

    def test_missing_price_never_becomes_zero(self):
        value = plan()
        value.costs[0].unit_amount = None
        result = calculate(value, trip())
        self.assertIsNone(result["total_cost"])
        self.assertFalse(result["cost_complete"])

    def test_missing_category_needs_explanation(self):
        value = plan()
        value.zero_cost_reasons.pop("per_diem")
        self.assertIsNone(calculate(value, trip())["total_cost"])

    def test_unknown_taxes_blocks_complete_total(self):
        value = plan()
        value.costs[0].taxes_included = None
        self.assertIsNone(calculate(value, trip())["total_cost"])

    def test_duplicate_category_zero_reason_rejected(self):
        value = plan()
        value.zero_cost_reasons["hotel"] = "not applicable"
        with self.assertRaises(ValueError):
            calculate(value, trip())

    def test_day_return_does_not_accept_hotel_cost(self):
        self.assertFalse(calculate(plan(), trip().model_copy(update={"lodging_required": False}))["cost_complete"])

    def test_cross_day_timezone_duration(self):
        value = plan()
        value.legs[0].departure_at = "2026-09-20T23:00:00+09:00"
        value.legs[0].arrival_at = "2026-09-20T17:00:00+00:00"
        request = trip().model_copy(update={"arrive_by":"2026-09-21T10:00:00+09:00"})
        self.assertEqual(calculate(value, request)["elapsed_minutes"]["outbound"], 180)

    def test_late_arrival_flagged(self):
        value = plan()
        value.legs[0].arrival_at = "2026-09-20T13:00:00+09:00"
        self.assertFalse(calculate(value, trip())["itinerary_valid"])

    def test_unknown_expiry_excluded_from_ranking(self):
        value = plan()
        value.valid_until = None
        self.assertEqual(compare([value], trip())["price_order"], [])

    def test_mixed_real_simulation_rejected(self):
        other = plan().model_copy(update={"plan_id":"second-test", "data_kind":"real"})
        with self.assertRaises(ValueError):
            compare([plan(), other], trip())

    def test_trip_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            calculate(plan().model_copy(update={"trip_id":"different-test"}), trip())

    def test_workflow_stops_without_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(trip(), [], tmp)
            self.assertEqual(result["status"], "needs_offers")
            self.assertTrue((Path(tmp) / (result["execution_id"] + ".json")).exists())

    def test_workflow_runs_policy_before_stopping_for_missing_quotes(self):
        store = PolicyStore(ROOT)
        record = next(r for r in store.list_snapshots() if r.document_id == "jrfu_domestic_travel")
        policy = RuleRequest(company_id=None, employee_scope=None, document_ids=[record.document_id],
                             snapshot_ids=[record.snapshot_id], usage_mode="demo")
        with tempfile.TemporaryDirectory() as tmp:
            result = run(trip(), [], tmp, policy, store)
        self.assertEqual(result["status"], "needs_offers")
        self.assertIn("lodging_limit", [r["kind"] for r in result["policy"]["rules"]])
        self.assertEqual([e["step"] for e in result["events"]], ["requirements", "policy", "offers"])

    def test_mvp_flow_imports_compares_and_exports_japanese_draft(self):
        store = PolicyStore(ROOT)
        record = next(r for r in store.list_snapshots() if r.document_id == "jrfu_domestic_travel")
        policy = RuleRequest(company_id=None, employee_scope=None, document_ids=[record.document_id],
                             snapshot_ids=[record.snapshot_id], usage_mode="demo")
        with tempfile.TemporaryDirectory() as tmp:
            result = run(trip(), [plan()], Path(tmp) / "runs", policy, store)
            self.assertIsNotNone(result["comparison"])
            self.assertEqual(len(result["comparison"]["results"]), 1)
            draft = build_draft(trip(), plan(), "review@example.invalid")
            saved = save_draft(draft, Path(tmp) / "drafts")
            self.assertTrue(Path(saved).exists())
        self.assertFalse(draft["sent"])
        self.assertIn("まだ送信されていません", draft["body"])

    def test_draft_is_unsent_and_content_bound(self):
        first = build_draft(trip(), plan(), "review@example.invalid")
        changed = build_draft(trip(), plan().model_copy(update={"version":"2"}), "review@example.invalid")
        self.assertFalse(first["sent"])
        self.assertNotEqual(first["confirmation_fingerprint"], changed["confirmation_fingerprint"])
        self.assertIn("規程上の根拠：適用が確認された条文は添付されていません", first["body"])
        self.assertIn("出張承認申請", first["subject"])

    def test_incomplete_trip_cannot_make_draft(self):
        with self.assertRaises(ValueError):
            build_draft(trip().model_copy(update={"purpose":None}), plan(), "review@example.invalid")

    def test_header_injection_rejected(self):
        with self.assertRaises(ValueError):
            build_draft(trip(), plan(), "a@example.invalid\r\nBcc:b@example.invalid")

    def test_repeated_draft_export_is_idempotent(self):
        draft = build_draft(trip(), plan(), "review@example.invalid")
        with tempfile.TemporaryDirectory() as tmp:
            first = save_draft(draft, tmp)
            second = save_draft(draft, tmp)
            self.assertEqual(first, second)
            self.assertEqual(len(list(Path(tmp).glob("*.eml"))), 1)

    def test_email_adapter_never_claims_success(self):
        self.assertEqual(send({}).status, "not_configured")

    def test_empty_actual_offer_file_is_explicit(self):
        result = load_plans(ROOT / "data/offers/plans.json")
        self.assertEqual(result.status, "no_results")


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalServer(("127.0.0.1", 0), ROOT)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_home_and_assets(self):
        for path in ("/", "/static/app.css", "/static/workspace.js"):
            with self.subTest(path=path), urlopen(self.base + path) as result:
                self.assertEqual(result.status, 200)
                self.assertIn("frame-ancestors 'none'", result.headers["Content-Security-Policy"])

    def test_plan_schema_is_downloadable(self):
        with urlopen(self.base + "/api/plan-schema") as result:
            schema = json.load(result)
        self.assertIn("plan_id", schema["properties"])

    def test_plan_file_endpoint_validates_common_format(self):
        request = Request(self.base + "/api/plans", data=json.dumps([plan().model_dump()]).encode(),
                          headers={"Content-Type":"application/json"})
        with urlopen(request) as response:
            value = json.load(response)
        self.assertEqual(value["status"], "success")
        self.assertEqual(value["plans"][0]["plan_id"], "unit-test")

    def test_demo_catalog_lists_only_user_uploads(self):
        with urlopen(self.base + "/api/snapshots") as result:
            self.assertEqual(json.load(result), [])

    def test_natural_language_api_returns_missing_fields_and_absolute_date(self):
        request = Request(self.base + "/api/intent", data=json.dumps({
            "text":"下周三去大阪当天回，见客户", "base_time":"2026-09-21T12:00:00+09:00"
        }, ensure_ascii=False).encode(), headers={"Content-Type":"application/json"})
        with urlopen(request) as response:
            value = json.load(response)
        self.assertEqual(value["date_context"]["departure_date"], "2026-09-30")

    def test_rules_api_rejects_bundled_sources(self):
        record = next(r for r in self.server.store.list_snapshots() if r.document_id == "jrfu_domestic_travel")
        payload = {"company_id":None, "employee_scope":None, "document_ids":[record.document_id],
                   "snapshot_ids":[record.snapshot_id], "usage_mode":"demo"}
        request = Request(self.base + "/api/rules", data=json.dumps(payload).encode(),
                          headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)

    def test_cross_origin_write_rejected(self):
        request = Request(self.base + "/api/trip", data=b"{}", headers={"Content-Type":"application/json", "Origin":"https://example.invalid"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)

    def test_unknown_fields_rejected(self):
        request = Request(self.base + "/api/trip", data=b'{"guess":true}', headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 400)

    def test_no_directory_listing(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/config/providers.json")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
