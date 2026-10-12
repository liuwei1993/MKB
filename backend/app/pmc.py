from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from .config import Settings
from .pubmed import Article, _normalize_pmcid

logger = logging.getLogger(__name__)

BIOC_BASE = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# BioC section types that are usually not useful for RAG
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
}


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

    async def fetch_fulltext(self, pmcid: str) -> str | None:
        """Fetch OA full text; return None if unavailable."""
        pmc = _normalize_pmcid(pmcid)
        if not pmc:
            return None
        text = await self._fetch_bioc(pmc)
        if not text:
            text = await self._fetch_pmc_xml(pmc)
        if not text:
            return None
        max_chars = self.settings.fulltext_max_chars
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        return text.strip() or None

    async def attach_fulltexts(self, articles: list[Article]) -> int:
        """
        Fetch OA full text for up to fulltext_max_articles with pmcid.
        Mutates articles in place. Returns count successfully fetched.
        """
        limit = self.settings.fulltext_max_articles
        all_with_pmcid = [a for a in articles if _normalize_pmcid(a.pmcid)]
        candidates = all_with_pmcid[:limit]
        t0 = time.perf_counter()
        if not candidates:
            logger.info("pmc_fulltext candidates=0 limit=%d (无 PMCID 命中)", limit)
            return 0

        sem = asyncio.Semaphore(3)

        async def one(article: Article) -> bool:
            async with sem:
                try:
                    text = await self.fetch_fulltext(article.pmcid)
                except Exception:
                    text = None
                await asyncio.sleep(0.12)
                if text:
                    article.fulltext = text
                    article.has_fulltext = True
                    return True
                return False

        results = await asyncio.gather(*(one(a) for a in candidates))
        fetched = sum(1 for r in results if r)
        total_chars = sum(len(a.fulltext) for a in candidates if a.has_fulltext)
        elapsed = time.perf_counter() - t0
        # 评估 FULLTEXT_MAX_ARTICLES：cap 被打满说明调大有收益空间
        if len(all_with_pmcid) > limit:
            logger.warning(
                "pmc_fulltext cap 打满: 有 PMCID 的文章 %d 篇，仅抓取 %d 篇"
                " (FULLTEXT_MAX_ARTICLES=%d)，调大该参数可覆盖更多全文",
                len(all_with_pmcid), limit, limit,
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

    async def _fetch_bioc(self, pmcid: str) -> str | None:
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

    async def _fetch_pmc_xml(self, pmcid: str) -> str | None:
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


def _parse_bioc(data: Any) -> str | None:
    """Extract body paragraphs from BioC JSON (list or dict forms)."""
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

    paragraphs: list[str] = []
    for doc in documents:
        for passage in doc.get("passages") or []:
            if not isinstance(passage, dict):
                continue
            text = (passage.get("text") or "").strip()
            if not text:
                continue
            infons = passage.get("infons") or {}
            section_type = str(
                infons.get("type")
                or infons.get("section_type")
                or infons.get("section")
                or ""
            ).lower()
            if section_type in _SKIP_TYPES:
                continue
            if "ref" in section_type and section_type != "abstract":
                continue
            paragraphs.append(text)

    if not paragraphs:
        return None
    return "\n\n".join(paragraphs)


def _parse_pmc_xml(xml_text: str) -> str | None:
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
    parts: list[str] = []
    for p in target.iter("p"):
        text = "".join(p.itertext()).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            parts.append(text)
    if not parts:
        # Fallback: all text
        text = re.sub(r"\s+", " ", "".join(target.itertext())).strip()
        return text or None
    return "\n\n".join(parts)


def _find_parent(root: ET.Element, child: ET.Element) -> ET.Element | None:
    for parent in root.iter():
        if child in list(parent):
            return parent
    return None
