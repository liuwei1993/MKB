from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .llm import LLMClient
from .pipeline import run_ask
from .titles import translate_titles

logger = logging.getLogger(__name__)

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
    articles: list[TitleIn] = Field(default_factory=list, max_length=50)


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
