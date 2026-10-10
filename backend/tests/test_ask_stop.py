import unittest
from unittest.mock import patch

from backend.app.main import ask


class _Request:
    def __init__(self, disconnect_after: int):
        self.disconnect_after = disconnect_after
        self.checks = 0

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.checks > self.disconnect_after


class AskStopTest(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_closes_generation(self):
        produced: list[int] = []
        closed = False

        async def fake_run_ask(_settings, _question, _context):
            nonlocal closed
            try:
                for i in range(8):
                    produced.append(i)
                    yield {"type": "token", "content": str(i)}
            finally:
                closed = True

        body = type("Body", (), {"question": "副作用", "context": None})()
        request = _Request(disconnect_after=2)
        with patch("backend.app.main.run_ask", fake_run_ask):
            chunks = [chunk async for chunk in (await ask(body, request)).body_iterator]

        # 断开后不再下发；生成器停在已经取出、但未发送的那一条。
        self.assertEqual(produced, [0, 1, 2])
        self.assertTrue(closed)
        self.assertEqual(len(chunks), 2)
        self.assertIn('"content": "0"', chunks[0])
        self.assertIn('"content": "1"', chunks[1])

    async def test_connected_client_receives_the_full_stream(self):
        async def fake_run_ask(_settings, _question, _context):
            yield {"type": "token", "content": "ok"}
            yield {"type": "done"}

        body = type("Body", (), {"question": "副作用", "context": None})()
        request = _Request(disconnect_after=99)
        with patch("backend.app.main.run_ask", fake_run_ask):
            chunks = [chunk async for chunk in (await ask(body, request)).body_iterator]

        self.assertEqual(len(chunks), 2)
        self.assertIn('"content": "ok"', chunks[0])
        self.assertIn('"type": "done"', chunks[1])
