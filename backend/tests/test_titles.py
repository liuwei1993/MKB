import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.titles import needs_translation, parse_title_json, translate_titles
from backend.app.main import app


class ParseTitleJsonTest(unittest.TestCase):
    def test_plain_object_keeps_allowed_pmids(self):
        raw = '{"1": "心衰", "2": "减重", "9": "多余"}'
        self.assertEqual(
            parse_title_json(raw, {"1", "2"}),
            {"1": "心衰", "2": "减重"},
        )

    def test_fenced_json(self):
        raw = '```json\n{"1": "阿司匹林"}\n```'
        self.assertEqual(parse_title_json(raw, {"1"}), {"1": "阿司匹林"})

    def test_invalid_or_empty_values_are_dropped(self):
        raw = '{"1": "", "2": 3, "3": "  有效  "}'
        self.assertEqual(parse_title_json(raw, {"1", "2", "3"}), {"3": "有效"})

    def test_unparseable_returns_empty(self):
        self.assertEqual(parse_title_json("not json", {"1"}), {})


class NeedsTranslationTest(unittest.TestCase):
    def test_english(self):
        self.assertTrue(needs_translation("SGLT2 inhibitors and heart failure"))

    def test_chinese_and_blank(self):
        self.assertFalse(needs_translation("心衰住院的影响"))
        self.assertFalse(needs_translation("SGLT2 抑制剂"))
        self.assertFalse(needs_translation("  "))


class FakeLLM:
    def __init__(self, replies: list[str | Exception]):
        self.replies = list(replies)
        self.calls: list[tuple[list[dict[str, str]], dict]] = []

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class TranslateTitlesTest(unittest.IsolatedAsyncioTestCase):
    async def test_skips_chinese_and_batches_english(self):
        articles = [{"pmid": "zh", "title": "已经是中文标题"}]
        articles += [
            {"pmid": str(i), "title": f"English title {i}"} for i in range(16)
        ]
        first = {str(i): f"译文{i}" for i in range(15)}
        second = {"15": "译文15", "999": "忽略"}
        llm = FakeLLM(
            [
                json.dumps(first, ensure_ascii=False),
                json.dumps(second, ensure_ascii=False),
            ]
        )

        got = await translate_titles(llm, articles)

        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0][1]["temperature"], 0)
        first_user = json.loads(llm.calls[0][0][1]["content"])
        second_user = json.loads(llm.calls[1][0][1]["content"])
        self.assertEqual(len(first_user), 15)
        self.assertEqual([item["pmid"] for item in second_user], ["15"])
        self.assertNotIn("zh", got)
        self.assertEqual(got["0"], "译文0")
        self.assertEqual(got["15"], "译文15")
        self.assertNotIn("999", got)

    async def test_drops_echoed_english(self):
        articles = [
            {"pmid": "1", "title": "Heart failure outcomes"},
            {"pmid": "2", "title": "Heart failure outcomes in diabetes"},
        ]
        llm = FakeLLM(
            [
                json.dumps(
                    {"1": "Heart failure outcomes", "2": "糖尿病患者的心衰结局"},
                    ensure_ascii=False,
                )
            ]
        )
        self.assertEqual(await translate_titles(llm, articles), {"2": "糖尿病患者的心衰结局"})

    async def test_failed_batch_is_skipped(self):
        articles = [
            {"pmid": "1", "title": "Alpha"},
            {"pmid": "2", "title": "Beta"},
        ]
        llm = FakeLLM([RuntimeError("boom")])
        self.assertEqual(await translate_titles(llm, articles), {})


class TranslateEndpointTest(unittest.TestCase):
    def test_returns_titles(self):
        class Stub:
            def __init__(self, settings):
                self.settings = settings

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def chat(self, messages, **kwargs):
                items = json.loads(messages[1]["content"])
                return json.dumps({items[0]["pmid"]: "中文标题"}, ensure_ascii=False)

        with patch("backend.app.main.LLMClient", Stub):
            client = TestClient(app)
            res = client.post(
                "/api/translate-titles",
                json={"articles": [{"pmid": "123", "title": "Heart failure"}]},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"titles": {"123": "中文标题"}})

    def test_llm_failure_returns_empty_titles(self):
        class Stub:
            def __init__(self, settings):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def chat(self, messages, **kwargs):
                raise RuntimeError("down")

        with patch("backend.app.main.LLMClient", Stub):
            client = TestClient(app)
            res = client.post(
                "/api/translate-titles",
                json={"articles": [{"pmid": "123", "title": "Heart failure"}]},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"titles": {}})
