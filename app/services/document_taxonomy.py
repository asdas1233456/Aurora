"""文档主题推断工具。"""

from __future__ import annotations


def infer_document_category(file_name: str) -> str:
    """从文件名推断知识主题。"""
    stem = file_name.rsplit(".", maxsplit=1)[0]
    if "_" in stem:
        stem = stem.split("_", maxsplit=1)[1] if stem.split("_", maxsplit=1)[0].isdigit() else stem

    normalized = stem.replace("-", " ").replace("_", " ").strip()
    if not normalized:
        return "Uncategorized"

    words = [word for word in normalized.split() if word]
    if not words:
        return "Uncategorized"

    return " ".join(word.capitalize() for word in words[:3])
