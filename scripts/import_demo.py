"""Import the two approved public sources without fabricating company adoption."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policy_import.models import Binding, ImportSpec, SearchRequest
from policy_import.store import PolicyStore, atomic_json

root = Path(__file__).resolve().parents[1]
store = PolicyStore(root)
for filename, query in (("import_jrfu.json", "宿泊費"), ("import_michibiku.json", "日当")):
    spec = ImportSpec.model_validate_json((root / "config" / filename).read_text(encoding="utf-8"))
    record = store.ingest(spec)
    store.bind(Binding(company_id=None, document_id=record.document_id, snapshot_id=record.snapshot_id,
                       usage_mode="demo", approval_evidence=None))
    request = SearchRequest(company_id=None, document_ids=[record.document_id], snapshot_ids=[record.snapshot_id],
                            usage_mode="demo", query=query)
    atomic_json(root / "examples" / f"search_{record.document_id}.json", request.model_dump())
    result = store.search(request)
    atomic_json(root / "output" / f"search_{record.document_id}.json", result.model_dump())
    print(record.document_id, record.extraction_status, len(record.chunks), "chunks", result.status)
