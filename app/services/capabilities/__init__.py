"""Capability registry primitives for Aurora built-in and external abilities."""

from app.services.capabilities.assembler import (
    CapabilityAccessError,
    CapabilityAssembler,
    CapabilityAssembly,
    CapabilityNotFoundError,
)
from app.services.capabilities.models import CapabilityContext, CapabilityDescriptor
from app.services.capabilities.registry import CapabilityRegistry, build_default_capability_registry

__all__ = [
    "CapabilityAccessError",
    "CapabilityAssembler",
    "CapabilityAssembly",
    "CapabilityContext",
    "CapabilityDescriptor",
    "CapabilityNotFoundError",
    "CapabilityRegistry",
    "build_default_capability_registry",
]
