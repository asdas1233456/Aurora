"""向量检索模块。"""

from __future__ import annotations

from pathlib import Path

from llama_index.core.schema import NodeWithScore

from app.config import AppConfig
from app.schemas import RetrievedChunk
from app.services.knowledge_base_service import load_index


def _normalize_node(node_with_score: NodeWithScore) -> RetrievedChunk:
    """把 LlamaIndex 的节点对象转换成项目内部结构。"""
    node = node_with_score.node
    metadata = node.metadata or {}

    source_path = str(
        metadata.get("source_path") or metadata.get("file_path") or metadata.get("file_name", "")
    )
    file_name = metadata.get("source_file") or Path(source_path).name or "未知文件"
    text = node.get_content(metadata_mode="none")

    return RetrievedChunk(
        file_name=file_name,
        source_path=source_path or file_name,
        text=text,
        score=node_with_score.score,
    )


def retrieve_chunks(
    question: str,
    config: AppConfig,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """根据问题从知识库中召回最相关的文本片段。"""
    index = load_index(config)
    retriever = index.as_retriever(similarity_top_k=top_k or config.default_top_k)
    nodes = retriever.retrieve(question)
    return [_normalize_node(node) for node in nodes]

