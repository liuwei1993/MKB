from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from .config import Settings
from .pubmed import Article, _normalize_pmcid, is_retracted

logger = logging.getLogger(__name__)

BIOC_BASE = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# A short token before a period is an abbreviation, not the end of a sentence.
_ABBREVS = {
    "al",
    "approx",
    "ca",
    "cf",
    "co",
    "dept",
    "dr",
    "ed",
    "eds",
    "eq",
    "eqs",
    "fig",
    "figs",
    "gen",
    "inc",
    "jr",
    "ltd",
    "mr",
    "mrs",
    "ms",
    "mt",
    "no",
    "nos",
    "pp",
    "prof",
    "sr",
    "st",
    "vol",
    "vs",
}
_CITE_RUN = (
    r"\d{1,3}(?:\s*[-–—]\s*\d{1,3})?"
    r"(?:(?:\s*[,，、;；]\s*|\s+)\d{1,3}(?:\s*[-–—]\s*\d{1,3})?)*"
)
_BRACKET_CITE = re.compile(
    r"\s*[\[［]\s*\d{1,3}(?:\s*[-–—,~，、;；]\s*\d{1,3})*\s*[\]］]"
)
_PAREN_CITE = re.compile(
    r"\s*[（(]\s*\d{1,3}(?:\s*[,，、;；]\s*\d{1,3})+\s*[)）]"
)
_AFTER_PUNCT = re.compile(
    rf"(?P<word>[A-Za-z]{{0,12}})(?<!\d)"
    rf"(?P<punct>[.!?。！？,，;；:：])\s+"
    rf"(?P<run>{_CITE_RUN})"
    rf"(?=\s|$|[\u4e00-\u9fff])"
)
_THOUSAND_SEP = r"[ \u00a0\u202f\u2009]"

# BioC passage `type` values that are usually not useful for RAG
_SKIP_TYPES = {
    "ref",
    "references",
    "bibliography",
    "ack",
    "acknowledgement",
    "acknowledgments",
    "fn",
    "footnote",
    "table_caption",
    "fig_caption",
    "title",  # article title often duplicated
    "front",
}

_SECTION_ALIASES = {
    "intro": "intro",
    "introduction": "intro",
    "background": "intro",
    "methods": "methods",
    "method": "methods",
    "materials": "methods",
    "materials_and_methods": "methods",
    "materialsandmethods": "methods",
    "results": "results",
    "result": "results",
    "discuss": "discuss",
    "discussion": "discuss",
    "concl": "discuss",
    "conclusion": "discuss",
    "conclusions": "discuss",
    "abstract": "abstract",
}


def normalize_section(raw: str) -> str:
    """Map BioC section_type to a small set of keys; empty means unknown."""
    key = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return ""
    return _SECTION_ALIASES.get(key, "other")


def join_paragraphs(paras: list[tuple[str, str]]) -> str:
    return "\n\n".join(text for _section, text in paras if text.strip())


def _truncate_paragraphs(
    paras: list[tuple[str, str]], max_chars: int
) -> list[tuple[str, str]]:
    if max_chars <= 0 or not paras:
        return []
    out: list[tuple[str, str]] = []
    used = 0
    for section, text in paras:
        text = text.strip()
        if not text:
            continue
        gap = 2 if out else 0
        if used + gap >= max_chars:
            break
        room = max_chars - used - gap
        if len(text) <= room:
            out.append((section, text))
            used += gap + len(text)
            continue
        clipped = text[: max(0, room - 1)].rstrip() + "…"
        if clipped.strip("…"):
            out.append((section, clipped))
        break
    return out


class PMCClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> PMCClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.settings.pubmed_timeout)
        return self

    async def __aexit__(self, *args) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    def _auth_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.settings.ncbi_email:
            params["email"] = self.settings.ncbi_email
        if self.settings.ncbi_api_key:
            params["api_key"] = self.settings.ncbi_api_key
        return params

    async def fetch_fulltext_paras(
        self, pmcid: str
    ) -> list[tuple[str, str]] | None:
        """Fetch OA full-text paragraphs as (section, text); None if unavailable."""
        pmc = _normalize_pmcid(pmcid)
        if not pmc:
            return None
        paras = await self._fetch_bioc(pmc)
        if not paras:
            paras = await self._fetch_pmc_xml(pmc)
        if not paras:
            return None
        return _truncate_paragraphs(paras, self.settings.fulltext_max_chars) or None

    async def fetch_fulltext(self, pmcid: str) -> str | None:
        """Fetch OA full text; return None if unavailable."""
        paras = await self.fetch_fulltext_paras(pmcid)
        if not paras:
            return None
        return join_paragraphs(paras) or None

    async def attach_fulltexts(
        self,
        articles: list[Article],
        candidates: list[Article] | None = None,
    ) -> int:
        """
        Fetch OA full text for the given candidates, or the first
        fulltext_max_articles with a PMCID when candidates is omitted.
        Mutates articles in place. Returns count successfully fetched.
        """
        limit = self.settings.fulltext_max_articles
        all_with_pmcid = [
            a
            for a in articles
            if _normalize_pmcid(a.pmcid) and not is_retracted(a)
        ]
        if candidates is None:
            candidates = all_with_pmcid[:limit]
        t0 = time.perf_counter()
        if not candidates:
            logger.info("pmc_fulltext candidates=0 limit=%d (无 PMCID 命中)", limit)
            return 0

        sem = asyncio.Semaphore(3)

        async def one(article: Article) -> bool:
            async with sem:
                try:
                    paras = await self.fetch_fulltext_paras(article.pmcid)
                except Exception:
                    paras = None
                await asyncio.sleep(0.12)
                if paras:
                    article.fulltext_paras = paras
                    article.fulltext = join_paragraphs(paras)
                    article.has_fulltext = True
                    return True
                return False

        results = await asyncio.gather(*(one(a) for a in candidates))
        fetched = sum(1 for r in results if r)
        total_chars = sum(len(a.fulltext) for a in candidates if a.has_fulltext)
        elapsed = time.perf_counter() - t0
        # 评估 FULLTEXT_MAX_ARTICLES：cap 被打满说明调大有收益空间
        if len(all_with_pmcid) > len(candidates):
            logger.warning(
                "pmc_fulltext cap 打满: 有 PMCID 的文章 %d 篇，仅抓取 %d 篇"
                " (FULLTEXT_MAX_ARTICLES=%d)，调大该参数可覆盖更多全文",
                len(all_with_pmcid), len(candidates), limit,
            )
        logger.info(
            "pmc_fulltext limit=%d candidates=%d fetched=%d failed=%d "
            "fulltext_chars=%d elapsed=%.2fs",
            limit,
            len(candidates),
            fetched,
            len(candidates) - fetched,
            total_chars,
            elapsed,
        )
        return fetched

    async def _fetch_bioc(self, pmcid: str) -> list[tuple[str, str]] | None:
        assert self._client is not None
        # API accepts PMCID with or without PMC prefix
        url = f"{BIOC_BASE}/{pmcid}/unicode"
        try:
            r = await self._client.get(url)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        ctype = r.headers.get("content-type", "")
        body = r.text.strip()
        if not body or body.lower().startswith("<!doctype") or "not found" in body.lower()[:200]:
            return None
        try:
            data = r.json()
        except Exception:
            if "json" not in ctype and not body.startswith("{") and not body.startswith("["):
                return None
            return None
        return _parse_bioc(data)

    async def _fetch_pmc_xml(self, pmcid: str) -> list[tuple[str, str]] | None:
        assert self._client is not None
        # efetch wants numeric id without PMC prefix
        numeric = pmcid[3:] if pmcid.upper().startswith("PMC") else pmcid
        params = {
            **self._auth_params(),
            "db": "pmc",
            "id": numeric,
            "retmode": "xml",
        }
        try:
            r = await self._client.get(f"{EUTILS}/efetch.fcgi", params=params)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        return _parse_pmc_xml(r.text)


def _is_thousands(run: str) -> bool:
    """True for one number written with groups of three digits, such as 26 145."""
    parts = re.split(_THOUSAND_SEP + "+", run.strip())
    if len(parts) < 2 or any(not part.isdigit() for part in parts):
        return False
    return all(len(part) == 3 for part in parts[1:])


def _keep_citation_run(text: str, match: re.Match[str]) -> bool:
    word = match.group("word")
    if word:
        start = match.start("word")
        if (start == 0 or not text[start - 1].isalpha()) and word.lower() in _ABBREVS:
            return True
    if _is_thousands(match.group("run")):
        return True
    nxt = re.match(r"\s*(\S)", text[match.end() :])
    if nxt is None:
        return False
    ch = nxt.group(1)
    if ch.isdigit() or ch in "%‰/":
        return True
    return ch.isascii() and ch.islower()


