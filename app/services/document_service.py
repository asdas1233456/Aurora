"""Document loading and source-file management."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from typing import Iterable

from llama_index.core.schema import Document
from pypdf import PdfReader

from app.config import SUPPORTED_EXTENSIONS
from app.schemas import DocumentDeleteResult, DocumentRenameResult, DocumentSummary


logger = logging.getLogger(__name__)

_PLAIN_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".sql"}


def list_source_files(data_dir: Path) -> list[Path]:
    """Return every supported source file under the data directory."""
    if not data_dir.exists():
        return []

    files = [
        path
        for path in data_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    sorted_files = sorted(files, key=lambda item: str(item).lower())
    logger.info("Scanned source directory with %s supported files.", len(sorted_files))
    return sorted_files


def save_uploaded_files(uploaded_files: Iterable[object], data_dir: Path) -> list[str]:
    """Save Streamlit-style uploaded files into the data directory."""
    data_dir.mkdir(parents=True, exist_ok=True)
    saved_names: list[str] = []

    for uploaded_file in uploaded_files:
        file_name = Path(getattr(uploaded_file, "name", "uploaded_file")).name
        _ensure_supported_file(file_name)
        target_path = data_dir / file_name

        with target_path.open("wb") as file_obj:
            file_obj.write(uploaded_file.getbuffer())

        saved_names.append(file_name)
        logger.info("Saved uploaded document: %s", target_path)

    return saved_names


def save_raw_files(files: Iterable[tuple[str, bytes]], data_dir: Path) -> list[str]:
    """Save raw file payloads from the REST API into the data directory."""
    data_dir.mkdir(parents=True, exist_ok=True)
    saved_names: list[str] = []

    for file_name, content in files:
        safe_name = Path(file_name).name
        _ensure_supported_file(safe_name)
        target_path = data_dir / safe_name
        target_path.write_bytes(content)
        saved_names.append(safe_name)
        logger.info("Saved raw uploaded document: %s", target_path)

    return saved_names


def load_documents(data_dir: Path) -> list[Document]:
    """Load every supported source document from the data directory."""
    source_files = list_source_files(data_dir)
    if not source_files:
        raise ValueError(
            "data/ directory does not contain supported documents. "
            f"Please add files with extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    return load_documents_from_paths(source_files, data_dir)


def load_documents_from_paths(
    file_paths: Iterable[str | Path],
    data_dir: Path,
    *,
    metadata_by_path: dict[str, dict[str, object]] | None = None,
) -> list[Document]:
    """Load specific source files and normalize their metadata for indexing."""
    normalized_paths = [Path(file_path).resolve(strict=False) for file_path in file_paths]
    if not normalized_paths:
        return []

    metadata_by_path = metadata_by_path or {}
    documents: list[Document] = []
    resolved_data_dir = data_dir.resolve(strict=False)

    for file_path in normalized_paths:
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"Document does not exist: {file_path}")

        try:
            content = _read_document_content(file_path)
        except Exception as exc:
            logger.exception("Document parsing failed for %s.", file_path)
            raise RuntimeError(f"Document parsing failed for {file_path.name}: {exc}") from exc

        absolute_path = str(file_path)
        relative_path = (
            file_path.relative_to(resolved_data_dir).as_posix()
            if _is_under_directory(file_path, data_dir)
            else file_path.name
        )
        extra_metadata = metadata_by_path.get(absolute_path, {})
        metadata = {
            "file_path": absolute_path,
            "file_name": file_path.name,
            "document_id": str(extra_metadata.get("document_id", "")),
            "source_file": file_path.name,
            "source_path": absolute_path,
            "relative_path": relative_path,
            "theme": str(extra_metadata.get("theme", "")),
            "tags": list(extra_metadata.get("tags", []) or []),
        }
        documents.append(Document(text=content, metadata=metadata, id_=absolute_path))

    logger.info("Loaded %s documents for indexing.", len(documents))
    return documents


def get_document_summaries(data_dir: Path) -> list[DocumentSummary]:
    """Return source document summaries for UI and API responses."""
    summaries: list[DocumentSummary] = []
    resolved_data_dir = data_dir.resolve(strict=False)
    for file_path in list_source_files(data_dir):
        stat_result = file_path.stat()
        summaries.append(
            DocumentSummary(
                document_id="",
                name=file_path.name,
                path=str(file_path.resolve(strict=False)),
                relative_path=file_path.resolve(strict=False).relative_to(resolved_data_dir).as_posix(),
                extension=file_path.suffix.lower().lstrip("."),
                size_bytes=stat_result.st_size,
                updated_at=_format_timestamp(stat_result.st_mtime),
                status="pending",
                theme="",
                tags=[],
            )
        )

    return summaries


def delete_documents(file_paths: Iterable[str | Path], data_dir: Path) -> DocumentDeleteResult:
    """Delete selected source files from the data directory."""
    deleted_paths: list[str] = []
    missing_paths: list[str] = []

    for file_path in file_paths:
        resolved_path = _resolve_data_file_path(Path(file_path), data_dir)
        if resolved_path is None or not resolved_path.exists() or not resolved_path.is_file():
            missing_paths.append(str(file_path))
            continue

        resolved_path.unlink()
        deleted_paths.append(str(resolved_path))
        logger.info("Deleted source document: %s", resolved_path)

    return DocumentDeleteResult(
        deleted_ids=[],
        deleted_paths=deleted_paths,
        missing_ids=[],
        missing_paths=missing_paths,
    )


def rename_document(file_path: str | Path, new_name: str, data_dir: Path) -> DocumentRenameResult:
    """Rename one source file inside the data directory."""
    resolved_path = _resolve_data_file_path(Path(file_path), data_dir)
    if resolved_path is None or not resolved_path.exists() or not resolved_path.is_file():
        raise FileNotFoundError(f"Document does not exist: {file_path}")

    sanitized_name = Path(new_name).name.strip()
    if not sanitized_name:
        raise ValueError("New file name cannot be empty.")
    _ensure_supported_file(sanitized_name)

    target_path = resolved_path.with_name(sanitized_name)
    resolved_target = _resolve_data_file_path(target_path, data_dir)
    if resolved_target is None:
        raise ValueError("Target file name is invalid.")
    if resolved_target.exists() and resolved_target != resolved_path:
        raise FileExistsError(f"Target file already exists: {sanitized_name}")

    resolved_path.rename(resolved_target)
    logger.info("Renamed source document: %s -> %s", resolved_path, resolved_target)
    return DocumentRenameResult(
        document_id="",
        old_path=str(resolved_path),
        new_path=str(resolved_target),
        old_relative_path=resolved_path.resolve(strict=False).relative_to(data_dir.resolve(strict=False)).as_posix(),
        new_relative_path=resolved_target.resolve(strict=False).relative_to(data_dir.resolve(strict=False)).as_posix(),
        new_name=resolved_target.name,
    )


def read_document_preview(file_path: Path, max_chars: int = 3000) -> str:
    """Read a preview for one supported source document."""
    suffix = file_path.suffix.lower()

    if suffix in _PLAIN_TEXT_EXTENSIONS:
        return file_path.read_text(encoding="utf-8", errors="ignore")[:max_chars]

    if suffix == ".pdf":
        return _read_pdf_text(file_path, max_pages=3)[:max_chars]

    return "Preview is not available for this file type yet."


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _ensure_supported_file(file_name: str) -> None:
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {suffix}. Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )


def _resolve_data_file_path(file_path: Path, data_dir: Path) -> Path | None:
    """Normalize a path into the data directory and prevent directory traversal."""
    candidate = file_path if file_path.is_absolute() else data_dir / file_path

    try:
        resolved_candidate = candidate.resolve(strict=False)
        resolved_data_dir = data_dir.resolve(strict=False)
    except OSError:
        return None

    if resolved_candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None

    if resolved_candidate != resolved_data_dir and resolved_data_dir not in resolved_candidate.parents:
        return None

    return resolved_candidate


def _is_under_directory(path: Path, directory: Path) -> bool:
    try:
        resolved_path = path.resolve(strict=False)
        resolved_directory = directory.resolve(strict=False)
    except OSError:
        return False
    return resolved_path == resolved_directory or resolved_directory in resolved_path.parents


def _read_document_content(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in _PLAIN_TEXT_EXTENSIONS:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        return _read_pdf_text(file_path)
    raise ValueError(f"Unsupported file type: {suffix}")


def _read_pdf_text(file_path: Path, *, max_pages: int | None = None) -> str:
    reader = PdfReader(str(file_path))
    pages = reader.pages[: max_pages] if max_pages is not None else reader.pages
    extracted_pages: list[str] = []
    for page in pages:
        extracted_pages.append(page.extract_text() or "")
    return "\n".join(extracted_pages)
