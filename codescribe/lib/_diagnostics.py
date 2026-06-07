"""Diagnostics helpers for the standalone agent.

This module is intentionally small and dependency-free so it can be used in
CLI contexts and as a lightweight instrumentation layer.

The primary sink is JSON Lines (JSONL), which is convenient for shell tooling
like jq/rg/awk and for later ingestion into pandas/DuckDB.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return uuid.uuid4().hex


def _json_safe(obj: Any) -> Any:
    """Best-effort conversion for JSON serialization."""
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return repr(obj)


def _redact(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return "***"
    if isinstance(value, (list, tuple)):
        return ["***" for _ in value]
    if isinstance(value, dict):
        return {k: "***" for k in value}
    return "***"


@dataclass
class DiagnosticsSink:
    """Base class for diagnostics sinks."""

    def emit(self, event: Mapping[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass
class NullDiagnosticsSink(DiagnosticsSink):
    def emit(self, event: Mapping[str, Any]) -> None:
        return None


@dataclass
class JsonlDiagnosticsSink(DiagnosticsSink):
    """Append-only JSONL sink.

    Parameters
    ----------
    path:
        Output file path. If None, defaults to
        `.codescribe/diagnostics/agent.jsonl` under the current working directory.
    redact_keys:
        Keys to redact in the event dict, recursively only at the top level.
        (Intended for tool args or prompts if you choose to log them.)
    flush:
        Flush after each line.
    """

    path: Optional[str] = None
    redact_keys: Sequence[str] = ()
    flush: bool = True

    def __post_init__(self) -> None:
        if not self.path:
            self.path = os.path.join(".codescribe", "diagnostics", "agent.jsonl")
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: Mapping[str, Any]) -> None:
        out: Dict[str, Any] = {}
        for k, v in dict(event).items():
            if k in self.redact_keys:
                out[k] = _redact(v)
            else:
                out[k] = _json_safe(v)

        # Ensure timestamp exists.
        out.setdefault("ts", iso_utc_now())

        line = json.dumps(out, ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            if self.flush:
                fh.flush()


class Timer:
    """Simple monotonic timer."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    @property
    def ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000.0