def strip_inline_citations(text: str) -> str:
    """Drop bibliography markers that were flattened into the prose.

    Keeps ages, measurements, percentages, and numbers grouped by thousands.
    """
    if not text:
        return text
    source = _PAREN_CITE.sub("", _BRACKET_CITE.sub("", text))

    def repl(match: re.Match[str]) -> str:
        if _keep_citation_run(source, match):
            return match.group(0)
        return f"{match.group('word')}{match.group('punct')} "

    cleaned = _AFTER_PUNCT.sub(repl, source)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", cleaned)
    return cleaned.strip()


def _remove_keep_tail(parent: ET.Element, child: ET.Element) -> None:
    """Remove an element without discarding the sentence that follows it."""
    tail = child.tail or ""
    children = list(parent)
    index = children.index(child)
    if tail:
        if index == 0:
            parent.text = (parent.text or "") + tail
        else:
            prev = children[index - 1]
            prev.tail = (prev.tail or "") + tail
    parent.remove(child)


def _is_bibr_xref(el: ET.Element) -> bool:
    return el.tag == "xref" and (el.get("ref-type") or "").lower() == "bibr"


def _previous_text(parent: ET.Element, el: ET.Element) -> str:
    children = list(parent)
    index = children.index(el)
    if index == 0:
        return parent.text or ""
    prev = children[index - 1]
    if prev.tail:
        return prev.tail
    return "".join(prev.itertext())


def _is_citation_sup(parent: ET.Element, el: ET.Element) -> bool:
    if el.tag != "sup" or parent.tag == "xref":
        return False
    inner = "".join(el.itertext()).strip()
    if not re.fullmatch(r"\d{1,3}(?:\s*[-–—,]\s*\d{1,3})*", inner):
        return False
    prev = _previous_text(parent, el)
    return not (prev and prev[-1].isdigit())


def _drop_citation_markers(root: ET.Element) -> None:
    for parent in list(root.iter()):
        for child in list(parent):
            if _is_bibr_xref(child):
                _remove_keep_tail(parent, child)
    for parent in list(root.iter()):
        for child in list(parent):
            if _is_citation_sup(parent, child):
                _remove_keep_tail(parent, child)


def _parse_bioc(data: Any) -> list[tuple[str, str]] | None:
    """Extract body paragraphs from BioC JSON as (section, text) pairs."""
    documents: list[dict] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                docs = item.get("documents") or []
                if isinstance(docs, list):
                    documents.extend(d for d in docs if isinstance(d, dict))
                elif "passages" in item:
                    documents.append(item)
    elif isinstance(data, dict):
        docs = data.get("documents") or []
        if isinstance(docs, list):
            documents.extend(d for d in docs if isinstance(d, dict))
        elif "passages" in data:
            documents.append(data)

    paragraphs: list[tuple[str, str]] = []
    for doc in documents:
        for passage in doc.get("passages") or []:
            if not isinstance(passage, dict):
                continue
            text = strip_inline_citations((passage.get("text") or "").strip())
            if not text:
                continue
            infons = passage.get("infons") or {}
            passage_type = str(infons.get("type") or "").lower()
            raw_section = str(
                infons.get("section_type") or infons.get("section") or ""
            ).lower()
            skip_key = passage_type or raw_section
            if skip_key in _SKIP_TYPES:
                continue
            if passage_type.startswith("title"):
                continue
            if "ref" in skip_key and skip_key != "abstract":
                continue
            paragraphs.append((normalize_section(raw_section), text))

    return paragraphs or None


def _parse_pmc_xml(xml_text: str) -> list[tuple[str, str]] | None:
    """Extract body paragraphs; section is empty (XML fallback has weak structure)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    # Drop reference lists
    for tag in ("ref-list", "ack", "fn-group", "footnote"):
        for el in list(root.iter(tag)):
            parent = _find_parent(root, el)
            if parent is not None:
                parent.remove(el)

    body = root.find(".//body")
    target = body if body is not None else root
    _drop_citation_markers(target)
    parts: list[tuple[str, str]] = []
    for p in target.iter("p"):
        text = strip_inline_citations(re.sub(r"\s+", " ", "".join(p.itertext())).strip())
        if text:
            parts.append(("", text))
    if not parts:
        # Fallback: all text
        text = strip_inline_citations(
            re.sub(r"\s+", " ", "".join(target.itertext())).strip()
        )
        return [("", text)] if text else None
    return parts


def _find_parent(root: ET.Element, child: ET.Element) -> ET.Element | None:
    for parent in root.iter():
        if child in list(parent):
            return parent
    return None
