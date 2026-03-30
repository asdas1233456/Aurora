"""Scope-aware and scene-aware memory retrieval for chat requests."""

from __future__ import annotations

from time import perf_counter

from app.config import AppConfig
from app.schemas import MemoryFact, MemoryRequestContext, ResolvedScopeContext
from app.services.abuse_guard import AbuseGuard
from app.services.audit_service import AuditService
from app.services.consistent_memory_retriever import ConsistentMemoryRetriever
from app.services.degradation_controller import DegradationController
from app.services.memory_access_policy import MemoryAccessPolicy
from app.services.memory_candidate_selector import MemoryCandidateSelector
from app.services.memory_injection_builder import MemoryInjectionBuilder
from app.services.memory_ranker import MemoryRanker
from app.services.memory_relevance_scorer import MemoryRelevanceScorer, MemoryRelevanceScorerPort
from app.services.memory_repository import MemoryRepository
from app.services.memory_retrieval_models import (
    MemoryQuery,
    MemoryRetrievalBundle,
    RetrievalMode,
)
from app.services.memory_retrieval_planner import RetrievalPlanner
from app.services.memory_retrieval_trace import RetrievalTraceService
from app.services.memory_scope import ScopeResolver
from app.services.observability_service import ObservabilityService
from app.services.retention_aware_retriever import RetentionAwareRetriever


