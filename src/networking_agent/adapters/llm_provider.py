from __future__ import annotations

import logging
import time

from networking_agent.adapters.base import LLMProvider
from networking_agent.config import Settings

logger = logging.getLogger("networking_agent.llm")


class AnthropicLLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, max_retries: int = 3):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self.model = model
        self.max_retries = max_retries

    def is_available(self) -> bool:
        return True

    def generate_json(self, system: str, prompt: str, schema_hint: str) -> str:
        full_system = (
            f"{system}\n\nRespond with ONLY valid JSON matching this shape "
            f"(no markdown fences, no commentary):\n{schema_hint}"
        )
        delay = 1.0
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    system=full_system,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(
                    block.text for block in resp.content if getattr(block, "type", "") == "text"
                )
                return text.strip()
            except Exception as e:  # noqa: BLE001 - external SDK error surface varies
                last_error = e
                logger.warning("LLM call failed (attempt %d): %s", attempt + 1, e)
                time.sleep(delay)
                delay *= 2
        raise RuntimeError(f"LLM call failed after {self.max_retries} attempts: {last_error}")


class NullLLMProvider(LLMProvider):
    """No-op provider used when ANTHROPIC_API_KEY is absent. Agents that
    depend on the LLM must fall back to deterministic, fact-only logic
    rather than calling this -- see agents/*.py `_fallback_*` functions."""

    def is_available(self) -> bool:
        return False

    def generate_json(self, system: str, prompt: str, schema_hint: str) -> str:
        raise RuntimeError("No LLM provider configured (ANTHROPIC_API_KEY missing)")


def get_llm_provider(settings: Settings) -> LLMProvider:
    if settings.anthropic_api_key:
        try:
            return AnthropicLLMProvider(settings.anthropic_api_key, settings.anthropic_model)
        except ImportError:
            logger.warning("anthropic package not installed; falling back to NullLLMProvider")
    return NullLLMProvider()
