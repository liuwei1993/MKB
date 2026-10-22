import unittest

import numpy as np

from backend.app.pmc import (
    _parse_bioc,
    _parse_pmc_xml,
    join_paragraphs,
    normalize_section,
)
from backend.app.pubmed import Article
from backend.app.rag import (
    Chunk,
    build_chunks,
    format_rag_evidence,
    pick_diverse,
    section_boost,
    section_label_zh,
)


BIOC = {
    "documents": [
        {
            "passages": [
                {
                    "infons": {"section_type": "INTRO", "type": "title_1"},
                    "text": "Introduction",
                },
                {
                    "infons": {"section_type": "INTRO", "type": "paragraph"},
                    "text": "Intro paragraph one.",
                },
                {
                    "infons": {"section_type": "METHODS", "type": "paragraph"},
                    "text": "Methods paragraph one.",
                },
                {
                    "infons": {"section_type": "RESULTS", "type": "paragraph"},
                    "text": "Results paragraph one.",
                },
                {
                    "infons": {"section_type": "REF", "type": "ref"},
                    "text": "1. Someone et al.",
                },
            ]
        }
    ]
}

XML = """
<article>
  <body>
    <sec>
      <title>Methods</title>
      <p>First XML paragraph.</p>
      <p>Second XML paragraph.</p>
    </sec>
  </body>
</article>
"""


class NormalizeSectionTest(unittest.TestCase):
    def test_maps_common_imrad_names(self):
        self.assertEqual(normalize_section("INTRO"), "intro")
        self.assertEqual(normalize_section("METHODS"), "methods")
        self.assertEqual(normalize_section("RESULTS"), "results")
        self.assertEqual(normalize_section("DISCUSS"), "discuss")
        self.assertEqual(normalize_section("DISCUSSION"), "discuss")
        self.assertEqual(normalize_section(""), "")
        self.assertEqual(normalize_section("CONCL"), "discuss")


class ParseSectionsTest(unittest.TestCase):
    def test_bioc_keeps_section_and_skips_titles_and_refs(self):
        paras = _parse_bioc(BIOC)
        self.assertIsNotNone(paras)
        assert paras is not None
        self.assertEqual(
            paras,
            [
                ("intro", "Intro paragraph one."),
                ("methods", "Methods paragraph one."),
                ("results", "Results paragraph one."),
            ],
        )
        self.assertEqual(
            join_paragraphs(paras),
            "Intro paragraph one.\n\nMethods paragraph one.\n\nResults paragraph one.",
        )

    def test_xml_fallback_has_empty_section(self):
        paras = _parse_pmc_xml(XML)
        self.assertIsNotNone(paras)
        assert paras is not None
        self.assertEqual(
            paras,
            [("", "First XML paragraph."), ("", "Second XML paragraph.")],
        )


class SectionChunkTest(unittest.TestCase):
    def test_build_chunks_does_not_merge_across_sections(self):
        article = Article(
            pmid="1",
            title="T",
            abstract="Abstract text.",
            journal="J",
            year="2020",
            authors="A",
        )
        article.has_fulltext = True
        article.fulltext_paras = [
            ("intro", "A" * 40),
            ("methods", "B" * 40),
        ]
        article.fulltext = join_paragraphs(article.fulltext_paras)
        chunks = build_chunks(
            [article],
            chunk_size=100,
            chunk_overlap=10,
            abstract_max_chars=200,
        )
        fulltext = [c for c in chunks if c.source == "fulltext"]
        self.assertEqual(len(fulltext), 2)
        self.assertEqual(fulltext[0].section, "intro")
        self.assertEqual(fulltext[1].section, "methods")
        self.assertTrue(fulltext[0].text.startswith("A"))
        self.assertTrue(fulltext[1].text.startswith("B"))

    def test_plain_fulltext_string_still_chunks_without_section(self):
        article = Article(
            pmid="2",
            title="T",
            abstract="",
            journal="J",
            year="2020",
            authors="A",
        )
        article.has_fulltext = True
        article.fulltext = "Para one.\n\nPara two."
        chunks = build_chunks(
            [article],
            chunk_size=100,
            chunk_overlap=0,
            abstract_max_chars=200,
        )
        self.assertEqual([c.section for c in chunks], [""])
        self.assertIn("Para one.", chunks[0].text)


class SectionBoostTest(unittest.TestCase):
    def test_treatment_prefers_results_over_methods(self):
        self.assertGreater(
            section_boost("treatment", "results"),
            section_boost("treatment", "methods"),
        )
        self.assertEqual(section_boost("other", "results"), 0.0)
        self.assertEqual(section_boost("treatment", ""), 0.0)

    def test_pick_diverse_with_boosted_scores_prefers_results(self):
        chunks = [
            Chunk("1", "t", "fulltext", "methods text", 0, section="methods"),
            Chunk("1", "t", "fulltext", "results text", 1, section="results"),
        ]
        # Same cosine; boost should lift results when applied outside.
        base = np.array([0.5, 0.5], dtype=np.float32)
        boosted = base + np.array(
            [section_boost("treatment", c.section) for c in chunks],
            dtype=np.float32,
        )
        picked = pick_diverse(chunks, boosted, top_k=1)
        self.assertEqual(picked[0].section, "results")


class SectionDisplayTest(unittest.TestCase):
    def test_labels_and_evidence_include_section(self):
        self.assertEqual(section_label_zh("results"), "结果")
        article = Article(
            pmid="9",
            title="Title",
            abstract="",
            journal="J",
            year="2021",
            authors="A",
        )
        chunks = [
            Chunk("9", "Title", "fulltext", "outcome data", 0, section="results"),
        ]
        text = format_rag_evidence(chunks, [article])
        self.assertIn("全文·结果#0", text)


class SampleRankingEvalTest(unittest.TestCase):
    """Tiny offline check: with equal cosine, treatment should surface Results."""

    def test_treatment_top3_favors_results_and_discuss(self):
        chunks = [
            Chunk("1", "t", "fulltext", "m1", 0, section="methods"),
            Chunk("1", "t", "fulltext", "i1", 1, section="intro"),
            Chunk("2", "t", "fulltext", "r1", 0, section="results"),
            Chunk("2", "t", "fulltext", "d1", 1, section="discuss"),
            Chunk("3", "t", "fulltext", "m2", 0, section="methods"),
            Chunk("3", "t", "fulltext", "r2", 1, section="results"),
        ]
        base = np.full(len(chunks), 0.55, dtype=np.float32)
        scores = base + np.asarray(
            [section_boost("treatment", c.section) for c in chunks],
            dtype=np.float32,
        )
        picked = pick_diverse(chunks, scores, top_k=3)
        sections = [c.section for c in picked]
        self.assertEqual(sections.count("methods"), 0)
        self.assertGreaterEqual(sections.count("results") + sections.count("discuss"), 2)


if __name__ == "__main__":
    unittest.main()
