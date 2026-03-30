from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_runtime_config
from app.api.internal_utils import (
    build_internal_request_context,
    ensure_internal_api,
    serialize_request_context,
)
from app.api.request_models import ProviderDryRunModel, ProviderResolveModel
from app.api.serializers import (
    serialize_business_request,
    serialize_business_response,
    serialize_memory_retrieval_bundle,
)
from app.config import AppConfig, _normalize_provider
from app.providers.factory import ProviderFactory
from app.providers.registry import build_default_provider_registry
from app.services.capability_guard import CapabilityGuard
from app.services.memory.governance.memory_scope import ScopeResolver
from app.services.memory.read.memory_retriever import MemoryRetriever
from app.services.rag_service import build_business_request
from app.services.retrieval_service import retrieve_chunks


router = APIRouter(prefix="/api/v1/internal/providers", tags=["internal-providers"], include_in_schema=False)


@router.get("")
def list_registered_providers(request: Request):
    ensure_internal_api(request)
    registry = build_default_provider_registry()
    items = registry.describe()
    return {
        "items": items,
        "count": len(items),
    }


@router.post("/resolve")
def resolve_provider(
    request: Request,
    payload: ProviderResolveModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
):
    ensure_internal_api(request)
    registry = build_default_provider_registry()
    effective_config = _build_provider_runtime_config(runtime_config, payload.provider, payload.model)
    resolved = _resolve_provider_info(effective_config, registry)
    return resolved


@router.post("/dry-run")
def dry_run_provider_generation(
    request: Request,
    payload: ProviderDryRunModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
):
    ensure_internal_api(request)
    registry = build_default_provider_registry()
    effective_config = _build_provider_runtime_config(runtime_config, payload.provider, payload.model)
    request_context = build_internal_request_context(
        request,
        effective_config,
        tenant_id=payload.tenant_id,
        user_id=payload.user_id,
        project_id=payload.project_id,
        session_id=payload.session_id,
        request_id=payload.request_id,
        team_id=payload.team_id,
        global_scope_id=payload.global_scope_id,
    )
    chat_history = [item.model_dump() for item in payload.chat_history]
    # Dry-run stays read-only with respect to chat persistence so provider validation
    # does not silently depend on third-feature session storage or recovery behavior.
    scope_resolver = ScopeResolver()
    resolved_context = scope_resolver.resolve(request_context)
    memory_bundle = MemoryRetriever(
        effective_config,
        scope_resolver=scope_resolver,
    ).retrieve_bundle(
        resolved_context,
        scene=payload.scene,
        user_query=payload.question,
        top_k=payload.top_k or effective_config.default_top_k,
        retrieval_metadata={"request_id": request_context.request_id, "dry_run": True},
    )
    retrieved_chunks, retrieval_query, rewritten_question = retrieve_chunks(
        question=payload.question,
        config=effective_config,
        top_k=payload.top_k,
        chat_history=chat_history,
    )
    business_request = build_business_request(
        question=payload.question,
        chat_history=chat_history,
        retrieved_chunks=retrieved_chunks,
        memory_context=memory_bundle.memory_context,
        config=effective_config,
        retrieval_query=retrieval_query,
        rewritten_question=rewritten_question,
        scene=payload.scene or "",
        requested_top_k=payload.top_k,
    )

    adapter = ProviderFactory(effective_config, registry=registry).create()
    business_response = CapabilityGuard().generate(adapter, business_request)

    return {
        "provider_resolution": _resolve_provider_info(effective_config, registry),
        "request_context": serialize_request_context(request_context),
        "business_request": serialize_business_request(business_request),
        "business_response": serialize_business_response(
            business_response,
            include_raw_response=payload.include_raw_response,
        ),
        "retrieval": {
            "retrieved_count": len(retrieved_chunks),
            "memory_count": len(memory_bundle.memory_context),
            "retrieval_query": retrieval_query,
            "rewritten_question": rewritten_question,
            "memory_bundle": serialize_memory_retrieval_bundle(memory_bundle),
        },
    }


def _build_provider_runtime_config(
    runtime_config: AppConfig,
    provider_override: str | None,
    model_override: str | None,
) -> AppConfig:
    provider_text = str(provider_override or "").strip()
    model_text = str(model_override or "").strip()
    updated_config = runtime_config
    if provider_text:
        updated_config = replace(updated_config, llm_provider=_normalize_provider(provider_text))
    if model_text:
        updated_config = replace(updated_config, llm_model=model_text)
    return updated_config


def _resolve_provider_info(
    runtime_config: AppConfig,
    registry,
) -> dict[str, object]:
    requested_provider = runtime_config.llm_provider
    fallback_to_local_mock = requested_provider == "local_mock" or not runtime_config.llm_api_ready
    resolved_provider = "local_mock" if fallback_to_local_mock else requested_provider
    entry = registry.get_entry(resolved_provider)
    return {
        "requested_provider": requested_provider,
        "requested_model": runtime_config.llm_model,
        "resolved_provider": entry["provider_name"],
        "adapter_type": entry["adapter_type"],
        "aliases": entry["aliases"],
        "llm_api_ready": runtime_config.llm_api_ready,
        "using_fallback": resolved_provider == "local_mock" and requested_provider != "local_mock",
        "fallback_reason": "llm_api_not_ready"
        if resolved_provider == "local_mock" and requested_provider != "local_mock"
        else "",
        "has_llm_api_key": bool(runtime_config.llm_api_key),
        "has_llm_api_base": bool(runtime_config.llm_api_base),
    }
