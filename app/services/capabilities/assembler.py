"""Capability assembly and visibility filtering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.config import AppConfig
from app.services.capabilities.base import BaseCommand, BaseResource, BaseTool
from app.services.capabilities.models import CapabilityContext, CapabilityDescriptor
from app.services.capabilities.registry import CapabilityRegistry, build_default_capability_registry
from app.services.knowledge_access_policy import KnowledgeAccessFilter, build_access_filter


class CapabilityNotFoundError(LookupError):
    """Raised when a capability name is unknown to the registry."""


class CapabilityAccessError(PermissionError):
    """Raised when a capability exists but is hidden for the current context."""


@dataclass(slots=True)
class CapabilityAssembly:
    """Visible capabilities for one request context."""

    context: CapabilityContext
    access_filter: KnowledgeAccessFilter
    descriptors: list[CapabilityDescriptor] = field(default_factory=list)
    tools: dict[str, BaseTool] = field(default_factory=dict)
    commands: dict[str, BaseCommand] = field(default_factory=dict)
    resources: dict[str, BaseResource] = field(default_factory=dict)


class CapabilityAssembler:
    """Filter and instantiate visible capabilities for one request.

    The assembler is the Phase 1 seam between today's Aurora services and the
    future multi-connector routing layer. It keeps orchestration code unaware of
    which module actually implements a capability.
    """

    def __init__(
        self,
        config: AppConfig,
        registry: CapabilityRegistry | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or build_default_capability_registry()

    def assemble(self, context: CapabilityContext) -> CapabilityAssembly:
        """Build the visible capability set for one context."""
        assembly = CapabilityAssembly(
            context=context,
            access_filter=build_access_filter(context),
        )
        for entry in self.registry.iter_entries():
            if not self._is_visible(entry.descriptor, context):
                continue
            capability = entry.factory(self.config)
            assembly.descriptors.append(entry.descriptor)
            if entry.descriptor.capability_type == "tool":
                assembly.tools[entry.descriptor.name] = capability  # type: ignore[assignment]
            elif entry.descriptor.capability_type == "command":
                assembly.commands[entry.descriptor.name] = capability  # type: ignore[assignment]
            elif entry.descriptor.capability_type == "resource":
                assembly.resources[entry.descriptor.name] = capability  # type: ignore[assignment]
        return assembly

    def require_tool(self, name: str, context: CapabilityContext) -> BaseTool:
        """Resolve one visible tool or raise a typed error."""
        capability = self._require(name, "tool", context)
        return capability  # type: ignore[return-value]

    def require_command(self, name: str, context: CapabilityContext) -> BaseCommand:
        """Resolve one visible command or raise a typed error."""
        capability = self._require(name, "command", context)
        return capability  # type: ignore[return-value]

    def require_resource(self, name: str, context: CapabilityContext) -> BaseResource:
        """Resolve one visible resource or raise a typed error."""
        capability = self._require(name, "resource", context)
        return capability  # type: ignore[return-value]

    def _require(self, name: str, capability_type: str, context: CapabilityContext):
        entry = self.registry.get_entry(name)
        if entry is None:
            raise CapabilityNotFoundError(f"Capability is not registered: {name}")
        if entry.descriptor.capability_type != capability_type:
            raise CapabilityNotFoundError(
                f"Capability {name} is registered as {entry.descriptor.capability_type}, not {capability_type}."
            )
        if not self._is_visible(entry.descriptor, context):
            raise CapabilityAccessError(f"Capability is not visible for current context: {name}")
        return entry.factory(self.config)

    def _is_visible(self, descriptor: CapabilityDescriptor, context: CapabilityContext) -> bool:
        """Apply Phase 1 visibility rules.

        We keep the rules intentionally small for now:
        model-initiated execution respects `allow_model_invoke`,
        user/API requests respect `allow_user_invoke`,
        system/workflow execution can still access internal capabilities,
        and descriptor metadata can further constrain visibility by tenant,
        department, scene, actor role, or arbitrary request metadata.
        """

        if context.invocation_source == "model":
            if not descriptor.allow_model_invoke:
                return False
        elif context.invocation_source in {"api", "user"} and not descriptor.allow_user_invoke:
            return False

        descriptor_metadata = dict(descriptor.metadata or {})
        if not self._matches_allowed_scope(
            context.tenant_id,
            descriptor_metadata.get("allowed_tenant_ids"),
        ):
            return False
        if not self._matches_allowed_scope(
            context.user_id,
            descriptor_metadata.get("allowed_user_ids"),
        ):
            return False
        if not self._matches_allowed_scope(
            context.department_id,
            descriptor_metadata.get("allowed_department_ids"),
        ):
            return False
        if not self._matches_allowed_scope(
            context.actor_role,
            descriptor_metadata.get("allowed_actor_roles"),
        ):
            return False
        if not self._matches_allowed_scope(
            context.scene,
            descriptor_metadata.get("allowed_scenes"),
        ):
            return False
        if self._matches_blocked_scope(
            context.scene,
            descriptor_metadata.get("blocked_scenes"),
        ):
            return False

        required_context_metadata = descriptor_metadata.get("required_context_metadata")
        if isinstance(required_context_metadata, Mapping) and not self._matches_context_metadata(
            context.metadata,
            required_context_metadata,
        ):
            return False

        blocked_context_metadata = descriptor_metadata.get("blocked_context_metadata")
        if isinstance(blocked_context_metadata, Mapping) and self._matches_context_metadata(
            context.metadata,
            blocked_context_metadata,
        ):
            return False

        return True

    def _matches_allowed_scope(self, actual_value: str, allowed_values: object) -> bool:
        normalized_allowed_values = self._normalize_scope_values(allowed_values)
        if not normalized_allowed_values:
            return True
        return str(actual_value or "").strip() in normalized_allowed_values

    def _matches_blocked_scope(self, actual_value: str, blocked_values: object) -> bool:
        normalized_blocked_values = self._normalize_scope_values(blocked_values)
        if not normalized_blocked_values:
            return False
        return str(actual_value or "").strip() in normalized_blocked_values

    def _normalize_scope_values(self, raw_values: object) -> set[str]:
        if raw_values is None:
            return set()
        if isinstance(raw_values, str):
            normalized_value = raw_values.strip()
            return {normalized_value} if normalized_value else set()
        if isinstance(raw_values, (list, tuple, set, frozenset)):
            return {
                str(item).strip()
                for item in raw_values
                if str(item).strip()
            }
        normalized_value = str(raw_values).strip()
        return {normalized_value} if normalized_value else set()

    def _matches_context_metadata(
        self,
        context_metadata: dict[str, object],
        metadata_rules: Mapping[str, object],
    ) -> bool:
        for key, expected_value in metadata_rules.items():
            actual_value = context_metadata.get(str(key))
            if not self._metadata_value_matches(actual_value, expected_value):
                return False
        return True

    def _metadata_value_matches(self, actual_value: object, expected_value: object) -> bool:
        if isinstance(expected_value, (list, tuple, set, frozenset)):
            return any(
                self._metadata_value_matches(actual_value, item)
                for item in expected_value
            )
        if isinstance(actual_value, (list, tuple, set, frozenset)):
            return any(
                self._metadata_value_matches(item, expected_value)
                for item in actual_value
            )
        if isinstance(expected_value, bool):
            return bool(actual_value) is expected_value
        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            try:
                return float(actual_value) == float(expected_value)
            except (TypeError, ValueError):
                return False
        if isinstance(expected_value, str):
            return str(actual_value or "").strip() == expected_value.strip()
        return actual_value == expected_value
