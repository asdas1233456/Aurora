"""Unified ETL pipeline for Aurora source documents."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from app.services.etl.models import ParsedDocument
from app.services.etl.parsers import (
    HTMLDocumentParser,
    PDFDocumentParser,
    SpreadsheetDocumentParser,
    TextDocumentParser,
    URLDocumentParser,
    WordDocumentParser,
)
from app.services.etl.parsers.base import DocumentParser
from app.services.etl.utils import resolve_relative_path


class ETLPipeline:
    """Resolve source parsers and normalize Aurora document ingestion."""

    def __init__(self, parsers: list[DocumentParser] | None = None) -> None:
        self._parsers = parsers or [
            PDFDocumentParser(),
            WordDocumentParser(),
            SpreadsheetDocumentParser(),
            HTMLDocumentParser(),
            URLDocumentParser(),
            TextDocumentParser(),
        ]

    def parse_file(
        self,
        file_path: str | Path,
        data_dir: Path,
        *,
        extra_metadata: Mapping[str, object] | None = None,
    ) -> ParsedDocument:
        """Parse one file into the Aurora normalized ETL contract."""
        resolved_file_path = Path(file_path).resolve(strict=False)
        parser = self._resolve_parser(resolved_file_path)
        relative_path = resolve_relative_path(resolved_file_path, data_dir)
        return parser.parse(
            file_path=resolved_file_path,
            relative_path=relative_path,
            extra_metadata=extra_metadata,
        )

    def _resolve_parser(self, file_path: Path) -> DocumentParser:
        suffix = file_path.suffix.lower()
        for parser in self._parsers:
            if suffix in parser.supported_extensions:
                return parser
        raise ValueError(f"Unsupported file type: {suffix}")
