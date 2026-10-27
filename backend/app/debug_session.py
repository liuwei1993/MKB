from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .llm import LLMClient
from .pipeline import (
    ANSWER_SYSTEM,
    SUGGEST_SYSTEM,
    UNDERSTAND_SYSTEM,
    answer_completion_tokens,
    answer_target_chars,
    answer_user_message,
    design_filter_query,
    empty_context,
    run_fulltext,
    run_pubmed_search,
    run_rag_passages,
    split_search_queries,
    suggest_followups,
    suggest_user_message,
    understand_turn,
    understand_user_message,
)
from .pmc import PMCClient
from .pubmed import Article, PubMedClient, select_fulltext_candidates
from .query_translate import (
    as_public,
    empty_translations,
    translate_pubmed_queries,
)

logger = logging.getLogger(__name__)

STEP_IDS = (
    "understand",
    "search",
    "fulltext",
    "passages",
    "answer",
    "suggest",
)
STEP_LABELS = {
    "understand": "问题理解",
    "search": "PubMed 检索",
    "fulltext": "PMC 全文",
    "passages": "RAG 段落",
    "answer": "生成回答",
    "suggest": "追问建议",
}
SESSION_TTL_S = 3600


@dataclass
class DebugSession:
    id: str
    question: str
    settings: Settings
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    current_step: str = "understand"
    status: str = "idle"  # idle | running | paused | done | error
    error: str | None = None
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Private server state
    articles: list[Article] = field(default_factory=list)
    relation: str = "new_topic"
    question_type: str = "other"
    standalone: str = ""
    broad_queries: list[str] = field(default_factory=list)
    priority_query: str | None = None
    queries: list[str] = field(default_factory=list)
    query_translations: list[dict[str, str]] = field(default_factory=list)
    candidate_pmids: list[str] = field(default_factory=list)
    evidence: str = ""
    evidence_mode: str = ""
    article_count: int = 0
    fulltext_n: int = 0
    with_abs: int = 0
    answer_text: str = ""
    suggestions: list[str] = field(default_factory=list)


_SESSIONS: dict[str, DebugSession] = {}


def _purge_expired() -> None:
    now = time.time()
    dead = [
        sid
        for sid, session in _SESSIONS.items()
        if now - session.updated_at > SESSION_TTL_S
    ]
    for sid in dead:
        _SESSIONS.pop(sid, None)


def get_session(session_id: str) -> DebugSession | None:
    _purge_expired()
    session = _SESSIONS.get(session_id)
    if session is None:
        return None
    session.updated_at = time.time()
    return session


def delete_session(session_id: str) -> bool:
    return _SESSIONS.pop(session_id, None) is not None


def create_session(settings: Settings, question: str) -> DebugSession:
    _purge_expired()
    question = (question or "").strip()
    if not question:
        raise ValueError("问题不能为空")
    session = DebugSession(
        id=uuid.uuid4().hex,
        question=question,
        settings=settings,
        standalone=question,
    )
    ctx = empty_context()
    session.steps["understand"] = {
        "id": "understand",
        "label": STEP_LABELS["understand"],
        "status": "pending",
        "prompts": {
            "system": UNDERSTAND_SYSTEM,
            "user": understand_user_message(question, ctx),
        },
        "input": {"question": question, "context": ctx},
        "output": None,
    }
    _SESSIONS[session.id] = session
    return session


def _step_meta() -> list[dict[str, str]]:
    return [{"id": sid, "label": STEP_LABELS[sid]} for sid in STEP_IDS]


def _article_metas(articles: list[Article]) -> list[dict[str, Any]]:
    return [a.to_meta() for a in articles]


