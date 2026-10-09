from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from .config import Settings
from .llm import LLMClient
from .pmc import PMCClient
from .pubmed import Article, PubMedClient
from .rag import build_chunks, format_rag_evidence, retrieve_chunks

SUMMARY_MAX_CHARS = 800
EXCERPT_MAX_CHARS = 500
# Keep enough of the latest answer for rephrase (shorten/translate); not for retrieval.
LAST_ANSWER_MAX_CHARS = 12000
RECENT_MAX_TURNS = 3
QUESTION_MAX_CHARS = 4000

UNDERSTAND_SYSTEM = """你是医学检索助手。根据对话上下文，判断用户本轮发言与历史的关系，并给出可独立检索的问题与 PubMed 检索式。
只返回 JSON，不要 markdown，不要解释：
{"relation":"follow_up","standalone_question":"...","queries":["..."]}

relation 只能是以下三者之一：
- follow_up：追问。必须消解指代和省略（如「那女性呢」「这篇呢」「副作用呢」）。standalone_question 不看对话也要完整，写明疾病、药物、人群。
- new_topic：换了主题。standalone_question 和 queries 不得带入此前的疾病、药物或人群。
- rephrase：只要求缩短、翻译或换说法，没有新的临床实体。queries 用空数组。

规则：
- 没有更早对话时，relation 必须是 new_topic。
- queries 为 1 到 3 条英文检索式；可用 MeSH 风格词汇、同义词和简单 AND/OR；每条保持简短。rephrase 时为空数组。
- standalone_question 用中文，完整、可单独理解。"""

SUMMARY_SYSTEM = """你把医学问答对话压缩成一段中文摘要，供后续追问消解指代。
只保留：疾病、药物、人群、用户关心的问题、已给出的主要结论、引用过的 PMID。
不要写检索段落或全文摘抄。不超过 800 字。只输出摘要正文。"""

ANSWER_SYSTEM = """你是医学文献助手。仅依据用户提供的文献检索段落（可能来自开放获取全文或摘要）作答，禁止编造未给出的文献或 PMID。
要求：
1. 用中文分点回答，结构清晰。回答「本轮独立问题」，用户原话仅帮助理解措辞。
2. 对关键结论标注证据来源，格式为 [PMID:数字]。
3. 如证据来自全文段落或摘要，可按材料如实引用，勿夸大证据等级。
4. 如证据冲突或不足，明确说明局限。
5. 若消息中有「上一轮摘录」，只用于对比或衔接，不得将其 PMID 当作本轮证据，除非该 PMID 也出现在本轮文献证据中。
6. 末尾用一两句总结临床/科研含义。
7. 声明：回答仅供科研与学习参考，不能替代临床诊疗决策。"""

REPHRASE_SYSTEM = """你是医学文献助手。用户希望改写上一轮回答（缩短、翻译或换说法）。本轮没有新的文献检索。
要求：
1. 只依据给出的上一轮完整回答改写，不要补充其中没有的事实、数据或 PMID。
2. 用中文；若用户明确要求翻译，则按用户要求的语言。
3. 开头明确说明：本轮未重新检索文献，内容来自上一轮回答的改写。
4. 声明：回答仅供科研与学习参考，不能替代临床诊疗决策。"""

_PMID_RE = re.compile(r"PMID\s*[:：]?\s*(\d{4,10})", re.I)
_RELATIONS = {"follow_up", "new_topic", "rephrase"}


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def empty_context() -> dict[str, Any]:
    return {"summary": "", "recent": [], "last_answer": ""}


def normalize_context(raw: dict | None) -> dict[str, Any]:
    """Sanitize the client envelope. Drops evidence text; keeps summary and recent turns."""
    if not isinstance(raw, dict):
        return empty_context()
    summary = _clip(str(raw.get("summary") or ""), SUMMARY_MAX_CHARS)
    last_answer = _clip(str(raw.get("last_answer") or ""), LAST_ANSWER_MAX_CHARS)
    recent_in = raw.get("recent") or []
    recent: list[dict[str, Any]] = []
    if isinstance(recent_in, list):
        for item in recent_in:
            if not isinstance(item, dict):
                continue
            question = _clip(str(item.get("question") or ""), QUESTION_MAX_CHARS)
            excerpt = _clip(str(item.get("excerpt") or ""), EXCERPT_MAX_CHARS)
            pmids: list[str] = []
            pmids_raw = item.get("pmids") or []
            if isinstance(pmids_raw, list):
                for pmid in pmids_raw:
                    token = str(pmid).strip()
                    if token.isdigit() and token not in pmids:
                        pmids.append(token)
                    if len(pmids) >= 20:
                        break
            if question or excerpt:
                recent.append(
                    {"question": question, "excerpt": excerpt, "pmids": pmids}
                )
    return {
        "summary": summary,
        "recent": recent[-RECENT_MAX_TURNS:],
        "last_answer": last_answer,
    }


