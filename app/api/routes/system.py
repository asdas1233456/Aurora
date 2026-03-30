from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_runtime_config
from app.api.serializers import serialize_overview, serialize_workspace_bootstrap
from app.api.system import get_bootstrap, get_overview
from app.config import AppConfig


router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/overview")
def get_system_overview(runtime_config: AppConfig = Depends(get_runtime_config)):
    return serialize_overview(get_overview(runtime_config))


@router.get("/bootstrap")
def get_system_bootstrap(runtime_config: AppConfig = Depends(get_runtime_config)):
    return serialize_workspace_bootstrap(get_bootstrap(runtime_config))
