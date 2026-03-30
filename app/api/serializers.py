"""Response serializers for public API payloads."""

from __future__ import annotations

from dataclasses import asdict

from app.schemas import Citation, DocumentSummary, KnowledgeBaseJob, KnowledgeGraph, SystemOverview


def serialize_document_summary(item: DocumentSummary) -> dict[str, object]:
    return {
        "document_id": item.document_id,
        "name": item.name,
        "relative_path": item.relative_path,
        "extension": item.extension,
        "size_bytes": item.size_bytes,
        "updated_at": item.updated_at,
        "status": item.status,
        "theme": item.theme,
        "tags": item.tags,
        "content_hash": item.content_hash,
        "indexed_hash": item.indexed_hash,
        "chunk_count": item.chunk_count,
        "citation_count": item.citation_count,
        "last_indexed_at": item.last_indexed_at,
        "last_error": item.last_error,
    }


def serialize_citation(item: Citation) -> dict[str, object]:
    return {
        "document_id": item.document_id,
        "file_name": item.file_name,
        "relative_path": item.relative_path,
        "snippet": item.snippet,
        "full_text": item.full_text,
        "score": item.score,
        "vector_score": item.vector_score,
        "lexical_score": item.lexical_score,
        "theme": item.theme,
        "tags": item.tags,
    }


def serialize_job(job: KnowledgeBaseJob | None) -> dict[str, object] | None:
    return asdict(job) if job else None


def serialize_graph(graph: KnowledgeGraph) -> dict[str, object]:
    return {
        "nodes": [asdict(node) for node in graph.nodes],
        "edges": [asdict(edge) for edge in graph.edges],
        "summary": graph.summary,
    }


def serialize_overview(item: SystemOverview) -> dict[str, object]:
    return asdict(item)


def serialize_workspace_bootstrap(payload: dict[str, object]) -> dict[str, object]:
    knowledge_status = dict(payload.get("knowledge_status") or {})
    knowledge_status["current_job"] = serialize_job(knowledge_status.get("current_job"))
    return {
        "overview": serialize_overview(payload["overview"]),
        "knowledge_status": knowledge_status,
        "documents": [serialize_document_summary(item) for item in payload.get("documents", [])],
        "graph": serialize_graph(payload["graph"]),
    }
