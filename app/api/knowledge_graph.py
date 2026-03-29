"""知识图谱相关内部 API。"""

from __future__ import annotations

from app.config import AppConfig
from app.services.knowledge_graph_service import build_knowledge_graph


def get_knowledge_graph(config: AppConfig):
    """返回知识图谱数据。"""
    return build_knowledge_graph(config)
