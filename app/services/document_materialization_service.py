"""Structured document materialization for normalized ETL outputs."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json

from llama_index.core.schema import BaseNode

from app.config import AppConfig
from app.schemas import DocumentPreviewMetadata, DocumentPreviewPayload, DocumentSummary
from app.services.document_service import build_document_preview_metadata
from app.services.etl import ParsedDocument
from app.services.storage_service import connect_state_db


def persist_materialized_document(
    config: AppConfig,
    *,
    document: DocumentSummary,
    parsed_document: ParsedDocument,
    nodes: list[BaseNode],
    content_hash: str,
) -> dict[str, object]:
    """Persist one parsed document into normalized version, segment, and chunk tables."""
    if not document.document_id:
        raise ValueError("document_id is required for materialized document persistence.")

    preview_metadata = build_document_preview_metadata(parsed_document)
    current_time = _now_text()
    version_id = _build_version_id(
        document_id=document.document_id,
        content_hash=content_hash,
        relative_path=parsed_document.relative_path,
    )
    manifest_json = json.dumps(_build_manifest_payload(parsed_document), ensure_ascii=False)
    access_metadata = _extract_access_metadata(parsed_document.metadata)

    with connect_state_db(config) as connection:
        # One document keeps only its latest active version in SQLite hot storage.
        connection.execute(
            "DELETE FROM document_versions WHERE document_id = ?",
            (document.document_id,),
        )
        connection.execute(
            """
            INSERT INTO document_versions (
                version_id,
                document_id,
                source_document_id,
                source_path,
                relative_path,
                file_name,
                content_hash,
                file_type,
                parser_name,
                segment_count,
                page_count,
                sheet_count,
                title,
                source_url,
                resolved_url,
                tenant_id,
                owner_user_id,
                department_id,
                is_public,
                manifest_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                document.document_id,
                parsed_document.source_id,
                parsed_document.source_path,
                parsed_document.relative_path,
                parsed_document.file_name,
                content_hash,
                preview_metadata.file_type,
                preview_metadata.parser_name,
                preview_metadata.segment_count,
                preview_metadata.page_count,
                preview_metadata.sheet_count,
                preview_metadata.title,
                preview_metadata.source_url,
                preview_metadata.resolved_url,
                access_metadata["tenant_id"],
                access_metadata["owner_user_id"],
                access_metadata["department_id"],
                access_metadata["is_public"],
                manifest_json,
                current_time,
            ),
        )
        _insert_segments(connection, document.document_id, version_id, parsed_document, current_time)
        _insert_chunks(connection, document.document_id, version_id, nodes, current_time)

    return {
        "version_id": version_id,
        "file_type": preview_metadata.file_type,
        "parser_name": preview_metadata.parser_name,
        "segment_count": preview_metadata.segment_count,
        "page_count": preview_metadata.page_count,
        "sheet_count": preview_metadata.sheet_count,
        "title": preview_metadata.title,
        "source_url": preview_metadata.source_url,
        "resolved_url": preview_metadata.resolved_url,
    }


def delete_materialized_document_by_source_path(config: AppConfig, source_path: str) -> None:
    """Delete one document's structured storage rows by source path."""
    normalized_source_path = str(source_path or "").strip()
    if not normalized_source_path:
        return

    with connect_state_db(config) as connection:
        connection.execute(
            "DELETE FROM document_versions WHERE source_path = ?",
            (normalized_source_path,),
        )


def clear_materialized_documents(config: AppConfig) -> None:
    """Clear every structured document storage table."""
    with connect_state_db(config) as connection:
        connection.execute("DELETE FROM document_versions")


def load_materialized_document_preview(
    config: AppConfig,
    *,
    document: DocumentSummary,
    max_chars: int = 3000,
) -> DocumentPreviewPayload | None:
    """Load preview text and metadata from structured storage when the active version is fresh."""
    if not _can_use_materialized_preview(document):
        return None

    with connect_state_db(config) as connection:
        version_row = connection.execute(
            """
            SELECT
                d.active_version_id,
                v.version_id,
                v.source_document_id,
                v.file_type,
                v.parser_name,
                v.segment_count,
                v.page_count,
                v.sheet_count,
                v.title,
                v.source_url,
                v.resolved_url
            FROM documents AS d
            JOIN document_versions AS v
              ON v.version_id = d.active_version_id
            WHERE d.document_id = ?
            """,
            (document.document_id,),
        ).fetchone()
        if not version_row:
            return None

        segment_rows = connection.execute(
            """
            SELECT
                content_markdown,
                content_text,
                page_number,
                sheet_name
            FROM document_segments
            WHERE version_id = ?
            ORDER BY sequence, segment_id
            """,
            (str(version_row["version_id"] or ""),),
        ).fetchall()

    if not segment_rows:
        return None

    # Preview text is reconstructed from normalized segments instead of reparsing files on every request.
    preview_parts = [
        str(row["content_markdown"] or row["content_text"] or "").strip()
        for row in segment_rows
        if str(row["content_markdown"] or row["content_text"] or "").strip()
    ]
    preview_text = "\n\n".join(preview_parts).strip()
    if not preview_text:
        return None

    page_numbers = [
        int(row["page_number"])
        for row in segment_rows
        if row["page_number"] is not None and int(row["page_number"]) > 0
    ]
    sheet_names = [
        str(row["sheet_name"] or "").strip()
        for row in segment_rows
        if str(row["sheet_name"] or "").strip()
    ]

    metadata = DocumentPreviewMetadata(
        file_type=str(version_row["file_type"] or document.extension or ""),
        parser_name=str(version_row["parser_name"] or ""),
        source_document_id=str(version_row["source_document_id"] or ""),
        segment_count=int(version_row["segment_count"] or len(segment_rows)),
        title=str(version_row["title"] or ""),
        source_url=str(version_row["source_url"] or ""),
        resolved_url=str(version_row["resolved_url"] or ""),
        page_count=int(version_row["page_count"] or len(page_numbers)),
        page_numbers=_dedupe_ints(page_numbers),
        sheet_count=int(version_row["sheet_count"] or len(sheet_names)),
        sheet_names=_dedupe_strings(sheet_names),
    )
    return DocumentPreviewPayload(
        document_id=document.document_id,
        preview=preview_text[:max_chars],
        metadata=metadata,
    )


