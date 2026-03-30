"""Local chunk index persistence for offline and demo retrieval."""

from __future__ import annotations

import json
from pathlib import Path
import re
import threading
from typing import Any

from llama_index.core.schema import BaseNode

from app.config import AppConfig
from app.services.storage_service import connect_state_db, table_exists


_LEGACY_LOCAL_INDEX_FILE_NAME = "local_chunk_index.json"
_LEGACY_IMPORT_METADATA_KEY = "local_index_legacy_imported"
_LOCAL_INDEX_LOCK = threading.RLock()
_ASCII_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
_CHINESE_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")


def load_local_index_chunks(config: AppConfig) -> list[dict[str, Any]]:
    _ensure_local_index_ready(config)
    with _LOCAL_INDEX_LOCK, connect_state_db(config) as connection:
        rows = connection.execute(
            """
            SELECT
                external_chunk_id,
                document_id,
                source_path,
                file_name,
                relative_path,
                text,
                theme,
                tags_json,
                position
            FROM local_chunks
            ORDER BY source_path, position, id
            """
        ).fetchall()
        return [_row_to_chunk_record(row) for row in rows]


def search_local_index_chunks(
    config: AppConfig,
    query: str,
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    _ensure_local_index_ready(config)
    normalized_limit = max(1, int(limit))

    with _LOCAL_INDEX_LOCK, connect_state_db(config) as connection:
        if table_exists(connection, "local_chunks_fts"):
            match_expression = _build_match_expression(query)
            if match_expression:
                rows = connection.execute(
                    """
                    SELECT
                        chunks.external_chunk_id,
                        chunks.document_id,
                        chunks.source_path,
                        chunks.file_name,
                        chunks.relative_path,
                        chunks.text,
                        chunks.theme,
                        chunks.tags_json,
                        chunks.position
                    FROM local_chunks_fts AS fts
                    JOIN local_chunks AS chunks
                      ON chunks.id = fts.rowid
                    WHERE local_chunks_fts MATCH ?
                    ORDER BY bm25(local_chunks_fts), chunks.source_path, chunks.position
                    LIMIT ?
                    """,
                    (match_expression, normalized_limit),
                ).fetchall()
                if rows:
                    return [_row_to_chunk_record(row) for row in rows]

        like_patterns = _build_like_patterns(query)
        if like_patterns:
            clauses = " OR ".join(
                "(file_name LIKE ? OR theme LIKE ? OR tags_text LIKE ? OR text LIKE ?)"
                for _ in like_patterns
            )
            params: list[object] = []
            for pattern in like_patterns:
                params.extend([pattern, pattern, pattern, pattern])
            params.append(normalized_limit)
            rows = connection.execute(
                f"""
                SELECT
                    external_chunk_id,
                    document_id,
                    source_path,
                    file_name,
                    relative_path,
                    text,
                    theme,
                    tags_json,
                    position
                FROM local_chunks
                WHERE {clauses}
                ORDER BY source_path, position, id
                LIMIT ?
                """,
                params,
            ).fetchall()
            if rows:
                return [_row_to_chunk_record(row) for row in rows]

        rows = connection.execute(
            """
            SELECT
                external_chunk_id,
                document_id,
                source_path,
                file_name,
                relative_path,
                text,
                theme,
                tags_json,
                position
            FROM local_chunks
            ORDER BY source_path, position, id
            LIMIT ?
            """,
            (normalized_limit,),
        ).fetchall()
        return [_row_to_chunk_record(row) for row in rows]


def count_local_index_chunks(config: AppConfig) -> int:
    _ensure_local_index_ready(config)
    with _LOCAL_INDEX_LOCK, connect_state_db(config) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM local_chunks").fetchone()
        return int(row["count"] or 0) if row else 0


def clear_local_index(config: AppConfig) -> None:
    with _LOCAL_INDEX_LOCK, connect_state_db(config) as connection:
        connection.execute("DELETE FROM local_chunks")
        if table_exists(connection, "local_chunks_fts"):
            connection.execute("DELETE FROM local_chunks_fts")
        connection.commit()


def delete_local_document_chunks(config: AppConfig, source_path: str) -> None:
    normalized_source_path = str(source_path or "").strip()
    if not normalized_source_path:
        return

    with _LOCAL_INDEX_LOCK, connect_state_db(config) as connection:
        if table_exists(connection, "local_chunks_fts"):
            row_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM local_chunks WHERE source_path = ?",
                    (normalized_source_path,),
                ).fetchall()
            ]
            if row_ids:
                connection.executemany(
                    "DELETE FROM local_chunks_fts WHERE rowid = ?",
                    [(row_id,) for row_id in row_ids],
                )
        connection.execute(
            "DELETE FROM local_chunks WHERE source_path = ?",
            (normalized_source_path,),
        )
        connection.commit()


