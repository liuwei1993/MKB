from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from .llm import LLMClient
from .pubmed import Article

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    pmid: str
    title: str
    source: str  # "fulltext" | "abstract"
    text: str
    index: int


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    # Prefer splitting on paragraph boundaries, then sliding window
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    pieces: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(para) > size:
            if buf:
                pieces.append(buf.strip())
                buf = ""
            pieces.extend(_sliding_window(para, size, overlap))
            continue
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) <= size:
            buf = candidate
        else:
            if buf:
                pieces.append(buf)
            buf = para
    if buf:
        pieces.append(buf)

    # Merge tiny trailing pieces and ensure overlap between windows when needed
    return [p for p in pieces if p.strip()]


def _sliding_window(text: str, size: int, overlap: int) -> list[str]:
    step = max(1, size - overlap)
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + size])
        if i + size >= n:
            break
        i += step
    return out


def build_chunks(
    articles: list[Article],
    *,
    chunk_size: int,
    chunk_overlap: int,
    abstract_max_chars: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for a in articles:
        if a.has_fulltext and a.fulltext.strip():
            parts = chunk_text(a.fulltext, chunk_size, chunk_overlap)
            for i, part in enumerate(parts):
                chunks.append(
                    Chunk(
                        pmid=a.pmid,
                        title=a.title,
                        source="fulltext",
                        text=part,
                        index=i,
                    )
                )
        else:
            abs_text = a.abstract.strip()
            if not abs_text:
                # Title-only fallback so the paper can still be retrieved weakly
                abs_text = a.title.strip() or "(no text)"
            if len(abs_text) > abstract_max_chars:
                abs_text = abs_text[: abstract_max_chars - 1] + "…"
            chunks.append(
                Chunk(
                    pmid=a.pmid,
                    title=a.title,
                    source="abstract",
                    text=abs_text,
                    index=0,
                )
            )
    return chunks


def _cosine_sim(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    q = query / (np.linalg.norm(query) + 1e-9)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
    m = matrix / norms
    return m @ q


async def retrieve_chunks(
    llm: LLMClient,
    question: str,
    chunks: list[Chunk],
    top_k: int,
) -> list[Chunk]:
    if not chunks:
        return []
    if len(chunks) <= top_k:
        logger.info(
            "rag_retrieve chunks=%d <= top_k=%d 全部入选，未调用 embedding",
            len(chunks), top_k,
        )
        # Still embed? Not necessary — return all
        return chunks

    texts = [c.text for c in chunks]
    # Embed query + documents; query first for a single batched-style flow
    t0 = time.perf_counter()
    q_vecs = await llm.embed([question])
    doc_vecs = await llm.embed(texts)
    q = np.asarray(q_vecs[0], dtype=np.float32)
    m = np.asarray(doc_vecs, dtype=np.float32)
    scores = _cosine_sim(q, m)
    order = np.argsort(-scores)[:top_k]
    picked = [chunks[int(i)] for i in order]
    _log_score_curve(chunks, scores, top_k, time.perf_counter() - t0)
    return picked


def _log_score_curve(
    chunks: list[Chunk], scores: np.ndarray, top_k: int, elapsed: float
) -> None:
    """打印 top_k 前后的相似度衰减，用于评估调大 RAG_TOP_K 的边际收益。"""
    n = len(chunks)
    k = min(top_k, n)
    s_sorted = np.sort(scores)[::-1]
    selected = np.argsort(-scores)[:k]
    ft_sel = sum(1 for i in selected if chunks[int(i)].source == "fulltext")
    after = [round(float(x), 4) for x in s_sorted[k : k + 5]]
    logger.info(
        "rag_retrieve chunks=%d top_k=%d selected_fulltext=%d/%d "
        "score_top1=%.4f score_at_k=%.4f scores_after_k=%s elapsed=%.2fs",
        n, k, ft_sel, k,
        float(s_sorted[0]), float(s_sorted[k - 1]), after, elapsed,
    )


def format_rag_evidence(chunks: list[Chunk], articles: list[Article]) -> str:
    by_pmid = {a.pmid: a for a in articles}
    blocks: list[str] = []
    for i, c in enumerate(chunks, 1):
        a = by_pmid.get(c.pmid)
        journal = f"{a.journal} ({a.year})" if a else ""
        authors = a.authors if a else ""
        source_label = "全文" if c.source == "fulltext" else "摘要"
        blocks.append(
            f"[{i}] PMID:{c.pmid} ({source_label}#{c.index})\n"
            f"Title: {c.title}\n"
            f"Journal: {journal}\n"
            f"Authors: {authors}\n"
            f"Passage:\n{c.text}"
        )
    return "\n\n".join(blocks)
