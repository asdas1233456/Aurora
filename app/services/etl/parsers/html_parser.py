"""HTML document parser for local HTML source files."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
import uuid

from app.services.etl.html_utils import extract_html_payload
from app.services.etl.models import ExtractedSegment, ParsedDocument


class HTMLDocumentParser:
    """Parse local HTML files into normalized Aurora ETL documents."""

    parser_name = "html_document_parser"
    supported_extensions = {".html", ".htm"}

    def parse(
        self,
        *,
        file_path: Path,
        relative_path: str,
        extra_metadata: Mapping[str, object] | None = None,
    ) -> ParsedDocument:
        """Parse one local HTML file."""
        source_id = uuid.uuid4().hex
        raw_html = file_path.read_text(encoding="utf-8", errors="ignore")
        title, plain_text, markdown_text = extract_html_payload(
            raw_html,
            default_title=file_path.stem or file_path.name,
        )
        if not plain_text:
            raise ValueError(f"Document is empty after parsing: {file_path.name}")

        segment = ExtractedSegment(
            segment_id=uuid.uuid4().hex,
            sequence=1,
            content_text=plain_text,
            content_markdown=markdown_text,
            metadata={
                "segment_kind": "web_page",
                "source_type": "html",
                "title": title,
            },
        )
        content_json = {
            "source_id": source_id,
            "file_name": file_path.name,
            "file_type": file_path.suffix.lower().lstrip("."),
            "parser_name": self.parser_name,
            "title": title,
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
            content_markdown=markdown_text,
            content_json=content_json,
            segments=[segment],
            metadata=dict(extra_metadata or {}),
        )
