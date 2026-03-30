"""Provider adapter registry for Aurora business generation."""

from __future__ import annotations

from app.config import LOCAL_MOCK_PROVIDER, OPENAI_COMPATIBLE_PROVIDERS, OPENAI_PROVIDER
from app.providers.base import ProviderAdapter
from app.providers.local_mock_adapter import LocalMockAdapter
from app.providers.openai_compatible_adapter import OpenAICompatibleAdapter


class ProviderRegistry:
    """Maps provider names to adapter implementations."""

    def __init__(self) -> None:
        self._adapter_types: dict[str, type[ProviderAdapter]] = {}
        self._name_to_canonical: dict[str, str] = {}
        self._entries: dict[str, dict[str, object]] = {}

    def register(
        self,
        provider_name: str,
        adapter_type: type[ProviderAdapter],
        *,
        aliases: tuple[str, ...] = (),
    ) -> None:
        # Collapse provider aliases at registration time so business code never branches on vendor names.
        canonical_name = str(provider_name or "").strip().lower()
        normalized_aliases = [
            str(alias or "").strip().lower()
            for alias in aliases
            if str(alias or "").strip()
        ]
        if not canonical_name:
            return

        self._entries[canonical_name] = {
            "provider_name": canonical_name,
            "adapter_type": adapter_type,
            "aliases": list(dict.fromkeys(normalized_aliases)),
        }

        for name in [canonical_name, *normalized_aliases]:
            self._adapter_types[name] = adapter_type
            self._name_to_canonical[name] = canonical_name

    def resolve(self, provider_name: str) -> type[ProviderAdapter]:
        normalized_name = str(provider_name or "").strip().lower()
        adapter_type = self._adapter_types.get(normalized_name)
        if adapter_type is None:
            raise NotImplementedError(f"llm_provider={provider_name} is not supported yet.")
        return adapter_type

    def supports(self, provider_name: str) -> bool:
        normalized_name = str(provider_name or "").strip().lower()
        return normalized_name in self._adapter_types

    def get_entry(self, provider_name: str) -> dict[str, object]:
        normalized_name = str(provider_name or "").strip().lower()
        canonical_name = self._name_to_canonical.get(normalized_name)
        if canonical_name is None:
            raise NotImplementedError(f"llm_provider={provider_name} is not supported yet.")
        entry = self._entries[canonical_name]
        return {
            "provider_name": entry["provider_name"],
            "adapter_type": entry["adapter_type"].__name__,
            "aliases": list(entry["aliases"]),
        }

    def describe(self) -> list[dict[str, object]]:
        return [
            {
                "provider_name": provider_name,
                "adapter_type": entry["adapter_type"].__name__,
                "aliases": list(entry["aliases"]),
            }
            for provider_name, entry in sorted(self._entries.items())
        ]


def build_default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(LOCAL_MOCK_PROVIDER, LocalMockAdapter)
    # OpenAI and compatible vendors share one request/response protocol, so they reuse one adapter.
    registry.register(
        OPENAI_PROVIDER,
        OpenAICompatibleAdapter,
        aliases=tuple(sorted(OPENAI_COMPATIBLE_PROVIDERS)),
    )
    return registry
