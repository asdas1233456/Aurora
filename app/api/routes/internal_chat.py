from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.internal_utils import (
    build_internal_request_context,
    ensure_internal_api,
    resolve_internal_identifier,
    serialize_request_context,
)
from app.api.serializers import serialize_chat_message_record, serialize_chat_session_record
from app.api.dependencies import get_runtime_config, require_internal_admin
from app.auth import AuthenticatedUser
from app.config import AppConfig
from app.schemas import ChatSessionRecord
from app.services.message_repository import MessageRepository
from app.services.session_recovery_service import SessionRecoveryService
from app.services.session_repository import SessionRepository


router = APIRouter(prefix="/api/v1/internal/chat", tags=["internal-chat"], include_in_schema=False)


@router.get("/sessions")
def list_chat_sessions(
    request: Request,
    tenant_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    runtime_config: AppConfig = Depends(get_runtime_config),
    _user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    resolved_tenant_id = resolve_internal_identifier(
        request,
        param_value=tenant_id,
        header_name="x-aurora-tenant-id",
        required=True,
        field_label="tenant_id",
    )
    resolved_user_id = resolve_internal_identifier(
        request,
        param_value=user_id,
        header_name="x-aurora-user-id",
    )
    resolved_project_id = resolve_internal_identifier(
        request,
        param_value=project_id,
        header_name="x-aurora-project-id",
    )
    normalized_status = str(status or "").strip() or None

    session_repository = SessionRepository(runtime_config)
    message_repository = MessageRepository(runtime_config)
    items = session_repository.list_sessions(
        tenant_id=resolved_tenant_id,
        user_id=resolved_user_id,
        project_id=resolved_project_id,
        status=normalized_status,
        limit=limit,
        offset=offset,
    )
    message_count_map = message_repository.count_by_session_ids(
        tenant_id=resolved_tenant_id,
        session_ids=[item.id for item in items],
    )

    return {
        "items": [
            {
                "session": serialize_chat_session_record(item),
                "message_count": message_count_map.get(item.id, 0),
            }
            for item in items
        ],
        "count": len(items),
        "filters": {
            "tenant_id": resolved_tenant_id,
            "user_id": resolved_user_id,
            "project_id": resolved_project_id,
            "status": normalized_status,
            "limit": limit,
            "offset": offset,
        },
    }


@router.get("/sessions/{session_id}")
def get_chat_session_detail(
    session_id: str,
    request: Request,
    tenant_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    runtime_config: AppConfig = Depends(get_runtime_config),
    _user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    resolved_tenant_id = resolve_internal_identifier(
        request,
        param_value=tenant_id,
        header_name="x-aurora-tenant-id",
        required=True,
        field_label="tenant_id",
    )
    resolved_session_id = resolve_internal_identifier(
        request,
        param_value=session_id,
        required=True,
        field_label="session_id",
    )
    resolved_user_id = resolve_internal_identifier(
        request,
        param_value=user_id,
        header_name="x-aurora-user-id",
    )
    resolved_project_id = resolve_internal_identifier(
        request,
        param_value=project_id,
        header_name="x-aurora-project-id",
    )

    session_repository = SessionRepository(runtime_config)
    message_repository = MessageRepository(runtime_config)
    session = session_repository.get_session(
        tenant_id=resolved_tenant_id,
        session_id=resolved_session_id,
    )
    if session is None or not _session_matches_filters(session, resolved_user_id, resolved_project_id):
        raise HTTPException(status_code=404, detail="Chat session not found.")

    return {
        "item": serialize_chat_session_record(session),
        "message_count": message_repository.count_by_session(
            tenant_id=resolved_tenant_id,
            session_id=resolved_session_id,
        ),
        "last_message": _serialize_optional_message(
            message_repository.get_latest_by_session(
                tenant_id=resolved_tenant_id,
                session_id=resolved_session_id,
            )
        ),
    }


@router.get("/sessions/{session_id}/recover")
def recover_chat_session(
    session_id: str,
    request: Request,
    tenant_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    request_id: str | None = None,
    message_limit: int = Query(default=12, ge=1, le=50),
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    resolved_tenant_id = resolve_internal_identifier(
        request,
        param_value=tenant_id,
        header_name="x-aurora-tenant-id",
        required=True,
        field_label="tenant_id",
    )
    resolved_session_id = resolve_internal_identifier(
        request,
        param_value=session_id,
        required=True,
        field_label="session_id",
    )
    resolved_user_id = resolve_internal_identifier(
        request,
        param_value=user_id,
        header_name="x-aurora-user-id",
    )
    resolved_project_id = resolve_internal_identifier(
        request,
        param_value=project_id,
        header_name="x-aurora-project-id",
    )

    session_repository = SessionRepository(runtime_config)
    message_repository = MessageRepository(runtime_config)
    recovery_service = SessionRecoveryService(
        runtime_config,
        session_repository=session_repository,
        message_repository=message_repository,
    )
    session = session_repository.get_session(
        tenant_id=resolved_tenant_id,
        session_id=resolved_session_id,
    )
    if session is None or not _session_matches_filters(session, resolved_user_id, resolved_project_id):
        raise HTTPException(status_code=404, detail="Chat session not found.")

    # Recovery always reuses the persisted session ownership to avoid depending on caller-supplied context.
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=session.tenant_id,
        user_id=session.user_id,
        project_id=session.project_id,
        session_id=session.id,
        request_id=request_id,
    )
    snapshot = recovery_service.recover_session(request_context, message_limit=message_limit)
    recovered_chat_history = recovery_service.build_recent_chat_history(
        snapshot,
        message_limit=message_limit,
    )

    return {
        "session": serialize_chat_session_record(session),
        "message_count": message_repository.count_by_session(
            tenant_id=session.tenant_id,
            session_id=session.id,
        ),
        "recent_messages": [serialize_chat_message_record(item) for item in snapshot.messages],
        "recovered_chat_history": recovered_chat_history,
        "restored_from_persistence": snapshot.restored_from_persistence,
        "message_limit": message_limit,
        "request_context": serialize_request_context(request_context),
    }


def _session_matches_filters(
    session: ChatSessionRecord,
    expected_user_id: str | None,
    expected_project_id: str | None,
) -> bool:
    if expected_user_id and session.user_id != expected_user_id:
        return False
    if expected_project_id and session.project_id != expected_project_id:
        return False
    return True


def _serialize_optional_message(message):
    if message is None:
        return None
    return serialize_chat_message_record(message)