def _insert_segments(
    connection,
    document_id: str,
    version_id: str,
    parsed_document: ParsedDocument,
    current_time: str,
) -> None:
    rows = [
        (
            segment.segment_id,
            version_id,
            document_id,
            segment.sequence,
            str(segment.metadata.get("segment_kind", "document") or "document"),
            segment.page_number,
            str(segment.metadata.get("sheet_name", "") or ""),
            segment.content_text,
            segment.content_markdown,
            json.dumps(dict(segment.metadata), ensure_ascii=False),
            current_time,
        )
        for segment in parsed_document.segments
    ]
    if not rows:
        return

    connection.executemany(
        """
        INSERT INTO document_segments (
            segment_id,
            version_id,
            document_id,
            sequence,
            segment_kind,
            page_number,
            sheet_name,
            content_text,
            content_markdown,
            metadata_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _insert_chunks(
    connection,
    document_id: str,
    version_id: str,
    nodes: list[BaseNode],
    current_time: str,
) -> None:
    rows: list[tuple[object, ...]] = []
    for position, node in enumerate(nodes, start=1):
        metadata = dict(node.metadata or {})
        text = node.get_content(metadata_mode="none").strip()
        if not text:
            continue

        tags = [str(item) for item in metadata.get("tags", []) or []]
        segment_id = str(metadata.get("source_segment_id", "") or "").strip() or None
        # Chunk rows denormalize the most common query fields so retrieval paths do not need to scan manifest JSON.
        rows.append(
            (
                str(getattr(node, "node_id", "") or getattr(node, "id_", "") or ""),
                version_id,
                document_id,
                segment_id,
                str(metadata.get("source_path") or metadata.get("file_path") or ""),
                str(metadata.get("source_file") or ""),
                str(metadata.get("relative_path") or ""),
                text,
                str(metadata.get("theme", "") or ""),
                json.dumps(tags, ensure_ascii=False),
                " ".join(tags),
                _coerce_page_number(metadata.get("page_number")),
                str(metadata.get("sheet_name", "") or ""),
                str(metadata.get("parser_name", "") or ""),
                str(metadata.get("source_type", "") or ""),
                str(metadata.get("tenant_id", "") or ""),
                str(metadata.get("owner_user_id") or metadata.get("user_id") or ""),
                str(metadata.get("department_id", "") or ""),
                1 if bool(metadata.get("is_public", True)) else 0,
                position,
                json.dumps(metadata, ensure_ascii=False),
                current_time,
            )
        )

    if not rows:
        return

    connection.executemany(
        """
        INSERT INTO document_chunks (
            chunk_id,
            version_id,
            document_id,
            segment_id,
            source_path,
            file_name,
            relative_path,
            text,
            theme,
            tags_json,
            tags_text,
            page_number,
            sheet_name,
            parser_name,
            source_type,
            tenant_id,
            owner_user_id,
            department_id,
            is_public,
            position,
            metadata_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _build_manifest_payload(parsed_document: ParsedDocument) -> dict[str, object]:
    payload = dict(parsed_document.content_json or {})
    payload.pop("segments", None)
    payload["source_id"] = parsed_document.source_id
    payload["source_path"] = parsed_document.source_path
    payload["relative_path"] = parsed_document.relative_path
    payload["file_name"] = parsed_document.file_name
    payload["file_type"] = parsed_document.file_type
    payload["parser_name"] = parsed_document.parser_name
    payload["metadata"] = dict(parsed_document.metadata)
    return payload


def _extract_access_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """Normalize access metadata for structured document tables."""
    owner_user_id = str(metadata.get("owner_user_id") or metadata.get("user_id") or "").strip()
    return {
        "tenant_id": str(metadata.get("tenant_id", "") or "").strip(),
        "owner_user_id": owner_user_id,
        "department_id": str(metadata.get("department_id", "") or "").strip(),
        "is_public": 1 if bool(metadata.get("is_public", True)) else 0,
    }


def _build_version_id(*, document_id: str, content_hash: str, relative_path: str) -> str:
    digest = hashlib.sha1(
        f"{document_id}:{content_hash}:{relative_path}".encode("utf-8")
    ).hexdigest()
    return digest


def _can_use_materialized_preview(document: DocumentSummary) -> bool:
    return (
        document.status == "indexed"
        and bool(document.document_id)
        and bool(document.content_hash)
        and document.indexed_hash == document.content_hash
    )


def _coerce_page_number(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        page_number = int(value)
    except (TypeError, ValueError):
        return None
    return page_number if page_number > 0 else None


def _dedupe_ints(values: list[int]) -> list[int]:
    deduped: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
