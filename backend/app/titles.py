from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

BATCH_SIZE = 15
MAX_ARTICLES = 50

_HAN = re.compile(r"[\u4e00-\u9fff]")

TRANSLATE_SYSTEM = (
    "将下列英文学术论文标题译为准确、简洁的中文。"
    "保留药物名、基因名等专有名词的英文缩写。"
    "只输出一个 JSON 对象，键为 pmid，值为中文标题。不要解释。"
)


def needs_translation(title: str) -> bool:
    text = (title or "").strip()
    if not text:
        return False
    return _HAN.search(text) is None


def parse_title_json(raw: str, allowed: set[str]) -> dict[str, str]:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        pmid = str(key).strip()
        if pmid not in allowed or not isinstance(value, str):
            continue
        zh = value.strip()
        if zh:
            out[pmid] = zh
    return out


async def translate_titles(llm, articles: list[dict]) -> dict[str, str]:
    english: list[dict[str, str]] = []
    seen: set[str] = set()
    for article in articles[:MAX_ARTICLES]:
        pmid = str(article.get("pmid") or "").strip()
        title = str(article.get("title") or "").strip()
        if not pmid or pmid in seen or not needs_translation(title):
            continue
        seen.add(pmid)
        english.append({"pmid": pmid, "title": title})

    titles: dict[str, str] = {}
    for i in range(0, len(english), BATCH_SIZE):
        batch = english[i : i + BATCH_SIZE]
        allowed = {item["pmid"] for item in batch}
        try:
            raw = await llm.chat(
                [
                    {"role": "system", "content": TRANSLATE_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(batch, ensure_ascii=False),
                    },
                ],
                temperature=0,
                max_tokens=2048,
            )
        except Exception:
            logger.warning("title batch failed", exc_info=True)
            continue
        parsed = parse_title_json(raw, allowed)
        for item in batch:
            zh = parsed.get(item["pmid"], "")
            if zh and zh != item["title"] and _HAN.search(zh):
                titles[item["pmid"]] = zh
    return titles
