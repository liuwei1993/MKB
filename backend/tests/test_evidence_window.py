import unittest
from unittest.mock import AsyncMock, patch

from backend.app.config import Settings
from backend.app.pipeline import (
    ANSWER_SYSTEM,
    UNDERSTAND_SYSTEM,
    design_filter_query,
    parse_understand,
)
from backend.app.pubmed import (
    Article,
    PubMedClient,
    is_retracted,
    select_fulltext_candidates,
)
from backend.app.rag import Chunk, format_rag_evidence


def _article(pmid: str, pmcid: str = "PMC1", types: list[str] | None = None) -> Article:
    return Article(
        pmid=pmid,
        title=pmid,
        abstract="abstract",
        journal="Journal",
        year="2020",
        authors="Doe J",
        pmcid=pmcid,
        pub_types=types if types is not None else ["Journal Article"],
    )


def _settings(**overrides: object) -> Settings:
    data = {
        "llm_model": "m",
        "llm_api_key": "k",
        "llm_base_url": "http://llm",
        "embedding_model": "e",
        "ncbi_email": "a@b.c",
        "ncbi_api_key": "key",
        "target_pmids": 2,
        "retmax_per_query": 25,
    }
    data.update(overrides)
    return Settings(**data)


class QuestionTypeTest(unittest.TestCase):
    def test_missing_question_type_is_other(self):
        parsed = parse_understand(
            '{"relation":"new_topic","standalone_question":"阿司匹林","queries":["aspirin"]}',
            "阿司匹林",
            has_history=False,
        )
        self.assertEqual(parsed["question_type"], "other")
        self.assertEqual(parsed["queries"], ["aspirin"])

    def test_invalid_question_type_is_other(self):
        parsed = parse_understand(
            '{"relation":"new_topic","question_type":"efficacy",'
            '"standalone_question":"阿司匹林","queries":["aspirin"]}',
            "阿司匹林",
            has_history=False,
        )
        self.assertEqual(parsed["question_type"], "other")

    def test_parse_failure_keeps_short_query_without_filter(self):
        parsed = parse_understand("not json", "阿司匹林预防", has_history=False)
        self.assertEqual(parsed["question_type"], "other")
        self.assertEqual(parsed["queries"], ["阿司匹林预防"])
        self.assertIsNone(design_filter_query(parsed["queries"], parsed["question_type"]))


class DesignFilterTest(unittest.TestCase):
    def test_treatment_appends_fixed_clause(self):
        query = design_filter_query(["heart failure"], "treatment")
        self.assertEqual(
            query,
            '(heart failure) AND ("systematic review"[pt] OR "meta-analysis"[pt] '
            'OR "network meta-analysis"[pt] OR "guideline"[pt] OR '
            '"practice guideline"[pt] OR "randomized controlled trial"[pt])',
        )
        self.assertEqual(
            design_filter_query(["statin"], "prevention"),
            '(statin) AND ("systematic review"[pt] OR "meta-analysis"[pt] '
            'OR "network meta-analysis"[pt] OR "guideline"[pt] OR '
            '"practice guideline"[pt] OR "randomized controlled trial"[pt])',
        )

    def test_diagnosis_and_prognosis_use_their_clauses(self):
        self.assertEqual(
            design_filter_query(["troponin"], "diagnosis"),
            '(troponin) AND ("systematic review"[pt] OR "meta-analysis"[pt] '
            'OR "network meta-analysis"[pt] OR "guideline"[pt] OR '
            '"practice guideline"[pt] OR "validation study"[pt] OR '
            '"evaluation study"[pt])',
        )
        self.assertEqual(
            design_filter_query(["cancer survival"], "prognosis"),
            '(cancer survival) AND ("systematic review"[pt] OR "meta-analysis"[pt] '
            'OR "network meta-analysis"[pt] OR "guideline"[pt] OR '
            '"practice guideline"[pt] OR "observational study"[pt])',
        )
        self.assertEqual(
            design_filter_query(["smoking"], "etiology"),
            '(smoking) AND ("systematic review"[pt] OR "meta-analysis"[pt] '
            'OR "network meta-analysis"[pt] OR "guideline"[pt] OR '
            '"practice guideline"[pt] OR "observational study"[pt])',
        )

    def test_mechanism_and_other_add_nothing(self):
        self.assertIsNone(design_filter_query(["egfr"], "mechanism"))
        self.assertIsNone(design_filter_query(["egfr"], "other"))
        self.assertIsNone(design_filter_query([], "treatment"))

    def test_prompt_forbids_model_written_filters(self):
        self.assertIn("question_type", UNDERSTAND_SYSTEM)
        self.assertIn("不要写", UNDERSTAND_SYSTEM)
        self.assertIn("[pt]", UNDERSTAND_SYSTEM)
        self.assertIn("单篇", ANSWER_SYSTEM)
        self.assertIn("撤稿", ANSWER_SYSTEM)
        self.assertIn("样本量", ANSWER_SYSTEM)


