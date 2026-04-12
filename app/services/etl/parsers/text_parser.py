"""Text-like document parser for the Aurora ETL pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
import uuid

from app.services.etl.models import ExtractedSegment, ParsedDocument
from app.services.etl.utils import normalize_text_block


class TextDocumentParser:
    """Parse plain-text style documents into the normalized ETL contract."""

    parser_name = "text_document_parser"
    supported_extensions = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".sql"}

    def parse(
        self,
        *,
        file_path: Path,
        relative_path: str,
        extra_metadata: Mapping[str, object] | None = None,
    ) -> ParsedDocument:
        """Parse a text-like file into one normalized source segment.

        Args:
            file_path: Absolute source file path.
            relative_path: Source path relative to the Aurora data directory.
            extra_metadata: Additional metadata reserved for higher layers.

        Returns:
            ParsedDocument: Normalized ETL output.

        Raises:
            ValueError: If the file content is empty after normalization.
        """
        raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
        normalized_text = normalize_text_block(raw_text)
        if not normalized_text:
            raise ValueError(f"Document is empty after parsing: {file_path.name}")

        source_id = uuid.uuid4().hex
        segment = ExtractedSegment(
            segment_id=uuid.uuid4().hex,
            sequence=1,
            content_text=normalized_text,
            content_markdown=normalized_text,
            metadata={
                "segment_kind": "document",
                "source_type": "text",
            },
        )

        content_json = {
            "source_id": source_id,
            "file_name": file_path.name,
            "file_type": file_path.suffix.lower().lstrip("."),
            "parser_name": self.parser_name,
            "segment_count": 1,
            "segments": [segment.to_dict()],
        }
        return ParsedDocument(
            source_id=source_id,
            source_path=str(file_path),
            relative_path=relative_path,
            file_name=file_path.name,
            file_type=file_path.suffix.lower().lstrip("."),
            parser_name=self.parser_name,
            content_markdown=normalized_text,
            content_json=content_json,
            segments=[segment],
            metadata=dict(extra_metadata or {}),
        )
