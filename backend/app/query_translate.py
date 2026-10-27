from __future__ import annotations

import json
import logging
import re
from typing import Any

from .llm import LLMClient

logger = logging.getLogger(__name__)

QUERY_TRANSLATE_SYSTEM = """你是医学信息检索助手。把用户给出的 PubMed 英文检索式译成便于人读的中文释义（不是可执行检索式）。
规则：
1. 保留大写布尔运算符 AND、OR、NOT，以及括号层级。
2. 医学术语、研究设计/文献类型等一律译成常用中文，不要在 zh 里原样保留英文短语。
3. zh 中去掉 PubMed 语法噪音：字段标签（如 [pt]、[MeSH Terms]、[Title/Abstract]）、包裹术语的英文引号。
4. 常见文献类型对照：systematic review→系统综述；meta-analysis→荟萃分析；network meta-analysis→网状荟萃分析；guideline→指南；practice guideline→实践指南；randomized controlled trial→随机对照试验；observational study→观察性研究；validation study→验证研究；evaluation study→评价研究。
5. 示例：输入
(smoking AND cardiovascular disease) AND ("systematic review"[pt] OR "meta-analysis"[pt] OR "observational study"[pt])
对应 zh 应为：
（吸烟 AND 心血管疾病）AND（系统综述 OR 荟萃分析 OR 观察性研究）
6. 只返回 JSON，不要 markdown，不要解释：
{"translations":[{"query":"原文检索式","zh":"中文释义"}, ...]}
7. translations 必须与输入 queries 等长、同序；query 字段原样回传输入中的字符串。"""

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _extract_json_obj(raw: str) -> dict | None:
    text = (raw or "").strip()
    fence = _FENCE.search(text)
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


def parse_query_translations(raw: str, queries: list[str]) -> list[dict[str, str]]:
    """Parse model output into [{query, zh}] aligned to queries."""
    fallback = [{"query": q, "zh": ""} for q in queries]
    data = _extract_json_obj(raw)
    if not data:
        return fallback
    items = data.get("translations")
    if not isinstance(items, list):
        return fallback
    by_query: dict[str, str] = {}
    ordered: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        zh = str(item.get("zh") or "").strip()
        if not query:
            continue
        if query not in by_query:
            ordered.append(query)
        by_query[query] = zh
    out: list[dict[str, str]] = []
    for q in queries:
        if q in by_query:
            out.append({"query": q, "zh": by_query[q]})
        elif ordered:
            # Fall back to positional match when model rewrote the query string.
            idx = len(out)
            if idx < len(ordered):
                out.append({"query": q, "zh": by_query.get(ordered[idx], "")})
            else:
                out.append({"query": q, "zh": ""})
        else:
            out.append({"query": q, "zh": ""})
    return out


async def translate_pubmed_queries(
    llm: LLMClient,
    queries: list[str],
    *,
    system_prompt: str | None = None,
) -> list[dict[str, str]]:
    cleaned = [str(q).strip() for q in queries if str(q).strip()]
    if not cleaned:
        return []
    payload = json.dumps({"queries": cleaned}, ensure_ascii=False)
    raw = await llm.chat(
        [
            {"role": "system", "content": system_prompt or QUERY_TRANSLATE_SYSTEM},
            {
                "role": "user",
                "content": f"请翻译下列 PubMed 检索式：\n{payload}",
            },
        ],
        max_tokens=4096,
        temperature=0.1,
    )
    return parse_query_translations(raw, cleaned)


def empty_translations(queries: list[str]) -> list[dict[str, str]]:
    return [{"query": q, "zh": ""} for q in queries if str(q).strip()]


def as_public(translations: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not translations:
        return out
    for item in translations:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        out.append({"query": query, "zh": str(item.get("zh") or "").strip()})
    return out
