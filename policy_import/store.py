from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path

from .extract import PARSER_VERSION, chunk_blocks, extract
from .models import Binding, Hit, ImportSpec, Issue, SearchRequest, SearchResponse, Snapshot


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value):
    import uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_METHOD = "fastembed:" + EMBEDDING_MODEL + ":384d_v1"
# FastEmbed cosine distance is unbounded for unrelated text; returning the
# nearest chunk without a floor would fabricate evidence for arbitrary input.
MAX_SEMANTIC_DISTANCE = 0.75


@lru_cache(maxsize=4)
def _embedder(cache_dir: str):
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=cache_dir)


def embeddings(texts, cache_dir):
    return [vector.tolist() for vector in _embedder(str(cache_dir)).embed(texts)]


class PolicyStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.snapshots = self.root / "data/policies/snapshots"
        self.bindings_path = self.root / "storage/bindings.json"
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import chromadb
            from chromadb.config import Settings
            self._client = chromadb.PersistentClient(path=str(self.root / "storage/chroma"),
                                                     settings=Settings(anonymized_telemetry=False))
        return self._client

    def folder(self, snapshot_id):
        # Generated IDs only; untrusted IDs cannot become filesystem paths.
        import re
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise ValueError("invalid snapshot_id")
        return self.snapshots / snapshot_id

    def load(self, snapshot_id):
        folder = self.folder(snapshot_id)
        if not (folder / "ready.json").exists():
            raise ValueError("snapshot is not indexed or does not exist")
        record = Snapshot.model_validate_json((folder / "record.json").read_text(encoding="utf-8"))
        original = folder / ("source." + record.source.type)
        if digest(original.read_bytes()) != record.content_sha256:
            raise ValueError("source snapshot hash mismatch")
        return record

    def list_snapshots(self):
        return [self.load(p.parent.name) for p in sorted(self.snapshots.glob("*/ready.json"))]

    def ingest(self, spec: ImportSpec, data: bytes | None = None):
        if data is None:
            if spec.source.file_path:
                path = Path(spec.source.file_path)
                data = (path if path.is_absolute() else self.root / path).read_bytes()
            else:
                import requests
                # Desktop CLI only. Do not expose this fetcher as a public URL-fetch service.
                with requests.get(spec.source.url, timeout=(10, 30), stream=True) as response:
                    response.raise_for_status()
                    data = b""
                    for part in response.iter_content(65536):
                        data += part
                        if len(data) > 25 * 1024 * 1024:
                            raise ValueError("source exceeds 25 MiB")
        if len(data) > 25 * 1024 * 1024:
            raise ValueError("source exceeds 25 MiB")
        content_hash = digest(data)
        identity = json.dumps({"spec": spec.model_dump(), "content_sha256": content_hash,
                               "parser_version": PARSER_VERSION}, sort_keys=True, ensure_ascii=False)
        snapshot_id = digest(identity.encode("utf-8"))
        folder = self.folder(snapshot_id)
        if (folder / "ready.json").exists():
            return self.load(snapshot_id)
        folder.mkdir(parents=True, exist_ok=True)
        original = folder / ("source." + spec.source.type)
        if original.exists():
            if original.read_bytes() != data:
                raise ValueError("immutable snapshot collision")
        else:
            with original.open("xb") as stream:
                stream.write(data)
        try:
            blocks, issues = extract(data, spec.source.type, spec.extraction)
            chunks = chunk_blocks(blocks, snapshot_id)
        except Exception as exc:
            atomic_json(folder / "failure.json", {"status": "failed", "source": spec.source.model_dump(),
                        "queried_at": now(), "message": str(exc)})
            raise
        record = Snapshot(document_id=spec.document_id, snapshot_id=snapshot_id, title=spec.title,
                          document_kind=spec.document_kind, issuer_name=spec.issuer_name,
                          policy_version=spec.policy_version, revision_date=spec.revision_date,
                          source=spec.source, snapshot_path=str(original.relative_to(self.root)),
                          content_sha256=content_hash, queried_at=now(), extraction=spec.extraction,
                          parser_version=PARSER_VERSION, extraction_status="partial" if issues else "success",
                          issues=issues, chunks=chunks)
        atomic_json(folder / "blocks.json", [b.model_dump() for b in blocks])
        atomic_json(folder / "record.json", record.model_dump())
        name = "policy_" + snapshot_id
        if chunks:
            try:
                existing = self.client.get_collection(name, embedding_function=None)
                if (existing.metadata or {}).get("embedding_method") != EMBEDDING_METHOD:
                    self.client.delete_collection(name)
            except Exception:
                pass
            collection = self.client.get_or_create_collection(name, embedding_function=None,
                                            metadata={"embedding_method": EMBEDDING_METHOD, "hnsw:space": "cosine"})
            for offset in range(0, len(chunks), 100):
                batch = chunks[offset:offset+100]
                collection.upsert(ids=[c.chunk_id for c in batch], documents=[c.text for c in batch],
                                  embeddings=embeddings([c.text for c in batch], self.root / "models"),
                                  metadatas=[{"document_id": spec.document_id, "snapshot_id": snapshot_id,
                                              "sequence": c.sequence, "chunk_type": c.chunk_type} for c in batch])
        atomic_json(folder / "ready.json", {"snapshot_id": snapshot_id, "chunk_count": len(chunks), "embedding_method": EMBEDDING_METHOD})
        return record

    def bindings(self):
        if not self.bindings_path.exists():
            return []
        raw = json.loads(self.bindings_path.read_text(encoding="utf-8"))
        return [Binding.model_validate(item) for item in raw]

    def bind(self, binding: Binding):
        record = self.load(binding.snapshot_id)
        if record.document_id != binding.document_id:
            raise ValueError("binding document_id does not match snapshot")
        if binding.usage_mode == "production" and record.document_kind == "template":
            raise ValueError("templates cannot be bound for production")
        values = self.bindings()
        if binding not in values:
            values.append(binding)
            atomic_json(self.bindings_path, [b.model_dump() for b in values])
        return binding

    def search(self, request: SearchRequest):
        response = SearchResponse(company_id=request.company_id, document_ids=request.document_ids,
                        snapshot_ids=request.snapshot_ids, usage_mode=request.usage_mode,
                        query=request.query, queried_at=now(), status="blocked", results=[], issues=[])
        try:
            bindings = self.bindings()
            records = [self.load(sid) for sid in dict.fromkeys(request.snapshot_ids)]
            if {r.document_id for r in records} != set(request.document_ids):
                raise PermissionError("document_ids must match the selected snapshots exactly")
            for record in records:
                allowed = any(b.company_id == request.company_id and b.snapshot_id == record.snapshot_id
                              and b.document_id == record.document_id and b.usage_mode == request.usage_mode
                              for b in bindings)
                if not allowed or (request.usage_mode == "production" and not request.company_id):
                    raise PermissionError("no exact applicability binding for this request")
                if record.extraction_status != "success" and record.chunks:
                    response.issues.append(Issue(code="PARTIAL_EXTRACTION", message=f"{record.title}: 一部を読み取れませんでした。該当箇所を原文で確認してください。"))
            hits = []
            for record in records:
                if record.extraction_status != "success" or not record.chunks:
                    continue
                index = {c.chunk_id: c for c in record.chunks}
                collection = self.client.get_collection("policy_" + record.snapshot_id, embedding_function=None)
                if (collection.metadata or {}).get("embedding_method") != EMBEDDING_METHOD or collection.count() != len(index):
                    self.reindex(record)
                    collection = self.client.get_collection("policy_" + record.snapshot_id, embedding_function=None)
                result = collection.query(query_embeddings=embeddings([request.query], self.root / "models"), n_results=min(len(index), max(request.limit * 3, request.limit)), include=["distances"])
                for chunk_id, distance in zip(result["ids"][0], result["distances"][0]):
                    if float(distance) > MAX_SEMANTIC_DISTANCE:
                        continue
                    chunk = index[chunk_id]
                    related_ids = set()
                    queue = [chunk]
                    while queue:
                        item = queue.pop()
                        for ref in item.references:
                            if ref.status != "resolved":
                                continue
                            for target_id in ref.target_chunk_ids:
                                if target_id != chunk_id and target_id not in related_ids:
                                    related_ids.add(target_id)
                                    queue.append(index[target_id])
                    hits.append(Hit(document_id=record.document_id, snapshot_id=record.snapshot_id,
                                    title=record.title, document_kind=record.document_kind,
                                    source=record.source, snapshot_path=record.snapshot_path,
                                    content_sha256=record.content_sha256, distance=float(distance), chunk=chunk,
                                    related_chunks=sorted((index[k] for k in related_ids), key=lambda c: c.sequence)))
            response.results = sorted(hits, key=lambda hit: (hit.distance, hit.document_id, hit.chunk.sequence))[:request.limit]
            response.status = "found" if response.results else "not_found"
            if not response.results:
                response.issues.append(Issue(code="NO_SEMANTIC_MATCH", message="関連する原文箇所を取得できませんでした。該当規定が存在しないことを意味しません。"))
        except PermissionError as exc:
            response.status = "blocked"
            response.issues.append(Issue(code="SCOPE_BLOCKED", message=str(exc)))
        except Exception as exc:
            response.status = "failed"
            response.issues.append(Issue(code="RETRIEVAL_FAILED", message=str(exc)))
        return response

    def reindex(self, record: Snapshot):
        name = "policy_" + record.snapshot_id
        try:
            self.client.delete_collection(name)
        except Exception:
            pass
        collection = self.client.create_collection(name, embedding_function=None,
            metadata={"embedding_method": EMBEDDING_METHOD, "hnsw:space": "cosine"})
        for offset in range(0, len(record.chunks), 100):
            batch = record.chunks[offset:offset+100]
            collection.upsert(ids=[c.chunk_id for c in batch], documents=[c.text for c in batch],
                embeddings=embeddings([c.text for c in batch], self.root / "models"),
                metadatas=[{"document_id": record.document_id, "snapshot_id": record.snapshot_id,
                            "sequence": c.sequence, "chunk_type": c.chunk_type} for c in batch])
        atomic_json(self.folder(record.snapshot_id) / "ready.json",
                    {"snapshot_id": record.snapshot_id, "chunk_count": len(record.chunks),
                     "embedding_method": EMBEDDING_METHOD})

    def delete(self, snapshot_id: str):
        record = self.load(snapshot_id)
        remaining = [binding for binding in self.bindings() if binding.snapshot_id != snapshot_id]
        atomic_json(self.bindings_path, [binding.model_dump() for binding in remaining])
        try:
            self.client.delete_collection("policy_" + snapshot_id)
        except Exception:
            pass
        import shutil
        shutil.rmtree(self.folder(snapshot_id))
        return record
