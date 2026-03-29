"""文档目录与索引状态管理。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading

from app.config import AppConfig
from app.schemas import DocumentSummary
from app.services.document_service import get_document_summaries
from app.services.document_taxonomy import infer_document_category


_CATALOG_LOCK = threading.RLock()
_CATALOG_FILE_NAME = "document_catalog.json"


def get_catalog_path(config: AppConfig) -> Path:
    config.ensure_directories()
    return config.db_dir / _CATALOG_FILE_NAME


def load_catalog_state(config: AppConfig) -> dict[str, dict[str, object]]:
    catalog_path = get_catalog_path(config)
    if not catalog_path.exists():
        return {}

    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    raw_documents = payload.get("documents", {})
    if not isinstance(raw_documents, dict):
        return {}

    normalized_state: dict[str, dict[str, object]] = {}
    for path, value in raw_documents.items():
        if isinstance(value, dict):
            normalized_state[str(path)] = value
    return normalized_state


def save_catalog_state(config: AppConfig, state: dict[str, dict[str, object]]) -> None:
    catalog_path = get_catalog_path(config)
    payload = {
        "updated_at": _now_text(),
        "documents": state,
    }
    catalog_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_document_catalog(config: AppConfig) -> list[DocumentSummary]:
    summaries, _ = sync_document_catalog(config)
    return summaries


def sync_document_catalog(config: AppConfig) -> tuple[list[DocumentSummary], list[str]]:
    with _CATALOG_LOCK:
        current_files = get_document_summaries(config.data_dir)
        existing_state = load_catalog_state(config)
        current_paths = {item.path for item in current_files}
        removed_paths = sorted(
            [path for path in existing_state.keys() if path not in current_paths],
            key=str.lower,
        )

        next_state: dict[str, dict[str, object]] = {}
        documents: list[DocumentSummary] = []

        for item in current_files:
            entry = dict(existing_state.get(item.path, {}))
            stat_signature = {
                "size_bytes": item.size_bytes,
                "updated_at": item.updated_at,
            }

            cached_signature = {
                "size_bytes": entry.get("_stat_size_bytes"),
                "updated_at": entry.get("_stat_updated_at"),
            }
            if stat_signature == cached_signature and entry.get("content_hash"):
                content_hash = str(entry.get("content_hash", ""))
            else:
                content_hash = _compute_file_hash(Path(item.path))

            entry["_stat_size_bytes"] = item.size_bytes
            entry["_stat_updated_at"] = item.updated_at
            entry["content_hash"] = content_hash
            entry["relative_path"] = item.relative_path
            entry["name"] = item.name
            entry["theme"] = str(entry.get("theme") or infer_document_category(item.name))
            entry["tags"] = _normalize_tags(entry.get("tags", []))
            entry["citation_count"] = int(entry.get("citation_count", 0) or 0)
            entry["chunk_count"] = int(entry.get("chunk_count", 0) or 0)
            entry["indexed_hash"] = str(entry.get("indexed_hash", "") or "")
            entry["last_processed_hash"] = str(entry.get("last_processed_hash", "") or "")
            entry["last_indexed_at"] = str(entry.get("last_indexed_at", "") or "")
            entry["last_error"] = str(entry.get("last_error", "") or "")
            entry["status"] = _resolve_status(
                content_hash=content_hash,
                indexed_hash=entry["indexed_hash"],
                last_processed_hash=entry["last_processed_hash"],
                last_error=entry["last_error"],
            )

            next_state[item.path] = entry
            documents.append(
                DocumentSummary(
                    name=item.name,
                    path=item.path,
                    relative_path=item.relative_path,
                    extension=item.extension,
                    size_bytes=item.size_bytes,
                    updated_at=item.updated_at,
                    status=str(entry["status"]),
                    theme=str(entry["theme"]),
                    tags=list(entry["tags"]),
                    content_hash=content_hash,
                    indexed_hash=str(entry["indexed_hash"]),
                    chunk_count=int(entry["chunk_count"]),
                    citation_count=int(entry["citation_count"]),
                    last_indexed_at=str(entry["last_indexed_at"]),
                    last_error=str(entry["last_error"]),
                )
            )

        save_catalog_state(config, next_state)
        documents.sort(key=lambda item: item.name.lower())
        return documents, removed_paths


def update_document_annotations(
    config: AppConfig,
    paths: list[str],
    *,
    theme: str | None = None,
    tags: list[str] | None = None,
) -> list[DocumentSummary]:
    with _CATALOG_LOCK:
        documents, _ = sync_document_catalog(config)
        state = load_catalog_state(config)

        for path in paths:
            entry = state.get(path)
            if not entry:
                continue
            if theme is not None:
                entry["theme"] = theme.strip() or infer_document_category(Path(path).name)
            if tags is not None:
                entry["tags"] = _normalize_tags(tags)

        save_catalog_state(config, state)
        return list_document_catalog(config)


def mark_documents_indexed(
    config: AppConfig,
    indexed_payloads: dict[str, dict[str, object]],
) -> None:
    with _CATALOG_LOCK:
        state = load_catalog_state(config)
        current_time = _now_text()
        for path, payload in indexed_payloads.items():
            entry = state.get(path)
            if not entry:
                continue
            content_hash = str(payload.get("content_hash") or entry.get("content_hash", ""))
            entry["indexed_hash"] = content_hash
            entry["last_processed_hash"] = content_hash
            entry["chunk_count"] = int(payload.get("chunk_count", 0) or 0)
            entry["last_indexed_at"] = current_time
            entry["last_error"] = ""
            entry["status"] = "indexed"
        save_catalog_state(config, state)


def mark_document_failed(
    config: AppConfig,
    path: str,
    *,
    error: str,
    content_hash: str = "",
) -> None:
    with _CATALOG_LOCK:
        state = load_catalog_state(config)
        entry = state.get(path)
        if not entry:
            return
        current_hash = content_hash.strip() or str(entry.get("content_hash", "") or "")
        entry["last_processed_hash"] = current_hash
        entry["last_error"] = error.strip()
        entry["status"] = _resolve_status(
            content_hash=current_hash,
            indexed_hash=str(entry.get("indexed_hash", "") or ""),
            last_processed_hash=current_hash,
            last_error=entry["last_error"],
        )
        save_catalog_state(config, state)


def bump_citation_counts(config: AppConfig, source_paths: list[str]) -> None:
    if not source_paths:
        return

    with _CATALOG_LOCK:
        state = load_catalog_state(config)
        for path in source_paths:
            entry = state.get(path)
            if not entry:
                continue
            entry["citation_count"] = int(entry.get("citation_count", 0) or 0) + 1
        save_catalog_state(config, state)


def reset_document_tracking(config: AppConfig, paths: list[str]) -> None:
    if not paths:
        return

    with _CATALOG_LOCK:
        state = load_catalog_state(config)
        for path in paths:
            entry = state.get(path)
            if not entry:
                continue
            entry["indexed_hash"] = ""
            entry["last_processed_hash"] = ""
            entry["chunk_count"] = 0
            entry["last_indexed_at"] = ""
            entry["last_error"] = ""
            entry["status"] = "pending"
        save_catalog_state(config, state)


def get_document_status_counts(config: AppConfig) -> dict[str, int]:
    documents = list_document_catalog(config)
    counts = {
        "indexed": 0,
        "changed": 0,
        "pending": 0,
        "failed": 0,
        "total": len(documents),
    }
    for document in documents:
        counts[document.status] = counts.get(document.status, 0) + 1
    return counts


def _compute_file_hash(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file_obj:
        while True:
            chunk = file_obj.read(1024 * 128)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_tags(raw_tags: object) -> list[str]:
    if isinstance(raw_tags, str):
        raw_items = raw_tags.split(",")
    elif isinstance(raw_tags, list):
        raw_items = raw_tags
    else:
        raw_items = []

    normalized: list[str] = []
    for item in raw_items:
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _resolve_status(
    *,
    content_hash: str,
    indexed_hash: str,
    last_processed_hash: str,
    last_error: str,
) -> str:
    if indexed_hash and indexed_hash == content_hash and not last_error:
        return "indexed"
    if last_error and last_processed_hash and last_processed_hash == content_hash:
        return "failed"
    if not indexed_hash:
        return "pending"
    return "changed"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
