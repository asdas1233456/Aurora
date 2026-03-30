"""Centralized access policy for Aurora memory facts."""

from __future__ import annotations

from app.schemas import MemoryFact, MemoryFactCreate, MemoryRequestContext, ResolvedScopeContext, ScopeRef
from app.services.memory_scope import ScopeResolver


class MemoryAccessPolicy:
    """Enforce minimum isolation for read and write access."""

    def __init__(self, scope_resolver: ScopeResolver | None = None) -> None:
        self._scope_resolver = scope_resolver or ScopeResolver()

    def can_read(
        self,
        request_context: MemoryRequestContext | ResolvedScopeContext,
        memory_fact: MemoryFact,
    ) -> bool:
        resolved_context = self._resolve_context(request_context)
        actor = resolved_context.request_context

        # Every memory access is fenced by tenant first, then by the resolved scope.
        if memory_fact.tenant_id != actor.tenant_id:
            return False
        if memory_fact.status == "deleted":
            return False
        if not self._scope_allowed(resolved_context, memory_fact.scope_type, memory_fact.scope_id):
            return False

        if memory_fact.scope_type == "session":
            return memory_fact.scope_id == actor.session_id
        if memory_fact.scope_type == "user":
            return (
                memory_fact.scope_id == actor.user_id
                and memory_fact.owner_user_id == actor.user_id
            )
        if memory_fact.scope_type == "project":
            return (
                memory_fact.scope_id == actor.project_id
                and memory_fact.project_id == actor.project_id
            )
        if memory_fact.scope_type == "team":
            return memory_fact.scope_id == actor.team_id
        if memory_fact.scope_type == "global":
            return memory_fact.scope_id == actor.global_scope_id
        return False

    def can_write(
        self,
        request_context: MemoryRequestContext | ResolvedScopeContext,
        proposed_memory_fact: MemoryFactCreate,
    ) -> bool:
        resolved_context = self._resolve_context(request_context)
        actor = resolved_context.request_context

        if proposed_memory_fact.tenant_id != actor.tenant_id:
            return False
        # Knowledge-base chunks are not allowed to bypass the KB layer into memory facts.
        if proposed_memory_fact.source_kind == "knowledge_base_document":
            return False

        if proposed_memory_fact.scope_type == "session":
            return (
                proposed_memory_fact.scope_id == actor.session_id
                and proposed_memory_fact.source_session_id == actor.session_id
                and proposed_memory_fact.owner_user_id == actor.user_id
            )
        if proposed_memory_fact.scope_type == "user":
            return (
                proposed_memory_fact.scope_id == actor.user_id
                and proposed_memory_fact.owner_user_id == actor.user_id
            )
        if proposed_memory_fact.scope_type == "project":
            return (
                proposed_memory_fact.scope_id == actor.project_id
                and proposed_memory_fact.project_id == actor.project_id
            )
        if proposed_memory_fact.scope_type == "team":
            # Shared scopes stay behind an explicit internal/system gate in stage 1.
            return (
                actor.allow_shared_scope_write
                and actor.actor_role in {"system", "admin"}
                and proposed_memory_fact.confirmed
                and proposed_memory_fact.scope_id == actor.team_id
            )
        if proposed_memory_fact.scope_type == "global":
            # Global writes are even more conservative and never open to normal chat.
            return (
                actor.allow_global_write
                and actor.actor_role in {"system", "admin"}
                and proposed_memory_fact.confirmed
                and proposed_memory_fact.scope_id == actor.global_scope_id
            )
        return False

    def _resolve_context(
        self, request_context: MemoryRequestContext | ResolvedScopeContext
    ) -> ResolvedScopeContext:
        if isinstance(request_context, ResolvedScopeContext):
            return request_context
        return self._scope_resolver.resolve(request_context)

    @staticmethod
    def _scope_allowed(
        resolved_context: ResolvedScopeContext,
        scope_type: str,
        scope_id: str,
    ) -> bool:
        return any(
            scope.scope_type == scope_type and scope.scope_id == scope_id
            for scope in resolved_context.allowed_scopes
        )
