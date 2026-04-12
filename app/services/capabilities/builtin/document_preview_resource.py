"""Built-in document preview resource."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.services.capabilities.base import BaseResource
from app.services.capabilities.models import CapabilityContext, CapabilityDescriptor
from app.services.catalog_service import get_document_by_id
from app.services.document_materialization_service import load_materialized_document_preview
from app.services.document_service import read_document_preview_payload
from app.services.knowledge_access_policy import build_access_filter, can_access_document


class KBDocumentPreviewResource(BaseResource):
    """Read document previews through the same normalized path used by the UI."""

    descriptor = CapabilityDescriptor(
        name="kb.document_preview",
        capability_type="resource",
        display_name="Document Preview",
        description="Read structured preview content for one document.",
        read_only=True,
        concurrency_safe=True,
        allow_user_invoke=True,
        allow_model_invoke=True,
        routing_tags=("kb", "preview", "document"),
    )

    def read(
        self,
        selector: Mapping[str, Any],
        context: CapabilityContext,
    ):
        """Return one document preview payload.

        Structured materialized storage is preferred as the hot path. We only
        fall back to source-file preview when the active structured version does
        not exist yet, which keeps preview behavior consistent with current UI.
        """

        document_id = str(selector.get("document_id") or "").strip()
        if not document_id:
            raise ValueError("document_id is required for kb.document_preview")

        max_chars_raw = selector.get("max_chars", 3000)
        max_chars = int(max_chars_raw) if max_chars_raw not in {None, ""} else 3000
        document = get_document_by_id(self.config, document_id)
        if not document:
            raise FileNotFoundError("Document does not exist or has been removed.")
        access_filter = selector.get("access_filter") or build_access_filter(context)
        if not can_access_document(document, access_filter):
            raise PermissionError("You do not have permission to preview this document.")

        materialized_preview = load_materialized_document_preview(
            self.config,
            document=document,
            max_chars=max_chars,
        )
        if materialized_preview is not None:
            return materialized_preview

        return read_document_preview_payload(
            Path(document.path),
            max_chars=max_chars,
            document_id=document_id,
        )
