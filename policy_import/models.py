from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(Model):
    type: Literal["pdf", "docx", "html", "md", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"]
    url: str | None
    file_path: str | None

    @model_validator(mode="after")
    def source_present(self):
        if not self.url and not self.file_path:
            raise ValueError("source.url or source.file_path is required")
        if self.url:
            from urllib.parse import urlsplit
            url = urlsplit(self.url)
            if url.scheme not in ("https", "http") or not url.hostname or url.username or url.password:
                raise ValueError("source.url must be an HTTP(S) URL without credentials")
        return self


class ExtractionOptions(Model):
    html_selector: str | None = None
    start_heading: str | None = None
    end_heading: str | None = None


class ImportSpec(Model):
    schema_version: Literal["1.0"] = "1.0"
    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    document_kind: Literal["policy", "template", "project"]
    issuer_name: str | None
    policy_version: str | None
    revision_date: str | None
    source: Source
    extraction: ExtractionOptions = Field(default_factory=ExtractionOptions)

    @field_validator("revision_date")
    @classmethod
    def valid_date(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("revision_date must be YYYY-MM-DD")
        return value


class Issue(Model):
    code: str
    message: str
    page_number: int | None = None
    chunk_id: str | None = None


class Location(Model):
    page_number: int | None
    block_index: int = Field(ge=1)
    locator: str
    bbox: list[float] | None = None


class Table(Model):
    rows: list[list[str | None]]
    location: Location
    # A null grid entry stays null; no inferred carry-forward of merged cells.
    cell_bboxes: list[list[list[float] | None]] | None = None


class Block(Model):
    text: str
    kind: Literal["text", "heading", "table"]
    location: Location
    table: Table | None = None


class Reference(Model):
    label: str
    target_chunk_ids: list[str]
    status: Literal["resolved", "unresolved", "ambiguous"]


class Chunk(Model):
    chunk_id: str
    snapshot_id: str
    sequence: int
    chunk_type: Literal["article", "table", "appendix", "context"]
    heading_path: list[str]
    article_label: str | None
    text: str
    locations: list[Location]
    tables: list[Table]
    references: list[Reference]
    issues: list[Issue]


class Snapshot(Model):
    schema_version: Literal["1.0"] = "1.0"
    document_id: str
    snapshot_id: str
    title: str
    document_kind: Literal["policy", "template", "project"]
    issuer_name: str | None
    policy_version: str | None
    revision_date: str | None
    source: Source
    snapshot_path: str
    content_sha256: str
    queried_at: str
    extraction_status: Literal["success", "partial", "failed"]
    extraction: ExtractionOptions
    parser_version: str
    issues: list[Issue]
    chunks: list[Chunk]

    @field_validator("queried_at")
    @classmethod
    def timestamp_with_zone(cls, value):
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("queried_at must include timezone")
        return value


class Binding(Model):
    schema_version: Literal["1.0"] = "1.0"
    company_id: str | None
    document_id: str
    snapshot_id: str
    usage_mode: Literal["demo", "production"]
    approval_evidence: str | None

    @model_validator(mode="after")
    def production_requires_evidence(self):
        if self.usage_mode == "production" and (not self.company_id or not self.approval_evidence):
            raise ValueError("production binding requires company_id and approval_evidence")
        return self


class SearchRequest(Model):
    schema_version: Literal["1.0"] = "1.0"
    company_id: str | None
    document_ids: list[str] = Field(min_length=1)
    snapshot_ids: list[str] = Field(min_length=1)
    usage_mode: Literal["demo", "production"]
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class Hit(Model):
    document_id: str
    snapshot_id: str
    title: str
    document_kind: Literal["policy", "template", "project"]
    source: Source
    snapshot_path: str
    content_sha256: str
    distance: float
    chunk: Chunk
    related_chunks: list[Chunk]


class SearchResponse(Model):
    schema_version: Literal["1.0"] = "1.0"
    company_id: str | None
    document_ids: list[str]
    snapshot_ids: list[str]
    usage_mode: Literal["demo", "production"]
    query: str
    queried_at: str
    status: Literal["found", "not_found", "blocked", "failed"]
    retrieval_method: Literal["chroma_semantic_fastembed_v1"] = "chroma_semantic_fastembed_v1"
    results: list[Hit]
    issues: list[Issue]
