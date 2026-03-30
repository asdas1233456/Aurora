"""Compatibility router built on top of the provider registry and factory."""

from __future__ import annotations

from app.config import AppConfig
from app.providers.base import ProviderAdapter
from app.providers.factory import ProviderFactory
from app.providers.registry import ProviderRegistry, build_default_provider_registry


class ProviderRouter:
    """Thin compatibility wrapper around ProviderFactory."""

    def __init__(
        self,
        config: AppConfig,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or build_default_provider_registry()

    def resolve(self) -> ProviderAdapter:
        return ProviderFactory(self.config, registry=self.registry).create()
