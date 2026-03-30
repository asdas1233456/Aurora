"""Scope resolution for Aurora memory isolation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.schemas import MemoryRequestContext, ResolvedScopeContext, ScopeRef, ScopeType


ResolverFunc = Callable[[MemoryRequestContext], str | None]


@dataclass(frozen=True, slots=True)
class ScopeRule:
    """A single, extensible scope resolution rule."""

    scope_type: ScopeType
    resolver: ResolverFunc


def _resolve_session_scope(context: MemoryRequestContext) -> str | None:
    return context.session_id.strip() or None


def _resolve_user_scope(context: MemoryRequestContext) -> str | None:
    return context.user_id.strip() or None


def _resolve_project_scope(context: MemoryRequestContext) -> str | None:
    return context.project_id.strip() or None


def _resolve_team_scope(context: MemoryRequestContext) -> str | None:
    return context.team_id.strip() or None


def _resolve_global_scope(context: MemoryRequestContext) -> str | None:
    return context.global_scope_id.strip() or None


def default_scope_rules() -> tuple[ScopeRule, ...]:
    """Default scope order follows Aurora's minimum-scope-first model."""

    # Order matters: narrower scopes are resolved first and will be queried first.
    return (
        ScopeRule("session", _resolve_session_scope),
        ScopeRule("user", _resolve_user_scope),
        ScopeRule("project", _resolve_project_scope),
        ScopeRule("team", _resolve_team_scope),
        ScopeRule("global", _resolve_global_scope),
    )


class ScopeResolver:
    """Resolve request context into the scopes a request may access."""

    def __init__(self, rules: Sequence[ScopeRule] | None = None) -> None:
        self._rules = tuple(rules or default_scope_rules())

    def resolve(self, request_context: MemoryRequestContext) -> ResolvedScopeContext:
        allowed_scopes: list[ScopeRef] = []
        seen_keys: set[tuple[str, str]] = set()

        for rule in self._rules:
            scope_id = (rule.resolver(request_context) or "").strip()
            if not scope_id:
                continue

            scope_key = (rule.scope_type, scope_id)
            if scope_key in seen_keys:
                continue

            seen_keys.add(scope_key)
            allowed_scopes.append(ScopeRef(scope_type=rule.scope_type, scope_id=scope_id))

        return ResolvedScopeContext(
            request_context=request_context,
            allowed_scopes=tuple(allowed_scopes),
        )
