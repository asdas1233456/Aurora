"""知识图谱构建服务。"""

from __future__ import annotations

from collections import defaultdict

from app.config import AppConfig
from app.schemas import KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode
from app.services.catalog_service import list_document_catalog
from app.services.document_taxonomy import infer_document_category


ROOT_NODE_ID = "aurora-root"


def build_knowledge_graph(config: AppConfig) -> KnowledgeGraph:
    """根据当前文档资产生成一个轻量知识图谱。"""
    documents = list_document_catalog(config)
    return build_knowledge_graph_from_documents(config, documents)


def build_filtered_knowledge_graph(
    config: AppConfig,
    *,
    theme: str | None = None,
    file_type: str | None = None,
) -> KnowledgeGraph:
    """Build the graph after applying optional server-side filters."""
    documents = filter_graph_documents(
        list_document_catalog(config),
        theme=theme,
        file_type=file_type,
    )
    return build_knowledge_graph_from_documents(config, documents)


def build_knowledge_graph_from_documents(
    config: AppConfig,
    documents: list[object],
) -> KnowledgeGraph:
    """Build the lightweight graph from a preloaded document list."""
    nodes: list[KnowledgeGraphNode] = [
        KnowledgeGraphNode(
            id=ROOT_NODE_ID,
            label="Aurora",
            node_type="root",
            size=max(28, 28 + len(documents)),
            meta={
                "document_count": len(documents),
                "collection": config.collection_name,
            },
        )
    ]
    edges: list[KnowledgeGraphEdge] = []

    category_node_ids: dict[str, str] = {}
    category_stats: defaultdict[str, dict[str, int]] = defaultdict(_make_bucket_stats)
    type_stats: defaultdict[str, dict[str, int]] = defaultdict(_make_bucket_stats)
    type_node_ids: dict[str, str] = {}
    status_counts: defaultdict[str, int] = defaultdict(int)
    tagged_document_count = 0
    untagged_document_count = 0
    uncategorized_document_count = 0
    citation_covered_document_count = 0

    for document in documents:
        category = document.theme or infer_document_category(document.name)
        status = _normalize_status(getattr(document, "status", "pending"))
        file_type = document.extension.upper()
        has_tags = bool(getattr(document, "tags", []))
        citation_count = _safe_int(getattr(document, "citation_count", 0))

        _update_bucket_stats(category_stats[category], status=status, has_tags=has_tags, citation_count=citation_count)
        _update_bucket_stats(type_stats[file_type], status=status, has_tags=has_tags, citation_count=citation_count)
        status_counts[status] += 1
        if has_tags:
            tagged_document_count += 1
        else:
            untagged_document_count += 1
        if category == "Uncategorized":
            uncategorized_document_count += 1
        if citation_count > 0:
            citation_covered_document_count += 1

    for category, bucket in sorted(category_stats.items()):
        count = bucket["document_count"]
        node_id = f"category:{_slugify(category)}"
        category_node_ids[category] = node_id
        nodes.append(
            KnowledgeGraphNode(
                id=node_id,
                label=category,
                node_type="category",
                size=14 + count * 2,
                meta=dict(bucket),
            )
        )
        edges.append(
            KnowledgeGraphEdge(
                source=ROOT_NODE_ID,
                target=node_id,
                label="contains",
                weight=count,
            )
        )

    for file_type, bucket in sorted(type_stats.items()):
        count = bucket["document_count"]
        node_id = f"type:{file_type.lower()}"
        type_node_ids[file_type] = node_id
        nodes.append(
            KnowledgeGraphNode(
                id=node_id,
                label=file_type,
                node_type="file_type",
                size=12 + count * 2,
                meta=dict(bucket),
            )
        )
        edges.append(
            KnowledgeGraphEdge(
                source=ROOT_NODE_ID,
                target=node_id,
                label="formats",
                weight=count,
            )
        )

    for document in documents:
        category = document.theme or infer_document_category(document.name)
        file_type = document.extension.upper()
        node_id = f"document:{document.document_id or _slugify(document.path)}"
        nodes.append(
            KnowledgeGraphNode(
                id=node_id,
                label=document.name,
                node_type="document",
                size=10 + min(12, max(1, int(document.size_bytes / 1024 / 8))),
                meta={
                    "document_id": document.document_id,
                    "relative_path": document.relative_path,
                    "updated_at": document.updated_at,
                    "extension": document.extension,
                    "size_bytes": document.size_bytes,
                    "category": category,
                    "tags": document.tags,
                    "status": document.status,
                    "chunk_count": _safe_int(getattr(document, "chunk_count", 0)),
                    "citation_count": _safe_int(getattr(document, "citation_count", 0)),
                    "last_indexed_at": str(getattr(document, "last_indexed_at", "") or ""),
                    "last_error": str(getattr(document, "last_error", "") or ""),
                    "title": str(getattr(document, "title", "") or ""),
                    "source_url": str(getattr(document, "source_url", "") or ""),
                    "resolved_url": str(getattr(document, "resolved_url", "") or ""),
                },
            )
        )
        edges.append(
            KnowledgeGraphEdge(
                source=category_node_ids[category],
                target=node_id,
                label="documents",
                weight=1,
            )
        )
        edges.append(
            KnowledgeGraphEdge(
                source=type_node_ids[file_type],
                target=node_id,
                label="typed_as",
                weight=1,
            )
        )

    return KnowledgeGraph(
        nodes=nodes,
        edges=edges,
        summary={
            "document_count": len(documents),
            "category_count": len(category_node_ids),
            "file_type_count": len(type_node_ids),
            "edge_count": len(edges),
            "indexed_document_count": status_counts.get("indexed", 0),
            "attention_document_count": (
                status_counts.get("pending", 0)
                + status_counts.get("changed", 0)
                + status_counts.get("failed", 0)
            ),
            "tagged_document_count": tagged_document_count,
            "untagged_document_count": untagged_document_count,
            "uncategorized_document_count": uncategorized_document_count,
            "citation_covered_document_count": citation_covered_document_count,
            "status_counts": dict(status_counts),
            "top_categories": _top_buckets(category_stats),
            "top_file_types": _top_buckets(type_stats),
        },
    )


