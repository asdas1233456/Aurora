"""Response serializers for public API payloads."""

from __future__ import annotations

import json
from dataclasses import asdict

from app.schemas import (
    BusinessRequest,
    BusinessResponse,
    Citation,
    ChatMessageRecord,
    ChatSessionRecord,
    DocumentPreviewPayload,
    DocumentSummary,
    KnowledgeBaseJob,
    KnowledgeGraph,
    LifecycleMaintenanceReport,
    MemoryContextItem,
    MemoryAccessAuditRecord,
    MemoryFact,
    MemoryRetentionAuditRecord,
    PolicyDecisionRecord,
    SecurityEventRecord,
    ScopeRef,
    SystemMetricSnapshotRecord,
    SystemOverview,
)
from app.services.memory.read.memory_retrieval_models import (
    DroppedMemoryCandidate,
    MemoryRetrievalBundle,
    MemoryRetrievalPlan,
    MemoryRetrievalResult,
)


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


def serialize_document_preview(item: DocumentPreviewPayload) -> dict[str, object]:
    return asdict(item)


def serialize_citation(item: Citation) -> dict[str, object]:
    return {
        "knowledge_id": item.knowledge_id,
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
        "chunk_id": item.chunk_id,
        "page_number": item.page_number,
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
        "auth": dict(payload.get("auth") or {}),
    }


def serialize_scope_ref(item: ScopeRef) -> dict[str, object]:
    return {"scope_type": item.scope_type, "scope_id": item.scope_id}


def serialize_business_request(item: BusinessRequest) -> dict[str, object]:
    return asdict(item)


def serialize_business_response(
    item: BusinessResponse,
    *,
    include_raw_response: bool = True,
) -> dict[str, object]:
    payload = asdict(item)
    if not include_raw_response:
        payload["raw_response"] = None
    return payload


def serialize_chat_session_record(item: ChatSessionRecord) -> dict[str, object]:
    return asdict(item)


def serialize_chat_message_record(item: ChatMessageRecord) -> dict[str, object]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "session_id": item.session_id,
        "user_id": item.user_id,
        "role": item.role,
        "content": item.content,
        "provider": item.provider,
        "model": item.model,
        "citations": _parse_json_text(item.citations_json, []),
        "metadata": _parse_json_text(item.metadata_json, {}),
        "created_at": item.created_at,
    }


def serialize_memory_fact(item: MemoryFact) -> dict[str, object]:
    return asdict(item)


def serialize_memory_audit_record(item: MemoryAccessAuditRecord) -> dict[str, object]:
    return asdict(item)


def serialize_memory_retention_audit_record(item: MemoryRetentionAuditRecord) -> dict[str, object]:
    return asdict(item)


def serialize_policy_decision_record(item: PolicyDecisionRecord) -> dict[str, object]:
    return asdict(item)


def serialize_security_event_record(item: SecurityEventRecord) -> dict[str, object]:
    return asdict(item)


def serialize_metric_snapshot_record(item: SystemMetricSnapshotRecord) -> dict[str, object]:
    return asdict(item)


def serialize_lifecycle_maintenance_report(item: LifecycleMaintenanceReport) -> dict[str, object]:
    return asdict(item)


def serialize_memory_context_item(item: MemoryContextItem) -> dict[str, object]:
    return asdict(item)


def serialize_memory_retrieval_plan(item: MemoryRetrievalPlan | None) -> dict[str, object] | None:
    if item is None:
        return None
    return {
        "scene": item.scene,
        "enabled": item.enabled,
        "enable_reason": item.enable_reason,
        "top_k": item.top_k,
        "candidate_limit": item.candidate_limit,
        "per_scope_candidate_limit": item.per_scope_candidate_limit,
        "retrieval_mode": item.retrieval_mode,
        "scope_weights": dict(item.scope_weights),
        "type_weights": dict(item.type_weights),
        "per_scope_top_k": dict(item.per_scope_top_k),
        "min_relevance_score": item.min_relevance_score,
        "min_injection_score": item.min_injection_score,
        "fallback_min_relevance_score": item.fallback_min_relevance_score,
        "recent_window_days": item.recent_window_days,
        "max_injection_chars_per_memory": item.max_injection_chars_per_memory,
        "query_cues": list(item.query_cues),
    }


def serialize_memory_retrieval_result(item: MemoryRetrievalResult) -> dict[str, object]:
    return {
        "memory_fact_id": item.memory_fact_id,
        "scope_type": item.scope_type,
        "scope_id": item.scope_id,
        "type": item.type,
        "content": item.content,
        "retrieval_score": item.retrieval_score,
        "matched_reason": item.matched_reason,
        "selected_for_injection": item.selected_for_injection,
        "source_session_id": item.source_session_id,
        "updated_at": item.updated_at,
        "source_confidence": item.source_confidence,
        "subject_key": item.subject_key,
        "fact_key": item.fact_key,
        "version": item.version,
        "source_type": item.source_type,
        "value_score": item.value_score,
        "retention_level": item.retention_level,
        "retrieval_visibility": item.retrieval_visibility,
        "forgetting_status": item.forgetting_status,
        "score_breakdown": dict(item.score_breakdown),
        "rank": item.rank,
    }


def serialize_dropped_memory_candidate(item: DroppedMemoryCandidate) -> dict[str, object]:
    return {
        "memory_fact_id": item.memory_fact_id,
        "scope_type": item.scope_type,
        "scope_id": item.scope_id,
        "type": item.type,
        "content": item.content,
        "drop_reason": item.drop_reason,
        "retrieval_score": item.retrieval_score,
        "matched_reason": item.matched_reason,
    }


def serialize_memory_retrieval_bundle(item: MemoryRetrievalBundle) -> dict[str, object]:
    return {
        "selected_memories": [serialize_memory_retrieval_result(entry) for entry in item.selected_memories],
        "dropped_candidates": [
            serialize_dropped_memory_candidate(entry)
            for entry in item.dropped_candidates
        ],
        "total_candidates": item.total_candidates,
        "total_selected": item.total_selected,
        "retrieval_plan": serialize_memory_retrieval_plan(item.retrieval_plan),
        "retrieval_trace": item.retrieval_trace,
        "memory_context": [serialize_memory_context_item(entry) for entry in item.memory_context],
    }


def _parse_json_text(raw_text: str, fallback):
    try:
        return json.loads(raw_text)
    except (TypeError, json.JSONDecodeError):
        return fallback
