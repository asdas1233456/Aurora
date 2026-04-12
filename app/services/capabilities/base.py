"""Base capability interfaces for Aurora runtime objects."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from app.config import AppConfig
from app.services.capabilities.models import CapabilityContext, CapabilityDescriptor


class BaseCapability(ABC):
    """Base class shared by tools, commands, and resources."""

    descriptor: CapabilityDescriptor

    def __init__(self, config: AppConfig) -> None:
        self.config = config


class BaseTool(BaseCapability):
    """Executable read/write capability."""

    @abstractmethod
    def execute(
        self,
        payload: Mapping[str, Any],
        context: CapabilityContext,
    ) -> Any:
        """Execute one tool call."""


class BaseCommand(BaseCapability):
    """User or system-facing entry command."""

    @abstractmethod
    def invoke(
        self,
        payload: Mapping[str, Any],
        context: CapabilityContext,
    ) -> Any:
        """Invoke one command."""


class BaseResource(BaseCapability):
    """Read-only resource surface."""

    @abstractmethod
    def read(
        self,
        selector: Mapping[str, Any],
        context: CapabilityContext,
    ) -> Any:
        """Read one resource payload."""
