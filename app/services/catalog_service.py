"""Document catalog and index status management."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import uuid

from app.config import AppConfig
from app.schemas import DocumentSummary
from app.services.document_service import get_document_summaries
from app.services.document_taxonomy import infer_document_category
from app.services.storage_service import connect_state_db


_CATALOG_LOCK = threading.RLock()
_LEGACY_CATALOG_FILE_NAME = "document_catalog.json"
_BOOTSTRAP_METADATA_KEY = "catalog_bootstrapped"
_LEGACY_IMPORT_METADATA_KEY = "catalog_legacy_imported"


def list_document_catalog(config: AppConfig) -> list[DocumentSummary]:
    _ensure_catalog_ready(config)
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        rows = connection.execute(
            "SELECT * FROM documents ORDER BY lower(name), document_id"
        ).fetchall()
        return [_row_to_document_summary(row) for row in rows]


def sync_document_catalog(
    config: AppConfig,
    *,
    full_scan: bool = True,
) -> tuple[list[DocumentSummary], list[str]]:
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        _migrate_legacy_catalog_if_needed(config, connection)
        if not full_scan:
            documents = _list_documents(connection)
            return documents, []

        current_files = get_document_summaries(config.data_dir)
        existing_by_path = _load_documents_by_path(connection)
        current_paths = {item.path for item in current_files}
        removed_paths = sorted(
            [path for path in existing_by_path if path not in current_paths],
            key=str.lower,
        )

        current_time = _now_text()
        for item in current_files:
            existing = existing_by_path.get(item.path)
            row = _build_document_row(
                item=item,
                existing=existing,
                current_time=current_time,
            )
            _upsert_document_row(connection, row)

        if removed_paths:
            connection.executemany(
                "DELETE FROM documents WHERE path = ?",
                [(path,) for path in removed_paths],
            )

        _set_metadata(connection, _BOOTSTRAP_METADATA_KEY, "1")
        connection.commit()
        return _list_documents(connection), removed_paths


def register_documents_in_catalog(
    config: AppConfig,
    paths: list[str | Path],
) -> list[DocumentSummary]:
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        _migrate_legacy_catalog_if_needed(config, connection)
        current_time = _now_text()
        updated_documents: list[DocumentSummary] = []
        for raw_path in paths:
            resolved_path = Path(raw_path).resolve(strict=False)
            if not resolved_path.exists() or not resolved_path.is_file():
                continue
            summary = _make_summary_from_path(resolved_path, config.data_dir)
            existing = _get_document_row_by_path(connection, summary.path)
            row = _build_document_row(
                item=summary,
                existing=existing,
                current_time=current_time,
                force_pending=True,
            )
            _upsert_document_row(connection, row)
            updated_documents.append(_row_to_document_summary(row))

        _set_metadata(connection, _BOOTSTRAP_METADATA_KEY, "1")
        connection.commit()
        return updated_documents


def update_document_annotations(
    config: AppConfig,
    paths: list[str],
    *,
    theme: str | None = None,
    tags: list[str] | None = None,
) -> list[DocumentSummary]:
    _ensure_catalog_ready(config)
    normalized_paths = [str(path or "").strip() for path in paths if str(path or "").strip()]
    if not normalized_paths:
        return list_document_catalog(config)

    current_time = _now_text()
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        for path in normalized_paths:
            row = _get_document_row_by_path(connection, path)
            if not row:
                continue

            next_theme = (
                theme.strip()
                if theme is not None and theme.strip()
                else (row["theme"] or infer_document_category(Path(path).name))
            )
            next_tags = (
                _normalize_tags(tags)
                if tags is not None
                else _deserialize_tags(row["tags_json"])
            )
            connection.execute(
                """
                UPDATE documents
                SET theme = ?,
                    tags_json = ?,
                    indexed_hash = '',
                    last_processed_hash = '',
                    chunk_count = 0,
                    active_version_id = '',
                    file_type = '',
                    parser_name = '',
                    segment_count = 0,
                    page_count = 0,
                    sheet_count = 0,
                    title = '',
                    source_url = '',
                    resolved_url = '',
                    last_indexed_at = '',
                    last_error = '',
                    status = 'pending',
                    updated_row_at = ?
                WHERE path = ?
                """,
                (next_theme, json.dumps(next_tags, ensure_ascii=False), current_time, path),
            )

        connection.commit()
        return _list_documents(connection)


def get_document_by_id(config: AppConfig, document_id: str) -> DocumentSummary | None:
    _ensure_catalog_ready(config)
    normalized_document_id = str(document_id or "").strip()
    if not normalized_document_id:
        return None

    with _CATALOG_LOCK, connect_state_db(config) as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE document_id = ?",
            (normalized_document_id,),
        ).fetchone()
        return _row_to_document_summary(row) if row else None


def get_documents_by_ids(
    config: AppConfig,
    document_ids: list[str],
) -> tuple[list[DocumentSummary], list[str]]:
    _ensure_catalog_ready(config)
    normalized_ids = [str(item or "").strip() for item in document_ids if str(item or "").strip()]
    if not normalized_ids:
        return [], []

    placeholders = ", ".join("?" for _ in normalized_ids)
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        rows = connection.execute(
            f"SELECT * FROM documents WHERE document_id IN ({placeholders})",
            normalized_ids,
        ).fetchall()
        documents_by_id = {
            row["document_id"]: _row_to_document_summary(row)
            for row in rows
        }

    documents: list[DocumentSummary] = []
    missing_ids: list[str] = []
    for document_id in normalized_ids:
        document = documents_by_id.get(document_id)
        if not document:
            missing_ids.append(document_id)
            continue
        documents.append(document)
    return documents, missing_ids


def remove_documents_from_catalog(config: AppConfig, document_ids: list[str]) -> list[str]:
    _ensure_catalog_ready(config)
    normalized_ids = {str(item or "").strip() for item in document_ids if str(item or "").strip()}
    if not normalized_ids:
        return []

    placeholders = ", ".join("?" for _ in normalized_ids)
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        rows = connection.execute(
            f"SELECT path FROM documents WHERE document_id IN ({placeholders})",
            list(normalized_ids),
        ).fetchall()
        removed_paths = [str(row["path"]) for row in rows]
        connection.execute(
            f"DELETE FROM documents WHERE document_id IN ({placeholders})",
            list(normalized_ids),
        )
        connection.commit()
        return removed_paths


def rename_document_in_catalog(
    config: AppConfig,
    *,
    document_id: str,
    old_path: str,
    new_path: str,
) -> None:
    _ensure_catalog_ready(config)
    normalized_document_id = str(document_id or "").strip()
    if not normalized_document_id:
        return

    new_file_path = Path(new_path).resolve(strict=False)
    if not new_file_path.exists() or not new_file_path.is_file():
        return

    current_time = _now_text()
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE document_id = ? OR path = ?",
            (normalized_document_id, old_path),
        ).fetchone()
        if not row:
            return

        summary = _make_summary_from_path(new_file_path, config.data_dir)
        updated_row = _build_document_row(
            item=summary,
            existing=row,
            current_time=current_time,
            force_pending=True,
            document_id=normalized_document_id,
        )
        connection.execute("DELETE FROM documents WHERE document_id = ?", (normalized_document_id,))
        _upsert_document_row(connection, updated_row)
        connection.commit()


def mark_documents_indexed(
    config: AppConfig,
    indexed_payloads: dict[str, dict[str, object]],
) -> None:
    if not indexed_payloads:
        return

    current_time = _now_text()
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        for path, payload in indexed_payloads.items():
            row = _get_document_row_by_path(connection, path)
            if not row:
                continue
            content_hash = str(payload.get("content_hash") or row["content_hash"] or "")
            connection.execute(
                """
                UPDATE documents
                SET indexed_hash = ?,
                    last_processed_hash = ?,
                    chunk_count = ?,
                    active_version_id = ?,
                    file_type = ?,
                    parser_name = ?,
                    segment_count = ?,
                    page_count = ?,
                    sheet_count = ?,
                    title = ?,
                    source_url = ?,
                    resolved_url = ?,
                    last_indexed_at = ?,
                    last_error = '',
                    status = 'indexed',
                    updated_row_at = ?
                WHERE path = ?
                """,
                (
                    content_hash,
                    content_hash,
                    int(payload.get("chunk_count", 0) or 0),
                    str(payload.get("version_id", "") or ""),
                    str(payload.get("file_type", "") or ""),
                    str(payload.get("parser_name", "") or ""),
                    int(payload.get("segment_count", 0) or 0),
                    int(payload.get("page_count", 0) or 0),
                    int(payload.get("sheet_count", 0) or 0),
                    str(payload.get("title", "") or ""),
                    str(payload.get("source_url", "") or ""),
                    str(payload.get("resolved_url", "") or ""),
                    current_time,
                    current_time,
                    path,
                ),
            )
        connection.commit()


def mark_document_failed(
    config: AppConfig,
    path: str,
    *,
    error: str,
    content_hash: str = "",
) -> None:
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        row = _get_document_row_by_path(connection, path)
        if not row:
            return

        current_hash = content_hash.strip() or str(row["content_hash"] or "")
        last_error = error.strip()
        status = _resolve_status(
            content_hash=current_hash,
            indexed_hash=str(row["indexed_hash"] or ""),
            last_processed_hash=current_hash,
            last_error=last_error,
        )
        connection.execute(
            """
            UPDATE documents
            SET last_processed_hash = ?,
                last_error = ?,
                status = ?,
                updated_row_at = ?
            WHERE path = ?
            """,
            (current_hash, last_error, status, _now_text(), path),
        )
        connection.commit()


def bump_citation_counts(config: AppConfig, source_paths: list[str]) -> None:
    normalized_paths = [str(path or "").strip() for path in source_paths if str(path or "").strip()]
    if not normalized_paths:
        return

    with _CATALOG_LOCK, connect_state_db(config) as connection:
        for path in normalized_paths:
            connection.execute(
                """
                UPDATE documents
                SET citation_count = citation_count + 1,
                    updated_row_at = ?
                WHERE path = ?
                """,
                (_now_text(), path),
            )
        connection.commit()


def reset_document_tracking(config: AppConfig, paths: list[str]) -> None:
    normalized_paths = [str(path or "").strip() for path in paths if str(path or "").strip()]
    if not normalized_paths:
        return

    current_time = _now_text()
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        for path in normalized_paths:
            connection.execute(
                """
                UPDATE documents
                SET indexed_hash = '',
                    last_processed_hash = '',
                    chunk_count = 0,
                    active_version_id = '',
                    file_type = '',
                    parser_name = '',
                    segment_count = 0,
                    page_count = 0,
                    sheet_count = 0,
                    title = '',
                    source_url = '',
                    resolved_url = '',
                    last_indexed_at = '',
                    last_error = '',
                    status = 'pending',
                    updated_row_at = ?
                WHERE path = ?
                """,
                (current_time, path),
            )
        connection.commit()


def reset_all_document_tracking(config: AppConfig) -> None:
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        connection.execute(
            """
            UPDATE documents
            SET indexed_hash = '',
                last_processed_hash = '',
                chunk_count = 0,
                active_version_id = '',
                file_type = '',
                parser_name = '',
                segment_count = 0,
                page_count = 0,
                sheet_count = 0,
                title = '',
                source_url = '',
                resolved_url = '',
                last_indexed_at = '',
                last_error = '',
                status = 'pending',
                updated_row_at = ?
            """,
            (_now_text(),),
        )
        connection.commit()


def get_document_status_counts(config: AppConfig) -> dict[str, int]:
    _ensure_catalog_ready(config)
    counts = {
        "indexed": 0,
        "changed": 0,
        "pending": 0,
        "failed": 0,
        "total": 0,
    }
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS count FROM documents GROUP BY status"
        ).fetchall()
        total_row = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()
        for row in rows:
            counts[str(row["status"] or "")] = int(row["count"] or 0)
        counts["total"] = int(total_row["count"] or 0) if total_row else 0
    return counts


def list_documents_needing_index(config: AppConfig) -> list[DocumentSummary]:
    _ensure_catalog_ready(config)
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        rows = connection.execute(
            """
            SELECT * FROM documents
            WHERE status IN ('pending', 'changed', 'failed')
            ORDER BY lower(name), document_id
            """
        ).fetchall()
        return [_row_to_document_summary(row) for row in rows]


def _ensure_catalog_ready(config: AppConfig) -> None:
    should_bootstrap = False
    with _CATALOG_LOCK, connect_state_db(config) as connection:
        _migrate_legacy_catalog_if_needed(config, connection)
        bootstrapped = _get_metadata(connection, _BOOTSTRAP_METADATA_KEY)
        if bootstrapped != "1":
            should_bootstrap = True

    if should_bootstrap:
        sync_document_catalog(config, full_scan=True)


def _migrate_legacy_catalog_if_needed(config: AppConfig, connection) -> None:
    if _get_metadata(connection, _LEGACY_IMPORT_METADATA_KEY) == "1":
        return

    legacy_path = config.db_dir / _LEGACY_CATALOG_FILE_NAME
    if legacy_path.exists():
        try:
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}

        raw_documents = payload.get("documents", {})
        current_time = _now_text()
        if isinstance(raw_documents, dict):
            for path, value in raw_documents.items():
                if not isinstance(value, dict):
                    continue
                file_path = Path(str(path)).resolve(strict=False)
                row = {
                    "document_id": str(value.get("document_id") or uuid.uuid4().hex),
                    "path": str(file_path),
                    "relative_path": str(value.get("relative_path") or file_path.name),
                    "name": str(value.get("name") or file_path.name),
                    "extension": file_path.suffix.lower().lstrip("."),
                    "size_bytes": int(value.get("_stat_size_bytes", 0) or 0),
                    "updated_at": str(value.get("_stat_updated_at", "") or ""),
                    "stat_size_bytes": int(value.get("_stat_size_bytes", 0) or 0),
                    "stat_updated_at": str(value.get("_stat_updated_at", "") or ""),
                    "content_hash": str(value.get("content_hash", "") or ""),
                    "indexed_hash": str(value.get("indexed_hash", "") or ""),
                    "last_processed_hash": str(value.get("last_processed_hash", "") or ""),
                    "theme": str(value.get("theme") or infer_document_category(file_path.name)),
                    "tags_json": json.dumps(
                        _normalize_tags(value.get("tags", [])),
                        ensure_ascii=False,
                    ),
                    "tenant_id": str(value.get("tenant_id", "") or ""),
                    "owner_user_id": str(
                        value.get("owner_user_id") or value.get("user_id") or ""
                    ),
                    "department_id": str(value.get("department_id", "") or ""),
                    "is_public": 1 if bool(value.get("is_public", True)) else 0,
                    "citation_count": int(value.get("citation_count", 0) or 0),
                    "chunk_count": int(value.get("chunk_count", 0) or 0),
                    "last_indexed_at": str(value.get("last_indexed_at", "") or ""),
                    "last_error": str(value.get("last_error", "") or ""),
                    "status": str(value.get("status", "pending") or "pending"),
                    "created_at": current_time,
                    "updated_row_at": current_time,
                }
                _upsert_document_row(connection, row)

    _set_metadata(connection, _LEGACY_IMPORT_METADATA_KEY, "1")
    connection.commit()


def _list_documents(connection) -> list[DocumentSummary]:
    rows = connection.execute(
        "SELECT * FROM documents ORDER BY lower(name), document_id"
    ).fetchall()
    return [_row_to_document_summary(row) for row in rows]


def _load_documents_by_path(connection) -> dict[str, object]:
    rows = connection.execute("SELECT * FROM documents").fetchall()
    return {str(row["path"]): row for row in rows}


def _get_document_row_by_path(connection, path: str):
    return connection.execute(
        "SELECT * FROM documents WHERE path = ?",
        (path,),
    ).fetchone()


def _build_document_row(
    *,
    item: DocumentSummary,
    existing,
    current_time: str,
    force_pending: bool = False,
    document_id: str = "",
) -> dict[str, object]:
    if existing and item.size_bytes == int(existing["stat_size_bytes"] or 0) and item.updated_at == str(
        existing["stat_updated_at"] or ""
    ) and str(existing["content_hash"] or ""):
        content_hash = str(existing["content_hash"] or "")
    else:
        content_hash = _compute_file_hash(Path(item.path))

    effective_document_id = document_id or (
        str(existing["document_id"]) if existing and str(existing["document_id"]) else uuid.uuid4().hex
    )
    theme = (
        str(existing["theme"])
        if existing and str(existing["theme"] or "").strip()
        else infer_document_category(item.name)
    )
    tags = _deserialize_tags(existing["tags_json"]) if existing else []
    tenant_id = (
        str(existing["tenant_id"] or "")
        if existing is not None
        else str(item.tenant_id or "")
    )
    owner_user_id = (
        str(existing["owner_user_id"] or "")
        if existing is not None
        else str(item.owner_user_id or "")
    )
    department_id = (
        str(existing["department_id"] or "")
        if existing is not None
        else str(item.department_id or "")
    )
    is_public = bool(int(existing["is_public"] or 0)) if existing is not None else bool(item.is_public)
    citation_count = int(existing["citation_count"] or 0) if existing else 0
    indexed_hash = "" if force_pending else (str(existing["indexed_hash"] or "") if existing else "")
    last_processed_hash = (
        "" if force_pending else (str(existing["last_processed_hash"] or "") if existing else "")
    )
    chunk_count = 0 if force_pending else (int(existing["chunk_count"] or 0) if existing else 0)
    last_indexed_at = "" if force_pending else (str(existing["last_indexed_at"] or "") if existing else "")
    last_error = "" if force_pending else (str(existing["last_error"] or "") if existing else "")
    status = (
        "pending"
        if force_pending
        else _resolve_status(
            content_hash=content_hash,
            indexed_hash=indexed_hash,
            last_processed_hash=last_processed_hash,
            last_error=last_error,
        )
    )

    return {
        "document_id": effective_document_id,
        "path": item.path,
        "relative_path": item.relative_path,
        "name": item.name,
        "extension": item.extension,
        "size_bytes": item.size_bytes,
        "updated_at": item.updated_at,
        "stat_size_bytes": item.size_bytes,
        "stat_updated_at": item.updated_at,
        "content_hash": content_hash,
        "indexed_hash": indexed_hash,
        "last_processed_hash": last_processed_hash,
        "theme": theme,
        "tags_json": json.dumps(tags, ensure_ascii=False),
        "tenant_id": tenant_id,
        "owner_user_id": owner_user_id,
        "department_id": department_id,
        "is_public": 1 if is_public else 0,
        "citation_count": citation_count,
        "chunk_count": chunk_count,
        "last_indexed_at": last_indexed_at,
        "last_error": last_error,
        "status": status,
        "created_at": str(existing["created_at"] or current_time) if existing else current_time,
        "updated_row_at": current_time,
    }


def _upsert_document_row(connection, row: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO documents (
            document_id,
            path,
            relative_path,
            name,
            extension,
            size_bytes,
            updated_at,
            stat_size_bytes,
            stat_updated_at,
            content_hash,
            indexed_hash,
            last_processed_hash,
            theme,
            tags_json,
            tenant_id,
            owner_user_id,
            department_id,
            is_public,
            citation_count,
            chunk_count,
            last_indexed_at,
            last_error,
            status,
            created_at,
            updated_row_at
        )
        VALUES (
            :document_id,
            :path,
            :relative_path,
            :name,
            :extension,
            :size_bytes,
            :updated_at,
            :stat_size_bytes,
            :stat_updated_at,
            :content_hash,
            :indexed_hash,
            :last_processed_hash,
            :theme,
            :tags_json,
            :tenant_id,
            :owner_user_id,
            :department_id,
            :is_public,
            :citation_count,
            :chunk_count,
            :last_indexed_at,
            :last_error,
            :status,
            :created_at,
            :updated_row_at
        )
        ON CONFLICT(document_id) DO UPDATE SET
            path = excluded.path,
            relative_path = excluded.relative_path,
            name = excluded.name,
            extension = excluded.extension,
            size_bytes = excluded.size_bytes,
            updated_at = excluded.updated_at,
            stat_size_bytes = excluded.stat_size_bytes,
            stat_updated_at = excluded.stat_updated_at,
            content_hash = excluded.content_hash,
            indexed_hash = excluded.indexed_hash,
            last_processed_hash = excluded.last_processed_hash,
            theme = excluded.theme,
            tags_json = excluded.tags_json,
            tenant_id = excluded.tenant_id,
            owner_user_id = excluded.owner_user_id,
            department_id = excluded.department_id,
            is_public = excluded.is_public,
            citation_count = excluded.citation_count,
            chunk_count = excluded.chunk_count,
            last_indexed_at = excluded.last_indexed_at,
            last_error = excluded.last_error,
            status = excluded.status,
            updated_row_at = excluded.updated_row_at
        """,
        row,
    )


