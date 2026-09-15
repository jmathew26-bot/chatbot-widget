from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMOutputError(Exception):
    pass


def parse_llm_json(raw_text: str, model: type[T]) -> T:
    """Strip markdown fences if present, parse JSON, validate against the
    pydantic schema. Raises LLMOutputError on any failure -- callers should
    catch this and fall back to a deterministic path rather than inserting
    unvalidated data into the database."""
    cleaned = raw_text.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*)```$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"LLM output was not valid JSON: {e}\nRaw: {raw_text[:500]}") from e
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise LLMOutputError(f"LLM output failed schema validation: {e}\nRaw: {raw_text[:500]}") from e
