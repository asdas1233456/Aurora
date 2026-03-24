"""知识库构建与向量索引模块。"""

from __future__ import annotations

import chromadb
import logging
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.config import AppConfig
from app.services.document_service import load_documents


logger = logging.getLogger(__name__)


def build_embedding_model(config: AppConfig) -> OpenAIEmbedding:
    """创建 embedding 模型。"""
    if config.embedding_provider not in {"openai", "openai_compatible"}:
        raise NotImplementedError(
            f"暂未实现 embedding_provider={config.embedding_provider}。"
            "后续可在此接入 Ollama 或本地向量模型。"
        )

    if not config.embedding_api_ready:
        raise ValueError(
            "Embedding API 配置不完整。请检查 EMBEDDING_PROVIDER、EMBEDDING_API_KEY、"
            "EMBEDDING_API_BASE、EMBEDDING_MODEL 等环境变量。"
        )

    embed_kwargs = {
        "model": config.embedding_model,
        "api_key": config.embedding_api_key_for_client,
    }

    if config.embedding_api_base:
        embed_kwargs["api_base"] = config.embedding_api_base

    return OpenAIEmbedding(**embed_kwargs)


def get_chroma_collection(config: AppConfig, reset: bool = False):
    """获取或创建 Chroma collection。"""
    client = chromadb.PersistentClient(path=str(config.db_dir))

    if reset:
        try:
            client.delete_collection(name=config.collection_name)
        except Exception:
            pass

    return client.get_or_create_collection(name=config.collection_name)


def get_collection_count(config: AppConfig) -> int:
    """返回当前向量库中的片段数量。"""
    try:
        collection = get_chroma_collection(config, reset=False)
        return collection.count()
    except Exception:
        return 0


def index_exists(config: AppConfig) -> bool:
    """判断知识库是否已经建立。"""
    try:
        return get_collection_count(config) > 0
    except Exception:
        return False


def rebuild_index(config: AppConfig) -> dict[str, int]:
    """重新构建整个知识库。"""
    logger.info("开始重建知识库，集合名=%s", config.collection_name)
    documents = load_documents(config.data_dir)

    splitter = SentenceSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
    )
    nodes = splitter.get_nodes_from_documents(documents)

    chroma_collection = get_chroma_collection(config, reset=True)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    VectorStoreIndex(
        nodes=nodes,
        storage_context=storage_context,
        embed_model=build_embedding_model(config),
        show_progress=True,
    )

    result = {
        "document_count": len(documents),
        "chunk_count": len(nodes),
    }
    logger.info("知识库重建完成，文档数=%s，片段数=%s", result["document_count"], result["chunk_count"])
    return result


def load_index(config: AppConfig) -> VectorStoreIndex:
    """从已存在的 Chroma 向量库加载索引。"""
    chroma_collection = get_chroma_collection(config, reset=False)

    if chroma_collection.count() == 0:
        raise FileNotFoundError("知识库尚未建立，请先点击“重建知识库”。")

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=build_embedding_model(config),
    )