def public_view(session: DebugSession) -> dict[str, Any]:
    step_views: dict[str, Any] = {}
    for sid in STEP_IDS:
        raw = session.steps.get(sid)
        if not raw:
            step_views[sid] = {
                "id": sid,
                "label": STEP_LABELS[sid],
                "status": "pending",
                "prompts": None,
                "input": None,
                "output": None,
            }
            continue
        step_views[sid] = {
            "id": sid,
            "label": STEP_LABELS[sid],
            "status": raw.get("status", "pending"),
            "prompts": raw.get("prompts"),
            "input": raw.get("input"),
            "output": raw.get("output"),
            "warning": raw.get("warning"),
        }
    return {
        "id": session.id,
        "question": session.question,
        "current_step": session.current_step,
        "status": session.status,
        "error": session.error,
        "steps_order": list(STEP_IDS),
        "steps_meta": _step_meta(),
        "steps": step_views,
        "query_translations": as_public(session.query_translations),
    }


def _ensure_runnable(session: DebugSession) -> None:
    if session.status == "running":
        raise RuntimeError("会话正在执行中，请稍候")
    if session.status == "done" and session.current_step == "suggest":
        # allow re-run of suggest
        pass


def _mark_downstream_stale(session: DebugSession, from_step: str) -> None:
    try:
        idx = STEP_IDS.index(from_step)
    except ValueError:
        return
    for sid in STEP_IDS[idx + 1 :]:
        if sid in session.steps:
            session.steps[sid]["status"] = "stale"


def _apply_understand_output(session: DebugSession, understood: dict[str, Any]) -> None:
    relation = understood["relation"]
    standalone = understood["standalone_question"]
    broad = list(understood["queries"])
    question_type = understood["question_type"]
    priority = (
        None if relation == "rephrase" else design_filter_query(broad, question_type)
    )
    queries = list(broad)
    if priority:
        queries.append(priority)
    session.relation = relation
    session.question_type = question_type
    session.standalone = standalone
    session.broad_queries = broad
    session.priority_query = priority
    session.queries = queries


async def _translate_for_session(
    session: DebugSession,
    llm: LLMClient,
    queries: list[str] | None = None,
) -> list[dict[str, str]]:
    target = [str(q).strip() for q in (queries if queries is not None else session.queries) if str(q).strip()]
    if not target:
        session.query_translations = []
        return []
    try:
        translations = await translate_pubmed_queries(llm, target)
    except Exception as exc:
        logger.warning("query_translate failed: %s", exc)
        translations = empty_translations(target)
        understand = session.steps.get("understand") or {}
        understand["warning"] = f"检索式翻译失败：{exc}"
        session.steps["understand"] = understand
        session.query_translations = translations
        return translations
    session.query_translations = translations
    return translations


