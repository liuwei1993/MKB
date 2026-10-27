import unittest

from backend.app.config import Settings
from backend.app import debug_session as ds


def _settings() -> Settings:
    return Settings(
        llm_model="test",
        llm_api_key="k",
        llm_base_url="http://example.invalid",
        embedding_model="emb",
        ncbi_email="a@b.c",
        ncbi_api_key="n",
        enable_debug_api=True,
    )


class DebugSessionUnitTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        ds._SESSIONS.clear()

    def test_create_and_public_view(self):
        session = ds.create_session(_settings(), "二甲双胍疗效？")
        view = ds.public_view(session)
        self.assertEqual(view["question"], "二甲双胍疗效？")
        self.assertEqual(view["current_step"], "understand")
        self.assertIn("understand", view["steps"])
        self.assertIsNotNone(view["steps"]["understand"]["prompts"])

    async def test_patch_answer_and_advance(self):
        session = ds.create_session(_settings(), "问题")
        session.current_step = "answer"
        session.evidence = "证据"
        session.steps["answer"] = {
            "id": "answer",
            "label": "生成回答",
            "status": "done",
            "prompts": {"system": "s", "user": "u"},
            "input": {},
            "output": {"answer": "旧回答"},
        }
        session.answer_text = "旧回答"
        view = ds.patch_output(session, {"answer": "新回答"})
        self.assertEqual(view["steps"]["answer"]["output"]["answer"], "新回答")
        self.assertEqual(session.answer_text, "新回答")
        advanced = ds.advance(session)
        self.assertEqual(advanced["current_step"], "suggest")


if __name__ == "__main__":
    unittest.main()