def _slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")


def _make_bucket_stats() -> dict[str, int]:
    return {
        "document_count": 0,
        "indexed_count": 0,
        "pending_count": 0,
        "changed_count": 0,
        "failed_count": 0,
        "tagged_document_count": 0,
        "citation_covered_document_count": 0,
    }


def _normalize_status(value: object) -> str:
    normalized = str(value or "pending").strip().lower()
    return normalized or "pending"


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _update_bucket_stats(
    bucket: dict[str, int],
    *,
    status: str,
    has_tags: bool,
    citation_count: int,
) -> None:
    bucket["document_count"] += 1
    if status == "indexed":
        bucket["indexed_count"] += 1
    elif status == "pending":
        bucket["pending_count"] += 1
    elif status == "changed":
        bucket["changed_count"] += 1
    elif status == "failed":
        bucket["failed_count"] += 1

    if has_tags:
        bucket["tagged_document_count"] += 1
    if citation_count > 0:
        bucket["citation_covered_document_count"] += 1


def _top_buckets(buckets: dict[str, dict[str, int]], *, limit: int = 5) -> list[dict[str, object]]:
    ranked_items = sorted(
        buckets.items(),
        key=lambda item: (
            item[1]["document_count"],
            item[1]["indexed_count"],
            -item[1]["failed_count"],
            item[0].lower(),
        ),
        reverse=True,
    )
    return [
        {
            "label": label,
            "document_count": stats["document_count"],
            "indexed_count": stats["indexed_count"],
            "attention_count": stats["pending_count"] + stats["changed_count"] + stats["failed_count"],
        }
        for label, stats in ranked_items[:limit]
    ]


def filter_graph_documents(
    documents: list[object],
    *,
    theme: str | None = None,
    file_type: str | None = None,
) -> list[object]:
    """Filter graph documents by inferred theme and file type."""
    normalized_theme = str(theme or "").strip().lower()
    normalized_file_type = str(file_type or "").strip().lstrip(".").lower()
    if not normalized_theme and not normalized_file_type:
        return documents

    filtered_documents: list[object] = []
    for document in documents:
        document_theme = str(document.theme or infer_document_category(document.name)).strip().lower()
        document_type = str(document.extension or "").strip().lstrip(".").lower()
        if normalized_theme and document_theme != normalized_theme:
            continue
        if normalized_file_type and document_type != normalized_file_type:
            continue
        filtered_documents.append(document)
    return filtered_documents
