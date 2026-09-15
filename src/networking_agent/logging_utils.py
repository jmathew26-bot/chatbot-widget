"""Structured agent-action logging. Every agent decision goes through
log_action() so there's one consistent, greppable audit trail -- and one
place that guarantees credentials never end up in a log line.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from networking_agent.config import REPO_ROOT

LOG_PATH = REPO_ROOT / "data" / "agent.log"

_SECRET_MARKERS = ("api_key", "token", "credential", "secret", "password")


def configure_logging(level: int = logging.INFO) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("networking_agent")
    if root.handlers:
        return
    root.setLevel(level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.WARNING)
    root.addHandler(stream_handler)


def log_action(agent: str, action: str, *, person: str | None = None, source: str | None = None, **fields) -> None:
    logger = logging.getLogger(f"networking_agent.{agent}")
    safe_fields = {
        k: ("<redacted>" if any(m in k.lower() for m in _SECRET_MARKERS) else v)
        for k, v in fields.items()
    }
    parts = [f"action={action}"]
    if person:
        parts.append(f"person={person!r}")
    if source:
        parts.append(f"source={source!r}")
    parts.extend(f"{k}={v!r}" for k, v in safe_fields.items())
    logger.info(" ".join(parts))