async def run_current_step(
    session: DebugSession,
    *,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_runnable(session)
    overrides = overrides or {}
    step = session.current_step
    session.status = "running"
    session.error = None
    try:
        if step == "understand":
            await _run_understand(session, system_prompt, user_prompt)
        elif step == "search":
            await _run_search(session, overrides)
        elif step == "fulltext":
            await _run_fulltext(session, overrides)
        elif step == "passages":
            await _run_passages(session, overrides)
        elif step == "answer":
            await _run_answer(session, system_prompt, user_prompt)
        elif step == "suggest":
            await _run_suggest(session, system_prompt, user_prompt)
        else:
            raise RuntimeError(f"未知步骤：{step}")
        session.status = "done" if step == "suggest" else "paused"
        _mark_downstream_stale(session, step)
    except Exception as exc:
        logger.exception("debug_step_failed step=%s", step)
        session.status = "error"
        session.error = str(exc)
        cur = session.steps.setdefault(
            step,
            {"id": step, "label": STEP_LABELS.get(step, step)},
        )
        cur["status"] = "error"
        raise
    finally:
        session.updated_at = time.time()
    return public_view(session)


async def _run_understand(
    session: DebugSession,
    system_prompt: str | None,
    user_prompt: str | None,
) -> None:
    ctx = empty_context()
    system = system_prompt or UNDERSTAND_SYSTEM
    user = user_prompt or understand_user_message(session.question, ctx)
    session.steps["understand"] = {
        "id": "understand",
        "label": STEP_LABELS["understand"],
        "status": "running",
        "prompts": {"system": system, "user": user},
        "input": {"question": session.question, "context": ctx},
        "output": None,
    }
    async with LLMClient(session.settings) as llm:
        understood = await understand_turn(
            llm,
            session.question,
            ctx,
            system_prompt=system,
            user_prompt=user,
        )
        _apply_understand_output(session, understood)
        translations = await _translate_for_session(session, llm)
    output = {
        "relation": session.relation,
        "question_type": session.question_type,
        "standalone_question": session.standalone,
        "broad_queries": list(session.broad_queries),
        "priority_query": session.priority_query,
        "queries": list(session.queries),
        "query_translations": translations,
    }
    session.steps["understand"]["status"] = "done"
    session.steps["understand"]["output"] = output


async def _run_search(session: DebugSession, overrides: dict[str, Any]) -> None:
    if "queries" in overrides and isinstance(overrides["queries"], list):
        session.queries = [str(q).strip() for q in overrides["queries"] if str(q).strip()]
        broad, priority = split_search_queries(session.queries)
        session.broad_queries = broad
        session.priority_query = priority
    if not session.queries:
        raise RuntimeError("没有可用的检索式，请先完成问题理解步骤")
    prompts = None
    session.steps["search"] = {
        "id": "search",
        "label": STEP_LABELS["search"],
        "status": "running",
        "prompts": prompts,
        "input": {
            "queries": list(session.queries),
            "broad_queries": list(session.broad_queries),
            "priority_query": session.priority_query,
            "query_translations": as_public(session.query_translations),
        },
        "output": None,
    }
    async with PubMedClient(session.settings) as pubmed:
        articles = await run_pubmed_search(
            pubmed, session.broad_queries or session.queries, session.priority_query
        )
    if not articles:
        raise RuntimeError("未检索到相关文献，请修改检索式后重试")
    session.articles = articles
    session.steps["search"]["status"] = "done"
    session.steps["search"]["output"] = {
        "count": len(articles),
        "articles": _article_metas(articles),
    }


async def _run_fulltext(session: DebugSession, overrides: dict[str, Any]) -> None:
    if not session.articles:
        raise RuntimeError("没有文献，请先完成检索步骤")
    if "pmids" in overrides and isinstance(overrides["pmids"], list):
        keep = {str(p).strip() for p in overrides["pmids"] if str(p).strip()}
        session.articles = [a for a in session.articles if a.pmid in keep]
    candidate_pmids = None
    if "candidate_pmids" in overrides and isinstance(overrides["candidate_pmids"], list):
        candidate_pmids = [
            str(p).strip() for p in overrides["candidate_pmids"] if str(p).strip()
        ]
    if "question_type" in overrides and overrides["question_type"]:
        session.question_type = str(overrides["question_type"]).strip()

    if candidate_pmids is None:
        candidates = select_fulltext_candidates(
            session.articles,
            session.question_type,
            session.settings.fulltext_max_articles,
        )
        candidate_pmids = [c.pmid for c in candidates]

    session.steps["fulltext"] = {
        "id": "fulltext",
        "label": STEP_LABELS["fulltext"],
        "status": "running",
        "prompts": None,
        "input": {
            "question_type": session.question_type,
            "candidate_pmids": candidate_pmids,
            "article_count": len(session.articles),
        },
        "output": None,
    }
    async with PMCClient(session.settings) as pmc:
        fulltext_n, used_pmids = await run_fulltext(
            session.settings,
            pmc,
            session.articles,
            session.question_type,
            candidate_pmids,
        )
    session.candidate_pmids = used_pmids
    session.fulltext_n = fulltext_n
    session.steps["fulltext"]["status"] = "done"
    session.steps["fulltext"]["output"] = {
        "fulltext_n": fulltext_n,
        "candidate_pmids": used_pmids,
        "articles": _article_metas(session.articles),
    }


async def _run_passages(session: DebugSession, overrides: dict[str, Any]) -> None:
    if not session.articles:
        raise RuntimeError("没有文献，请先完成检索与全文步骤")
    if "standalone_question" in overrides and overrides["standalone_question"]:
        session.standalone = str(overrides["standalone_question"]).strip()
    session.steps["passages"] = {
        "id": "passages",
        "label": STEP_LABELS["passages"],
        "status": "running",
        "prompts": None,
        "input": {
            "standalone_question": session.standalone,
            "question_type": session.question_type,
            "rag_top_k": session.settings.rag_top_k,
            "chunk_size": session.settings.chunk_size,
            "chunk_overlap": session.settings.chunk_overlap,
        },
        "output": None,
    }
    async with LLMClient(session.settings) as llm:
        rag = await run_rag_passages(
            session.settings,
            llm,
            session.articles,
            session.standalone,
            session.question_type,
        )
    session.evidence = rag["evidence"]
    session.evidence_mode = rag["mode"]
    session.article_count = rag["article_count"]
    session.fulltext_n = rag["fulltext_n"]
    session.with_abs = rag["with_abs"]
    session.steps["passages"]["status"] = "done"
    session.steps["passages"]["output"] = {
        "mode": rag["mode"],
        "passages": rag["passages"],
        "evidence": rag["evidence"],
        "article_count": rag["article_count"],
        "fulltext_n": rag["fulltext_n"],
        "with_abs": rag["with_abs"],
    }


async def _run_answer(
    session: DebugSession,
    system_prompt: str | None,
    user_prompt: str | None,
) -> None:
    if not session.evidence and not session.articles:
        raise RuntimeError("没有证据文本，请先完成段落检索")
    ctx = empty_context()
    length_queries = session.broad_queries or session.queries
    target_chars = answer_target_chars(length_queries)
    max_tokens = answer_completion_tokens(
        length_queries,
        floor=4096,
        cap=session.settings.answer_max_tokens,
    )
    system = system_prompt or ANSWER_SYSTEM
    user = user_prompt or answer_user_message(
        question=session.question,
        standalone=session.standalone,
        queries=session.queries,
        evidence=session.evidence,
        mode=session.evidence_mode or "摘要",
        article_count=session.article_count or len(session.articles),
        fulltext_n=session.fulltext_n,
        with_abs=session.with_abs,
        ctx=ctx,
        target_chars=target_chars,
    )
    session.steps["answer"] = {
        "id": "answer",
        "label": STEP_LABELS["answer"],
        "status": "running",
        "prompts": {"system": system, "user": user},
        "input": {
            "standalone_question": session.standalone,
            "queries": list(session.queries),
            "evidence_chars": len(session.evidence),
            "target_chars": target_chars,
            "max_tokens": max_tokens,
        },
        "output": None,
    }
    async with LLMClient(session.settings) as llm:
        result = await llm.chat_result(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
    answer = result["content"]
    session.answer_text = answer
    session.steps["answer"]["status"] = "done"
    session.steps["answer"]["output"] = {
        "answer": answer,
        "finish_reason": result.get("finish_reason"),
        "truncated": bool(result.get("truncated")),
        "completion_tokens": (result.get("usage") or {}).get("completion_tokens"),
        "target_chars": target_chars,
        "answer_chars": len(answer),
        "max_tokens": max_tokens,
    }
    if result.get("truncated"):
        session.steps["answer"]["warning"] = (
            f"回答因达到 max_tokens={max_tokens} 被截断；"
            f"目标约 {target_chars} 字，可提高 ANSWER_MAX_TOKENS 后重新生成。"
        )


async def _run_suggest(
    session: DebugSession,
    system_prompt: str | None,
    user_prompt: str | None,
) -> None:
    if not session.answer_text.strip():
        raise RuntimeError("没有回答正文，请先完成生成回答步骤")
    system = system_prompt or SUGGEST_SYSTEM
    user = user_prompt or suggest_user_message(session.question, session.answer_text)
    session.steps["suggest"] = {
        "id": "suggest",
        "label": STEP_LABELS["suggest"],
        "status": "running",
        "prompts": {"system": system, "user": user},
        "input": {
            "question": session.question,
            "answer_chars": len(session.answer_text),
        },
        "output": None,
    }
    async with LLMClient(session.settings) as llm:
        questions = await suggest_followups(
            llm,
            session.question,
            session.answer_text,
            system_prompt=system,
            user_prompt=user,
        )
    session.suggestions = questions
    session.steps["suggest"]["status"] = "done"
    session.steps["suggest"]["output"] = {"questions": questions}


def patch_output(session: DebugSession, output: dict[str, Any]) -> dict[str, Any]:
    _ensure_runnable(session)
    step = session.current_step
    cur = session.steps.get(step)
    if cur is None or cur.get("output") is None:
        raise RuntimeError("当前步骤尚无输出可修改，请先运行本步")

    if step == "understand":
        _patch_understand(session, cur, output)
    elif step == "search":
        _patch_search(session, cur, output)
    elif step == "fulltext":
        _patch_fulltext(session, cur, output)
    elif step == "passages":
        _patch_passages(session, cur, output)
    elif step == "answer":
        answer = str(output.get("answer") or "").strip()
        if not answer:
            raise ValueError("answer 不能为空")
        session.answer_text = answer
        prev = cur.get("output") if isinstance(cur.get("output"), dict) else {}
        cur["output"] = {
            **prev,
            "answer": answer,
            "answer_chars": len(answer),
            "truncated": False,
        }
        if cur.get("warning") and "截断" in str(cur.get("warning")):
            cur["warning"] = None
    elif step == "suggest":
        questions = output.get("questions")
        if not isinstance(questions, list):
            raise ValueError("questions 必须是数组")
        cleaned = [str(q).strip() for q in questions if str(q).strip()][:3]
        session.suggestions = cleaned
        cur["output"] = {"questions": cleaned}
    else:
        raise RuntimeError(f"未知步骤：{step}")

    cur["status"] = "done"
    session.status = "paused"
    _mark_downstream_stale(session, step)
    session.updated_at = time.time()
    return public_view(session)


def _patch_understand(
    session: DebugSession, cur: dict[str, Any], output: dict[str, Any]
) -> None:
    relation = str(output.get("relation") or session.relation).strip() or "new_topic"
    question_type = (
        str(output.get("question_type") or session.question_type).strip() or "other"
    )
    standalone = (
        str(output.get("standalone_question") or session.standalone).strip()
        or session.question
    )
    if "queries" in output and isinstance(output["queries"], list):
        queries = [str(q).strip() for q in output["queries"] if str(q).strip()]
        broad, priority = split_search_queries(queries)
    else:
        broad = [
            str(q).strip()
            for q in (output.get("broad_queries") or session.broad_queries)
            if str(q).strip()
        ]
        priority = output.get("priority_query", session.priority_query)
        priority = str(priority).strip() if priority else None
        queries = list(broad)
        if priority:
            queries.append(priority)
    session.relation = relation
    session.question_type = question_type
    session.standalone = standalone
    session.broad_queries = broad
    session.priority_query = priority
    session.queries = queries
    translations = as_public(output.get("query_translations") or session.query_translations)
    # Realign translations to current queries when possible
    zh_by_q = {t["query"]: t["zh"] for t in translations}
    session.query_translations = [
        {"query": q, "zh": zh_by_q.get(q, "")} for q in queries
    ]
    cur["output"] = {
        "relation": relation,
        "question_type": question_type,
        "standalone_question": standalone,
        "broad_queries": list(broad),
        "priority_query": priority,
        "queries": list(queries),
        "query_translations": as_public(session.query_translations),
    }


def _patch_search(
    session: DebugSession, cur: dict[str, Any], output: dict[str, Any]
) -> None:
    articles_meta = output.get("articles")
    if not isinstance(articles_meta, list):
        raise ValueError("articles 必须是数组")
    keep = {
        str(item.get("pmid")).strip()
        for item in articles_meta
        if isinstance(item, dict) and str(item.get("pmid") or "").strip()
    }
    if not keep:
        raise ValueError("至少保留一篇文献")
    session.articles = [a for a in session.articles if a.pmid in keep]
    # Preserve user order from meta when possible
    by_pmid = {a.pmid: a for a in session.articles}
    ordered: list[Article] = []
    for item in articles_meta:
        if not isinstance(item, dict):
            continue
        pmid = str(item.get("pmid") or "").strip()
        if pmid in by_pmid and by_pmid[pmid] not in ordered:
            ordered.append(by_pmid[pmid])
    session.articles = ordered or session.articles
    cur["output"] = {
        "count": len(session.articles),
        "articles": _article_metas(session.articles),
    }


def _patch_fulltext(
    session: DebugSession, cur: dict[str, Any], output: dict[str, Any]
) -> None:
    articles_meta = output.get("articles")
    if isinstance(articles_meta, list):
        keep = {
            str(item.get("pmid")).strip()
            for item in articles_meta
            if isinstance(item, dict) and str(item.get("pmid") or "").strip()
        }
        if keep:
            session.articles = [a for a in session.articles if a.pmid in keep]
    if "candidate_pmids" in output and isinstance(output["candidate_pmids"], list):
        session.candidate_pmids = [
            str(p).strip() for p in output["candidate_pmids"] if str(p).strip()
        ]
    if "fulltext_n" in output:
        try:
            session.fulltext_n = int(output["fulltext_n"])
        except (TypeError, ValueError):
            pass
    cur["output"] = {
        "fulltext_n": session.fulltext_n,
        "candidate_pmids": list(session.candidate_pmids),
        "articles": _article_metas(session.articles),
    }


def _patch_passages(
    session: DebugSession, cur: dict[str, Any], output: dict[str, Any]
) -> None:
    evidence = output.get("evidence")
    if evidence is not None:
        session.evidence = str(evidence)
    passages = output.get("passages")
    if passages is not None and not isinstance(passages, list):
        raise ValueError("passages 必须是数组")
    mode = str(output.get("mode") or session.evidence_mode or "摘要")
    session.evidence_mode = mode
    if "article_count" in output:
        try:
            session.article_count = int(output["article_count"])
        except (TypeError, ValueError):
            pass
    if "fulltext_n" in output:
        try:
            session.fulltext_n = int(output["fulltext_n"])
        except (TypeError, ValueError):
            pass
    if "with_abs" in output:
        try:
            session.with_abs = int(output["with_abs"])
        except (TypeError, ValueError):
            pass
    prev = cur.get("output") if isinstance(cur.get("output"), dict) else {}
    cur["output"] = {
        "mode": mode,
        "passages": passages if isinstance(passages, list) else prev.get("passages", []),
        "evidence": session.evidence,
        "article_count": session.article_count,
        "fulltext_n": session.fulltext_n,
        "with_abs": session.with_abs,
    }


def advance(session: DebugSession) -> dict[str, Any]:
    _ensure_runnable(session)
    step = session.current_step
    cur = session.steps.get(step)
    if not cur or cur.get("output") is None:
        raise RuntimeError("当前步骤尚无输出，请先运行或保存输出")
    try:
        idx = STEP_IDS.index(step)
    except ValueError as exc:
        raise RuntimeError(f"未知步骤：{step}") from exc
    if idx >= len(STEP_IDS) - 1:
        session.status = "done"
        session.updated_at = time.time()
        return public_view(session)
    next_step = STEP_IDS[idx + 1]
    session.current_step = next_step
    session.status = "idle"
    session.error = None
    # Seed next step prompts/input preview
    _seed_next_step(session, next_step)
    session.updated_at = time.time()
    return public_view(session)


def _seed_next_step(session: DebugSession, step: str) -> None:
    existing = session.steps.get(step)
    if (
        existing
        and existing.get("status") == "done"
        and existing.get("output") is not None
    ):
        # Keep a previously completed step until user re-runs it.
        return
    if step == "search":
        session.steps["search"] = {
            "id": "search",
            "label": STEP_LABELS["search"],
            "status": "pending",
            "prompts": None,
            "input": {
                "queries": list(session.queries),
                "broad_queries": list(session.broad_queries),
                "priority_query": session.priority_query,
                "query_translations": as_public(session.query_translations),
            },
            "output": None,
        }
    elif step == "fulltext":
        candidates = select_fulltext_candidates(
            session.articles,
            session.question_type,
            session.settings.fulltext_max_articles,
        )
        session.steps["fulltext"] = {
            "id": "fulltext",
            "label": STEP_LABELS["fulltext"],
            "status": "pending",
            "prompts": None,
            "input": {
                "question_type": session.question_type,
                "candidate_pmids": [c.pmid for c in candidates],
                "article_count": len(session.articles),
            },
            "output": None,
        }
    elif step == "passages":
        session.steps["passages"] = {
            "id": "passages",
            "label": STEP_LABELS["passages"],
            "status": "pending",
            "prompts": None,
            "input": {
                "standalone_question": session.standalone,
                "question_type": session.question_type,
                "rag_top_k": session.settings.rag_top_k,
                "chunk_size": session.settings.chunk_size,
                "chunk_overlap": session.settings.chunk_overlap,
            },
            "output": None,
        }
    elif step == "answer":
        ctx = empty_context()
        length_queries = session.broad_queries or session.queries
        target_chars = answer_target_chars(length_queries)
        max_tokens = answer_completion_tokens(
            length_queries,
            floor=4096,
            cap=session.settings.answer_max_tokens,
        )
        system = ANSWER_SYSTEM
        user = answer_user_message(
            question=session.question,
            standalone=session.standalone,
            queries=session.queries,
            evidence=session.evidence,
            mode=session.evidence_mode or "摘要",
            article_count=session.article_count or len(session.articles),
            fulltext_n=session.fulltext_n,
            with_abs=session.with_abs,
            ctx=ctx,
            target_chars=target_chars,
        )
        session.steps["answer"] = {
            "id": "answer",
            "label": STEP_LABELS["answer"],
            "status": "pending",
            "prompts": {"system": system, "user": user},
            "input": {
                "standalone_question": session.standalone,
                "queries": list(session.queries),
                "evidence_chars": len(session.evidence),
                "target_chars": target_chars,
                "max_tokens": max_tokens,
            },
            "output": None,
        }
    elif step == "suggest":
        session.steps["suggest"] = {
            "id": "suggest",
            "label": STEP_LABELS["suggest"],
            "status": "pending",
            "prompts": {
                "system": SUGGEST_SYSTEM,
                "user": suggest_user_message(session.question, session.answer_text),
            },
            "input": {
                "question": session.question,
                "answer_chars": len(session.answer_text),
            },
            "output": None,
        }


async def translate_queries(
    session: DebugSession,
    queries: list[str] | None = None,
) -> dict[str, Any]:
    _ensure_runnable(session)
    session.status = "running"
    try:
        if queries is not None:
            cleaned = [str(q).strip() for q in queries if str(q).strip()]
            session.queries = cleaned
            broad, priority = split_search_queries(cleaned)
            session.broad_queries = broad
            session.priority_query = priority
        async with LLMClient(session.settings) as llm:
            translations = await _translate_for_session(session, llm)
        understand = session.steps.get("understand")
        if understand and isinstance(understand.get("output"), dict):
            understand["output"]["queries"] = list(session.queries)
            understand["output"]["broad_queries"] = list(session.broad_queries)
            understand["output"]["priority_query"] = session.priority_query
            understand["output"]["query_translations"] = translations
            understand["warning"] = None
        search = session.steps.get("search")
        if search and isinstance(search.get("input"), dict):
            search["input"]["queries"] = list(session.queries)
            search["input"]["query_translations"] = translations
        session.status = "paused"
    except Exception:
        session.status = "error"
        raise
    finally:
        session.updated_at = time.time()
    return public_view(session)
