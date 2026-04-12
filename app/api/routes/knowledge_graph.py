from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_app_config, require_permission
from app.api.serializers import serialize_graph
from app.auth import AuthenticatedUser
from app.config import AppConfig
from app.services.knowledge_graph_service import build_filtered_knowledge_graph


router = APIRouter(prefix="/api/v1/knowledge-graph", tags=["knowledge-graph"])
alias_router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


@router.get("")
@alias_router.get("")
def get_knowledge_graph_view(
    theme: str | None = Query(default=None),
    file_type: str | None = Query(default=None, alias="type"),
    config: AppConfig = Depends(get_app_config),
    _user: AuthenticatedUser = Depends(require_permission("graph.read")),
):
    return serialize_graph(
        build_filtered_knowledge_graph(
            config,
            theme=theme,
            file_type=file_type,
        )
    )
