"""_telemetry
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, List

import hashlib

from codescribe import lib

def write_archive_toml(chat_entries: List[Dict[str, str]], neural_model: object) -> None:
    """Write a chat archive TOML file under `.codescribe/chat/`.

    Folder structure: YYYY/MM/DD/timestamp_sha.toml
    """

    base_dir = Path(".codescribe") / "chat"

    now_local = datetime.now()
    timestamp = now_local.strftime("%H%M%S")
    date_path = now_local.strftime("%Y/%m/%d")
    sha = hashlib.sha1(str(now_local.timestamp()).encode()).hexdigest()[:8]

    folder = base_dir / date_path
    folder.mkdir(parents=True, exist_ok=True)

    filename = f"{timestamp}_{sha}.toml"
    file_path = folder / filename
    file_path.touch()

    lines: List[str] = []
    for entry in chat_entries:
        role = entry["role"]
        content = entry["content"].strip()
        lines.append(f"[[chat.{role}]]")
        lines.append("content = '''")
        lines.append(content)
        lines.append("'''\n")

    metadata = [f"# {entry}" for entry in str(neural_model.__repr__()).split("\n")]
    metadata.append("\n")

    file_path.write_text("\n".join(metadata + lines))
    lib.format_seed_prompt(file_path, chat_entries)


def iso_utc_now() -> str:
    """UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    """Generate a stable, human-friendly run id.

    Note: We keep the prior `_loop.py` format because it produces sortable run
    directories (timestamp prefix).
    """

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(3)}"


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically write text to *path* (best-effort on local filesystems)."""
    os.makedirs(path.parent, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Atomically write JSON to *path*."""
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    """Append one JSON object as a single line (JSONL)."""
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


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
class ToolLogSink:
    """Base class for tool log sinks."""

    def emit(self, event: Mapping[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass
class NullToolLogSink(ToolLogSink):
    def emit(self, event: Mapping[str, Any]) -> None:
        return None


@dataclass
class ToolLogJsonl(ToolLogSink):
    """Append-only JSONL tool log sink.

    Parameters
    ----------
    path:
        Output file path. If None, defaults to
        `.codescribe/tool-logs/agent.jsonl` under the current working directory.
    redact_keys:
        Keys to redact in the event dict, at the top level.
    flush:
        Flush after each line.
    """

    path: Optional[str] = None
    redact_keys: Sequence[str] = ()
    flush: bool = True

    def __post_init__(self) -> None:
        if not self.path:
            self.path = os.path.join(".codescribe", "logs", "toolusage.jsonl")
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: Mapping[str, Any]) -> None:
        out: Dict[str, Any] = {}
        for k, v in dict(event).items():
            if k in self.redact_keys:
                out[k] = _redact(v)
            else:
                out[k] = _json_safe(v)

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
