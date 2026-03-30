"""Shared SQLite storage helpers for catalog and local index state."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import AppConfig


_STATE_DB_FILE_NAME = "aurora_state.sqlite3"


def get_state_db_path(config: AppConfig) -> Path:
    config.ensure_directories()
    return config.db_dir / _STATE_DB_FILE_NAME


@contextmanager
def connect_state_db(config: AppConfig) -> Iterator[sqlite3.Connection]:
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
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _get_table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition_sql: str,
) -> None:
    if column_name in _get_table_columns(connection, table_name):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition_sql}")


def _memory_facts_table_sql(table_name: str = "memory_facts") -> str:
    return f"""
        CREATE TABLE {table_name} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            scope_type TEXT NOT NULL CHECK (scope_type IN ('session', 'user', 'project', 'team', 'global')),
            scope_id TEXT NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('fact', 'preference', 'decision', 'pending_issue')),
            content TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('active', 'stale', 'superseded', 'deleted', 'conflict_pending_review')
            ),
            source_session_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            subject_key TEXT NOT NULL DEFAULT '',
            fact_key TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            superseded_by TEXT DEFAULT NULL,
            supersedes TEXT DEFAULT NULL,
            correction_of TEXT DEFAULT NULL,
            source_type TEXT NOT NULL DEFAULT 'system_generated',
            source_confidence REAL NOT NULL DEFAULT 0,
            reviewed_by_human INTEGER DEFAULT NULL,
            consistency_group_id TEXT DEFAULT NULL,
            value_score REAL NOT NULL DEFAULT 0,
            retention_level TEXT NOT NULL DEFAULT 'normal'
                CHECK (retention_level IN ('critical', 'high', 'normal', 'low', 'temporary')),
            ttl_seconds INTEGER DEFAULT NULL,
            expires_at TEXT DEFAULT NULL,
            last_accessed_at TEXT DEFAULT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            successful_use_count INTEGER NOT NULL DEFAULT 0,
            decay_factor REAL NOT NULL DEFAULT 1.0,
            archived_at TEXT DEFAULT NULL,
            retrieval_visibility TEXT NOT NULL DEFAULT 'normal'
                CHECK (retrieval_visibility IN ('normal', 'deprioritized', 'hidden_from_default', 'archive_only')),
            forgetting_status TEXT NOT NULL DEFAULT 'none'
                CHECK (forgetting_status IN ('none', 'cooling', 'expired', 'archived')),
            next_evaluation_at TEXT DEFAULT NULL,
            retention_policy_id TEXT DEFAULT NULL,
            archive_bucket TEXT DEFAULT NULL
        )
    """


def _memory_access_audit_table_sql(table_name: str = "memory_access_audit") -> str:
    return f"""
        CREATE TABLE {table_name} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            memory_fact_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (
                action IN (
                    'create',
                    'read',
                    'retrieve',
                    'inject',
                    'update',
                    'correct',
                    'deprecate',
                    'archive',
                    'redact',
                    'delete'
                )
            ),
            actor_user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            scope_type TEXT NOT NULL DEFAULT '',
            retrieval_stage TEXT NOT NULL DEFAULT '',
            decision_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """


def _ensure_memory_fact_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_facts_scope_status
            ON memory_facts(tenant_id, scope_type, scope_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_facts_owner
            ON memory_facts(tenant_id, owner_user_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_facts_project
            ON memory_facts(tenant_id, project_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_facts_source_session
            ON memory_facts(tenant_id, source_session_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_facts_identity_current
            ON memory_facts(
                tenant_id,
                scope_type,
                scope_id,
                subject_key,
                fact_key,
                status,
                updated_at DESC
            );
        CREATE INDEX IF NOT EXISTS idx_memory_facts_consistency_group
            ON memory_facts(
                tenant_id,
                scope_type,
                scope_id,
                consistency_group_id,
                status,
                updated_at DESC
            );
        CREATE INDEX IF NOT EXISTS idx_memory_facts_visibility
            ON memory_facts(
                tenant_id,
                status,
                retrieval_visibility,
                forgetting_status,
                value_score DESC,
                updated_at DESC
            );
        CREATE INDEX IF NOT EXISTS idx_memory_facts_next_evaluation
            ON memory_facts(tenant_id, next_evaluation_at, status);
        """
    )
    try:
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_facts_unique_effective
            ON memory_facts(tenant_id, scope_type, scope_id, subject_key, fact_key)
            WHERE status = 'active' AND COALESCE(superseded_by, '') = ''
            """
        )
    except sqlite3.IntegrityError:
        # Existing legacy data can be dirty; write-path rules still enforce the invariant for new rows.
        pass


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

        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            last_active_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chat_sessions_tenant_user
            ON chat_sessions(tenant_id, user_id, last_active_at DESC);
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_project
            ON chat_sessions(tenant_id, project_id, last_active_at DESC);
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_last_active
            ON chat_sessions(user_id, last_active_at DESC);
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_project_last_active
            ON chat_sessions(project_id, last_active_at DESC);
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_active
            ON chat_sessions(last_active_at DESC);

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            citations_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created_at
            ON chat_messages(tenant_id, session_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_only
            ON chat_messages(session_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS memory_facts (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            scope_type TEXT NOT NULL CHECK (scope_type IN ('session', 'user', 'project', 'team', 'global')),
            scope_id TEXT NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('fact', 'preference', 'decision', 'pending_issue')),
            content TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('active', 'stale', 'superseded', 'deleted', 'conflict_pending_review')
            ),
            source_session_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            subject_key TEXT NOT NULL DEFAULT '',
            fact_key TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            superseded_by TEXT DEFAULT NULL,
            supersedes TEXT DEFAULT NULL,
            correction_of TEXT DEFAULT NULL,
            source_type TEXT NOT NULL DEFAULT 'system_generated',
            source_confidence REAL NOT NULL DEFAULT 0,
            reviewed_by_human INTEGER DEFAULT NULL,
            consistency_group_id TEXT DEFAULT NULL,
            value_score REAL NOT NULL DEFAULT 0,
            retention_level TEXT NOT NULL DEFAULT 'normal'
                CHECK (retention_level IN ('critical', 'high', 'normal', 'low', 'temporary')),
            ttl_seconds INTEGER DEFAULT NULL,
            expires_at TEXT DEFAULT NULL,
            last_accessed_at TEXT DEFAULT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            successful_use_count INTEGER NOT NULL DEFAULT 0,
            decay_factor REAL NOT NULL DEFAULT 1.0,
            archived_at TEXT DEFAULT NULL,
            retrieval_visibility TEXT NOT NULL DEFAULT 'normal'
                CHECK (retrieval_visibility IN ('normal', 'deprioritized', 'hidden_from_default', 'archive_only')),
            forgetting_status TEXT NOT NULL DEFAULT 'none'
                CHECK (forgetting_status IN ('none', 'cooling', 'expired', 'archived')),
            next_evaluation_at TEXT DEFAULT NULL,
            retention_policy_id TEXT DEFAULT NULL,
            archive_bucket TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_access_audit (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            memory_fact_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (
                action IN (
                    'create',
                    'read',
                    'retrieve',
                    'inject',
                    'update',
                    'correct',
                    'deprecate',
                    'archive',
                    'redact',
                    'delete'
                )
            ),
            actor_user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            scope_type TEXT NOT NULL DEFAULT '',
            retrieval_stage TEXT NOT NULL DEFAULT '',
            decision_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memory_access_audit_fact
            ON memory_access_audit(tenant_id, memory_fact_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_access_audit_request
            ON memory_access_audit(tenant_id, request_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_access_audit_session
            ON memory_access_audit(tenant_id, session_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_access_audit_action
            ON memory_access_audit(tenant_id, action, created_at DESC);

        CREATE TABLE IF NOT EXISTS memory_retention_audit (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            memory_fact_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (
                action IN (
                    'initialized',
                    'evaluated',
                    'deprioritized',
                    'hidden_from_default',
                    'expired',
                    'archived',
                    'restored',
                    'accessed',
                    'successful_use'
                )
            ),
            reason TEXT NOT NULL DEFAULT '',
            value_score REAL NOT NULL DEFAULT 0,
            retention_level TEXT NOT NULL DEFAULT 'normal',
            retrieval_visibility TEXT NOT NULL DEFAULT 'normal',
            forgetting_status TEXT NOT NULL DEFAULT 'none',
            policy_id TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memory_retention_audit_fact
            ON memory_retention_audit(tenant_id, memory_fact_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_retention_audit_action
            ON memory_retention_audit(tenant_id, action, created_at DESC);

        CREATE TABLE IF NOT EXISTS security_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (
                event_type IN (
                    'sensitive_memory_detected',
                    'unauthorized_scope_write_attempt',
                    'suspicious_prompt_injection',
                    'abnormal_retrieval_volume',
                    'policy_blocked_write',
                    'provider_failure_fallback',
                    'rate_limit_triggered'
                )
            ),
            severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
            actor_user_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            target_memory_fact_id TEXT DEFAULT NULL,
            request_id TEXT NOT NULL DEFAULT '',
            event_payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'acknowledged', 'resolved', 'ignored')),
            created_at TEXT NOT NULL,
            resolved_at TEXT DEFAULT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_security_events_tenant_created
            ON security_events(tenant_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_security_events_request
            ON security_events(tenant_id, request_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_security_events_status
            ON security_events(tenant_id, status, created_at DESC);

        CREATE TABLE IF NOT EXISTS policy_decisions (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            policy_name TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (
                decision IN ('allow', 'deny', 'redact', 'review', 'fallback', 'throttle', 'observe')
            ),
            reason TEXT NOT NULL DEFAULT '',
            target_type TEXT NOT NULL DEFAULT '',
            target_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_policy_decisions_request
            ON policy_decisions(request_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_policy_decisions_policy
            ON policy_decisions(policy_name, decision, created_at DESC);

        CREATE TABLE IF NOT EXISTS system_metrics_snapshot (
            id TEXT PRIMARY KEY,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL DEFAULT 0,
            dimensions_json TEXT NOT NULL DEFAULT '{}',
            captured_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_system_metrics_snapshot_metric
            ON system_metrics_snapshot(metric_name, captured_at DESC);
        """
    )
    _ensure_memory_fact_schema(connection)
    _ensure_memory_access_audit_schema(connection)
    _ensure_memory_fact_indexes(connection)

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


