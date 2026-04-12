"""Normalized ETL models shared by document parsers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ExtractedSegment:
    """A normalized source segment produced by the ETL pipeline.

    Attributes:
        segment_id: Stable UUID for the extracted source segment.
        sequence: Segment order within the source document.
        content_text: Plain-text content for downstream processing.
        content_markdown: Markdown-normalized content for retrieval and display.
        page_number: Source page number when available.
        metadata: Extra parser metadata kept with the segment.
    """

    segment_id: str
    sequence: int
    content_text: str
    content_markdown: str
    page_number: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serialize the segment into a JSON-friendly dict."""
        return {
            "segment_id": self.segment_id,
            "sequence": self.sequence,
            "content_text": self.content_text,
            "content_markdown": self.content_markdown,
            "page_number": self.page_number,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ParsedDocument:
    """Normalized ETL output for one source file."""

    source_id: str
    source_path: str
    relative_path: str
    file_name: str
    file_type: str
    parser_name: str
    content_markdown: str
    content_json: dict[str, object]
    segments: list[ExtractedSegment]
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def content_text(self) -> str:
        """Return the concatenated plain-text form of the parsed document."""
        return "\n\n".join(
            segment.content_text.strip()
            for segment in self.segments
            if segment.content_text.strip()
        ).strip()

    def to_dict(self) -> dict[str, object]:
        """Serialize the parsed document into a JSON-friendly dict."""
        return {
            "source_id": self.source_id,
            "source_path": self.source_path,
            "relative_path": self.relative_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "parser_name": self.parser_name,
            "content_markdown": self.content_markdown,
            "content_json": dict(self.content_json),
            "segments": [segment.to_dict() for segment in self.segments],
            "metadata": dict(self.metadata),
        }
