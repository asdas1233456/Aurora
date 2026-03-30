from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_app_config
from app.api.logs import clear_application_logs, get_logs_summary, get_recent_logs
from app.config import AppConfig


router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


@router.get("")
def get_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    level: str = Query(default=""),
    keyword: str = Query(default=""),
    start_time: str = Query(default=""),
    end_time: str = Query(default=""),
    config: AppConfig = Depends(get_app_config),
):
    return {
        "summary": get_logs_summary(config),
        "filters": {
            "level": level,
            "keyword": keyword,
            "start_time": start_time,
            "end_time": end_time,
        },
        "lines": get_recent_logs(
            config,
            limit=limit,
            level=level,
            keyword=keyword,
            start_time=start_time,
            end_time=end_time,
        ),
    }


@router.delete("")
def delete_logs(config: AppConfig = Depends(get_app_config)):
    clear_application_logs(config)
    return {"message": "日志已清空。"}
