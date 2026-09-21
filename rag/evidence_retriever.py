"""Adapt verified PolicyStore evidence to LlamaIndex's retriever interface."""
from __future__ import annotations

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode


class EvidenceRetriever(BaseRetriever):
    def __init__(self, citations):
        self._citations = citations
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        nodes = []
        for item in self._citations:
            body = (f"[{item['reference']}] 资料：{item['title']}；位置：{item['location']}\n"
                    f"原文：\n{item['text']}")
            node = TextNode(
                id_=item["chunk_id"],
                text=body,
                metadata={
                    "reference": item["reference"],
                    "document_id": item["document_id"],
                    "snapshot_id": item["snapshot_id"],
                    "chunk_id": item["chunk_id"],
                    "title": item["title"],
                    "article_label": item["article_label"] or "",
                    "location": item["location"],
                    "distance": item["distance"],
                },
                excluded_embed_metadata_keys=["distance"],
                excluded_llm_metadata_keys=["distance"],
            )
            nodes.append(NodeWithScore(node=node))
        return nodes
