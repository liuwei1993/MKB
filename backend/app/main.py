from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import debug_session as debug_store
from .config import get_settings
from .llm import LLMClient
from .pipeline import run_ask
from .titles import MAX_ARTICLES, translate_titles

logger = logging.getLogger(__name__)

# uvicorn 只配置自己的 logger，根 logger 默认 WARNING，且 basicConfig 在已有 handler 时是空操作。
# 显式把 backend 调到 INFO，评估日志才会进容器 stderr。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("backend").setLevel(logging.INFO)

app = FastAPI(title="MKB PubMed Q&A", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RecentTurn(BaseModel):
    question: str = Field(default="", max_length=4000)
    excerpt: str = Field(default="", max_length=2000)
    pmids: list[str] = Field(default_factory=list, max_length=20)


class ContextIn(BaseModel):
    summary: str = Field(default="", max_length=2000)
    recent: list[RecentTurn] = Field(default_factory=list, max_length=6)
    # Latest full answer for rephrase turns (shorten/translate); not used for retrieval.
    last_answer: str = Field(default="", max_length=20000)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    context: ContextIn | None = None


class TitleIn(BaseModel):
    pmid: str = Field(..., min_length=1, max_length=32)
    title: str = Field(default="", max_length=2000)


class TranslateTitlesRequest(BaseModel):
    articles: list[TitleIn] = Field(default_factory=list, max_length=MAX_ARTICLES)


@app.get("/api/health")
async def health():
    s = get_settings()
    return {
        "ok": True,
        "llm_model": s.llm_model,
        "embedding_model": s.embedding_model,
        "llm_configured": bool(s.llm_api_key and s.llm_base_url),
        "embedding_configured": bool(
            s.llm_api_key and s.llm_base_url and s.embedding_model
        ),
        "pubmed_configured": bool(s.ncbi_email and s.ncbi_api_key),
        "fulltext_max_articles": s.fulltext_max_articles,
        "rag_top_k": s.rag_top_k,
    }


@app.post("/api/translate-titles")
async def translate_titles_api(body: TranslateTitlesRequest):
    settings = get_settings()
    try:
        async with LLMClient(settings) as llm:
            titles = await translate_titles(
                llm, [item.model_dump() for item in body.articles]
            )
    except Exception:
        logger.warning("title translation failed", exc_info=True)
        titles = {}
    return {"titles": titles}


class DebugCreateRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)


class DebugRunRequest(BaseModel):
    system_prompt: str | None = Field(default=None, max_length=20000)
    user_prompt: str | None = Field(default=None, max_length=100000)
    overrides: dict[str, Any] | None = None


class DebugPatchRequest(BaseModel):
    output: dict[str, Any]


class DebugTranslateQueriesRequest(BaseModel):
    queries: list[str] | None = Field(default=None, max_length=100)


def _require_debug_enabled() -> None:
    if not get_settings().enable_debug_api:
        raise HTTPException(status_code=404, detail="Not Found")


def _require_session(session_id: str) -> debug_store.DebugSession:
    session = debug_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="调试会话不存在或已过期")
    return session


@app.post("/api/debug/sessions")
async def debug_create_session(body: DebugCreateRequest):
    _require_debug_enabled()
    try:
        session = debug_store.create_session(get_settings(), body.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return debug_store.public_view(session)


@app.get("/api/debug/sessions/{session_id}")
async def debug_get_session(session_id: str):
    _require_debug_enabled()
    session = _require_session(session_id)
    return debug_store.public_view(session)


@app.delete("/api/debug/sessions/{session_id}")
async def debug_delete_session(session_id: str):
    _require_debug_enabled()
    deleted = debug_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="调试会话不存在或已过期")
    return {"ok": True}


@app.post("/api/debug/sessions/{session_id}/run")
async def debug_run_step(session_id: str, body: DebugRunRequest | None = None):
    _require_debug_enabled()
    session = _require_session(session_id)
    payload = body or DebugRunRequest()
    try:
        return await debug_store.run_current_step(
            session,
            system_prompt=payload.system_prompt,
            user_prompt=payload.user_prompt,
            overrides=payload.overrides,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("debug_run_failed session=%s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.patch("/api/debug/sessions/{session_id}/output")
async def debug_patch_output(session_id: str, body: DebugPatchRequest):
    _require_debug_enabled()
    session = _require_session(session_id)
    try:
        return debug_store.patch_output(session, body.output)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/debug/sessions/{session_id}/advance")
async def debug_advance(session_id: str):
    _require_debug_enabled()
    session = _require_session(session_id)
    try:
        return debug_store.advance(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/debug/sessions/{session_id}/translate-queries")
async def debug_translate_queries(
    session_id: str, body: DebugTranslateQueriesRequest | None = None
):
    _require_debug_enabled()
    session = _require_session(session_id)
    payload = body or DebugTranslateQueriesRequest()
    try:
        return await debug_store.translate_queries(session, payload.queries)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("debug_translate_failed session=%s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/ask")
async def ask(body: AskRequest, request: Request):
    settings = get_settings()

    async def event_stream():
        context = body.context.model_dump() if body.context else None
        agen = run_ask(settings, body.question, context)
        try:
            async for event in agen:
                # 客户端已断开时立刻结束生成，避免模型继续输出。
                if await request.is_disconnected():
                    return
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await agen.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
