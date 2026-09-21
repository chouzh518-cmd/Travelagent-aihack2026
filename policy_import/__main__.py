import argparse
import json
import sys
from pathlib import Path

from .models import Binding, ImportSpec, SearchRequest, SearchResponse, Snapshot
from .store import PolicyStore, atomic_json


def main():
    parser = argparse.ArgumentParser(description="規程の取り込みと原文検索")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest", "bind", "search"):
        p = sub.add_parser(name)
        p.add_argument("json_file")
    sub.add_parser("list")
    sub.add_parser("schema")
    args = parser.parse_args()
    try:
        store = PolicyStore(args.root)
        if args.command == "schema":
            for model in (ImportSpec, Binding, SearchRequest, Snapshot, SearchResponse):
                atomic_json(Path(args.root) / "schemas" / f"{model.__name__}.json", model.model_json_schema())
            result = {"status": "success", "message": "データ形式を保存しました。"}
        elif args.command == "list":
            result = [{"document_id": r.document_id, "snapshot_id": r.snapshot_id,
                       "title": r.title, "extraction_status": r.extraction_status, "chunks": len(r.chunks)} for r in store.list_snapshots()]
        else:
            value = Path(args.json_file).read_text(encoding="utf-8")
            if args.command == "ingest":
                result = store.ingest(ImportSpec.model_validate_json(value)).model_dump()
            elif args.command == "bind":
                result = store.bind(Binding.model_validate_json(value)).model_dump()
            else:
                result = store.search(SearchRequest.model_validate_json(value)).model_dump()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and result.get("status") in ("failed", "blocked"):
            return 2
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
