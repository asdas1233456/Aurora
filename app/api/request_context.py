"""Request-context helpers shared by public and internal API entrypoints."""

from __future__ import annotations

import getpass
import re
from uuid import uuid4

from app.config import AppConfig
from app.schemas import MemoryRequestContext


_SAFE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_.:-]+")


def build_request_context(
    *,
    config: AppConfig,
    tenant_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    team_id: str | None = None,
    global_scope_id: str | None = None,
    actor_role: str = "conversation",
    allow_shared_scope_write: bool = False,
    allow_global_write: bool = False,
) -> MemoryRequestContext:
    normalized_request_id = _normalize_identifier(request_id) or str(uuid4())
    normalized_user_id = _normalize_identifier(user_id) or _normalize_identifier(getpass.getuser()) or "local_user"
    normalized_project_id = _normalize_identifier(project_id) or _normalize_identifier(config.base_dir.name) or "aurora"

    return MemoryRequestContext(
        request_id=normalized_request_id,
        tenant_id=_normalize_identifier(tenant_id) or "local_tenant",
        user_id=normalized_user_id,
        project_id=normalized_project_id,
        session_id=_normalize_identifier(session_id) or f"session:{normalized_request_id}",
        team_id=_normalize_identifier(team_id) or "team_default",
        global_scope_id=_normalize_identifier(global_scope_id) or "global_default",
        actor_role=actor_role.strip() or "conversation",
        allow_shared_scope_write=allow_shared_scope_write,
        allow_global_write=allow_global_write,
    )


def _normalize_identifier(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return _SAFE_ID_PATTERN.sub("_", normalized)
