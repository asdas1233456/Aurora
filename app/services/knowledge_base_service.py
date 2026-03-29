"""Knowledge base indexing services."""

from __future__ import annotations

import chromadb
import logging

from llama_index.core import VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode, Document
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.config import AppConfig, is_openai_compatible_provider, is_openai_provider
from app.services.document_service import load_documents
from app.services.local_index_service import (
    clear_local_index,
    count_local_index_chunks,
    delete_local_document_chunks,
    persist_local_nodes,
)


logger = logging.getLogger(__name__)


def build_embedding_model(config: AppConfig) -> OpenAIEmbedding:
    """Build the embedding client for vector indexing."""
    if not (
        is_openai_provider(config.embedding_provider)
        or is_openai_compatible_provider(config.embedding_provider)
    ):
        raise NotImplementedError(
            f"embedding_provider={config.embedding_provider} is not supported yet."
        )

    if not config.embedding_api_ready:
        raise ValueError(
            "Embedding API configuration is incomplete. Please check provider, key, base URL, and model."
        )

    embed_kwargs = {
        "model": config.embedding_model,
        "api_key": config.embedding_api_key_for_client,
    }
    if config.embedding_api_base:
        embed_kwargs["api_base"] = config.embedding_api_base

    return OpenAIEmbedding(**embed_kwargs)


def get_chroma_collection(config: AppConfig, reset: bool = False):
    """Get or create the Chroma collection."""
    client = chromadb.PersistentClient(path=str(config.db_dir))

    if reset:
        try:
            client.delete_collection(name=config.collection_name)
        except Exception:
            pass

    return client.get_or_create_collection(name=config.collection_name)


def get_vector_collection_count(config: AppConfig) -> int:
    """Return vector chunk count when the embedding index exists."""
    if not config.embedding_api_ready:
        return 0
    try:
        collection = get_chroma_collection(config, reset=False)
        return collection.count()
    except Exception:
        return 0


def get_collection_count(config: AppConfig) -> int:
    """Return the active retrieval index size."""
    vector_count = get_vector_collection_count(config)
    if vector_count > 0:
        return vector_count
    return count_local_index_chunks(config)


def index_exists(config: AppConfig) -> bool:
    """Return whether any retrieval index is available."""
    return get_collection_count(config) > 0


def create_splitter(config: AppConfig) -> SentenceSplitter:
    """Create the shared chunk splitter."""
    return SentenceSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
    )


def create_nodes_from_documents(config: AppConfig, documents: list[Document]) -> list[BaseNode]:
    """Convert documents to chunk nodes."""
    splitter = create_splitter(config)
    return splitter.get_nodes_from_documents(documents)


def delete_document_chunks(config: AppConfig, source_path: str) -> None:
    """Delete one document from every retrieval backend."""
    try:
        collection = get_chroma_collection(config, reset=False)
        collection.delete(where={"source_path": source_path})
    except Exception:
        pass

    delete_local_document_chunks(config, source_path)


def add_nodes_with_embeddings(
    config: AppConfig,
    nodes: list[BaseNode],
    *,
    embed_batch_size: int = 24,
    progress_callback: callable | None = None,
    cancel_checker: callable | None = None,
) -> int:
    """Write nodes to the available retrieval backend."""
    if not nodes:
        return 0

    if not config.embedding_api_ready:
        inserted = persist_local_nodes(config, nodes)
        if progress_callback:
            progress_callback(inserted, inserted)
        return inserted

    embed_model = build_embedding_model(config)
    vector_store = ChromaVectorStore(chroma_collection=get_chroma_collection(config, reset=False))
    total = len(nodes)
    inserted = 0

    for start_index in range(0, total, embed_batch_size):
        if cancel_checker and cancel_checker():
            raise RuntimeError("知识库重建已取消。")

        batch_nodes = nodes[start_index : start_index + embed_batch_size]
        batch_texts = [node.get_content(metadata_mode="none") for node in batch_nodes]
        embeddings = embed_model.get_text_embedding_batch(batch_texts, show_progress=False)

        for node, embedding in zip(batch_nodes, embeddings, strict=False):
            node.embedding = embedding

        vector_store.add(batch_nodes)
        inserted += len(batch_nodes)

        if progress_callback:
            progress_callback(inserted, total)

    persist_local_nodes(config, nodes)
    return inserted


def rebuild_index(config: AppConfig) -> dict[str, int]:
    """Perform a full rebuild of the retrieval index."""
    logger.info("Starting knowledge base rebuild, collection=%s", config.collection_name)
    documents = load_documents(config.data_dir)
    nodes = create_nodes_from_documents(config, documents)

    get_chroma_collection(config, reset=True)
    clear_local_index(config)
    add_nodes_with_embeddings(config, nodes)

    result = {
        "document_count": len(documents),
        "chunk_count": len(nodes),
    }
    logger.info(
        "Knowledge base rebuild completed, documents=%s, chunks=%s",
        result["document_count"],
        result["chunk_count"],
    )
    return result


def load_index(config: AppConfig) -> VectorStoreIndex:
    """Load the vector index when embeddings are available."""
    chroma_collection = get_chroma_collection(config, reset=False)

    if chroma_collection.count() == 0:
        raise FileNotFoundError("知识库尚未建立，请先执行重建。")

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=build_embedding_model(config),
    )
