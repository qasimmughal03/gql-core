"""Minimal client for a local Ollama server (https://ollama.com), stdlib only.

Used by the NL->Cypher benchmarks. Deterministic decoding (temperature 0,
fixed seed) so runs are reproducible for a given model build.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


class OllamaUnavailable(RuntimeError):
    pass


@dataclass
class Generation:
    text: str
    seconds: float
    prompt_tokens: int | None
    output_tokens: int | None


class OllamaClient:
    def __init__(self, model: str, base_url: str = DEFAULT_URL, timeout_s: float = 600.0,
                 num_predict: int = 512, num_ctx: int = 8192) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.num_predict = num_predict
        self.num_ctx = num_ctx

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def check(self) -> dict:
        """Fail fast with a clear message if the server or the model is missing."""
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=10) as resp:
                tags = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as exc:
            raise OllamaUnavailable(
                f"Cannot reach Ollama at {self.base_url} ({exc}). Install it from https://ollama.com "
                f"and run `ollama pull {self.model}`."
            ) from exc
        models = {m["name"] for m in tags.get("models", [])}
        if self.model not in models and f"{self.model}:latest" not in models:
            raise OllamaUnavailable(f"Model {self.model!r} is not pulled. Run `ollama pull {self.model}`. "
                                    f"Available: {sorted(models)}")
        info = self._post("/api/show", {"model": self.model})
        return {"model": self.model, "digest": next((m.get("digest") for m in tags["models"]
                                                     if m["name"] in (self.model, f"{self.model}:latest")), None),
                "details": info.get("details", {})}

    def generate(self, prompt: str, stop: list[str] | None = None) -> Generation:
        t0 = time.perf_counter()
        data = self._post("/api/chat", {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0, "seed": 0, "num_predict": self.num_predict,
                        "num_ctx": self.num_ctx, **({"stop": stop} if stop else {})},
        })
        return Generation(
            text=data.get("message", {}).get("content", ""),
            seconds=time.perf_counter() - t0,
            prompt_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )


class PredictionCache:
    """Append-only JSONL cache keyed by question id, so interrupted runs resume."""

    def __init__(self, path) -> None:
        self.path = path
        self.items: dict[str, dict] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        rec = json.loads(line)
                        self.items[rec["id"]] = rec

    def get(self, key: str) -> dict | None:
        return self.items.get(key)

    def put(self, rec: dict) -> None:
        self.items[rec["id"]] = rec
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