def extract_pmids(text: str) -> list[str]:
    found: list[str] = []
    for match in _PMID_RE.finditer(text or ""):
        pmid = match.group(1)
        if pmid not in found:
            found.append(pmid)
        if len(found) >= 20:
            break
    return found


def _extract_json_obj(raw: str) -> dict | None:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def _queries_from(data: dict) -> list[str]:
    raw = data.get("queries")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        query = str(item).strip()
        if query and query not in out:
            out.append(query)
        if len(out) >= 3:
            break
    return out


def parse_understand(raw: str, question: str, *, has_history: bool) -> dict[str, Any]:
    data = _extract_json_obj(raw) or {}
    relation = str(data.get("relation") or "").strip()
    if relation not in _RELATIONS:
        relation = "follow_up" if has_history else "new_topic"
    if relation in {"follow_up", "rephrase"} and not has_history:
        relation = "new_topic"
    standalone = str(data.get("standalone_question") or "").strip() or question
    queries = [] if relation == "rephrase" else _queries_from(data)
    if relation != "rephrase" and not queries:
        queries = [standalone]
    return {
        "relation": relation,
        "standalone_question": standalone,
        "queries": queries[:3],
    }


def format_context_block(ctx: dict[str, Any]) -> str:
    parts: list[str] = []
    summary = str(ctx.get("summary") or "").strip()
    if summary:
        parts.append(f"更早对话摘要：\n{summary}")
    recent = ctx.get("recent") or []
    if recent:
        lines = ["最近对话："]
        for i, turn in enumerate(recent, 1):
            pmids = ", ".join(turn.get("pmids") or []) or "无"
            lines.append(
                f"[{i}] 用户：{turn.get('question') or ''}\n"
                f"助手摘录：{turn.get('excerpt') or '（无）'}\n"
                f"引用 PMID：{pmids}"
            )
        parts.append("\n".join(lines))
    if not parts:
        return "（无更早对话）"
    return "\n\n".join(parts)


def naive_summary(summary: str, turn: dict[str, Any]) -> str:
    pmids = ",".join(turn.get("pmids") or [])
    bit = f"用户：{turn.get('question') or ''}；回答：{turn.get('excerpt') or ''}"
    if pmids:
        bit += f"；PMID：{pmids}"
    joined = f"{summary}\n{bit}".strip() if summary else bit
    return _clip(joined, SUMMARY_MAX_CHARS)


def previous_turn(ctx: dict[str, Any]) -> dict[str, Any] | None:
    recent = ctx.get("recent") or []
    if not recent:
        return None
    return recent[-1]


async def understand_turn(
    llm: LLMClient,
    question: str,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    has_history = bool(str(ctx.get("summary") or "").strip() or ctx.get("recent"))
    raw = await llm.chat(
        [
            {"role": "system", "content": UNDERSTAND_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"{format_context_block(ctx)}\n\n"
                    f"用户本轮原话：\n{question}"
                ),
            },
        ],
        max_tokens=512,
        temperature=0.1,
    )
    return parse_understand(raw, question, has_history=has_history)


async def fold_oldest(
    llm: LLMClient,
    summary: str,
    turn: dict[str, Any],
) -> str:
    pmids = ", ".join(turn.get("pmids") or []) or "无"
    raw = await llm.chat(
        [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"已有摘要：\n{summary or '（无）'}\n\n"
                    "请并入这一轮后重写摘要：\n"
                    f"用户：{turn.get('question') or ''}\n"
                    f"回答摘录：{turn.get('excerpt') or ''}\n"
                    f"PMID：{pmids}"
                ),
            },
        ],
        max_tokens=600,
        temperature=0.1,
    )
    text = _clip(raw, SUMMARY_MAX_CHARS)
    return text or naive_summary(summary, turn)