def _ensure_memory_fact_schema(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "memory_facts"):
        return

    memory_table_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'memory_facts'"
    ).fetchone()
    memory_table_sql = str(memory_table_sql_row["sql"] or "") if memory_table_sql_row else ""
    if "conflict_pending_review" not in memory_table_sql:
        connection.execute("ALTER TABLE memory_facts RENAME TO memory_facts_legacy")
        connection.execute(_memory_facts_table_sql("memory_facts"))
        connection.execute(
            """
            INSERT INTO memory_facts (
                id, tenant_id, owner_user_id, project_id, scope_type, scope_id,
                type, content, status, source_session_id, created_at, updated_at,
                subject_key, fact_key, version, superseded_by, supersedes, correction_of,
                source_type, source_confidence, reviewed_by_human, consistency_group_id,
                value_score, retention_level, ttl_seconds, expires_at, last_accessed_at,
                access_count, successful_use_count, decay_factor, archived_at,
                retrieval_visibility, forgetting_status, next_evaluation_at,
                retention_policy_id, archive_bucket
            )
            SELECT
                id,
                tenant_id,
                owner_user_id,
                project_id,
                scope_type,
                scope_id,
                type,
                content,
                status,
                source_session_id,
                created_at,
                updated_at,
                COALESCE(subject_key, ''),
                COALESCE(fact_key, ''),
                COALESCE(version, 1),
                superseded_by,
                supersedes,
                correction_of,
                COALESCE(source_type, 'system_generated'),
                COALESCE(source_confidence, 0),
                reviewed_by_human,
                consistency_group_id,
                COALESCE(value_score, 0),
                COALESCE(retention_level, 'normal'),
                ttl_seconds,
                expires_at,
                last_accessed_at,
                COALESCE(access_count, 0),
                COALESCE(successful_use_count, 0),
                COALESCE(decay_factor, 1.0),
                archived_at,
                COALESCE(retrieval_visibility, 'normal'),
                COALESCE(forgetting_status, 'none'),
                next_evaluation_at,
                retention_policy_id,
                archive_bucket
            FROM memory_facts_legacy
            """
        )
        connection.execute("DROP TABLE memory_facts_legacy")

    _ensure_column(connection, "memory_facts", "subject_key", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "memory_facts", "fact_key", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "memory_facts", "version", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "memory_facts", "superseded_by", "TEXT DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "supersedes", "TEXT DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "correction_of", "TEXT DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "source_type", "TEXT NOT NULL DEFAULT 'system_generated'")
    _ensure_column(connection, "memory_facts", "source_confidence", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "memory_facts", "reviewed_by_human", "INTEGER DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "consistency_group_id", "TEXT DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "value_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(
        connection,
        "memory_facts",
        "retention_level",
        "TEXT NOT NULL DEFAULT 'normal'",
    )
    _ensure_column(connection, "memory_facts", "ttl_seconds", "INTEGER DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "expires_at", "TEXT DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "last_accessed_at", "TEXT DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "access_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "memory_facts", "successful_use_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "memory_facts", "decay_factor", "REAL NOT NULL DEFAULT 1.0")
    _ensure_column(connection, "memory_facts", "archived_at", "TEXT DEFAULT NULL")
    _ensure_column(
        connection,
        "memory_facts",
        "retrieval_visibility",
        "TEXT NOT NULL DEFAULT 'normal'",
    )
    _ensure_column(
        connection,
        "memory_facts",
        "forgetting_status",
        "TEXT NOT NULL DEFAULT 'none'",
    )
    _ensure_column(connection, "memory_facts", "next_evaluation_at", "TEXT DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "retention_policy_id", "TEXT DEFAULT NULL")
    _ensure_column(connection, "memory_facts", "archive_bucket", "TEXT DEFAULT NULL")

    # Backfill legacy rows with deterministic identities so new indexes and retrieval logic stay safe.
    connection.execute(
        """
        UPDATE memory_facts
        SET subject_key = scope_type || ':' || scope_id
        WHERE COALESCE(subject_key, '') = ''
        """
    )
    connection.execute(
        """
        UPDATE memory_facts
        SET fact_key = type || '.legacy.' || substr(replace(id, '-', ''), 1, 12)
        WHERE COALESCE(fact_key, '') = ''
        """
    )
    connection.execute(
        """
        UPDATE memory_facts
        SET version = 1
        WHERE COALESCE(version, 0) <= 0
        """
    )
    connection.execute(
        """
        UPDATE memory_facts
        SET source_type = 'system_generated'
        WHERE COALESCE(source_type, '') = ''
        """
    )
    connection.execute(
        """
        UPDATE memory_facts
        SET source_confidence = 0
        WHERE source_confidence IS NULL
        """
    )
    connection.execute(
        """
        UPDATE memory_facts
        SET consistency_group_id = subject_key || '|' || fact_key
        WHERE COALESCE(consistency_group_id, '') = ''
        """
    )
    connection.execute(
        """
        UPDATE memory_facts
        SET retention_level = 'normal'
        WHERE COALESCE(retention_level, '') = ''
        """
    )
    connection.execute(
        """
        UPDATE memory_facts
        SET retrieval_visibility = 'normal'
        WHERE COALESCE(retrieval_visibility, '') = ''
        """
    )
    connection.execute(
        """
        UPDATE memory_facts
        SET forgetting_status = 'none'
        WHERE COALESCE(forgetting_status, '') = ''
        """
    )
    connection.execute(
        """
        UPDATE memory_facts
        SET decay_factor = 1.0
        WHERE decay_factor IS NULL OR decay_factor <= 0
        """
    )


def _ensure_memory_access_audit_schema(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "memory_access_audit"):
        connection.execute(_memory_access_audit_table_sql("memory_access_audit"))
        return

    audit_table_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'memory_access_audit'"
    ).fetchone()
    audit_table_sql = str(audit_table_sql_row["sql"] or "") if audit_table_sql_row else ""
    needs_rebuild = any(
        marker not in audit_table_sql
        for marker in (
            "inject",
            "correct",
            "deprecate",
            "archive",
            "redact",
            "scope_type",
            "retrieval_stage",
            "decision_reason",
        )
    )
    if needs_rebuild:
        connection.execute("ALTER TABLE memory_access_audit RENAME TO memory_access_audit_legacy")
        connection.execute(_memory_access_audit_table_sql("memory_access_audit"))
        connection.execute(
            """
            INSERT INTO memory_access_audit (
                id, tenant_id, request_id, memory_fact_id, action, actor_user_id,
                session_id, scope_type, retrieval_stage, decision_reason, created_at
            )
            SELECT
                id,
                tenant_id,
                request_id,
                memory_fact_id,
                CASE
                    WHEN action IN ('create', 'read', 'retrieve', 'update', 'delete') THEN action
                    ELSE 'update'
                END,
                actor_user_id,
                session_id,
                '',
                '',
                '',
                created_at
            FROM memory_access_audit_legacy
            """
        )
        connection.execute("DROP TABLE memory_access_audit_legacy")

    _ensure_column(connection, "memory_access_audit", "scope_type", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "memory_access_audit", "retrieval_stage", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "memory_access_audit", "decision_reason", "TEXT NOT NULL DEFAULT ''")
