"""Provider adapter abstractions for Aurora business contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas import BusinessRequest, BusinessResponse


class ProviderAdapter(ABC):
    """Base adapter that speaks Aurora business contracts only."""

    provider_name: str
    model_name: str
    supports_streaming: bool = False

    @abstractmethod
    def generate(self, request: BusinessRequest) -> BusinessResponse:
        """Generate a business response from a business request."""

