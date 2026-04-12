from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_app_config, require_permission
from app.api.logs import clear_application_logs, get_logs_summary, get_recent_logs
from app.api.security import audit_app_event, concurrency_slot, enforce_rate_limit, make_request_context
from app.auth import AuthenticatedUser
from app.config import AppConfig


router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


@router.get("")
def get_logs(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    level: str = Query(default=""),
    keyword: str = Query(default=""),
    start_time: str = Query(default=""),
    end_time: str = Query(default=""),
    config: AppConfig = Depends(get_app_config),
    user: AuthenticatedUser = Depends(require_permission("logs.read")),
):
    request_context = make_request_context(request, config, user, actor_role="system")
    enforce_rate_limit(
        config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="log_read",
        target_type="logs",
    )
    with concurrency_slot(
        config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="log_read",
        target_type="logs",
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
def delete_logs(
    request: Request,
    config: AppConfig = Depends(get_app_config),
    user: AuthenticatedUser = Depends(require_permission("logs.clear")),
):
    request_context = make_request_context(request, config, user, actor_role="system")
    enforce_rate_limit(
        config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="log_clear",
        target_type="logs",
    )
    clear_application_logs(config)
    audit_app_event(
        config,
        user=user,
        action="logs.clear",
        outcome="succeeded",
        request_context=request_context,
        target_type="logs",
    )
    return {"message": "日志已清空。"}
