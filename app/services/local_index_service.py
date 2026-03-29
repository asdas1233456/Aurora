"""Local chunk index persistence for offline and demo retrieval."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

from llama_index.core.schema import BaseNode

from app.config import AppConfig


_LOCAL_INDEX_FILE_NAME = "local_chunk_index.json"
_LOCAL_INDEX_LOCK = threading.RLock()


def get_local_index_path(config: AppConfig) -> Path:
    config.ensure_directories()
    return config.db_dir / _LOCAL_INDEX_FILE_NAME


def load_local_index_chunks(config: AppConfig) -> list[dict[str, Any]]:
    index_path = get_local_index_path(config)
    if not index_path.exists():
        return []

    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    raw_chunks = payload.get("chunks", [])
    if not isinstance(raw_chunks, list):
        return []

    chunks: list[dict[str, Any]] = []
    for item in raw_chunks:
        if isinstance(item, dict):
            chunks.append(item)
    return chunks


def count_local_index_chunks(config: AppConfig) -> int:
    return len(load_local_index_chunks(config))


def clear_local_index(config: AppConfig) -> None:
    with _LOCAL_INDEX_LOCK:
        _save_local_index_chunks(config, [])


def delete_local_document_chunks(config: AppConfig, source_path: str) -> None:
    with _LOCAL_INDEX_LOCK:
        next_chunks = [
            item
            for item in load_local_index_chunks(config)
            if str(item.get("source_path", "")) != str(source_path)
        ]
        _save_local_index_chunks(config, next_chunks)


def persist_local_nodes(config: AppConfig, nodes: list[BaseNode]) -> int:
    chunk_records = serialize_local_nodes(nodes)
    if not chunk_records:
        return 0

    grouped_records: dict[str, list[dict[str, Any]]] = {}
    for record in chunk_records:
        grouped_records.setdefault(str(record["source_path"]), []).append(record)

    with _LOCAL_INDEX_LOCK:
        existing_chunks = load_local_index_chunks(config)
        for source_path, records in grouped_records.items():
            existing_chunks = [
                item
                for item in existing_chunks
                if str(item.get("source_path", "")) != str(source_path)
            ]
            existing_chunks.extend(records)
        _save_local_index_chunks(config, existing_chunks)

    return len(chunk_records)


def serialize_local_nodes(nodes: list[BaseNode]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for position, node in enumerate(nodes, start=1):
        metadata = node.metadata or {}
        text = node.get_content(metadata_mode="none").strip()
        if not text:
            continue

        source_path = str(metadata.get("source_path") or metadata.get("file_path") or "")
        file_name = str(metadata.get("source_file") or Path(source_path or "chunk.txt").name)
        tags = metadata.get("tags", []) or []

        records.append(
            {
                "chunk_id": str(getattr(node, "node_id", "") or getattr(node, "id_", "") or ""),
                "source_path": source_path or file_name,
                "file_name": file_name,
                "text": text,
                "theme": str(metadata.get("theme", "") or ""),
                "tags": [str(item) for item in tags],
                "position": position,
            }
        )

    return records


def _save_local_index_chunks(config: AppConfig, chunks: list[dict[str, Any]]) -> None:
    payload = {"chunks": chunks}
    get_local_index_path(config).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
