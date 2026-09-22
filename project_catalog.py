"""Read the exact, file-backed project catalog used by the employee workspace."""
from __future__ import annotations

import json
import re
from pathlib import Path


FIELD_LABELS = {
    "出張プロジェクト": "project_name",
    "出発地": "origin",
    "目的地": "destination",
    "予算上限": "budget_jpy",
    "出張期間": "duration_limit_days",
    "顧客到着期限": "arrival_deadline",
    "出張目的": "purpose",
    "出発日時": "departure_at",
    "到着期限": "arrive_by",
    "帰着期限": "return_by",
    "宿泊": "lodging_required",
}


def _project_path(root: Path, relative_path: str) -> Path:
    base = (root / "data/projects").resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(base):
        raise ValueError("プロジェクト資料は data/projects 内に配置してください。")
    return path


def _read_markdown(path: Path):
    if path.suffix != ".md":
        raise ValueError("プロジェクト資料には .md ファイルを指定してください。")
    data = path.read_bytes()
    if len(data) > 1_000_000:
        raise ValueError("プロジェクト資料は 1 MB 以下にしてください。")
    return data.decode("utf-8-sig")


def _extract_fields(content: str):
    fields = {}
    for line in content.splitlines():
        match = re.fullmatch(r"\s*- ([^：]+)：(.*?)\s*", line)
        if not match:
            continue
        field = FIELD_LABELS.get(match.group(1))
        value = match.group(2).strip()
        if field and value and value not in {"未入力", "未確認", "なし"}:
            fields[field] = value
    if "budget_jpy" in fields:
        amount = re.fullmatch(r"([0-9,]+)円", fields["budget_jpy"])
        if amount:
            fields["budget_jpy"] = int(amount.group(1).replace(",", ""))
    if "duration_limit_days" in fields:
        days = re.fullmatch(r"([0-9]+)日以内", fields["duration_limit_days"])
        if days:
            fields["duration_limit_days"] = int(days.group(1))
    if "lodging_required" in fields:
        lodging = {"必要": True, "不要": False}.get(fields["lodging_required"])
        if lodging is not None:
            fields["lodging_required"] = lodging
    return fields


def load_projects(root: str | Path):
    root = Path(root).resolve()
    catalog_path = root / "data/projects/catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if set(catalog) != {"projects"} or not isinstance(catalog["projects"], list):
        raise ValueError("プロジェクト一覧の形式を確認してください。")
    projects = []
    seen_ids = set()
    for item in catalog["projects"]:
        if set(item) != {"project_id", "project_name", "documents"}:
            raise ValueError("プロジェクト登録項目は project_id、project_name、documents です。")
        project_id = item["project_id"]
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", project_id):
            raise ValueError("project_id は小文字英数字とハイフンで登録してください。")
        if project_id in seen_ids:
            raise ValueError("project_id が重複しています。")
        seen_ids.add(project_id)
        if not isinstance(item["project_name"], str) or not item["project_name"].strip():
            raise ValueError("project_name を登録してください。")
        if not isinstance(item["documents"], list):
            raise ValueError("documents は資料の配列で登録してください。")
        documents = []
        fields = {}
        for document in item["documents"]:
            if set(document) != {"document_id", "title", "document_kind", "path"}:
                raise ValueError("資料登録項目は document_id、title、document_kind、path です。")
            if document["document_kind"] not in {"project", "policy"}:
                raise ValueError("document_kind は project または policy です。")
            path = _project_path(root, document["path"])
            content = _read_markdown(path)
            fields.update(_extract_fields(content))
            documents.append({
                "document_id": document["document_id"],
                "title": document["title"],
                "document_kind": document["document_kind"],
                "path": document["path"],
                "content": content,
            })
        fields["project_name"] = item["project_name"]
        projects.append({
            "project_id": project_id,
            "project_name": item["project_name"],
            "fields": fields,
            "documents": documents,
        })
    return projects
