"""Built-in knowledge-base rebuild command."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.capabilities.base import BaseCommand
from app.services.capabilities.models import CapabilityContext, CapabilityDescriptor
from app.services.knowledge_base_job_service import start_rebuild_job


class KBRebuildCommand(BaseCommand):
    """Expose the existing rebuild job service as a command capability."""

    descriptor = CapabilityDescriptor(
        name="kb.rebuild",
        capability_type="command",
        display_name="Rebuild Knowledge Base",
        description="Start a background knowledge-base rebuild job.",
        read_only=False,
        concurrency_safe=False,
        allow_user_invoke=True,
        allow_model_invoke=False,
        routing_tags=("kb", "index", "job"),
    )

    def invoke(
        self,
        payload: Mapping[str, Any],
        context: CapabilityContext,
    ):
        """Start one rebuild job.

        The command keeps all rebuild orchestration in `knowledge_base_job_service`
        so the new capability layer does not duplicate job-state logic.
        """

        mode = str(payload.get("mode", "sync") or "sync").strip().lower() or "sync"
        return start_rebuild_job(self.config, mode=mode)
