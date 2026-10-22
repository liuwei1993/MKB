from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from .llm import LLMClient
from .pubmed import Article

logger = logging.getLogger(__name__)

_SECTION_LABEL_ZH = {
    "intro": "引言",
    "methods": "方法",
    "results": "结果",
    "discuss": "讨论",
    "abstract": "摘要",
    "other": "其他",
}

# Additive cosine boost by question_type × section. Empty section → 0.
_SECTION_BOOST: dict[str, dict[str, float]] = {
    "treatment": {"results": 0.12, "discuss": 0.08, "methods": -0.04, "intro": 0.0},
    "prevention": {"results": 0.12, "discuss": 0.08, "methods": -0.04, "intro": 0.0},
    "diagnosis": {"results": 0.10, "methods": 0.10, "discuss": 0.04, "intro": 0.0},
    "prognosis": {"results": 0.12, "discuss": 0.08, "methods": -0.02, "intro": 0.0},
    "etiology": {"discuss": 0.10, "results": 0.08, "intro": 0.04, "methods": 0.0},
    "mechanism": {"intro": 0.08, "discuss": 0.10, "methods": 0.04, "results": 0.0},
}


@dataclass
class Chunk:
    pmid: str
    title: str
    source: str  # "fulltext" | "abstract"
    text: str
    index: int
    section: str = ""


def section_label_zh(section: str) -> str:
    return _SECTION_LABEL_ZH.get(section, "")


def section_boost(question_type: str, section: str) -> float:
    if not section:
        return 0.0
    return float(_SECTION_BOOST.get(question_type, {}).get(section, 0.0))


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


def _chunk_paragraphs(
    paras: list[tuple[str, str]],
    size: int,
    overlap: int,
) -> list[tuple[str, str]]:
    """Pack paragraphs without crossing section boundaries."""
    if not paras:
        return []
    out: list[tuple[str, str]] = []
    # Group consecutive paragraphs that share the same section key.
    groups: list[tuple[str, list[str]]] = []
    for section, text in paras:
        text = text.strip()
        if not text:
            continue
        if groups and groups[-1][0] == section:
            groups[-1][1].append(text)
        else:
            groups.append((section, [text]))
    for section, texts in groups:
        for part in chunk_text("\n\n".join(texts), size, overlap):
            out.append((section, part))
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
        if a.has_fulltext and (a.fulltext_paras or a.fulltext.strip()):
            if a.fulltext_paras:
                parts = _chunk_paragraphs(a.fulltext_paras, chunk_size, chunk_overlap)
            else:
                parts = [
                    ("", part)
                    for part in chunk_text(a.fulltext, chunk_size, chunk_overlap)
                ]
            for i, (section, part) in enumerate(parts):
                chunks.append(
                    Chunk(
                        pmid=a.pmid,
                        title=a.title,
                        source="fulltext",
                        text=part,
                        index=i,
                        section=section,
                    )
                )
            abs_text = a.abstract.strip()
            if abs_text:
                if len(abs_text) > abstract_max_chars:
                    abs_text = abs_text[: abstract_max_chars - 1] + "…"
                chunks.append(
                    Chunk(
                        pmid=a.pmid,
                        title=a.title,
                        source="abstract",
                        text=abs_text,
                        index=len(parts),
                        section="abstract",
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
                    section="abstract" if a.abstract.strip() else "",
                )
            )
    return chunks


def _cosine_sim(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    q = query / (np.linalg.norm(query) + 1e-9)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
    m = matrix / norms
    return m @ q


def _cap_per_pmid(chunks: list[Chunk], per_pmid: int) -> list[Chunk]:
    counts: dict[str, int] = {}
    kept: list[Chunk] = []
    for chunk in chunks:
        used = counts.get(chunk.pmid, 0)
        if used >= per_pmid:
            continue
        counts[chunk.pmid] = used + 1
        kept.append(chunk)
    return kept


def pick_diverse(chunks: list[Chunk], scores: np.ndarray, top_k: int, per_pmid: int = 4) -> list[Chunk]:
    """Keep the highest-scoring chunks without letting one paper fill every slot."""
    order = np.argsort(-scores)
    picked: list[Chunk] = []
    counts: dict[str, int] = {}
    for idx in order:
        chunk = chunks[int(idx)]
        if counts.get(chunk.pmid, 0) >= per_pmid:
            continue
        picked.append(chunk)
        counts[chunk.pmid] = counts.get(chunk.pmid, 0) + 1
        if len(picked) >= top_k:
            break
    return picked


async def retrieve_chunks(
    llm: LLMClient,
    question: str,
    chunks: list[Chunk],
    top_k: int,
    question_type: str = "",
) -> list[Chunk]:
    if not chunks:
        return []
    if len(chunks) <= top_k:
        logger.info(
            "rag_retrieve chunks=%d <= top_k=%d 全部入选，未调用 embedding",
            len(chunks), top_k,
        )
        return _cap_per_pmid(chunks, 4)

    texts = [c.text for c in chunks]
    # Embed query + documents; query first for a single batched-style flow
    t0 = time.perf_counter()
    q_vecs = await llm.embed([question])
    doc_vecs = await llm.embed(texts)
    q = np.asarray(q_vecs[0], dtype=np.float32)
    m = np.asarray(doc_vecs, dtype=np.float32)
    scores = _cosine_sim(q, m)
    if question_type:
        boosts = np.asarray(
            [section_boost(question_type, c.section) for c in chunks],
            dtype=np.float32,
        )
        scores = scores + boosts
    picked = pick_diverse(chunks, scores, top_k)
    _log_score_curve(chunks, scores, top_k, time.perf_counter() - t0, question_type)
    return picked


def _log_score_curve(
    chunks: list[Chunk],
    scores: np.ndarray,
    top_k: int,
    elapsed: float,
    question_type: str = "",
) -> None:
    """打印 top_k 前后的相似度衰减，用于评估调大 RAG_TOP_K 的边际收益。"""
    n = len(chunks)
    k = min(top_k, n)
    s_sorted = np.sort(scores)[::-1]
    selected = np.argsort(-scores)[:k]
    ft_sel = sum(1 for i in selected if chunks[int(i)].source == "fulltext")
    section_counts: dict[str, int] = {}
    for i in selected:
        key = chunks[int(i)].section or "-"
        section_counts[key] = section_counts.get(key, 0) + 1
    after = [round(float(x), 4) for x in s_sorted[k : k + 5]]
    logger.info(
        "rag_retrieve chunks=%d top_k=%d selected_fulltext=%d/%d "
        "question_type=%s sections=%s "
        "score_top1=%.4f score_at_k=%.4f scores_after_k=%s elapsed=%.2fs",
        n, k, ft_sel, k,
        question_type or "-",
        section_counts,
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
        sec = section_label_zh(c.section)
        if sec:
            source_label = f"{source_label}·{sec}"
        type_line = ""
        if a and a.pub_types:
            type_line = f"Type: {', '.join(a.pub_types)}\n"
        blocks.append(
            f"[{i}] PMID:{c.pmid} ({source_label}#{c.index})\n"
            f"Title: {c.title}\n"
            f"Journal: {journal}\n"
            f"Authors: {authors}\n"
            f"{type_line}"
            f"Passage:\n{c.text}"
        )
    return "\n\n".join(blocks)
