from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional

import requests

from .types import AppConfig, LLMResponse, LLMUsage


class LLMClient:
    def __init__(self, config: AppConfig, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()

    def generate(self, prompt: str) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        attempt = 0
        last_error: Optional[Exception] = None
        backoff_seconds = 1.0
        while attempt < 6:
            attempt += 1
            try:
                response = self.session.post(
                    self.config.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.config.timeout_sec,
                )
            except requests.Timeout as exc:
                last_error = exc
                if attempt >= 3:
                    break
                self._sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            except requests.RequestException as exc:
                last_error = exc
                self._sleep(backoff_seconds)
                backoff_seconds *= 2
                continue

            if response.status_code == 200:
                data = response.json()
                text = self._extract_text(data)
                usage = self._parse_usage(data)
                return LLMResponse(text=text, usage=usage, raw=data)

            if response.status_code in {400, 401, 403}:
                raise RuntimeError(f"LLM request failed: {response.status_code} {response.text}")

            if response.status_code == 429:
                self._sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 32)
                continue

            if response.status_code >= 500:
                self._sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 32)
                continue

            raise RuntimeError(f"Unexpected LLM status {response.status_code}: {response.text}")

        if last_error:
            raise RuntimeError(f"LLM request failed after retries: {last_error}") from last_error
        raise RuntimeError("LLM request failed after retries")

    def _sleep(self, seconds: float) -> None:
        jitter = random.random() * 0.25
        time.sleep(max(seconds + jitter, 0.5))

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> str:
        if "text" in data:
            return data["text"]
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            if "content" in message and isinstance(message["content"], str):
                return message["content"]
            if "content" in message and isinstance(message["content"], list):
                chunks = [p.get("text", "") if isinstance(p, dict) else str(p) for p in message["content"]]
                return "".join(chunks)
            if "text" in choices[0]:
                return choices[0]["text"]
        raise RuntimeError("LLM response missing text content")

    @staticmethod
    def _parse_usage(data: Dict[str, Any]) -> Optional[LLMUsage]:
        usage = data.get("usage")
        if not usage:
            return None
        return LLMUsage(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            reasoning_tokens=usage.get("reasoning_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
