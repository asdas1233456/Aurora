from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_config
from app.api.knowledge_graph import get_knowledge_graph
from app.api.serializers import serialize_graph
from app.config import AppConfig


router = APIRouter(prefix="/api/v1/knowledge-graph", tags=["knowledge-graph"])


@router.get("")
def get_knowledge_graph_view(config: AppConfig = Depends(get_app_config)):
    return serialize_graph(get_knowledge_graph(config))