async def update_envelope(
    llm: LLMClient,
    ctx: dict[str, Any],
    question: str,
    answer: str,
) -> dict[str, Any]:
    """Append this turn. When recent is already full, fold the oldest into summary."""
    summary = str(ctx.get("summary") or "")
    recent = list(ctx.get("recent") or [])
    new_turn = {
        "question": _clip(question, QUESTION_MAX_CHARS),
        "excerpt": _clip(answer, EXCERPT_MAX_CHARS),
        "pmids": extract_pmids(answer),
    }
    if len(recent) >= RECENT_MAX_TURNS:
        oldest = recent[0]
        try:
            summary = await fold_oldest(llm, summary, oldest)
        except Exception:
            summary = naive_summary(summary, oldest)
        recent = recent[1:]
    recent.append(new_turn)
    return {
        "summary": summary,
        "recent": recent,
        "last_answer": _clip(answer, LAST_ANSWER_MAX_CHARS),
    }


def format_evidence_fallback(articles: list[Article], max_chars: int) -> str:
    """Abstract-only evidence when RAG/embedding fails."""
    blocks: list[str] = []
    for i, a in enumerate(articles, 1):
        abs_text = a.abstract.strip() or "(无摘要)"
        if len(abs_text) > max_chars:
            abs_text = abs_text[: max_chars - 1] + "…"
        blocks.append(
            f"[{i}] PMID:{a.pmid}\n"
            f"Title: {a.title}\n"
            f"Journal: {a.journal} ({a.year})\n"
            f"Authors: {a.authors}\n"
            f"Abstract: {abs_text}"
        )
    return "\n\n".join(blocks)


def _answer_user_message(
    *,
    question: str,
    standalone: str,
    queries: list[str],
    evidence: str,
    mode: str,
    article_count: int,
    fulltext_n: int,
    with_abs: int,
    ctx: dict[str, Any],
) -> str:
    prior = previous_turn(ctx)
    prior_block = ""
    if prior:
        prior_block = (
            "上一轮摘录（仅供对比衔接，不是本轮证据；其中的 PMID 只有也出现在本轮文献证据中才可引用）：\n"
            f"用户：{prior.get('question') or ''}\n"
            f"助手：{prior.get('excerpt') or '（无）'}\n\n"
        )
    return (
        f"{prior_block}"
        f"本轮独立问题：\n{standalone}\n\n"
        f"用户原话：\n{question}\n\n"
        f"检索查询：{queries}\n\n"
        f"以下为文献证据（模式：{mode}；检索 {article_count} 篇，"
        f"开放获取全文 {fulltext_n} 篇，有摘要 {with_abs} 篇）：\n\n"
        f"{evidence}"
    )


def _rephrase_user_message(question: str, ctx: dict[str, Any]) -> str:
    prior = previous_turn(ctx)
    if prior is None and not str(ctx.get("last_answer") or "").strip():
        return f"用户本轮要求：\n{question}\n\n（没有上一轮回答可改写。）"
    prior_answer = str(ctx.get("last_answer") or "").strip() or str(
        (prior or {}).get("excerpt") or ""
    ).strip()
    prior_q = str((prior or {}).get("question") or "").strip()
    return (
        f"用户本轮要求：\n{question}\n\n"
        f"上一轮问题：\n{prior_q or '（无）'}\n\n"
        f"上一轮完整回答：\n{prior_answer or '（无）'}\n"
    )


