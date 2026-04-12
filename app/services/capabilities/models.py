"""Shared dataclasses for capability registration and runtime context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.schemas import MemoryRequestContext


CapabilityType = Literal["tool", "command", "resource"]
CapabilityInvocationSource = Literal["system", "api", "user", "model", "workflow"]


@dataclass(slots=True)
class CapabilityDescriptor:
    """Static metadata used by the registry and assembler.

    The descriptor intentionally stays small in Phase 1. It captures the
    capability traits that are already useful for assembly and future routing:
    read-only behavior, concurrency hints, and whether the capability should be
    visible to model-initiated execution.
    """

    name: str
    capability_type: CapabilityType
    display_name: str
    description: str
    capability_id: str = ""
    read_only: bool = True
    concurrency_safe: bool = True
    allow_user_invoke: bool = True
    allow_model_invoke: bool = True
    defer_load: bool = False
    routing_tags: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("Capability name is required.")
        self.name = normalized_name
        self.capability_id = str(self.capability_id or normalized_name)
        self.display_name = self.display_name.strip() or normalized_name
        self.description = self.description.strip()
        self.routing_tags = tuple(str(item).strip() for item in self.routing_tags if str(item).strip())
        self.metadata = dict(self.metadata)


@dataclass(slots=True)
class CapabilityContext:
    """Runtime context passed into capability execution."""

    request_id: str
    tenant_id: str
    user_id: str
    project_id: str
    session_id: str
    department_id: str = ""
    team_id: str = ""
    scene: str = ""
    actor_role: str = "system"
    invocation_source: CapabilityInvocationSource = "system"
    metadata: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_request_context(
        cls,
        request_context: MemoryRequestContext | None,
        *,
        scene: str = "",
        invocation_source: CapabilityInvocationSource = "system",
        metadata: dict[str, object] | None = None,
    ) -> "CapabilityContext":
        """Build a capability context from the existing chat request context.

        Phase 1 keeps the assembler lightweight by reusing the fields Aurora
        already resolves for memory isolation and auditing, instead of
        introducing a second request-context model.
        """

        if request_context is None:
            return cls(
                request_id=f"{invocation_source}:capability",
                tenant_id="local_tenant",
                user_id="system",
                project_id="aurora",
                session_id=f"{invocation_source}:session",
                scene=scene,
                invocation_source=invocation_source,
                metadata=dict(metadata or {}),
            )

        return cls(
            request_id=request_context.request_id,
            tenant_id=request_context.tenant_id,
            user_id=request_context.user_id,
            project_id=request_context.project_id,
            session_id=request_context.session_id,
            department_id=request_context.department_id,
            team_id=request_context.team_id,
            scene=scene,
            actor_role=request_context.actor_role,
            invocation_source=invocation_source,
            metadata=dict(metadata or {}),
        )
