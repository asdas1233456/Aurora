"""Backward-compatible alias for the OpenAI-compatible adapter."""

from __future__ import annotations

from app.providers.openai_compatible_adapter import OpenAICompatibleAdapter


OpenAIAdapter = OpenAICompatibleAdapter

__all__ = ["OpenAIAdapter", "OpenAICompatibleAdapter"]
