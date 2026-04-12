"""Capability registration for built-in and future external abilities."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.config import AppConfig
from app.services.capabilities.base import BaseCapability
from app.services.capabilities.builtin import register_builtin_capabilities
from app.services.capabilities.models import CapabilityDescriptor, CapabilityType


CapabilityFactory = Callable[[AppConfig], BaseCapability]


@dataclass(slots=True)
class RegisteredCapability:
    """One registry entry with static metadata plus runtime factory."""

    descriptor: CapabilityDescriptor
    factory: CapabilityFactory


class CapabilityRegistry:
    """Registry holding capability descriptors and factories.

    The registry is intentionally simple in Phase 1: it only knows how to store
    definitions and build runtime wrappers. Business logic continues to live in
    the existing Aurora services that these wrappers delegate to.
    """

    def __init__(self) -> None:
        self._entries: dict[str, RegisteredCapability] = {}

    def register(self, descriptor: CapabilityDescriptor, factory: CapabilityFactory) -> None:
        """Register one capability factory."""
        if descriptor.name in self._entries:
            raise ValueError(f"Capability already registered: {descriptor.name}")
        self._entries[descriptor.name] = RegisteredCapability(descriptor=descriptor, factory=factory)

    def get_entry(self, name: str) -> RegisteredCapability | None:
        """Return one registry entry by capability name."""
        return self._entries.get(str(name or "").strip())

    def build(self, name: str, config: AppConfig) -> BaseCapability:
        """Instantiate one capability wrapper for the supplied config."""
        entry = self.get_entry(name)
        if entry is None:
            raise KeyError(f"Capability is not registered: {name}")
        return entry.factory(config)

    def list_descriptors(self, capability_type: CapabilityType | None = None) -> list[CapabilityDescriptor]:
        """List registered descriptors, optionally filtered by type."""
        descriptors = [entry.descriptor for entry in self._entries.values()]
        if capability_type is None:
            return list(descriptors)
        return [descriptor for descriptor in descriptors if descriptor.capability_type == capability_type]

    def iter_entries(self) -> Iterable[RegisteredCapability]:
        """Iterate over registered entries in insertion order."""
        return tuple(self._entries.values())


def build_default_capability_registry() -> CapabilityRegistry:
    """Build the default Aurora capability registry."""
    registry = CapabilityRegistry()
    register_builtin_capabilities(registry)
    return registry