async def run_ask(
    settings: Settings,
    question: str,
    context: dict | None = None,
) -> AsyncIterator[dict[str, Any]]:
    question = question.strip()
    if not question:
        yield {"type": "error", "message": "问题不能为空"}
        return

    ctx = normalize_context(context)
    llm = LLMClient(settings)
    pubmed = PubMedClient(settings)
    pmc = PMCClient(settings)
    await llm.__aenter__()
    await pubmed.__aenter__()
    await pmc.__aenter__()
    try:
        try:
            yield {"type": "status", "message": "正在结合对话理解问题…"}
            understood = await understand_turn(llm, question, ctx)
            relation = understood["relation"]
            standalone = understood["standalone_question"]
            queries = understood["queries"]
            yield {
                "type": "queries",
                "queries": queries,
                "relation": relation,
                "standalone_question": standalone,
                "retrieval": relation != "rephrase",
            }

            evidence = ""
            mode = ""
            article_count = 0
            fulltext_n = 0
            with_abs = 0
            if relation == "rephrase":
                yield {
                    "type": "status",
                    "message": "本轮为改写上一回答，不重新检索…",
                }
            else:
                async for event in _retrieve_evidence(
                    settings, llm, pubmed, pmc, standalone, queries
                ):
                    if event["type"] == "_evidence":
                        evidence = event["evidence"]
                        mode = event["mode"]
                        article_count = event["article_count"]
                        fulltext_n = event["fulltext_n"]
                        with_abs = event["with_abs"]
                    else:
                        yield event
                        if event["type"] == "error":
                            return

            if relation == "rephrase":
                messages = [
                    {"role": "system", "content": REPHRASE_SYSTEM},
                    {"role": "user", "content": _rephrase_user_message(question, ctx)},
                ]
            else:
                messages = [
                    {"role": "system", "content": ANSWER_SYSTEM},
                    {
                        "role": "user",
                        "content": _answer_user_message(
                            question=question,
                            standalone=standalone,
                            queries=queries,
                            evidence=evidence,
                            mode=mode,
                            article_count=article_count,
                            fulltext_n=fulltext_n,
                            with_abs=with_abs,
                            ctx=ctx,
                        ),
                    },
                ]

            yield {"type": "status", "message": "正在整理回答…"}
            answer_parts: list[str] = []
            async for token in llm.chat_stream(
                messages,
                max_tokens=2048,
                temperature=0.2,
            ):
                answer_parts.append(token)
                yield {"type": "token", "content": token}

            if len(ctx.get("recent") or []) >= RECENT_MAX_TURNS:
                yield {"type": "status", "message": "正在压缩更早的对话…"}
            new_ctx = await update_envelope(llm, ctx, question, "".join(answer_parts))
            yield {"type": "context", "context": new_ctx}
            yield {"type": "done"}
        except Exception as e:
            yield {"type": "error", "message": str(e)}
    finally:
        await pmc.__aexit__(None, None, None)
        await pubmed.__aexit__(None, None, None)
        await llm.__aexit__(None, None, None)


async def _retrieve_evidence(
    settings: Settings,
    llm: LLMClient,
    pubmed: PubMedClient,
    pmc: PMCClient,
    standalone: str,
    queries: list[str],
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "status", "message": "正在检索 PubMed…"}
    articles = await pubmed.search_articles(queries)
    if not articles:
        yield {
            "type": "error",
            "message": "未检索到相关文献，请换个问法或补充关键词后重试。",
        }
        return

    yield {
        "type": "meta",
        "articles": [a.to_meta() for a in articles],
        "count": len(articles),
    }

    yield {"type": "status", "message": "正在获取开放获取全文…"}
    fulltext_n = await pmc.attach_fulltexts(articles)

    yield {
        "type": "meta",
        "articles": [a.to_meta() for a in articles],
        "count": len(articles),
    }

    with_abs = sum(1 for a in articles if a.abstract.strip())
    if fulltext_n == 0 and with_abs == 0:
        yield {
            "type": "status",
            "message": "无全文且无摘要，将仅依据标题等信息作答（证据有限）。",
        }

    evidence: str
    used_rag = False
    try:
        yield {"type": "status", "message": "正在检索相关段落…"}
        chunks = build_chunks(
            articles,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            abstract_max_chars=settings.abstract_max_chars,
        )
        top = await retrieve_chunks(
            llm, standalone, chunks, top_k=settings.rag_top_k
        )
        evidence = format_rag_evidence(top, articles)
        used_rag = True
        ft_chunks = sum(1 for c in top if c.source == "fulltext")
        yield {
            "type": "status",
            "message": (
                f"已获取 {fulltext_n} 篇全文，选用 {len(top)} 个段落"
                f"（其中全文段落 {ft_chunks}），正在整理回答…"
            ),
        }
    except Exception as rag_err:
        yield {
            "type": "status",
            "message": f"段落检索失败，回退摘要作答（{rag_err}）…",
        }
        evidence = format_evidence_fallback(articles, settings.abstract_max_chars)

    yield {
        "type": "_evidence",
        "evidence": evidence,
        "mode": "RAG 段落" if used_rag else "摘要",
        "article_count": len(articles),
        "fulltext_n": fulltext_n,
        "with_abs": with_abs,
    }
