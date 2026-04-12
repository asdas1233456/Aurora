"""Shared knowledge-access filtering helpers for retrieval and resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.schemas import DocumentSummary

if TYPE_CHECKING:
    from app.services.capabilities.models import CapabilityContext


@dataclass(slots=True)
class KnowledgeAccessFilter:
    """Normalized metadata filter used across retrieval and resource reads.

    Phase 1 keeps the policy intentionally compact:
    public documents are always readable, tenant-scoped documents require a
    tenant match, and optional owner/department scopes further narrow access.
    Legacy rows without scope metadata remain readable so existing installs do
    not become empty after upgrading before a rebuild.
    """

    tenant_id: str = ""
    user_id: str = ""
    department_id: str = ""
    allow_public: bool = True

    @property
    def has_scope_constraints(self) -> bool:
        return bool(self.tenant_id or self.user_id or self.department_id)


def build_access_filter(context: CapabilityContext) -> KnowledgeAccessFilter:
    """Build a knowledge filter from the assembled capability context."""
    metadata = dict(context.metadata or {})
    return KnowledgeAccessFilter(
        tenant_id=str(context.tenant_id or metadata.get("tenant_id", "") or "").strip(),
        user_id=str(context.user_id or metadata.get("user_id", "") or "").strip(),
        department_id=str(
            context.department_id or metadata.get("department_id", "") or ""
        ).strip(),
        allow_public=bool(metadata.get("allow_public_knowledge", True)),
    )


def can_access_metadata(
    access_filter: KnowledgeAccessFilter,
    *,
    tenant_id: str = "",
    owner_user_id: str = "",
    department_id: str = "",
    is_public: bool = True,
) -> bool:
    """Evaluate one metadata tuple against the shared Aurora access rules."""
    normalized_tenant = str(tenant_id or "").strip()
    normalized_owner = str(owner_user_id or "").strip()
    normalized_department = str(department_id or "").strip()
    public_flag = bool(is_public)

    if public_flag and access_filter.allow_public:
        return True

    tenant_allowed = not normalized_tenant or normalized_tenant == access_filter.tenant_id
    if not tenant_allowed:
        return False

    # Legacy or tenant-wide rows without finer-grained scope remain visible.
    if not normalized_owner and not normalized_department:
        return True
    if normalized_owner and normalized_owner == access_filter.user_id:
        return True
    if (
        normalized_department
        and access_filter.department_id
        and normalized_department == access_filter.department_id
    ):
        return True
    return False


def can_access_document(document: DocumentSummary, access_filter: KnowledgeAccessFilter) -> bool:
    """Check whether the current caller can read one document summary."""
    return can_access_metadata(
        access_filter,
        tenant_id=document.tenant_id,
        owner_user_id=document.owner_user_id,
        department_id=document.department_id,
        is_public=document.is_public,
    )


def build_sql_access_clause(
    access_filter: KnowledgeAccessFilter,
    *,
    table_alias: str = "",
) -> tuple[str, list[object]]:
    """Build a SQLite WHERE clause for structured/local chunk filtering."""
    prefix = f"{table_alias}." if table_alias else ""
    tenant_column = f"{prefix}tenant_id"
    owner_column = f"{prefix}owner_user_id"
    department_column = f"{prefix}department_id"
    public_column = f"{prefix}is_public"

    scope_clause = f"({owner_column} = '' AND {department_column} = '')"
    parameters: list[object] = []
    if access_filter.user_id:
        scope_clause = f"({scope_clause} OR {owner_column} = ?)"
        parameters.append(access_filter.user_id)
    if access_filter.department_id:
        scope_clause = f"({scope_clause} OR {department_column} = ?)"
        parameters.append(access_filter.department_id)

    if access_filter.tenant_id:
        tenant_clause = f"({tenant_column} = '' OR {tenant_column} = ?)"
        parameters.insert(0, access_filter.tenant_id)
    else:
        tenant_clause = f"{tenant_column} = ''"

    private_clause = f"({tenant_clause} AND {scope_clause})"
    if access_filter.allow_public:
        return f"({public_column} = 1 OR {private_clause})", parameters
    return private_clause, parameters


def build_chroma_where(access_filter: KnowledgeAccessFilter) -> dict[str, object] | None:
    """Build a Chroma `where` expression for dense retrieval metadata filtering."""
    if not access_filter.has_scope_constraints and access_filter.allow_public:
        # Open-access callers do not need an explicit filter.
        return None

    scope_clauses: list[dict[str, object]] = [
        {"$and": [{"owner_user_id": ""}, {"department_id": ""}]},
    ]
    if access_filter.user_id:
        scope_clauses.append({"owner_user_id": access_filter.user_id})
    if access_filter.department_id:
        scope_clauses.append({"department_id": access_filter.department_id})

    tenant_clause: dict[str, object]
    if access_filter.tenant_id:
        tenant_clause = {"$or": [{"tenant_id": ""}, {"tenant_id": access_filter.tenant_id}]}
    else:
        tenant_clause = {"tenant_id": ""}

    private_clause: dict[str, object] = {"$and": [tenant_clause, {"$or": scope_clauses}]}
    if access_filter.allow_public:
        return {"$or": [{"is_public": True}, private_clause]}
    return private_clause
