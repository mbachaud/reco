"""OpenAI-compatible chat-completions driver.

Covers OpenAI, Anthropic (via compat endpoints), Gemini API / Vertex compat,
OpenRouter, and local Ollama / LM Studio servers — Track B's workhorse.
"""
import json
import urllib.error
import urllib.request

from reco.gateway.drivers.base import DriverResult


class HttpOpenAIDriver:
    name = "http_openai"

    def __init__(self, *, base_url: str, model: str, api_key: str | None = None,
                 temperature: int | float = 0, max_tokens: int = 1200,
                 provider: str = "http", extra_body: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.provider = provider
        self.extra_body = extra_body or {}

    def decide(self, static_context: str, observation: str, timeout_s: int) -> DriverResult:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": static_context},
                {"role": "user", "content": observation},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            **self.extra_body,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                error = "rate_limit"
            elif 500 <= exc.code < 600:
                error = "transient"
            else:
                error = "fatal"
            return DriverResult(error=error, meta={"status": exc.code})
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return DriverResult(error="timeout", meta={"exception": repr(exc)})
            return DriverResult(error="transient", meta={"exception": repr(exc)})
        except (TimeoutError, OSError) as exc:
            return DriverResult(error="transient", meta={"exception": repr(exc)})

        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return DriverResult(error="transient", meta={"body": str(payload)[:500]})
        return DriverResult(text=text, usage=payload.get("usage") or {})
