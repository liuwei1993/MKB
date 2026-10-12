from __future__ import annotations

import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

BATCH_SIZE = 8
RETRY_BATCH_SIZE = 4
TRANSLATE_CONCURRENCY = 2
MAX_ARTICLES = 100
_CACHE_MAX = 4000

_HAN = re.compile(r"[\u4e00-\u9fff]")
_PAIR = re.compile(r'"(\d{1,16})"\s*:\s*"((?:[^"\\]|\\.)*)"')
_TITLE_CACHE: dict[tuple[str, str], str] = {}

TRANSLATE_SYSTEM = (
    "将下列英文学术论文标题译为准确、简洁的中文。"
    "保留药物名、基因名等专有名词的英文缩写。"
    "只输出一个 JSON 对象，键为 pmid，值为中文标题。不要解释。"
)


def clear_title_cache() -> None:
    _TITLE_CACHE.clear()


def needs_translation(title: str) -> bool:
    text = (title or "").strip()
    if not text:
        return False
    return _HAN.search(text) is None


def _put(out: dict[str, str], pmid: str, value: object, allowed: set[str]) -> None:
    if pmid not in allowed or not isinstance(value, str):
        return
    zh = value.strip()
    if zh:
        out[pmid] = zh


def _map_payload(data: object, allowed: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            _put(out, str(key).strip(), value, allowed)
        return out
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            pmid = item.get("pmid", item.get("id", ""))
            title = item.get("title", item.get("zh", ""))
            _put(out, str(pmid).strip(), title, allowed)
    return out


def _load_json_value(text: str) -> object | None:
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj < 0 and start_arr < 0:
        return None
    if start_arr >= 0 and (start_obj < 0 or start_arr < start_obj):
        start, closing = start_arr, "]"
    else:
        start, closing = start_obj, "}"
    end = text.rfind(closing)
    if end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _salvage_pairs(text: str, allowed: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in _PAIR.finditer(text):
        raw_val = match.group(2)
        try:
            value = json.loads(f'"{raw_val}"')
        except json.JSONDecodeError:
            value = raw_val
        _put(out, match.group(1), value, allowed)
    return out


def parse_title_json(raw: str, allowed: set[str]) -> dict[str, str]:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    loaded = _load_json_value(text)
    if loaded is not None:
        return _map_payload(loaded, allowed)
    return _salvage_pairs(text, allowed)


def _accept(batch: list[dict[str, str]], parsed: dict[str, str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for item in batch:
        zh = parsed.get(item["pmid"], "")
        if zh and zh != item["title"] and _HAN.search(zh):
            titles[item["pmid"]] = zh
    return titles


def _remember(pmid: str, title: str, zh: str) -> None:
    key = (pmid, title)
    if len(_TITLE_CACHE) >= _CACHE_MAX and key not in _TITLE_CACHE:
        _TITLE_CACHE.pop(next(iter(_TITLE_CACHE)))
    _TITLE_CACHE[key] = zh


async def _one_batch(llm, batch: list[dict[str, str]]) -> dict[str, str]:
    allowed = {item["pmid"] for item in batch}
    try:
        raw = await llm.chat(
            [
                {"role": "system", "content": TRANSLATE_SYSTEM},
                {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=2048,
        )
    except Exception:
        logger.warning("title batch failed", exc_info=True)
        return {}
    return _accept(batch, parse_title_json(raw, allowed))


async def translate_titles(llm, articles: list[dict]) -> dict[str, str]:
    english: list[dict[str, str]] = []
    seen: set[str] = set()
    cached: dict[str, str] = {}
    for article in articles[:MAX_ARTICLES]:
        pmid = str(article.get("pmid") or "").strip()
        title = str(article.get("title") or "").strip()
        if not pmid or pmid in seen or not needs_translation(title):
            continue
        seen.add(pmid)
        hit = _TITLE_CACHE.get((pmid, title))
        if hit:
            cached[pmid] = hit
            continue
        english.append({"pmid": pmid, "title": title})

    if not english:
        return cached

    sem = asyncio.Semaphore(TRANSLATE_CONCURRENCY)

    async def run(batch: list[dict[str, str]]) -> dict[str, str]:
        async with sem:
            return await _one_batch(llm, batch)

    batches = [english[i : i + BATCH_SIZE] for i in range(0, len(english), BATCH_SIZE)]
    titles = dict(cached)
    for part in await asyncio.gather(*(run(batch) for batch in batches)):
        titles.update(part)

    missing = [item for item in english if item["pmid"] not in titles]
    if missing:
        retry_batches = [
            missing[i : i + RETRY_BATCH_SIZE]
            for i in range(0, len(missing), RETRY_BATCH_SIZE)
        ]
        for part in await asyncio.gather(*(run(batch) for batch in retry_batches)):
            titles.update(part)

    fresh = {item["pmid"]: item["title"] for item in english}
    for pmid, zh in titles.items():
        title = fresh.get(pmid)
        if title and pmid not in cached:
            _remember(pmid, title, zh)
    logger.info(
        "title_translate requested=%d cache_hit=%d returned=%d",
        len(english) + len(cached),
        len(cached),
        len(titles),
    )
    return titles
