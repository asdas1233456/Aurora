"""Utility helpers for normalized ETL parsing."""

from __future__ import annotations

from pathlib import Path
import re


_EXCESSIVE_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")


def normalize_text_block(text: str) -> str:
    """Normalize whitespace without destroying meaningful line structure."""
    normalized_lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").split("\n")]
    normalized_text = "\n".join(normalized_lines).strip()
    return _EXCESSIVE_BLANK_LINES_PATTERN.sub("\n\n", normalized_text)


def resolve_relative_path(file_path: Path, data_dir: Path) -> str:
    """Resolve a safe relative path for the source file."""
    resolved_file_path = file_path.resolve(strict=False)
    resolved_data_dir = data_dir.resolve(strict=False)

    if resolved_file_path == resolved_data_dir or resolved_data_dir in resolved_file_path.parents:
        return resolved_file_path.relative_to(resolved_data_dir).as_posix()
    return file_path.name
