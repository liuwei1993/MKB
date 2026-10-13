import unittest

import numpy as np

from backend.app.pubmed import Article
from backend.app.rag import Chunk, build_chunks, pick_diverse


def _article(pmid: str, fulltext: str, abstract: str) -> Article:
    article = Article(
        pmid=pmid,
        title=pmid,
        abstract=abstract,
        journal="J",
        year="2020",
        authors="Doe",
    )
    article.fulltext = fulltext
    article.has_fulltext = True
    return article


class RagDiversityTest(unittest.TestCase):
    def test_one_paper_cannot_fill_every_slot(self):
        chunks = [
            Chunk(pmid="1" if i < 8 else "2", title="t", source="fulltext", text=str(i), index=i)
            for i in range(10)
        ]
        scores = np.array([10 - i for i in range(10)], dtype=np.float32)
        picked = pick_diverse(chunks, scores, top_k=6, per_pmid=2)
        self.assertEqual(sum(1 for chunk in picked if chunk.pmid == "1"), 2)
        self.assertIn("2", {chunk.pmid for chunk in picked})
        self.assertLessEqual(len(picked), 6)

    def test_fulltext_article_still_contributes_its_abstract(self):
        chunks = build_chunks(
            [_article("1", "alpha " * 40, "the abstract")],
            chunk_size=20,
            chunk_overlap=0,
            abstract_max_chars=100,
        )
        self.assertIn("abstract", {chunk.source for chunk in chunks})
        self.assertIn("fulltext", {chunk.source for chunk in chunks})


if __name__ == "__main__":
    unittest.main()
