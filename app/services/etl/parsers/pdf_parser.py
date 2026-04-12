"""PDF parser backed by PyMuPDF with a pypdf fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
import logging
import uuid

from pypdf import PdfReader

from app.services.etl.models import ExtractedSegment, ParsedDocument
from app.services.etl.utils import normalize_text_block


logger = logging.getLogger(__name__)

try:
    import fitz
except ImportError:  # pragma: no cover - fallback path is exercised when PyMuPDF is unavailable.
    fitz = None


class PDFDocumentParser:
    """Parse PDF files into page-level normalized segments."""

    parser_name = "pymupdf_pdf_parser"
    supported_extensions = {".pdf"}

    def parse(
        self,
        *,
        file_path: Path,
        relative_path: str,
        extra_metadata: Mapping[str, object] | None = None,
    ) -> ParsedDocument:
        """Parse a PDF file into page-level normalized segments."""
        source_id = uuid.uuid4().hex
        pages = self.extract_pages(file_path)
        if not pages:
            raise ValueError(f"Document does not contain extractable text: {file_path.name}")

        segments: list[ExtractedSegment] = []
        markdown_sections = [f"# {file_path.name}"]
        for page_number, page_text in pages:
            normalized_text = normalize_text_block(page_text)
            if not normalized_text:
                continue

            markdown_text = f"## Page {page_number}\n\n{normalized_text}"
            markdown_sections.append(markdown_text)
            segments.append(
                ExtractedSegment(
                    segment_id=uuid.uuid4().hex,
                    sequence=len(segments) + 1,
                    content_text=normalized_text,
                    content_markdown=markdown_text,
                    page_number=page_number,
                    metadata={
                        "segment_kind": "page",
                        "source_type": "pdf",
                    },
                )
            )

        if not segments:
            raise ValueError(f"Document does not contain extractable text: {file_path.name}")

        content_json = {
            "source_id": source_id,
            "file_name": file_path.name,
            "file_type": "pdf",
            "parser_name": self._effective_parser_name(),
            "page_count": len(segments),
            "segments": [segment.to_dict() for segment in segments],
        }
        return ParsedDocument(
            source_id=source_id,
            source_path=str(file_path),
            relative_path=relative_path,
            file_name=file_path.name,
            file_type="pdf",
            parser_name=self._effective_parser_name(),
            content_markdown="\n\n".join(markdown_sections).strip(),
            content_json=content_json,
            segments=segments,
            metadata=dict(extra_metadata or {}),
        )

    def extract_pages(self, file_path: Path) -> list[tuple[int, str]]:
        """Extract page text using PyMuPDF first, then pypdf as a fallback."""
        if fitz is not None:
            try:
                with fitz.open(file_path) as document:
                    return [
                        (page.number + 1, page.get_text("text", sort=True))
                        for page in document
                    ]
            except Exception:
                logger.exception("PyMuPDF parsing failed for %s, falling back to pypdf.", file_path)

        reader = PdfReader(str(file_path))
        return [
            (index, page.extract_text() or "")
            for index, page in enumerate(reader.pages, start=1)
        ]

    def _effective_parser_name(self) -> str:
        return self.parser_name if fitz is not None else "pypdf_pdf_parser"
