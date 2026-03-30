"""Provider factory built on top of the provider registry."""

from __future__ import annotations

from app.config import AppConfig, is_local_mock_provider
from app.providers.base import ProviderAdapter
from app.providers.registry import ProviderRegistry, build_default_provider_registry


class ProviderFactory:
    """Creates provider adapters from config and registry metadata."""

    def __init__(
        self,
        config: AppConfig,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or build_default_provider_registry()

    def create(self) -> ProviderAdapter:
        provider_name = self.config.llm_provider
        # Local mock is both a first-class provider and the controlled fallback when remote config is absent.
        if is_local_mock_provider(provider_name) or not self.config.llm_api_ready:
            adapter_type = self.registry.resolve("local_mock")
            return adapter_type(self.config)

        adapter_type = self.registry.resolve(provider_name)
        return adapter_type(self.config)
