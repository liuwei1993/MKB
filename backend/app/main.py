from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .pipeline import run_ask

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


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    context: ContextIn | None = None


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


@app.post("/api/ask")
async def ask(body: AskRequest):
    settings = get_settings()

    async def event_stream():
        context = body.context.model_dump() if body.context else None
        async for event in run_ask(settings, body.question, context):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
