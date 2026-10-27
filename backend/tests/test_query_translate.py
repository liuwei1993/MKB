import unittest

from backend.app.pipeline import split_search_queries
from backend.app.query_translate import parse_query_translations


class QueryTranslateTest(unittest.TestCase):
    def test_parse_aligned_translations(self):
        raw = """
        {"translations":[
          {"query":"diabetes AND metformin","zh":"糖尿病 AND 二甲双胍"},
          {"query":"(x) AND \\"randomized controlled trial\\"[pt]","zh":"（x）AND（随机对照试验）"}
        ]}
        """
        queries = [
            "diabetes AND metformin",
            '(x) AND "randomized controlled trial"[pt]',
        ]
        out = parse_query_translations(raw, queries)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["zh"], "糖尿病 AND 二甲双胍")
        self.assertEqual(out[1]["zh"], "（x）AND（随机对照试验）")
        self.assertNotIn("[pt]", out[1]["zh"])

    def test_parse_fallback_empty(self):
        out = parse_query_translations("not json", ["a", "b"])
        self.assertEqual(out, [{"query": "a", "zh": ""}, {"query": "b", "zh": ""}])

    def test_split_search_queries(self):
        broad, priority = split_search_queries(
            [
                "diabetes AND metformin",
                '(diabetes AND metformin) AND ("randomized controlled trial"[pt])',
            ]
        )
        self.assertEqual(broad, ["diabetes AND metformin"])
        self.assertIsNotNone(priority)
        self.assertIn("[pt]", priority or "")


if __name__ == "__main__":
    unittest.main()
