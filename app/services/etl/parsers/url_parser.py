"""URL parser for `.url` internet shortcut files."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse
import uuid

import requests

from app.services.etl.html_utils import extract_html_payload
from app.services.etl.models import ExtractedSegment, ParsedDocument
from app.services.etl.utils import normalize_text_block


class URLDocumentParser:
    """Parse `.url` files by fetching the target web content."""

    parser_name = "url_document_parser"
    supported_extensions = {".url"}

    def parse(
        self,
        *,
        file_path: Path,
        relative_path: str,
        extra_metadata: Mapping[str, object] | None = None,
    ) -> ParsedDocument:
        """Parse one `.url` internet shortcut file."""
        source_url = _read_url_from_shortcut(file_path)
        parsed_url = urlparse(source_url)
        if parsed_url.scheme not in {"http", "https"}:
            raise ValueError(f"Unsupported URL scheme for {file_path.name}: {parsed_url.scheme or 'missing'}")

        response = requests.get(
            source_url,
            headers={"User-Agent": "AuroraKnowledgeBot/1.0"},
            timeout=(5, 20),
        )
        response.raise_for_status()

        content_type = str(response.headers.get("Content-Type", "") or "").lower()
        if "html" in content_type or response.text.lstrip().startswith("<"):
            title, plain_text, markdown_text = extract_html_payload(
                response.text,
                default_title=response.url,
            )
        else:
            title = response.url
            plain_text = normalize_text_block(response.text)
            markdown_text = f"# {title}\n\n{plain_text}".strip()

        if not plain_text:
            raise ValueError(f"URL content is empty after parsing: {source_url}")

        source_id = uuid.uuid4().hex
        segment = ExtractedSegment(
            segment_id=uuid.uuid4().hex,
            sequence=1,
            content_text=plain_text,
            content_markdown=markdown_text,
            metadata={
                "segment_kind": "web_page",
                "source_type": "url",
                "source_url": source_url,
                "resolved_url": response.url,
                "content_type": content_type,
                "title": title,
            },
        )
        content_json = {
            "source_id": source_id,
            "file_name": file_path.name,
            "file_type": "url",
            "parser_name": self.parser_name,
            "source_url": source_url,
            "resolved_url": response.url,
            "title": title,
            "segment_count": 1,
            "segments": [segment.to_dict()],
        }
        return ParsedDocument(
            source_id=source_id,
            source_path=str(file_path),
            relative_path=relative_path,
            file_name=file_path.name,
            file_type="url",
            parser_name=self.parser_name,
            content_markdown=markdown_text,
            content_json=content_json,
            segments=[segment],
            metadata=dict(extra_metadata or {}),
        )


def _read_url_from_shortcut(file_path: Path) -> str:
    raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    for line in lines:
        if line.upper().startswith("URL="):
            return line.split("=", 1)[1].strip()
    if lines:
        return lines[0]
    raise ValueError(f"URL shortcut is empty: {file_path.name}")
