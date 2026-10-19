"""Stable Ollama chat adapter used by every HW1 model call."""

from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional


DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b")
DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))
DEFAULT_SEED = int(os.environ.get("OLLAMA_SEED", "36"))
THINK_RE = re.compile(
    r"^\s*(?:<think>)?.*?</think>\s*",
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class CompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    raw: dict[str, Any] = field(default_factory=dict)


class ModelClient:
    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST) -> None:
        self.model = model
        self.host = host.rstrip("/")

    def complete(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.2,
        format: Optional[str | dict[str, Any]] = None,
    ) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_ctx": DEFAULT_NUM_CTX, "seed": DEFAULT_SEED},
        }
        if tools:
            payload["tools"] = tools
        if format is not None:
            payload["format"] = format

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Retry transient connection drops (Ollama occasionally closes the
        # socket while reloading a model); give up after three attempts.
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                break
            except (urllib.error.URLError, http.client.HTTPException, ConnectionError) as exc:
                if attempt == 2:
                    raise RuntimeError(
                        f"Ollama request failed at {self.host}. Is `ollama serve` running? {exc}"
                    ) from exc
                time.sleep(2)

        message = body.get("message") or {}
        text = THINK_RE.sub("", message.get("content") or "").strip()
        input_tokens = int(body.get("prompt_eval_count") or 0)
        output_tokens = int(body.get("eval_count") or 0)
        return CompletionResult(
            text=text.strip(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            raw=body,
        )


def complete(
    messages: list[dict[str, str]],
    tools: Optional[list[dict[str, Any]]] = None,
    temperature: float = 0.2,
    format: Optional[str | dict[str, Any]] = None,
    client: Optional[ModelClient] = None,
) -> CompletionResult:
    adapter = client or ModelClient()
    return adapter.complete(
        messages, tools=tools, temperature=temperature, format=format
    )
