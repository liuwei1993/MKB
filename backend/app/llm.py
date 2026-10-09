from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import Settings


class LLMClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> LLMClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.settings.llm_timeout)
        return self

    async def __aexit__(self, *args) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

    async def embed(self, texts: list[str], *, batch_size: int = 10) -> list[list[float]]:
        """Embed texts via OpenAI-compatible /embeddings (DashScope; max batch 10)."""
        assert self._client is not None
        if not texts:
            return []
        # DashScope text-embedding-v3 rejects batches larger than 10
        batch_size = max(1, min(batch_size, 10))
        model = self.settings.embedding_model
        url = f"{self.settings.llm_base_url}/embeddings"
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            payload = {"model": model, "input": batch}
            r = await self._client.post(url, headers=self._headers(), json=payload)
            data = r.json()
            if r.status_code >= 400:
                err = data.get("error") or data
                raise RuntimeError(f"Embedding error ({r.status_code}): {err}")
            items = data.get("data") or []
            # API may return unsorted; sort by index
            items = sorted(items, key=lambda x: int(x.get("index", 0)))
            for item in items:
                emb = item.get("embedding")
                if not isinstance(emb, list):
                    raise RuntimeError("Embedding response missing embedding vector")
                vectors.append(emb)
            if len(items) != len(batch):
                raise RuntimeError(
                    f"Embedding batch size mismatch: expected {len(batch)}, got {len(items)}"
                )
        return vectors

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        assert self._client is not None
        url = f"{self.settings.llm_base_url}/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
            # deepseek-v4.1-flash otherwise spends the budget on reasoning_content
            "enable_thinking": False,
        }
        r = await self._client.post(url, headers=self._headers(), json=payload)
        data = r.json()
        if r.status_code >= 400:
            err = data.get("error") or data
            raise RuntimeError(f"LLM error ({r.status_code}): {err}")
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        return content.strip()

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        assert self._client is not None
        url = f"{self.settings.llm_base_url}/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "enable_thinking": False,
        }
        async with self._client.stream(
            "POST", url, headers=self._headers(), json=payload
        ) as r:
            if r.status_code >= 400:
                body = await r.aread()
                try:
                    err = json.loads(body).get("error") or body.decode()
                except Exception:
                    err = body.decode(errors="replace")
                raise RuntimeError(f"LLM stream error ({r.status_code}): {err}")

            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk: dict[str, Any] = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                delta = ((chunk.get("choices") or [{}])[0]).get("delta") or {}
                # Only surface answer text; ignore reasoning_content
                content = delta.get("content")
                if content:
                    yield content
