"""Built-in Aurora capabilities registered in Phase 1."""

from typing import TYPE_CHECKING

from app.services.capabilities.builtin.document_preview_resource import KBDocumentPreviewResource
from app.services.capabilities.builtin.kb_rebuild_command import KBRebuildCommand
from app.services.capabilities.builtin.rag_query_tool import KBRetrieveTool

if TYPE_CHECKING:
    from app.services.capabilities.registry import CapabilityRegistry


def register_builtin_capabilities(registry: "CapabilityRegistry") -> None:
    """Register built-in Aurora capabilities into the supplied registry."""
    registry.register(KBRetrieveTool.descriptor, lambda config: KBRetrieveTool(config))
    registry.register(KBRebuildCommand.descriptor, lambda config: KBRebuildCommand(config))
    registry.register(KBDocumentPreviewResource.descriptor, lambda config: KBDocumentPreviewResource(config))


__all__ = [
    "KBDocumentPreviewResource",
    "KBRebuildCommand",
    "KBRetrieveTool",
    "register_builtin_capabilities",
]
