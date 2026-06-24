from __future__ import annotations

import json
from typing import Any, Dict, List

__all__ = ["TextProtocol"]


class TextProtocol:
    """Helpers for text-based tool-calling fallback and token estimation."""

    STRICT_TOOL_JSON_SYSTEM = """\
You are a coding agent with access to tools.

When you want to use a tool, you MUST respond with exactly one JSON object and nothing else.
The JSON object MUST match this schema:
{
  \"text\": string,              # optional natural language to show to user (can be empty)
  \"tool_calls\": [
    {
      \"id\": string,
      \"name\": string,
      \"arguments\": object
    }
  ]
}

If you do not need tools, respond with exactly one JSON object of the same form with tool_calls=[] and put your final answer in text.
Do not wrap in markdown fences. Do not output any other keys.
"""

    @classmethod
    def tools_to_strict_json_spec(cls, tools: List[Dict[str, Any]]) -> str:
        # Tools are passed in OpenAI format. We embed only the essentials to reduce tokens.
        lines = ["AVAILABLE TOOLS (names + JSON schemas):"]
        for t in tools or []:
            fn = (t or {}).get("function") or {}
            name = fn.get("name")
            params = fn.get("parameters")
            desc = fn.get("description", "")
            if not name or params is None:
                continue
            lines.append(f"- {name}: {desc}".strip())
            lines.append(json.dumps(params, ensure_ascii=False))
        return "\n".join(lines).strip()

    @classmethod
    def parse_strict_tool_json(cls, raw: str) -> Dict[str, Any]:
        """Parse the strict tool-call JSON object.

        Some providers occasionally return multiple JSON objects concatenated
        (e.g. one per candidate). In that case we accept the *first* JSON object
        and ignore trailing data.
        """

        s = (raw or "").strip()
        try:
            obj = json.loads(s)
        except Exception:
            # Try to decode just the first JSON value (tolerate trailing data).
            try:
                decoder = json.JSONDecoder()
                obj, end = decoder.raw_decode(s)
                _ = end
            except Exception as exc:
                raise ValueError(
                    "Model did not return strict tool-call JSON. "
                    "Expected a single JSON object with keys: text, tool_calls. "
                    f"Raw output starts with: {s[:200]!r}"
                ) from exc

        if not isinstance(obj, dict):
            raise ValueError(
                "Model returned JSON but not an object. "
                f"Got: {type(obj).__name__}. Raw output starts with: {s[:200]!r}"
            )

        text = obj.get("text")
        if not isinstance(text, str):
            text = ""

        tool_calls_in = obj.get("tool_calls")
        tool_calls: List[Dict[str, Any]] = []
        if isinstance(tool_calls_in, list):
            for i, call in enumerate(tool_calls_in):
                if not isinstance(call, dict):
                    continue
                cid = call.get("id")
                name = call.get("name")
                args = call.get("arguments")
                if not isinstance(cid, str) or not cid:
                    cid = f"call_{i+1}"
                if not isinstance(name, str) or not name:
                    continue
                if not isinstance(args, dict):
                    args = {}
                tool_calls.append({"id": cid, "name": name, "arguments": args})

        return {"text": text, "tool_calls": tool_calls}

    @classmethod
    def count_tokens(cls, text: str) -> int:
        """Estimate token count from raw text (~4 chars per token)."""
        return max(1, (len(text) + 3) // 4)

    @classmethod
    def count_message_tokens(cls, messages: List[Dict[str, Any]]) -> int:
        total = 0
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                total += cls.count_tokens(content)
            elif isinstance(content, list):
                total += cls.count_tokens(json.dumps(content, ensure_ascii=False))
        return total
