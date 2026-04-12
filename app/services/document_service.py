"""Document loading and source-file management."""

from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Iterable

from llama_index.core.schema import Document

from app.config import AppConfig, SUPPORTED_EXTENSIONS
from app.schemas import (
    DocumentDeleteResult,
    DocumentPreviewMetadata,
    DocumentPreviewPayload,
    DocumentRenameResult,
    DocumentSummary,
)
from app.services.etl import ETLPipeline, ParsedDocument
from app.services.etl.parsers.pdf_parser import PDFDocumentParser
from app.services.etl.utils import normalize_text_block


logger = logging.getLogger(__name__)

_PLAIN_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".sql"}
_ETL_PIPELINE = ETLPipeline()
_PDF_PARSER = PDFDocumentParser()


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


def quarantine_rejected_upload(
    *,
    file_name: str,
    content: bytes,
    reason: str,
    config: AppConfig,
    content_type: str = "",
) -> None:
    """Store rejected uploads outside the active knowledge base for later inspection."""
    if not config.upload_quarantine_enabled:
        return

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    safe_name = Path(file_name).name or f"upload-{timestamp}.bin"
    quarantine_name = f"{timestamp}-{safe_name}"
    target_path = config.upload_quarantine_dir / quarantine_name
    metadata_path = target_path.with_suffix(target_path.suffix + ".json")

    try:
        config.upload_quarantine_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        metadata_path.write_text(
            json.dumps(
                {
                    "file_name": safe_name,
                    "reason": str(reason or "").strip() or "rejected",
                    "content_type": str(content_type or "").strip(),
                    "size_bytes": len(content),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        logger.warning("Failed to quarantine rejected upload %s.", safe_name, exc_info=True)


def load_documents(data_dir: Path) -> list[Document]:
    """Load every supported source document from the data directory.

    PDF files are normalized into page-level `Document` objects so later retrieval
    can preserve page metadata for citations.
    """
    source_files = list_source_files(data_dir)
    if not source_files:
        raise ValueError(
            "data/ directory does not contain supported documents. "
            f"Please add files with extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    return load_documents_from_paths(source_files, data_dir)


def load_parsed_documents_from_paths(
    file_paths: Iterable[str | Path],
    data_dir: Path,
    *,
    metadata_by_path: dict[str, dict[str, object]] | None = None,
) -> list[ParsedDocument]:
    """Parse specific source files into the normalized Aurora ETL contract."""
    normalized_paths = [Path(file_path).resolve(strict=False) for file_path in file_paths]
    if not normalized_paths:
        return []

    metadata_by_path = metadata_by_path or {}
    parsed_documents: list[ParsedDocument] = []

    for file_path in normalized_paths:
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"Document does not exist: {file_path}")

        try:
            extra_metadata = metadata_by_path.get(str(file_path), {})
            parsed_documents.append(
                _ETL_PIPELINE.parse_file(
                    file_path=file_path,
                    data_dir=data_dir,
                    extra_metadata=extra_metadata,
                )
            )
        except Exception as exc:
            logger.exception("Document parsing failed for %s.", file_path)
            raise RuntimeError(f"Document parsing failed for {file_path.name}: {exc}") from exc

    return parsed_documents


def load_documents_from_paths(
    file_paths: Iterable[str | Path],
    data_dir: Path,
    *,
    metadata_by_path: dict[str, dict[str, object]] | None = None,
) -> list[Document]:
    """Load specific source files and normalize their metadata for indexing."""
    parsed_documents = load_parsed_documents_from_paths(
        file_paths,
        data_dir,
        metadata_by_path=metadata_by_path,
    )
    documents = build_llama_documents_from_parsed_documents(parsed_documents)

    logger.info(
        "Loaded %s source files into %s normalized documents for indexing.",
        len(parsed_documents),
        len(documents),
    )
    return documents


def build_llama_documents_from_parsed_documents(
    parsed_documents: Iterable[ParsedDocument],
) -> list[Document]:
    """Convert normalized parsed documents into LlamaIndex `Document` objects."""
    documents: list[Document] = []
    for parsed_document in parsed_documents:
        documents.extend(_build_llama_documents(parsed_document))
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
                is_public=True,
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
    return read_document_preview_payload(file_path, max_chars=max_chars).preview


def read_document_preview_payload(
    file_path: Path,
    max_chars: int = 3000,
    *,
    document_id: str = "",
) -> DocumentPreviewPayload:
    """Read a preview plus structured ETL metadata for one source document."""
    suffix = file_path.suffix.lower()

    if suffix in _PLAIN_TEXT_EXTENSIONS:
        return DocumentPreviewPayload(
            document_id=document_id,
            preview=file_path.read_text(encoding="utf-8", errors="ignore")[:max_chars],
            metadata=DocumentPreviewMetadata(
                file_type=suffix.lstrip("."),
                parser_name="plain_text_reader",
                segment_count=1,
            ),
        )

    if suffix in SUPPORTED_EXTENSIONS:
        parsed_document = _ETL_PIPELINE.parse_file(file_path, data_dir=file_path.parent)
        preview_text = parsed_document.content_markdown or parsed_document.content_text
        return DocumentPreviewPayload(
            document_id=document_id,
            preview=preview_text[:max_chars],
            metadata=build_document_preview_metadata(parsed_document),
        )

    return DocumentPreviewPayload(
        document_id=document_id,
        preview="Preview is not available for this file type yet.",
        metadata=DocumentPreviewMetadata(
            file_type=suffix.lstrip("."),
            parser_name="unsupported_preview_reader",
        ),
    )


def build_document_preview_metadata(parsed_document: ParsedDocument) -> DocumentPreviewMetadata:
    """Build structured preview metadata from one parsed ETL document."""
    content_json = dict(parsed_document.content_json or {})
    page_numbers = _collect_page_numbers(parsed_document)
    sheet_names = _collect_sheet_names(parsed_document)

    return DocumentPreviewMetadata(
        file_type=parsed_document.file_type,
        parser_name=parsed_document.parser_name,
        source_document_id=parsed_document.source_id,
        segment_count=len(parsed_document.segments),
        title=_coerce_text(content_json.get("title")) or _first_segment_metadata_value(parsed_document, "title"),
        source_url=_coerce_text(content_json.get("source_url")) or _first_segment_metadata_value(parsed_document, "source_url"),
        resolved_url=_coerce_text(content_json.get("resolved_url")) or _first_segment_metadata_value(parsed_document, "resolved_url"),
        content_type=_coerce_text(content_json.get("content_type")) or _first_segment_metadata_value(parsed_document, "content_type"),
        page_count=_coerce_positive_int(content_json.get("page_count")) or len(page_numbers),
        page_numbers=page_numbers,
        sheet_count=_coerce_positive_int(content_json.get("sheet_count")) or len(sheet_names),
        sheet_names=sheet_names,
    )


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
        return normalize_text_block(file_path.read_text(encoding="utf-8", errors="ignore"))
    if suffix in SUPPORTED_EXTENSIONS:
        parsed_document = _ETL_PIPELINE.parse_file(file_path, data_dir=file_path.parent)
        return normalize_text_block(parsed_document.content_markdown or parsed_document.content_text)
    raise ValueError(f"Unsupported file type: {suffix}")


def _read_pdf_text(file_path: Path, *, max_pages: int | None = None) -> str:
    pages = _PDF_PARSER.extract_pages(file_path)
    if max_pages is not None:
        pages = pages[:max_pages]
    extracted_pages = [
        normalize_text_block(page_text)
        for _, page_text in pages
        if normalize_text_block(page_text)
    ]
    return "\n\n".join(extracted_pages)


def _build_llama_documents(parsed_document: ParsedDocument) -> list[Document]:
    base_metadata = _build_base_metadata(parsed_document)
    documents: list[Document] = []

    for segment in parsed_document.segments:
        segment_metadata = dict(base_metadata)
        segment_metadata["source_segment_id"] = segment.segment_id
        segment_metadata["segment_index"] = segment.sequence
        segment_metadata["segment_kind"] = str(segment.metadata.get("segment_kind", "document"))
        segment_metadata["source_type"] = str(
            segment.metadata.get("source_type", parsed_document.file_type)
        )
        if segment.page_number is not None:
            segment_metadata["page_number"] = segment.page_number
        for metadata_key in ("sheet_name", "source_url", "resolved_url", "title", "content_type"):
            metadata_value = segment.metadata.get(metadata_key)
            if metadata_value is None or metadata_value == "":
                continue
            segment_metadata[metadata_key] = metadata_value

        documents.append(
            Document(
                text=segment.content_markdown or segment.content_text,
                metadata=segment_metadata,
                id_=segment.segment_id,
            )
        )

    return documents


def _build_base_metadata(parsed_document: ParsedDocument) -> dict[str, object]:
    extra_metadata = parsed_document.metadata
    owner_user_id = str(
        extra_metadata.get("owner_user_id") or extra_metadata.get("user_id") or ""
    ).strip()
    metadata = {
        "file_path": parsed_document.source_path,
        "file_name": parsed_document.file_name,
        "document_id": str(extra_metadata.get("document_id", "")),
        "source_file": parsed_document.file_name,
        "source_path": parsed_document.source_path,
        "relative_path": parsed_document.relative_path,
        "theme": str(extra_metadata.get("theme", "")),
        "tags": list(extra_metadata.get("tags", []) or []),
        "parser_name": parsed_document.parser_name,
        "file_type": parsed_document.file_type,
        "source_document_id": parsed_document.source_id,
        # These access fields are always written so vector/local indexes can
        # filter without depending on optional JSON metadata at query time.
        "tenant_id": str(extra_metadata.get("tenant_id", "") or ""),
        "owner_user_id": owner_user_id,
        "user_id": owner_user_id,
        "department_id": str(extra_metadata.get("department_id", "") or ""),
        "is_public": bool(extra_metadata.get("is_public", True)),
    }

    return metadata


def _collect_page_numbers(parsed_document: ParsedDocument) -> list[int]:
    page_numbers: list[int] = []
    seen: set[int] = set()
    for segment in parsed_document.segments:
        page_number = segment.page_number
        if page_number is None or page_number <= 0 or page_number in seen:
            continue
        seen.add(page_number)
        page_numbers.append(page_number)
    return page_numbers


def _collect_sheet_names(parsed_document: ParsedDocument) -> list[str]:
    sheet_names: list[str] = []
    seen: set[str] = set()
    for segment in parsed_document.segments:
        sheet_name = normalize_text_block(str(segment.metadata.get("sheet_name", "") or ""))
        if not sheet_name or sheet_name in seen:
            continue
        seen.add(sheet_name)
        sheet_names.append(sheet_name)
    return sheet_names


def _first_segment_metadata_value(parsed_document: ParsedDocument, key: str) -> str:
    for segment in parsed_document.segments:
        value = _coerce_text(segment.metadata.get(key))
        if value:
            return value
    return ""


def _coerce_positive_int(value: object) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return normalized if normalized > 0 else 0


def _coerce_text(value: object) -> str:
    text = normalize_text_block("" if value is None else str(value))
    return text
