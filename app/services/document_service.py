"""文档加载与上传保存模块。"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from typing import Iterable

from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document
from pypdf import PdfReader

from app.config import SUPPORTED_EXTENSIONS
from app.schemas import DocumentSummary


logger = logging.getLogger(__name__)


def list_source_files(data_dir: Path) -> list[Path]:
    """列出 data/ 目录下所有受支持的文件。"""
    if not data_dir.exists():
        return []

    files = [
        path
        for path in data_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    sorted_files = sorted(files, key=lambda item: str(item).lower())
    logger.info("扫描文档目录完成，共发现 %s 个文件。", len(sorted_files))
    return sorted_files


def save_uploaded_files(uploaded_files: Iterable[object], data_dir: Path) -> list[str]:
    """把 Streamlit 上传的文件写入 data/ 目录。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    saved_names: list[str] = []

    for uploaded_file in uploaded_files:
        file_name = Path(getattr(uploaded_file, "name", "uploaded_file")).name
        _ensure_supported_file(file_name)
        target_path = data_dir / file_name

        with target_path.open("wb") as file_obj:
            file_obj.write(uploaded_file.getbuffer())

        saved_names.append(file_name)
        logger.info("保存上传文件成功: %s", target_path)

    return saved_names


def save_raw_files(files: Iterable[tuple[str, bytes]], data_dir: Path) -> list[str]:
    """保存原始字节文件，供 REST API 上传场景复用。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    saved_names: list[str] = []

    for file_name, content in files:
        safe_name = Path(file_name).name
        _ensure_supported_file(safe_name)
        target_path = data_dir / safe_name
        target_path.write_bytes(content)
        saved_names.append(safe_name)
        logger.info("保存原始上传文件成功: %s", target_path)

    return saved_names


def load_documents(data_dir: Path) -> list[Document]:
    """读取 data/ 目录中的文档，并补充统一的元数据字段。"""
    if not data_dir.exists():
        raise FileNotFoundError(f"文档目录不存在：{data_dir}")

    source_files = list_source_files(data_dir)
    if not source_files:
        raise ValueError("data/ 目录中没有可用文档，请先上传或放入 pdf/txt/md 文件。")

    try:
        reader = SimpleDirectoryReader(
            input_files=[str(file_path) for file_path in source_files],
            filename_as_id=True,
        )
        documents = reader.load_data()
    except Exception as exc:
        logger.exception("文档解析失败。")
        raise RuntimeError(f"文档解析失败，请检查文件格式或内容是否异常：{exc}") from exc

    for document in documents:
        metadata = document.metadata or {}

        file_path_value = str(metadata.get("file_path", metadata.get("file_name", "")))
        source_file = Path(file_path_value).name if file_path_value else "未知文件"

        metadata["source_file"] = source_file
        metadata["source_path"] = file_path_value or source_file
        document.metadata = metadata

    logger.info("文档加载完成，共生成 %s 个 Document 对象。", len(documents))
    return documents


def get_document_summaries(data_dir: Path) -> list[DocumentSummary]:
    """返回文档摘要列表，用于页面和 API 展示。"""
    summaries: list[DocumentSummary] = []
    for file_path in list_source_files(data_dir):
        stat_result = file_path.stat()
        summaries.append(
            DocumentSummary(
                name=file_path.name,
                path=str(file_path),
                extension=file_path.suffix.lower().lstrip("."),
                size_bytes=stat_result.st_size,
                updated_at=_format_timestamp(stat_result.st_mtime),
            )
        )

    return summaries


def read_document_preview(file_path: Path, max_chars: int = 3000) -> str:
    """读取文档预览内容。"""
    suffix = file_path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")[:max_chars]

    if suffix == ".pdf":
        reader = PdfReader(str(file_path))
        pages_text: list[str] = []
        for page in reader.pages[: min(len(reader.pages), 3)]:
            pages_text.append(page.extract_text() or "")
        return "\n".join(pages_text)[:max_chars]

    return "当前文件类型暂不支持预览。"


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _ensure_supported_file(file_name: str) -> None:
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型：{suffix}，仅支持 {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
