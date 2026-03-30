"""Shared SQLite storage helpers for catalog and local index state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import AppConfig


_STATE_DB_FILE_NAME = "aurora_state.sqlite3"


def get_state_db_path(config: AppConfig) -> Path:
    config.ensure_directories()
    return config.db_dir / _STATE_DB_FILE_NAME


def connect_state_db(config: AppConfig) -> sqlite3.Connection:
    connection = sqlite3.connect(
        get_state_db_path(config),
        timeout=30,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(connection)
    return connection


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            relative_path TEXT NOT NULL,
            name TEXT NOT NULL,
            extension TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT '',
            stat_size_bytes INTEGER NOT NULL DEFAULT 0,
            stat_updated_at TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            indexed_hash TEXT NOT NULL DEFAULT '',
            last_processed_hash TEXT NOT NULL DEFAULT '',
            theme TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            citation_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            last_indexed_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT '',
            updated_row_at TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_documents_name ON documents(name);
        CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
        CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents(updated_at);

        CREATE TABLE IF NOT EXISTS local_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_chunk_id TEXT NOT NULL DEFAULT '',
            document_id TEXT NOT NULL DEFAULT '',
            source_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            text TEXT NOT NULL,
            theme TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            tags_text TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_local_chunks_source_path ON local_chunks(source_path);
        CREATE INDEX IF NOT EXISTS idx_local_chunks_document_id ON local_chunks(document_id);
        """
    )

    if not table_exists(connection, "local_chunks_fts"):
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE local_chunks_fts USING fts5(
                    source_path UNINDEXED,
                    file_name,
                    relative_path,
                    theme,
                    tags_text,
                    text,
                    tokenize='unicode61'
                )
                """
            )
        except sqlite3.OperationalError:
            # FTS5 might be unavailable in some Python/SQLite builds.
            pass
