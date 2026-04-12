"""Parser protocol for Aurora ETL document loaders."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol

from app.services.etl.models import ParsedDocument


class DocumentParser(Protocol):
    """Protocol implemented by concrete ETL parsers."""

    parser_name: str
    supported_extensions: set[str]

    def parse(
        self,
        *,
        file_path: Path,
        relative_path: str,
        extra_metadata: Mapping[str, object] | None = None,
    ) -> ParsedDocument:
        """Parse a source file into a normalized Aurora document."""