def persist_local_nodes(config: AppConfig, nodes: list[BaseNode]) -> int:
    chunk_records = serialize_local_nodes(nodes)
    if not chunk_records:
        return 0

    grouped_records: dict[str, list[dict[str, Any]]] = {}
    for record in chunk_records:
        grouped_records.setdefault(str(record["source_path"]), []).append(record)

    with _LOCAL_INDEX_LOCK, connect_state_db(config) as connection:
        for source_path, records in grouped_records.items():
            existing_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM local_chunks WHERE source_path = ?",
                    (source_path,),
                ).fetchall()
            ]
            if existing_ids and table_exists(connection, "local_chunks_fts"):
                connection.executemany(
                    "DELETE FROM local_chunks_fts WHERE rowid = ?",
                    [(row_id,) for row_id in existing_ids],
                )
            connection.execute(
                "DELETE FROM local_chunks WHERE source_path = ?",
                (source_path,),
            )

            inserted_rows: list[tuple[int, str, str, str, str, str, str]] = []
            for record in records:
                cursor = connection.execute(
                    """
                    INSERT INTO local_chunks (
                        external_chunk_id,
                        document_id,
                        source_path,
                        file_name,
                        relative_path,
                        text,
                        theme,
                        tags_json,
                        tags_text,
                        position
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(record["chunk_id"]),
                        str(record["document_id"]),
                        str(record["source_path"]),
                        str(record["file_name"]),
                        str(record["relative_path"]),
                        str(record["text"]),
                        str(record["theme"]),
                        json.dumps(record["tags"], ensure_ascii=False),
                        " ".join(record["tags"]),
                        int(record["position"]),
                    ),
                )
                inserted_rows.append(
                    (
                        int(cursor.lastrowid),
                        str(record["source_path"]),
                        str(record["file_name"]),
                        str(record["relative_path"]),
                        str(record["theme"]),
                        " ".join(record["tags"]),
                        str(record["text"]),
                    )
                )

            if inserted_rows and table_exists(connection, "local_chunks_fts"):
                connection.executemany(
                    """
                    INSERT INTO local_chunks_fts (
                        rowid,
                        source_path,
                        file_name,
                        relative_path,
                        theme,
                        tags_text,
                        text
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    inserted_rows,
                )

        connection.commit()

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
                "document_id": str(metadata.get("document_id", "") or ""),
                "source_path": source_path or file_name,
                "file_name": file_name,
                "relative_path": str(metadata.get("relative_path", "") or file_name),
                "text": text,
                "theme": str(metadata.get("theme", "") or ""),
                "tags": [str(item) for item in tags],
                "position": position,
            }
        )

    return records


def _ensure_local_index_ready(config: AppConfig) -> None:
    with _LOCAL_INDEX_LOCK, connect_state_db(config) as connection:
        if _get_metadata(connection, _LEGACY_IMPORT_METADATA_KEY) == "1":
            return

        legacy_path = config.db_dir / _LEGACY_LOCAL_INDEX_FILE_NAME
        if legacy_path.exists():
            try:
                payload = json.loads(legacy_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}

            raw_chunks = payload.get("chunks", [])
            if isinstance(raw_chunks, list):
                for item in raw_chunks:
                    if not isinstance(item, dict):
                        continue
                    cursor = connection.execute(
                        """
                        INSERT INTO local_chunks (
                            external_chunk_id,
                            document_id,
                            source_path,
                            file_name,
                            relative_path,
                            text,
                            theme,
                            tags_json,
                            tags_text,
                            position
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(item.get("chunk_id", "") or ""),
                            str(item.get("document_id", "") or ""),
                            str(item.get("source_path", "") or ""),
                            str(item.get("file_name", "") or ""),
                            str(item.get("relative_path", "") or ""),
                            str(item.get("text", "") or ""),
                            str(item.get("theme", "") or ""),
                            json.dumps(
                                [str(tag) for tag in item.get("tags", []) or []],
                                ensure_ascii=False,
                            ),
                            " ".join([str(tag) for tag in item.get("tags", []) or []]),
                            int(item.get("position", 0) or 0),
                        ),
                    )
                    if table_exists(connection, "local_chunks_fts"):
                        connection.execute(
                            """
                            INSERT INTO local_chunks_fts (
                                rowid,
                                source_path,
                                file_name,
                                relative_path,
                                theme,
                                tags_text,
                                text
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                int(cursor.lastrowid),
                                str(item.get("source_path", "") or ""),
                                str(item.get("file_name", "") or ""),
                                str(item.get("relative_path", "") or ""),
                                str(item.get("theme", "") or ""),
                                " ".join([str(tag) for tag in item.get("tags", []) or []]),
                                str(item.get("text", "") or ""),
                            ),
                        )

        _set_metadata(connection, _LEGACY_IMPORT_METADATA_KEY, "1")
        connection.commit()


def _row_to_chunk_record(row) -> dict[str, Any]:
    return {
        "chunk_id": str(row["external_chunk_id"] or ""),
        "document_id": str(row["document_id"] or ""),
        "source_path": str(row["source_path"] or ""),
        "file_name": str(row["file_name"] or ""),
        "relative_path": str(row["relative_path"] or ""),
        "text": str(row["text"] or ""),
        "theme": str(row["theme"] or ""),
        "tags": _deserialize_tags(row["tags_json"]),
        "position": int(row["position"] or 0),
    }


def _deserialize_tags(raw_tags: object) -> list[str]:
    if isinstance(raw_tags, str):
        try:
            payload = json.loads(raw_tags)
        except json.JSONDecodeError:
            payload = [item.strip() for item in raw_tags.split(",") if item.strip()]
        if isinstance(payload, list):
            return [str(item).strip() for item in payload if str(item).strip()]
    return []


def _build_match_expression(query: str) -> str:
    tokens: list[str] = []
    lowered_query = str(query or "").lower()
    tokens.extend(_ASCII_TOKEN_PATTERN.findall(lowered_query))
    tokens.extend(_CHINESE_TOKEN_PATTERN.findall(str(query or "")))
    unique_tokens = []
    for token in tokens:
        normalized = token.strip()
        if normalized and normalized not in unique_tokens:
            unique_tokens.append(normalized)
    if not unique_tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in unique_tokens[:8])


def _build_like_patterns(query: str) -> list[str]:
    terms = [
        term.strip()
        for term in re.split(r"[\s,，。！？!?:;；/|]+", str(query or ""))
        if term.strip()
    ]
    patterns: list[str] = []
    for term in terms[:6]:
        patterns.append(f"%{term}%")
    return patterns


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
