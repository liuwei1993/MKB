import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.titles import (
    MAX_ARTICLES,
    clear_title_cache,
    needs_translation,
    parse_title_json,
    translate_titles,
)
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

    def test_truncated_object_keeps_complete_pairs(self):
        raw = '{"1": "心衰治疗", "2": "阿司匹林'
        self.assertEqual(parse_title_json(raw, {"1", "2"}), {"1": "心衰治疗"})

    def test_list_payload(self):
        raw = '[{"pmid": "1", "title": "阿司匹林"}]'
        self.assertEqual(parse_title_json(raw, {"1"}), {"1": "阿司匹林"})


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
        if not self.replies:
            raise RuntimeError("no more replies")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class TranslateTitlesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_title_cache()

    async def test_skips_chinese_and_batches_english(self):
        articles = [{"pmid": "zh", "title": "已经是中文标题"}]
        articles += [
            {"pmid": str(i), "title": f"English title {i}"} for i in range(16)
        ]

        class LLM:
            def __init__(self):
                self.calls: list[tuple[list[dict[str, str]], dict]] = []

            async def chat(self, messages, **kwargs):
                self.calls.append((messages, kwargs))
                items = json.loads(messages[1]["content"])
                return json.dumps(
                    {item["pmid"]: f"译文{item['pmid']}" for item in items},
                    ensure_ascii=False,
                )

        llm = LLM()
        got = await translate_titles(llm, articles)

        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0][1]["temperature"], 0)
        seen: list[str] = []
        for call in llm.calls:
            batch = json.loads(call[0][1]["content"])
            self.assertEqual(len(batch), 8)
            seen.extend(item["pmid"] for item in batch)
        self.assertEqual(sorted(seen, key=int), [str(i) for i in range(16)])
        self.assertNotIn("zh", got)
        self.assertEqual(got["0"], "译文0")
        self.assertEqual(got["15"], "译文15")

    async def test_drops_echoed_english_and_retries_that_pmid(self):
        articles = [
            {"pmid": "1", "title": "Heart failure outcomes"},
            {"pmid": "2", "title": "Heart failure outcomes in diabetes"},
        ]
        echoed = json.dumps(
            {"1": "Heart failure outcomes", "2": "糖尿病患者的心衰结局"},
            ensure_ascii=False,
        )
        llm = FakeLLM([echoed, json.dumps({"1": "Heart failure outcomes"})])
        self.assertEqual(
            await translate_titles(llm, articles),
            {"2": "糖尿病患者的心衰结局"},
        )
        self.assertEqual(len(llm.calls), 2)
        second = json.loads(llm.calls[1][0][1]["content"])
        self.assertEqual([item["pmid"] for item in second], ["1"])

    async def test_salvage_then_retries_truncated_tail(self):
        articles = [
            {"pmid": "1", "title": "Alpha outcomes"},
            {"pmid": "2", "title": "Beta outcomes"},
        ]
        llm = FakeLLM(
            [
                '{"1": "甲结果", "2": "乙',
                '{"2": "乙结果"}',
            ]
        )
        self.assertEqual(
            await translate_titles(llm, articles),
            {"1": "甲结果", "2": "乙结果"},
        )

    async def test_failed_batch_is_retried_then_skipped(self):
        articles = [
            {"pmid": "1", "title": "Alpha"},
            {"pmid": "2", "title": "Beta"},
        ]
        llm = FakeLLM([RuntimeError("boom"), RuntimeError("boom")])
        self.assertEqual(await translate_titles(llm, articles), {})
        self.assertEqual(len(llm.calls), 2)

    async def test_cache_skips_second_call(self):
        articles = [{"pmid": "1", "title": "Heart failure"}]
        llm = FakeLLM([json.dumps({"1": "心衰"}, ensure_ascii=False)])
        first = await translate_titles(llm, articles)
        second = await translate_titles(llm, articles)
        self.assertEqual(first, {"1": "心衰"})
        self.assertEqual(second, {"1": "心衰"})
        self.assertEqual(len(llm.calls), 1)

    async def test_cache_misses_when_title_changes(self):
        llm = FakeLLM(
            [
                json.dumps({"1": "心衰"}, ensure_ascii=False),
                json.dumps({"1": "心力衰竭结局"}, ensure_ascii=False),
            ]
        )
        first = await translate_titles(llm, [{"pmid": "1", "title": "Heart failure"}])
        second = await translate_titles(
            llm, [{"pmid": "1", "title": "Heart failure outcomes"}]
        )
        self.assertEqual(first, {"1": "心衰"})
        self.assertEqual(second, {"1": "心力衰竭结局"})
        self.assertEqual(len(llm.calls), 2)


class TranslateEndpointTest(unittest.TestCase):
    def setUp(self):
        clear_title_cache()

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

    def test_accepts_more_than_fifty_articles(self):
        class Stub:
            def __init__(self, settings):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def chat(self, messages, **kwargs):
                items = json.loads(messages[1]["content"])
                return json.dumps(
                    {item["pmid"]: f"标题{item['pmid']}" for item in items},
                    ensure_ascii=False,
                )

        articles = [
            {"pmid": str(i), "title": f"English title {i}"} for i in range(60)
        ]
        with patch("backend.app.main.LLMClient", Stub):
            client = TestClient(app)
            res = client.post("/api/translate-titles", json={"articles": articles})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["titles"]), 60)

    def test_rejects_above_max_articles(self):
        client = TestClient(app)
        articles = [
            {"pmid": str(i), "title": "Heart failure"} for i in range(MAX_ARTICLES + 1)
        ]
        res = client.post("/api/translate-titles", json={"articles": articles})
        self.assertEqual(res.status_code, 422)
