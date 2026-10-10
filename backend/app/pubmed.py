from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

import httpx

from .config import Settings

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@dataclass
class Article:
    pmid: str
    title: str
    abstract: str
    journal: str
    year: str
    authors: str
    pmcid: str = ""
    doi: str = ""
    pub_types: list[str] = field(default_factory=list)
    has_fulltext: bool = False
    fulltext: str = field(default="", repr=False)

    def preferred_url(self) -> tuple[str, str]:
        """Return (url, url_label) preferring PMC full text, then DOI, then PubMed."""
        pmc = _normalize_pmcid(self.pmcid)
        if pmc:
            return (
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc}/",
                "全文 (PMC)",
            )
        if self.doi.strip():
            return (f"https://doi.org/{self.doi.strip()}", "原文 (DOI)")
        return (f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/", "PubMed")

    def to_meta(self) -> dict:
        url, url_label = self.preferred_url()
        return {
            "pmid": self.pmid,
            "title": self.title,
            "journal": self.journal,
            "year": self.year,
            "authors": self.authors,
            "pmcid": _normalize_pmcid(self.pmcid),
            "doi": self.doi.strip(),
            "url": url,
            "url_label": url_label,
            "has_abstract": bool(self.abstract.strip()),
            "has_fulltext": self.has_fulltext,
            "pub_types": list(self.pub_types),
        }

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_pmcid(pmcid: str) -> str:
    raw = (pmcid or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper.startswith("PMC"):
        return f"PMC{raw[3:]}"
    if raw.isdigit():
        return f"PMC{raw}"
    return raw


class PubMedClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> PubMedClient:
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

    async def esearch(self, term: str, retmax: int) -> list[str]:
        assert self._client is not None
        params = {
            **self._auth_params(),
            "db": "pubmed",
            "term": term,
            "retmax": str(retmax),
            "retmode": "json",
            "sort": "relevance",
        }
        r = await self._client.get(f"{EUTILS}/esearch.fcgi", params=params)
        r.raise_for_status()
        data = r.json()
        result = data.get("esearchresult") or {}
        if result.get("ERROR"):
            raise RuntimeError(f"PubMed esearch error: {result['ERROR']}")
        return list(result.get("idlist") or [])

    async def efetch(self, pmids: list[str]) -> list[Article]:
        if not pmids:
            return []
        assert self._client is not None
        articles: list[Article] = []
        for i in range(0, len(pmids), 200):
            batch = pmids[i : i + 200]
            params = {
                **self._auth_params(),
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml",
            }
            r = await self._client.get(f"{EUTILS}/efetch.fcgi", params=params)
            r.raise_for_status()
            articles.extend(_parse_pubmed_xml(r.text))
            if i + 200 < len(pmids):
                await asyncio.sleep(0.12)
        return articles

    async def search_articles(self, queries: list[str]) -> list[Article]:
        seen: list[str] = []
        seen_set: set[str] = set()
        per = self.settings.retmax_per_query
        target = self.settings.target_pmids

        for q in queries:
            if len(seen) >= target:
                break
            ids = await self.esearch(q, retmax=per)
            for pmid in ids:
                if pmid not in seen_set:
                    seen_set.add(pmid)
                    seen.append(pmid)
                    if len(seen) >= target:
                        break
            await asyncio.sleep(0.12)

        return await self.efetch(seen)


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _parse_ids(art: ET.Element) -> tuple[str, str]:
    pmcid = ""
    doi = ""
    for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
        id_type = (aid.get("IdType") or "").lower()
        val = (aid.text or "").strip()
        if not val:
            continue
        if id_type == "pmc" and not pmcid:
            pmcid = val
        elif id_type == "doi" and not doi:
            doi = val
    return pmcid, doi


def _parse_pubmed_xml(xml_text: str) -> list[Article]:
    root = ET.fromstring(xml_text)
    out: list[Article] = []
    for art in root.findall(".//PubmedArticle"):
        medline = art.find("MedlineCitation")
        if medline is None:
            continue
        pmid = _text(medline.find("PMID"))
        article = medline.find("Article")
        if not pmid or article is None:
            continue
        title = _text(article.find("ArticleTitle"))
        abstract_parts = [
            _text(a)
            for a in article.findall("Abstract/AbstractText")
            if _text(a)
        ]
        abstract = "\n".join(abstract_parts)
        journal = _text(article.find("Journal/Title"))
        year = _text(article.find("Journal/JournalIssue/PubDate/Year"))
        if not year:
            medline_date = _text(article.find("Journal/JournalIssue/PubDate/MedlineDate"))
            year = medline_date[:4] if medline_date else ""
        author_els = article.findall("AuthorList/Author")[:3]
        names: list[str] = []
        for a in author_els:
            last = _text(a.find("LastName"))
            initials = _text(a.find("Initials"))
            collective = _text(a.find("CollectiveName"))
            if last:
                names.append(f"{last} {initials}".strip())
            elif collective:
                names.append(collective)
        authors = ", ".join(names)
        if len(article.findall("AuthorList/Author")) > 3:
            authors = f"{authors} et al." if authors else "et al."
        pmcid, doi = _parse_ids(art)
        pub_types: list[str] = []
        for node in article.findall("PublicationTypeList/PublicationType"):
            label = _text(node)
            if label and label not in pub_types:
                pub_types.append(label)
        out.append(
            Article(
                pmid=pmid,
                title=title or "(untitled)",
                abstract=abstract,
                journal=journal,
                year=year,
                authors=authors,
                pmcid=pmcid,
                doi=doi,
                pub_types=pub_types,
            )
        )
    return out