class FulltextSlotTest(unittest.TestCase):
    def test_keeps_seven_relevance_and_reserves_later_review(self):
        articles = [_article(str(i), pmcid=f"PMC{i}") for i in range(1, 8)]
        articles.append(_article("8", pmcid="PMC8"))
        articles.append(
            _article("9", pmcid="PMC9", types=["Journal Article", "Systematic Review"])
        )
        articles.extend(_article(str(i), pmcid=f"PMC{i}") for i in range(10, 13))
        chosen = [a.pmid for a in select_fulltext_candidates(articles, "treatment", 10)]
        self.assertEqual(chosen, ["1", "2", "3", "4", "5", "6", "7", "9", "8", "10"])

    def test_plain_article_stays_out_when_reserve_is_full(self):
        articles = [_article(str(i), pmcid=f"PMC{i}") for i in range(1, 8)]
        articles.append(_article("8", pmcid="PMC8"))
        articles.append(_article("9", pmcid="PMC9", types=["Systematic Review"]))
        articles.append(_article("10", pmcid="PMC10", types=["Meta-Analysis"]))
        articles.append(
            _article("11", pmcid="PMC11", types=["Randomized Controlled Trial"])
        )
        chosen = [a.pmid for a in select_fulltext_candidates(articles, "treatment", 10)]
        self.assertEqual(chosen, ["1", "2", "3", "4", "5", "6", "7", "9", "10", "11"])
        self.assertNotIn("8", chosen)

    def test_backfills_when_high_tier_is_short(self):
        articles = [_article(str(i), pmcid=f"PMC{i}") for i in range(1, 12)]
        chosen = [a.pmid for a in select_fulltext_candidates(articles, "treatment", 10)]
        self.assertEqual(chosen, [str(i) for i in range(1, 11)])

    def test_other_and_mechanism_keep_relevance_order(self):
        articles = [_article(str(i), pmcid=f"PMC{i}") for i in range(1, 15)]
        articles[12] = _article("13", pmcid="PMC13", types=["Systematic Review"])
        for question_type in ("other", "mechanism"):
            chosen = [
                a.pmid
                for a in select_fulltext_candidates(articles, question_type, 10)
            ]
            self.assertEqual(chosen, [str(i) for i in range(1, 11)])

    def test_retracted_and_missing_pmcid_are_skipped(self):
        articles = [
            _article("1", pmcid="PMC1", types=["Systematic Review", "Retracted Publication"]),
            _article("2", pmcid="", types=["Systematic Review"]),
            _article("3", pmcid="PMC3"),
        ]
        chosen = [a.pmid for a in select_fulltext_candidates(articles, "treatment", 10)]
        self.assertEqual(chosen, ["3"])
        self.assertTrue(is_retracted(articles[0]))

    def test_diagnosis_reserves_validation_study(self):
        articles = [_article(str(i), pmcid=f"PMC{i}") for i in range(1, 8)]
        articles.append(_article("8", pmcid="PMC8"))
        articles.append(_article("9", pmcid="PMC9", types=["Validation Study"]))
        chosen = [a.pmid for a in select_fulltext_candidates(articles, "diagnosis", 10)]
        self.assertEqual(chosen[:8], ["1", "2", "3", "4", "5", "6", "7", "9"])

    def test_network_meta_analysis_fills_a_reserve_slot(self):
        articles = [_article(str(i), pmcid=f"PMC{i}") for i in range(1, 8)]
        articles.append(_article("8", pmcid="PMC8"))
        articles.append(_article("9", pmcid="PMC9", types=["Network Meta-Analysis"]))
        chosen = [a.pmid for a in select_fulltext_candidates(articles, "treatment", 10)]
        self.assertEqual(chosen[:8], ["1", "2", "3", "4", "5", "6", "7", "9"])

    def test_review_tag_alone_is_not_high_tier(self):
        articles = [_article(str(i), pmcid=f"PMC{i}") for i in range(1, 8)]
        articles.append(_article("8", pmcid="PMC8", types=["Review"]))
        articles.extend(
            _article(str(i), pmcid=f"PMC{i}", types=["Systematic Review"])
            for i in range(9, 12)
        )
        chosen = [a.pmid for a in select_fulltext_candidates(articles, "treatment", 10)]
        self.assertEqual(chosen, ["1", "2", "3", "4", "5", "6", "7", "9", "10", "11"])
        self.assertNotIn("8", chosen)

    def test_clinical_trial_does_not_take_the_reserve_ahead_of_a_review(self):
        articles = [_article(str(i), pmcid=f"PMC{i}") for i in range(1, 8)]
        articles.append(_article("8", pmcid="PMC8", types=["Clinical Trial"]))
        articles.extend(_article(str(i), pmcid=f"PMC{i}") for i in range(10, 13))
        articles.append(_article("13", pmcid="PMC13", types=["Systematic Review"]))
        chosen = [a.pmid for a in select_fulltext_candidates(articles, "treatment", 10)]
        self.assertEqual(chosen[7], "13")


