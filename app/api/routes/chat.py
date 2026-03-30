from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.chat import ask_question
from app.api.dependencies import get_runtime_config
from app.api.request_models import ChatRequestModel
from app.api.serializers import serialize_citation
from app.config import AppConfig
from app.services.rag_service import stream_answer_with_rag


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("/ask")
def ask_kb_question(
    payload: ChatRequestModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
):
    try:
        result = ask_question(
            question=payload.question,
            chat_history=[item.model_dump() for item in payload.chat_history],
            config=runtime_config,
            top_k=payload.top_k,
        )
    except Exception as exc:
        logger.exception("REST 问答失败。")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "answer": result.answer,
        "retrieved_count": result.retrieved_count,
        "retrieval_ms": result.retrieval_ms,
        "generation_ms": result.generation_ms,
        "total_ms": result.total_ms,
        "rewritten_question": result.rewritten_question,
        "retrieval_query": result.retrieval_query,
        "confidence": result.confidence,
        "citations": [serialize_citation(item) for item in result.citations],
    }


@router.post("/stream")
def stream_kb_question(
    payload: ChatRequestModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
):
    def generate():
        started_at = time.perf_counter()
        try:
            (
                stream,
                citations,
                retrieved_count,
                retrieval_ms,
                rewritten_question,
                retrieval_query,
                confidence,
            ) = stream_answer_with_rag(
                question=payload.question,
                chat_history=[item.model_dump() for item in payload.chat_history],
                config=runtime_config,
                top_k=payload.top_k,
            )

            yield json.dumps(
                {
                    "type": "meta",
                    "retrieved_count": retrieved_count,
                    "retrieval_ms": retrieval_ms,
                    "rewritten_question": rewritten_question,
                    "retrieval_query": retrieval_query,
                    "confidence": confidence,
                },
                ensure_ascii=False,
            ) + "\n"

            full_answer_parts: list[str] = []
            generation_started_at = time.perf_counter()
            for chunk in stream:
                if not chunk:
                    continue
                full_answer_parts.append(chunk)
                yield json.dumps({"type": "delta", "content": chunk}, ensure_ascii=False) + "\n"
            generation_ms = (time.perf_counter() - generation_started_at) * 1000

            yield json.dumps(
                {
                    "type": "done",
                    "answer": "".join(full_answer_parts),
                    "citations": [serialize_citation(item) for item in citations],
                    "retrieved_count": retrieved_count,
                    "retrieval_ms": retrieval_ms,
                    "generation_ms": generation_ms,
                    "total_ms": (time.perf_counter() - started_at) * 1000,
                    "rewritten_question": rewritten_question,
                    "retrieval_query": retrieval_query,
                    "confidence": confidence,
                },
                ensure_ascii=False,
            ) + "\n"
        except Exception as exc:
            logger.exception("REST 流式问答失败。")
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")
