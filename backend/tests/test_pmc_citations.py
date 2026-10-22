import unittest

from backend.app.pmc import (
    _parse_bioc,
    _parse_pmc_xml,
    join_paragraphs,
    strip_inline_citations,
)

XML = """
<article>
  <body>
    <p>We compared the effect sizes.<xref ref-type="bibr" rid="ref16">16</xref>
    <xref ref-type="bibr" rid="ref17">17</xref>
    <xref ref-type="bibr" rid="ref18">18</xref> The associations were examined in this population,<xref ref-type="bibr" rid="ref17">17</xref>
    <xref ref-type="bibr" rid="ref18">18</xref> and they are included only for comparison.</p>
    <p>Fitness predicts mortality.<xref ref-type="bibr" rid="ref3"><sup>3</sup></xref> Although strength has received less attention.</p>
    <p>Reported by our group.<xref ref-type="bibr" rid="ref30">30</xref> The results persisted in the fully adjusted model (fig 5<xref ref-type="fig" rid="fig5"/>).</p>
    <p>Shown previously.<sup>16</sup><sup>17</sup> The next sentence has 10<sup>6</sup> cells.</p>
    <p>Adults (25-44 years old) and adolescents (16-19 years of age) were followed. Over 24.2 years, 26 145 (2.3%) participants died (n=985). The cohort included 1 142 599 men. Strength was associated with a 20-35% lower risk. See fig 1 and table 2.</p>
  </body>
</article>
"""


class PmcCitationXmlTest(unittest.TestCase):
    def test_bibr_markers_drop_out_without_taking_the_following_sentence(self):
        paras = _parse_pmc_xml(XML)
        self.assertIsNotNone(paras)
        assert paras is not None
        text = join_paragraphs(paras)
        self.assertIn(
            "We compared the effect sizes. The associations were examined in this population, and they are included only for comparison.",
            text,
        )
        self.assertIn(
            "Fitness predicts mortality. Although strength has received less attention.",
            text,
        )
        self.assertIn(
            "Reported by our group. The results persisted in the fully adjusted model (fig 5).",
            text,
        )
        self.assertIn("Shown previously. The next sentence has 106 cells.", text)
        self.assertNotRegex(text, r"effect sizes\.\s*16")
        self.assertNotRegex(text, r"population,\s*17")
        self.assertNotRegex(text, r"mortality\.\s*3\s+Although")
        self.assertNotRegex(text, r"group\.\s*30")
        self.assertNotRegex(text, r"previously\.\s*16")

    def test_measurements_sample_sizes_and_figure_labels_stay(self):
        text = join_paragraphs(_parse_pmc_xml(XML) or [])
        self.assertIn("25-44 years old", text)
        self.assertIn("16-19 years of age", text)
        self.assertIn("26 145 (2.3%)", text)
        self.assertIn("1 142 599 men", text)
        self.assertIn("20-35%", text)
        self.assertIn("n=985", text)
        self.assertIn("fig 1", text)
        self.assertIn("table 2", text)
        self.assertIn("fig 5", text)


class InlineCitationTest(unittest.TestCase):
    def test_drops_citation_numbers_after_punctuation(self):
        raw = (
            "预测因素。 1 2 另一个重要。 3 尽管肌肉力量。"
            " 4 5 6 7 8 9 10 11 12 13 儿童期。"
            "比较。 16 17 18 体重指数。"
            "检验， 17 18 本研究纳入它们。"
        )
        cleaned = strip_inline_citations(raw)
        self.assertIn("预测因素。 另一个重要。 尽管肌肉力量。", cleaned)
        self.assertIn("儿童期。", cleaned)
        self.assertIn("比较。 体重指数。", cleaned)
        self.assertIn("检验， 本研究纳入它们。", cleaned)
        self.assertNotIn("16 17 18", cleaned)
        self.assertNotIn("1 2", cleaned)
        self.assertNotIn("4 5 6", cleaned)
        self.assertNotIn("17 18", cleaned)

    def test_drops_bracket_and_parenthetical_citations_only(self):
        cleaned = strip_inline_citations("见前文 [16, 17, 18] 与 (16, 17)。保留 (25-44) 与 (2.3%)。")
        self.assertNotIn("[16", cleaned)
        self.assertNotIn("(16, 17)", cleaned)
        self.assertIn("见前文", cleaned)
        self.assertIn("与", cleaned)
        self.assertIn("(25-44)", cleaned)
        self.assertIn("(2.3%)", cleaned)

    def test_keeps_quantities_ages_and_thousand_groups(self):
        raw = (
            "Adults (25-44 years old) and adolescents (16-19 years of age) were followed. "
            "Over 24.2 years, 26 145 (2.3%) participants died (n=985). "
            "The cohort included 1 142 599 men, and 26\u2009145 deaths were recorded. "
            "Strength was associated with a 20-35% lower risk. See fig 1, table 2, and vs. 6 SGC/day."
        )
        cleaned = strip_inline_citations(raw)
        for piece in (
            "25-44 years old",
            "16-19 years of age",
            "26 145 (2.3%)",
            "1 142 599 men",
            "26\u2009145 deaths",
            "20-35%",
            "n=985",
            "fig 1",
            "table 2",
            "vs. 6 SGC/day",
        ):
            self.assertIn(piece, cleaned)

    def test_bioc_passage_drops_flattened_citations_and_extra_spaces(self):
        data = {
            "documents": [
                {
                    "passages": [
                        {
                            "infons": {"section_type": "INTRO", "type": "paragraph"},
                            "text": "pressure. 16 17 18 The associations were examined.   Next.",
                        }
                    ]
                }
            ]
        }
        paras = _parse_bioc(data) or []
        self.assertEqual(
            join_paragraphs(paras),
            "pressure. The associations were examined. Next.",
        )


if __name__ == "__main__":
    unittest.main()