class MemoryRetriever:
    """Retrieve readable memory facts or run the full ranked retrieval pipeline."""

    def __init__(
        self,
        config: AppConfig,
        *,
        repository: MemoryRepository | None = None,
        access_policy: MemoryAccessPolicy | None = None,
        audit_service: AuditService | None = None,
        scope_resolver: ScopeResolver | None = None,
        consistent_retriever: ConsistentMemoryRetriever | None = None,
        planner: RetrievalPlanner | None = None,
        candidate_selector: MemoryCandidateSelector | None = None,
        relevance_scorer: MemoryRelevanceScorerPort | None = None,
        ranker: MemoryRanker | None = None,
        injection_builder: MemoryInjectionBuilder | None = None,
        trace_service: RetrievalTraceService | None = None,
        retention_retriever: RetentionAwareRetriever | None = None,
        abuse_guard: AbuseGuard | None = None,
        observability: ObservabilityService | None = None,
        degradation_controller: DegradationController | None = None,
    ) -> None:
        self._repository = repository or MemoryRepository(config)
        self._scope_resolver = scope_resolver or ScopeResolver()
        self._access_policy = access_policy or MemoryAccessPolicy(self._scope_resolver)
        self._audit_service = audit_service or AuditService(config)
        self._consistent_retriever = consistent_retriever or ConsistentMemoryRetriever()
        self._planner = planner or RetrievalPlanner()
        self._candidate_selector = candidate_selector or MemoryCandidateSelector(
            config,
            repository=self._repository,
            access_policy=self._access_policy,
        )
        self._relevance_scorer = relevance_scorer or MemoryRelevanceScorer()
        self._ranker = ranker or MemoryRanker()
        self._injection_builder = injection_builder or MemoryInjectionBuilder()
        self._trace_service = trace_service or RetrievalTraceService()
        self._retention_retriever = retention_retriever or RetentionAwareRetriever()
        self._abuse_guard = abuse_guard or AbuseGuard()
        self._observability = observability or ObservabilityService(config)
        self._degradation_controller = degradation_controller or DegradationController(
            config,
            audit_service=self._audit_service,
            observability=self._observability,
        )

    def retrieve(
        self,
        request_context: MemoryRequestContext | ResolvedScopeContext,
        *,
        top_k: int = 3,
    ) -> list[MemoryFact]:
        """Backward-compatible readable retrieval used by existing internal tooling."""

        resolved_context = self._resolve_context(request_context)
        request_actor = resolved_context.request_context
        rate_limit = self._abuse_guard.check_and_consume(
            request_actor,
            action_name="memory_retrieval",
        )
        if not rate_limit.allowed:
            self._handle_rate_limit(request_actor, reason=rate_limit.reason)
            return []

        # Fetch extra candidates because consistency filtering can hide superseded or lower-scope duplicates.
        candidate_limit = max(top_k * 4, top_k, 10)
        started_at = perf_counter()
        candidates = self._repository.list_active_by_scopes(
            tenant_id=request_actor.tenant_id,
            scopes=resolved_context.allowed_scopes,
            limit=candidate_limit,
        )
        self._observability.increment_metric(
            "memory_candidate_count",
            value=float(len(candidates)),
            dimensions={"mode": "legacy"},
        )

        allowed = [
            item
            for item in candidates
            if self._access_policy.can_read(resolved_context, item)
        ]
        consistent_results = self._consistent_retriever.filter_for_default_retrieval(
            allowed,
            top_k=candidate_limit,
        )
        results = self._retention_retriever.filter_facts_for_default_retrieval(
            consistent_results,
            top_k=top_k,
        )

        for item in results:
            self._safe_record_memory_action(
                request_context=request_actor,
                memory_fact_id=item.id,
                action="retrieve",
                scope_type=item.scope_type,
                retrieval_stage="selected",
            )
        self._repository.touch_memory_facts([item.id for item in results])
        self._record_retrieval_metrics(
            request_context=request_actor,
            selected_count=len(results),
            total_candidates=len(candidates),
            selected_scope_counts=self._scope_counts(results),
            latency_ms=(perf_counter() - started_at) * 1000,
            empty_result=len(results) == 0,
        )

        return results

    def retrieve_bundle(
        self,
        request_context: MemoryRequestContext | ResolvedScopeContext,
        *,
        scene: str | None,
        user_query: str,
        top_k: int,
        retrieval_mode: RetrievalMode | None = None,
        retrieval_metadata: dict[str, object] | None = None,
        fail_open: bool = False,
    ) -> MemoryRetrievalBundle:
        """Run Aurora's fifth-feature retrieval pipeline and return a bounded bundle."""

        resolved_context = self._resolve_context(request_context)
        request_actor = resolved_context.request_context
        rate_limit = self._abuse_guard.check_and_consume(
            request_actor,
            action_name="memory_retrieval",
        )
        if not rate_limit.allowed:
            self._handle_rate_limit(request_actor, reason=rate_limit.reason)
            scene_name = self._planner.resolve_scene(scene, user_query)
            policy = self._planner.build_scene_policy(scene_name)
            query = MemoryQuery(
                tenant_id=request_actor.tenant_id,
                user_id=request_actor.user_id,
                project_id=request_actor.project_id,
                session_id=request_actor.session_id,
                scene=scene_name,
                user_query=user_query,
                allowed_scopes=resolved_context.allowed_scopes,
                top_k=top_k,
                retrieval_mode=retrieval_mode or policy.default_retrieval_mode,
                retrieval_metadata=dict(retrieval_metadata or {}),
            )
            plan = self._planner.plan(query, policy)
            bundle = self._empty_bundle(
                query,
                plan,
                error=f"rate_limited:{rate_limit.reason}",
            )
            self._degradation_controller.degrade_memory_retrieval(
                request_context=request_actor,
                reason="rate_limited",
                payload={"action_name": "memory_retrieval", "detail": rate_limit.reason},
            )
            return bundle

        started_at = perf_counter()
        try:
            scene_name = self._planner.resolve_scene(scene, user_query)
            policy = self._planner.build_scene_policy(scene_name)
            query = MemoryQuery(
                tenant_id=request_actor.tenant_id,
                user_id=request_actor.user_id,
                project_id=request_actor.project_id,
                session_id=request_actor.session_id,
                scene=scene_name,
                user_query=user_query,
                allowed_scopes=resolved_context.allowed_scopes,
                top_k=top_k,
                retrieval_mode=retrieval_mode or policy.default_retrieval_mode,
                retrieval_metadata=dict(retrieval_metadata or {}),
            )
            plan = self._planner.plan(query, policy)
            if not plan.enabled:
                return self._empty_bundle(query, plan, error="")

            readable_candidates = self._candidate_selector.select(resolved_context, query, plan)
            self._observability.increment_metric(
                "memory_candidate_count",
                value=float(len(readable_candidates)),
                dimensions={"scene": scene_name},
            )
            consistent_candidates, consistency_drops = self._consistent_retriever.collapse_candidates(
                readable_candidates,
                scope_weights=plan.scope_weights,
            )
            retention_candidates, retention_drops = self._retention_retriever.filter_candidates_for_default_retrieval(
                consistent_candidates
            )

            relevance_signals = {
                item.memory_fact_id: self._relevance_scorer.score(query, item)
                for item in retention_candidates
            }
            bundle = self._ranker.rank(
                query=query,
                plan=plan,
                candidates=retention_candidates,
                relevance_signals=relevance_signals,
                consistency_drops=[*consistency_drops, *retention_drops],
            )
            bundle.total_candidates = len(readable_candidates)
            bundle.memory_context = self._injection_builder.build_context(
                bundle.selected_memories,
                plan=plan,
            )
            bundle.retrieval_plan = plan
            bundle.retrieval_trace = self._trace_service.build_trace(
                query=query,
                plan=plan,
                bundle=bundle,
                readable_candidate_count=len(readable_candidates),
                consistent_candidate_count=len(consistent_candidates),
                consistency_dropped_count=len(consistency_drops),
            )

            for item in bundle.selected_memories:
                self._safe_record_memory_action(
                    request_context=request_actor,
                    memory_fact_id=item.memory_fact_id,
                    action="retrieve",
                    scope_type=item.scope_type,
                    retrieval_stage="selected",
                    decision_reason=item.matched_reason,
                )
                if not bool(query.retrieval_metadata.get("preview")):
                    self._safe_record_memory_action(
                        request_context=request_actor,
                        memory_fact_id=item.memory_fact_id,
                        action="inject",
                        scope_type=item.scope_type,
                        retrieval_stage="injected",
                        decision_reason=item.matched_reason,
                    )
            if not bool(query.retrieval_metadata.get("preview")):
                self._repository.touch_memory_facts(
                    [item.memory_fact_id for item in bundle.selected_memories]
                )

            selected_scope_counts = self._scope_counts(bundle.selected_memories)
            self._record_retrieval_metrics(
                request_context=request_actor,
                selected_count=bundle.total_selected,
                total_candidates=len(readable_candidates),
                selected_scope_counts=selected_scope_counts,
                latency_ms=(perf_counter() - started_at) * 1000,
                empty_result=bundle.total_selected == 0,
                selected_context_size=sum(len(item.content) for item in bundle.memory_context),
            )
            self._observability.increment_metric(
                "memory_injection_count",
                value=float(len(bundle.memory_context)),
                dimensions={"scene": scene_name},
            )
            self._observability.log_event(
                "memory.retrieval_completed",
                request_context=request_actor,
                payload=self._observability.build_retrieval_trace_payload(
                    request_context=request_actor,
                    trace=bundle.retrieval_trace or {},
                ),
            )
            if len(readable_candidates) >= max(plan.candidate_limit, 1):
                self._record_security_event(
                    request_actor,
                    event_type="abnormal_retrieval_volume",
                    severity="medium",
                    payload={
                        "scene": scene_name,
                        "candidate_limit": plan.candidate_limit,
                        "selected_count": bundle.total_selected,
                    },
                )

            return bundle
        except Exception as exc:
            if not fail_open:
                raise

            scene_name = self._planner.resolve_scene(scene, user_query)
            policy = self._planner.build_scene_policy(scene_name)
            query = MemoryQuery(
                tenant_id=resolved_context.request_context.tenant_id,
                user_id=resolved_context.request_context.user_id,
                project_id=resolved_context.request_context.project_id,
                session_id=resolved_context.request_context.session_id,
                scene=scene_name,
                user_query=user_query,
                allowed_scopes=resolved_context.allowed_scopes,
                top_k=top_k,
                retrieval_mode=retrieval_mode or policy.default_retrieval_mode,
                retrieval_metadata=dict(retrieval_metadata or {}),
            )
            plan = self._planner.plan(query, policy)
            bundle = self._empty_bundle(
                query,
                plan,
                error=f"{exc.__class__.__name__}: {exc}",
            )
            self._degradation_controller.degrade_memory_retrieval(
                request_context=request_actor,
                reason="exception",
                payload={"exception_type": exc.__class__.__name__},
            )
            self._observability.increment_metric("retrieval_empty_result_count")
            return bundle

    def _empty_bundle(
        self,
        query: MemoryQuery,
        plan,
        *,
        error: str,
    ) -> MemoryRetrievalBundle:
        bundle = MemoryRetrievalBundle(
            selected_memories=[],
            dropped_candidates=[],
            total_candidates=0,
            total_selected=0,
            retrieval_plan=plan,
            memory_context=[],
        )
        bundle.retrieval_trace = self._trace_service.build_trace(
            query=query,
            plan=plan,
            bundle=bundle,
            readable_candidate_count=0,
            consistent_candidate_count=0,
            consistency_dropped_count=0,
            error=error,
        )
        return bundle

    def _safe_record_memory_action(
        self,
        *,
        request_context: MemoryRequestContext,
        memory_fact_id: str,
        action: str,
        scope_type: str,
        retrieval_stage: str = "",
        decision_reason: str = "",
    ) -> None:
        self._degradation_controller.protect_side_effect(
            f"audit.memory.{action}",
            lambda: self._audit_service.record_memory_action(
                request_context=request_context,
                memory_fact_id=memory_fact_id,
                action=action,
                scope_type=scope_type,
                retrieval_stage=retrieval_stage,
                decision_reason=decision_reason,
            ),
            request_context=request_context,
        )

    def _handle_rate_limit(
        self,
        request_context: MemoryRequestContext,
        *,
        reason: str,
    ) -> None:
        self._observability.increment_metric("rate_limit_trigger_count")
        self._degradation_controller.protect_side_effect(
            "policy.abuse_guard.rate_limit",
            lambda: self._audit_service.record_policy_decision(
                request_id=request_context.request_id,
                policy_name="abuse_guard.rate_limit",
                decision="throttle",
                reason=reason,
                target_type="memory_retrieval",
                target_id=request_context.session_id,
                payload={"tenant_id": request_context.tenant_id, "user_id": request_context.user_id},
            ),
            request_context=request_context,
        )
        self._record_security_event(
            request_context,
            event_type="rate_limit_triggered",
            severity="medium",
            payload={"action_name": "memory_retrieval", "reason": reason},
        )

    def _record_security_event(
        self,
        request_context: MemoryRequestContext,
        *,
        event_type: str,
        severity: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._degradation_controller.protect_side_effect(
            f"security.{event_type}",
            lambda: self._audit_service.record_security_event(
                tenant_id=request_context.tenant_id,
                event_type=event_type,
                severity=severity,
                actor_user_id=request_context.user_id,
                session_id=request_context.session_id,
                request_id=request_context.request_id,
                event_payload=payload,
            ),
            request_context=request_context,
        )

    def _record_retrieval_metrics(
        self,
        *,
        request_context: MemoryRequestContext,
        selected_count: int,
        total_candidates: int,
        selected_scope_counts: dict[str, int],
        latency_ms: float,
        empty_result: bool,
        selected_context_size: int = 0,
    ) -> None:
        self._observability.increment_metric(
            "memory_selected_count",
            value=float(selected_count),
            dimensions={"tenant_id": request_context.tenant_id},
        )
        self._observability.record_metric(
            "memory_retrieval_latency_ms",
            value=latency_ms,
            dimensions={"tenant_id": request_context.tenant_id},
        )
        self._observability.record_metric(
            "memory_context_size",
            value=float(selected_context_size or selected_count),
            dimensions={"tenant_id": request_context.tenant_id},
        )
        if empty_result:
            self._observability.increment_metric("retrieval_empty_result_count")
        for scope_type, scope_count in selected_scope_counts.items():
            self._observability.increment_metric(
                "per_scope_selected_count",
                value=float(scope_count),
                dimensions={"scope_type": scope_type},
            )

    @staticmethod
    def _scope_counts(items) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            scope_type = str(getattr(item, "scope_type", ""))
            counts[scope_type] = counts.get(scope_type, 0) + 1
        return counts

    def _resolve_context(
        self,
        request_context: MemoryRequestContext | ResolvedScopeContext,
    ) -> ResolvedScopeContext:
        if isinstance(request_context, ResolvedScopeContext):
            return request_context
        return self._scope_resolver.resolve(request_context)
