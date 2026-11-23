"""Minimal client for the Google Gemini API (generateContent), stdlib only.

Same interface as ``OllamaClient`` (``check()`` and ``generate()``), so the NL->Cypher
benchmarks can use either. The API key is read from the ``GEMINI_API_KEY`` (or
``GOOGLE_API_KEY``) environment variable and sent in a request header, never in the URL,
and is never written to results or caches.

Decoding: temperature 0 and minimal thinking -- ``thinkingBudget: 0`` on Gemini 2.x,
``thinkingLevel: "minimal"`` on Gemini 3+ (which rejects a zero budget).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from benchmark.ollama_client import Generation

API = "https://generativelanguage.googleapis.com/v1beta"


class GeminiUnavailable(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise GeminiUnavailable("Set GEMINI_API_KEY (or GOOGLE_API_KEY) in the environment.")
    return key


class GeminiClient:
    def __init__(self, model: str, timeout_s: float = 120.0, max_output_tokens: int = 512,
                 max_retries: int = 8, disable_thinking: bool = True) -> None:
        self.model = model.removeprefix("models/")
        self.timeout_s = timeout_s
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries
        self.disable_thinking = disable_thinking

    def _request(self, url: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(
            url,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": _api_key()},
        )
        delay = 5.0
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:500]
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 120.0)
                    continue
                raise GeminiUnavailable(f"Gemini API HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 120.0)
                    continue
                raise GeminiUnavailable(f"Cannot reach the Gemini API ({exc}).") from exc
        raise GeminiUnavailable("unreachable")

    def _thinking_config(self) -> dict | None:
        if not self.disable_thinking:
            return None
        if self.model.startswith(("gemini-1", "gemini-2")):
            return {"thinkingBudget": 0}
        return {"thinkingLevel": "minimal"}

    def check(self) -> dict:
        info = self._request(f"{API}/models/{self.model}")
        return {"provider": "gemini", "model": self.model, "version": info.get("version"),
                "display_name": info.get("displayName"),
                "decoding": {"temperature": 0.0, "thinking": self._thinking_config(),
                             "max_output_tokens": self.max_output_tokens}}

    def generate(self, prompt: str, stop: list[str] | None = None) -> Generation:
        config: dict = {"temperature": 0.0, "maxOutputTokens": self.max_output_tokens}
        if stop:
            config["stopSequences"] = stop
        if (tc := self._thinking_config()) is not None:
            config["thinkingConfig"] = tc
        payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
        t0 = time.perf_counter()
        data = self._request(f"{API}/models/{self.model}:generateContent", payload)
        cands = data.get("candidates") or []
        parts = (cands[0].get("content") or {}).get("parts", []) if cands else []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = data.get("usageMetadata", {})
        return Generation(text=text, seconds=time.perf_counter() - t0,
                          prompt_tokens=usage.get("promptTokenCount"),
                          output_tokens=usage.get("candidatesTokenCount"))


def make_client(provider: str, model: str):
    if provider == "gemini":
        return GeminiClient(model)
    from benchmark.ollama_client import OllamaClient
    return OllamaClient(model)


def run_slug(provider: str, model: str) -> str:
    slug = model.replace(":", "_").replace("/", "_")
    return slug if provider == "ollama" else f"{provider}_{slug}"
