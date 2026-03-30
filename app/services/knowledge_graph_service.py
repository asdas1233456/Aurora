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
    category_counts: defaultdict[str, int] = defaultdict(int)
    type_counts: defaultdict[str, int] = defaultdict(int)
    type_node_ids: dict[str, str] = {}

    for document in documents:
        category = document.theme or infer_document_category(document.name)
        category_counts[category] += 1
        file_type = document.extension.upper()
        type_counts[file_type] += 1

    for category, count in sorted(category_counts.items()):
        node_id = f"category:{_slugify(category)}"
        category_node_ids[category] = node_id
        nodes.append(
            KnowledgeGraphNode(
                id=node_id,
                label=category,
                node_type="category",
                size=14 + count * 2,
                meta={
                    "document_count": count,
                },
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

    for file_type, count in sorted(type_counts.items()):
        node_id = f"type:{file_type.lower()}"
        type_node_ids[file_type] = node_id
        nodes.append(
            KnowledgeGraphNode(
                id=node_id,
                label=file_type,
                node_type="file_type",
                size=12 + count * 2,
                meta={
                    "document_count": count,
                },
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
        },
    )


def _slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