def _make_summary_from_path(file_path: Path, data_dir: Path) -> DocumentSummary:
    resolved_path = file_path.resolve(strict=False)
    stat_result = resolved_path.stat()
    resolved_data_dir = data_dir.resolve(strict=False)
    try:
        relative_path = resolved_path.relative_to(resolved_data_dir).as_posix()
    except ValueError:
        relative_path = resolved_path.name

    return DocumentSummary(
        document_id="",
        name=resolved_path.name,
        path=str(resolved_path),
        relative_path=relative_path,
        extension=resolved_path.suffix.lower().lstrip("."),
        size_bytes=stat_result.st_size,
        updated_at=datetime.fromtimestamp(stat_result.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        status="pending",
        theme="",
        tags=[],
        is_public=True,
    )


def _row_to_document_summary(row) -> DocumentSummary:
    return DocumentSummary(
        document_id=str(_row_value(row, "document_id") or ""),
        name=str(_row_value(row, "name") or ""),
        path=str(_row_value(row, "path") or ""),
        relative_path=str(_row_value(row, "relative_path") or ""),
        extension=str(_row_value(row, "extension") or ""),
        size_bytes=int(_row_value(row, "size_bytes", 0) or 0),
        updated_at=str(_row_value(row, "updated_at") or ""),
        status=str(_row_value(row, "status", "pending") or "pending"),
        theme=str(_row_value(row, "theme") or ""),
        tags=_deserialize_tags(_row_value(row, "tags_json", "[]")),
        content_hash=str(_row_value(row, "content_hash") or ""),
        indexed_hash=str(_row_value(row, "indexed_hash") or ""),
        chunk_count=int(_row_value(row, "chunk_count", 0) or 0),
        citation_count=int(_row_value(row, "citation_count", 0) or 0),
        last_indexed_at=str(_row_value(row, "last_indexed_at") or ""),
        last_error=str(_row_value(row, "last_error") or ""),
        active_version_id=str(_row_value(row, "active_version_id") or ""),
        file_type=str(_row_value(row, "file_type") or ""),
        parser_name=str(_row_value(row, "parser_name") or ""),
        segment_count=int(_row_value(row, "segment_count", 0) or 0),
        page_count=int(_row_value(row, "page_count", 0) or 0),
        sheet_count=int(_row_value(row, "sheet_count", 0) or 0),
        title=str(_row_value(row, "title") or ""),
        source_url=str(_row_value(row, "source_url") or ""),
        resolved_url=str(_row_value(row, "resolved_url") or ""),
        tenant_id=str(_row_value(row, "tenant_id") or ""),
        owner_user_id=str(_row_value(row, "owner_user_id") or ""),
        department_id=str(_row_value(row, "department_id") or ""),
        is_public=bool(int(_row_value(row, "is_public", 1) or 0)),
    )


def _row_value(row, key: str, default: object = "") -> object:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _deserialize_tags(raw_tags: object) -> list[str]:
    if isinstance(raw_tags, str):
        try:
            payload = json.loads(raw_tags)
        except json.JSONDecodeError:
            return _normalize_tags(raw_tags.split(","))
        if isinstance(payload, list):
            return _normalize_tags(payload)
        return []
    if isinstance(raw_tags, list):
        return _normalize_tags(raw_tags)
    return []


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


def _get_metadata(connection, key: str) -> str:
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = ?",
        (key,),
    ).fetchone()
    return str(row["value"] or "") if row else ""


def _set_metadata(connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO metadata (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