class EvidenceTextTest(unittest.TestCase):
    def test_evidence_includes_publication_type(self):
        article = _article("1", types=["Systematic Review"])
        chunks = [
            Chunk(pmid="1", title="T", source="abstract", text="hello", index=0)
        ]
        text = format_rag_evidence(chunks, [article])
        self.assertIn("Type: Systematic Review", text)

    def test_retracted_articles_are_not_evidence_sources(self):
        from backend.app.pubmed import articles_for_evidence

        kept = articles_for_evidence(
            [
                _article("1", types=["Retracted Publication"]),
                _article("2", types=["Meta-Analysis"]),
            ]
        )
        self.assertEqual([a.pmid for a in kept], ["2"])


class PrioritySearchTest(unittest.IsolatedAsyncioTestCase):
    async def test_priority_ids_are_added_after_target_is_full(self):
        pubmed = PubMedClient(_settings(), client=object())
        calls: list[str] = []

        async def esearch(term: str, retmax: int) -> list[str]:
            calls.append(term)
            if term == "broad":
                return ["1", "2"]
            return ["9", "10", "2"]

        async def efetch(pmids: list[str]) -> list[Article]:
            return [_article(pmid, pmcid=f"PMC{pmid}") for pmid in pmids]

        pubmed.esearch = esearch  # type: ignore[method-assign]
        pubmed.efetch = efetch  # type: ignore[method-assign]
        with patch("backend.app.pubmed.asyncio.sleep", new=AsyncMock()):
            articles = await pubmed.search_articles(
                ["broad"],
                priority_query='(broad) AND ("systematic review"[pt])',
            )
        self.assertEqual([a.pmid for a in articles], ["1", "2", "9", "10"])
        self.assertEqual(calls[0], "broad")
        self.assertIn('(broad) AND ("systematic review"[pt])', calls)

    async def test_empty_priority_keeps_broad_results(self):
        pubmed = PubMedClient(_settings(target_pmids=10), client=object())

        async def esearch(term: str, retmax: int) -> list[str]:
            if term == "broad":
                return ["1"]
            return []

        async def efetch(pmids: list[str]) -> list[Article]:
            return [_article(pmid, pmcid=f"PMC{pmid}") for pmid in pmids]

        pubmed.esearch = esearch  # type: ignore[method-assign]
        pubmed.efetch = efetch  # type: ignore[method-assign]
        with patch("backend.app.pubmed.asyncio.sleep", new=AsyncMock()):
            articles = await pubmed.search_articles(["broad"], priority_query="(broad) AND x")
        self.assertEqual([a.pmid for a in articles], ["1"])

    async def test_priority_error_keeps_broad_results(self):
        pubmed = PubMedClient(_settings(target_pmids=10), client=object())

        async def esearch(term: str, retmax: int) -> list[str]:
            if term == "broad":
                return ["1"]
            raise RuntimeError("PubMed esearch error: query syntax")

        async def efetch(pmids: list[str]) -> list[Article]:
            return [_article(pmid, pmcid=f"PMC{pmid}") for pmid in pmids]

        pubmed.esearch = esearch  # type: ignore[method-assign]
        pubmed.efetch = efetch  # type: ignore[method-assign]
        with patch("backend.app.pubmed.asyncio.sleep", new=AsyncMock()):
            articles = await pubmed.search_articles(["broad"], priority_query="(broad) AND bad")
        self.assertEqual([a.pmid for a in articles], ["1"])

    async def test_priority_extra_is_capped_at_15(self):
        pubmed = PubMedClient(_settings(target_pmids=1), client=object())

        async def esearch(term: str, retmax: int) -> list[str]:
            if term == "broad":
                return ["1"]
            return [str(i) for i in range(2, 40)]

        async def efetch(pmids: list[str]) -> list[Article]:
            return [_article(pmid, pmcid=f"PMC{pmid}") for pmid in pmids]

        pubmed.esearch = esearch  # type: ignore[method-assign]
        pubmed.efetch = efetch  # type: ignore[method-assign]
        with patch("backend.app.pubmed.asyncio.sleep", new=AsyncMock()):
            articles = await pubmed.search_articles(["broad"], priority_query="filtered")
        self.assertEqual(len(articles), 16)
        self.assertEqual(articles[0].pmid, "1")

    async def test_broad_search_pages_until_the_target_is_full(self):
        pubmed = PubMedClient(
            _settings(target_pmids=30, retmax_per_query=25), client=object()
        )
        calls: list[tuple[str, int, int]] = []

        async def esearch(term: str, retmax: int, retstart: int = 0) -> list[str]:
            calls.append((term, retmax, retstart))
            if retstart == 0:
                return [str(i) for i in range(1, 26)]
            return [str(i) for i in range(26, 31)]

        async def efetch(pmids: list[str]) -> list[Article]:
            return [_article(pmid, pmcid=f"PMC{pmid}") for pmid in pmids]

        pubmed.esearch = esearch  # type: ignore[method-assign]
        pubmed.efetch = efetch  # type: ignore[method-assign]
        with patch("backend.app.pubmed.asyncio.sleep", new=AsyncMock()):
            articles = await pubmed.search_articles(["broad"])
        self.assertEqual([a.pmid for a in articles], [str(i) for i in range(1, 31)])
        self.assertEqual(calls, [("broad", 25, 0), ("broad", 25, 25)])


if __name__ == "__main__":
    unittest.main()
