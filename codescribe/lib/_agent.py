"""Standalone baremetal coding agent (native tool-calling only)."""

import copy
import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from alive_progress import alive_bar

from codescribe import lib

__all__ = ["Agent"]

_REACT_NUDGE = """\
You are a coding agent with access to tools.

Available tools (high level):
- read: read file contents
- glob: find files by pattern
- bash: run shell commands
- edit: exact text replacements in a file
- write: create/overwrite a file

Rules:
- Be concise and practical.
- Use tools whenever you need to inspect files, run commands, or change the filesystem.
- Do NOT fabricate tool outputs. If you need info, call a tool.
- Batch ALL independent reads and globs into a single turn before acting — gather everything you need first, then implement.
- Once you have the information needed, implement immediately without further exploration.
- Do not re-read files you have already read unless they were modified since your last read.
- Prefer one comprehensive edit over multiple small edits to the same file.
- IMPORTANT: Only use the tools listed here. For shell work, ONLY use the bash tool and ONLY run commands that succeed under the bash tool's safety policy. If a command is blocked, pick an allowed alternative.
- Avoid repeating identical tool calls with the same arguments unless the workspace changed (e.g., after an edit).
- Before using edit, ensure you have read the exact file region you are changing.
- When all required actions are complete, respond with the final answer immediately — do not do additional cleanup or exploration.
"""

# Internal defaults (kept out of the public Agent interface)
_DEFAULT_MAX_TOOL_CALLS_TOTAL = 120
_DEFAULT_MAX_TOOL_CALLS_PER_ITERATION = 10
_DEFAULT_MAX_REPEATED_CALLS = 2
_DEFAULT_MAX_CONSECUTIVE_ERROR_ITERS = 3


def _count_tokens(text: str) -> int:
    """Estimate token count from raw text (~4 chars per token)."""
    return max(1, (len(text) + 3) // 4)


def _count_message_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += _count_tokens(content)
        elif isinstance(content, list):
            total += _count_tokens(json.dumps(content, ensure_ascii=False))
    return total


def _usage_in_out(usage: Optional[Dict[str, Any]]) -> Tuple[int, int, int, int, int]:
    if not usage:
        return 0, 0, 0, 0, 0
    input_tokens = usage.get("prompt_tokens")
    if input_tokens is None:
        input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("completion_tokens")
    if output_tokens is None:
        output_tokens = usage.get("output_tokens", 0)
    reasoning_tokens = int(usage.get("reasoning_tokens", 0) or 0)
    cache_creation_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
    return int(input_tokens or 0), int(output_tokens or 0), reasoning_tokens, cache_creation_tokens, cache_read_tokens


def _fmt_args(name: str, args: Dict[str, Any]) -> str:
    """Short human-readable preview of tool arguments."""
    if name == "bash":
        cmd = (args.get("command") or "").replace("\n", " ").strip()
        return (cmd[:60] + "…") if len(cmd) > 60 else cmd
    if name in ("read", "write"):
        return args.get("path", "")
    if name == "edit":
        path = args.get("path", "")
        n = len(args.get("edits") or [])
        return f"{path}  ({n} edit{'s' if n != 1 else ''})"
    s = json.dumps(args, ensure_ascii=False)
    return (s[:60] + "…") if len(s) > 60 else s


def _print_reasoning_block(text: str) -> None:
    """Print reasoning lines prefixed with │, dimmed when stdout is a TTY."""
    use_ansi = getattr(sys.stdout, "isatty", lambda: False)()
    dim = "\033[2m" if use_ansi else ""
    reset = "\033[0m" if use_ansi else ""
    for line in (text.splitlines() or [""]):
        print(f"    │ {dim}{line}{reset}")


def _is_error_output(output: str) -> bool:
    return (output or "").lstrip().startswith("Error:")


def _diagnostic_result_hint(name: str, output: str) -> str:
    """One-line hint for console diagnostics.

    Uses the same core summarizer as the model-facing tool output summaries to
    avoid duplicate formatting logic.
    """

    summary, _ = _summarize_tool_output(name, output)
    first = (summary.splitlines() or ["(empty)"])[0].strip()
    # Keep it compact for the right margin printing.
    return (first[:70] + "…") if len(first) > 70 else first


def _validate_schema_value(
    schema: Dict[str, Any], value: Any, path: str = "args"
) -> Optional[str]:
    expected_type = schema.get("type")

    if expected_type == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"
        props = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                return f"missing required argument {key!r}"
        if schema.get("additionalProperties") is False:
            extras = [k for k in value if k not in props]
            if extras:
                return f"unexpected argument(s): {', '.join(repr(k) for k in extras)}"
        for key, item in value.items():
            if key in props:
                err = _validate_schema_value(props[key], item, f"{path}.{key}")
                if err:
                    return err
        return None

    if expected_type == "array":
        if not isinstance(value, list):
            return f"{path} must be an array"
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            return f"{path} must contain at least {min_items} item(s)"
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(value):
                err = _validate_schema_value(item_schema, item, f"{path}[{idx}]")
                if err:
                    return err
        return None

    if expected_type == "string":
        if not isinstance(value, str):
            return f"{path} must be a string"
        return None

    if expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{path} must be an integer"
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            return f"{path} must be >= {minimum}"
        return None

    return None


def _stable_json(obj: Any) -> str:
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except Exception:
        return json.dumps(str(obj), ensure_ascii=False)


def _tool_call_key(name: str, args: Dict[str, Any]) -> str:
    return f"{name}:{_stable_json(args)}"


def _parse_bash_exit_code(output: str) -> Optional[int]:
    first = (output.splitlines() or [""])[0].strip()
    m = re.match(r"exit_code:\s*(-?\d+)\s*$", first)
    return int(m.group(1)) if m else None


def _summarize_tool_output(name: str, output: str) -> Tuple[str, bool]:
    """Return (summary_text, attach_hint) — used only for the workspace context block."""
    out = output or ""
    out_s = out.strip()

    if _is_error_output(out_s):
        msg = out_s[6:].strip()
        msg = (msg[:400] + "…") if len(msg) > 400 else msg
        return f"Error: {msg}", True

    if name == "bash":
        code = _parse_bash_exit_code(out)
        lines = [
            l for l in out.splitlines()[1:] if l and l not in ("STDOUT:", "STDERR:")
        ]
        head = lines[:12]
        tail = lines[-12:] if len(lines) > 24 else []
        body = head + (["…(snip)…"] if tail else []) + tail
        body_txt = "\n".join(body).strip() or "(no output)"
        if code is not None and code != 0:
            return f"bash exit_code={code}\n{body_txt}", True
        return f"bash exit_code={code if code is not None else '?'}\n{body_txt}", False

    if not out_s:
        return "(empty)", False

    lines = out.splitlines()
    if len(lines) <= 24 and len(out) <= 1500:
        return out_s, False

    head = lines[:12]
    tail = lines[-12:]
    omitted = max(0, len(lines) - (len(head) + len(tail)))
    summary = "\n".join(head)
    if omitted:
        summary += f"\n…[truncated {omitted} lines]…\n" + "\n".join(tail)
    return summary.strip(), False



class Agent:
    """Standalone coding agent (native tools only)."""

    def _emit(self, payload: Dict[str, Any]) -> None:
        try:
            self.logging.emit(payload)
        except Exception:
            pass

    def __init__(
        self,
        model: lib.Model,
        tools: Optional[List[lib.AgentTool]] = None,
        max_iterations: int = 20,
        show_diagnostics: bool = False,
        logging: Optional[Any] = None,
    ) -> None:

        allowed_types = lib.ALLOWED_MODEL_TYPES
        if not isinstance(model, allowed_types):
            allowed = ", ".join(t.__name__ for t in allowed_types)
            raise TypeError(
                f"Invalid model type: {type(model).__name__}. Expected one of: {allowed}"
            )

        if not getattr(model, "supports_native_tools", False) or not hasattr(
            model, "chat_with_tools"
        ):
            raise RuntimeError(
                f"Model {type(model).__name__} must support native tool calling (chat_with_tools)."
            )

        self.model = model
        source = tools if tools is not None else lib.DEFAULT_TOOLS
        self._tools: Dict[str, lib.AgentTool] = {t.name: copy.copy(t) for t in source}
        self.max_iterations = max_iterations
        self.show_diagnostics = show_diagnostics

        # Internal policy defaults (kept out of __init__ to avoid interface bloat)
        self._max_tool_calls_total = _DEFAULT_MAX_TOOL_CALLS_TOTAL
        self._max_tool_calls_per_iteration = _DEFAULT_MAX_TOOL_CALLS_PER_ITERATION
        self._max_repeated_calls = _DEFAULT_MAX_REPEATED_CALLS
        self._max_consecutive_error_iters = _DEFAULT_MAX_CONSECUTIVE_ERROR_ITERS
        # Per-run state
        self._state: Dict[str, Any] = {}

        # Tool log sink (JSONL recommended). Must expose .emit(dict).
        self.logging = logging if logging is not None else lib.NullToolLogSink()

    def enable_tool(self, name: str) -> None:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name!r}")
        self._tools[name].enabled = True

    def disable_tool(self, name: str) -> None:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name!r}")
        self._tools[name].enabled = False

    def _enabled_tools(self) -> List[lib.AgentTool]:
        return [tool for tool in self._tools.values() if tool.enabled]

    def _tool_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._enabled_tools()]

    def _execute(
        self,
        name: str,
        args: Dict[str, Any],
        *,
        run_id: Optional[str] = None,
        iteration: Optional[int] = None,
        model_text: Optional[str] = None,
    ) -> str:
        t = lib.Timer()
        ok = True
        error: Optional[str] = None
        output: str

        if name not in self._tools:
            ok = False
            error = f"unknown tool {name!r}"
            output = f"Error: {error}"
        else:
            tool = self._tools[name]
            if not tool.enabled:
                ok = False
                error = f"tool {name!r} is disabled"
                output = f"Error: {error}"
            elif not isinstance(args, dict):
                ok = False
                error = f"tool {name!r} arguments must be an object"
                output = f"Error: {error}"
            else:
                err = _validate_schema_value(tool.parameters, args)
                if err:
                    ok = False
                    error = err
                    output = f"Error: {err}"
                else:
                    self._emit(
                        {
                            "event": "tool_start",
                            "run_id": run_id,
                            "iteration": iteration,
                            "tool": name,
                            "args": args,
                            "model_reasoning": model_text or None,
                        }
                    )

                    try:
                        output = tool.run(args)
                    except Exception as exc:
                        ok = False
                        error = repr(exc)
                        output = f"Error: {exc}"

                    # Detect tools that signal failure via error-string return
                    # rather than raising (e.g. "Error: file not found",
                    # "Error: blocked shell syntax detected").
                    if ok and _is_error_output(output):
                        ok = False
                        error = output.lstrip()[6:].strip()

        self._emit(
            {
                "event": "tool_end",
                "run_id": run_id,
                "iteration": iteration,
                "tool": name,
                "ok": ok,
                "error": error,
                "duration_ms": round(t.ms, 3),
                "output_chars": len(output),
                "output_preview": output[:500] if output else None,
            }
        )

        return output

    def _init_run_state(self) -> None:
        self._state = {
            "tool_calls_total": 0,
            "call_counts": {},  # key -> count
            "recent": [],  # list[{tool,args_preview,summary,ok}]
            "recent_errors": [],
            "consecutive_error_iters": 0,
        }

    def _record_tool_result(self, name: str, args: Dict[str, Any], output: str) -> None:
        summary, _ = _summarize_tool_output(name, output)

        rec = {
            "tool": name,
            "args_preview": _fmt_args(name, args),
            "summary": summary[:2000],
            "ok": not _is_error_output(output or ""),
        }
        self._state["recent"].append(rec)
        self._state["recent"] = self._state["recent"][-12:]

        if not rec["ok"]:
            self._state["recent_errors"].append(f"{name}: {summary[:400]}")
            self._state["recent_errors"] = self._state["recent_errors"][-5:]

    def _workspace_context_block(self, *, iteration: int, max_iterations: int) -> str:
        tool_calls_total = int(self._state.get("tool_calls_total", 0))
        recent = self._state.get("recent", [])
        recent_errors = self._state.get("recent_errors", [])

        lines: List[str] = []
        lines.append("WORKSPACE CONTEXT")
        lines.append(f"- iteration: {iteration}/{max_iterations}")
        lines.append(
            f"- tool_calls_total: {tool_calls_total}/{self._max_tool_calls_total}"
        )

        if recent_errors:
            lines.append("- recent_errors:")
            for e in recent_errors[-3:]:
                lines.append(f"  - {e}")

        if recent:
            lines.append("- recent_tool_results:")
            for r in recent[-10:]:
                s = (r.get("summary") or "").replace("\n", " | ")
                s = (s[:240] + "…") if len(s) > 240 else s
                lines.append(f"  - {r['tool']}({r['args_preview']}): {s}")

        return "\n".join(lines).strip()

    @staticmethod
    def _upsert_workspace_context(messages: List[Dict[str, Any]], block: str) -> None:
        """Append or update WORKSPACE CONTEXT on the last user message.

        Keeping this out of the system prompt lets the static system message stay
        identical across every iteration, which is required for Anthropic prompt
        caching to hit.  Attaching the block to the last user message (string or
        tool-result blocks) is semantically equivalent and does not break turn
        alternation rules.
        """
        _MARKER = "WORKSPACE CONTEXT"

        for i in range(len(messages) - 1, -1, -1):
            m = messages[i]
            if m.get("role") != "user":
                continue
            c = m.get("content", "")

            if isinstance(c, str):
                # Strip any prior workspace block then append the fresh one.
                tag = "\n\n" + _MARKER
                idx = c.find(tag)
                base = c[:idx] if idx >= 0 else (c if not c.startswith(_MARKER) else "")
                messages[i] = dict(m, content=(base + "\n\n" + block).lstrip())
                return

            if isinstance(c, list):
                # Drop any previous workspace text block and append the new one.
                kept = [
                    b for b in c
                    if not (
                        isinstance(b, dict)
                        and b.get("type") == "text"
                        and b.get("text", "").startswith(_MARKER)
                    )
                ]
                kept.append({"type": "text", "text": block})
                messages[i] = dict(m, content=kept)
                return

        # No user message found yet — prepend as the first user message.
        messages.append({"role": "user", "content": block})

    def run(
        self,
        task: str,
        system: str = "",
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Run the agent on a task and return its final answer."""

        messages: List[Dict[str, Any]] = []

        sys_parts: List[str] = []
        if system:
            sys_parts.append(system.strip())
        sys_parts.append(_REACT_NUDGE.strip())
        messages.append(
            {"role": "system", "content": "\n\n".join(p for p in sys_parts if p)}
        )

        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": task})

        total_input_tokens = 0
        total_output_tokens = 0
        total_reasoning_tokens = 0
        total_cache_creation_tokens = 0
        total_cache_read_tokens = 0
        empty_reply_nudged = False

        run_id = lib.new_run_id()
        self._init_run_state()
        self._emit(
            {
                "event": "run_start",
                "run_id": run_id,
                "mode": "native_tools",
                "max_iterations": self.max_iterations,
            }
        )

        for iteration in range(self.max_iterations):
            self._emit(
                {
                    "event": "iteration_start",
                    "run_id": run_id,
                    "iteration": iteration + 1,
                }
            )

            # Refresh compact workspace context each iteration (token efficient grounding).
            self._upsert_workspace_context(
                messages,
                self._workspace_context_block(
                    iteration=iteration + 1, max_iterations=self.max_iterations
                ),
            )

            model_timer = lib.Timer()
            if self.show_diagnostics:
                with alive_bar(
                    None,
                    title=f"  iter {iteration + 1}",
                    spinner="waves",
                    bar=None,
                    monitor=False,
                    stats=False,
                    elapsed=True,
                    receipt=True,
                ):
                    response = self.model.chat_with_tools(messages, self._tool_schemas())
            else:
                response = self.model.chat_with_tools(messages, self._tool_schemas())

            text = (response.get("text") or "").strip()
            tool_calls = response.get("tool_calls") or []
            reasoning = (response.get("reasoning") or "").strip()
            usage = response.get("usage") or getattr(self.model, "last_usage", None)
            input_tokens, output_tokens, reasoning_tokens, cache_creation_tokens, cache_read_tokens = _usage_in_out(usage)
            if usage:
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                total_reasoning_tokens += reasoning_tokens
                total_cache_creation_tokens += cache_creation_tokens
                total_cache_read_tokens += cache_read_tokens
            else:
                total_input_tokens += _count_message_tokens(messages)
                output_text = text
                if not output_text and tool_calls:
                    output_text = json.dumps(tool_calls, ensure_ascii=False)
                total_output_tokens += _count_tokens(output_text) if output_text else 0

            if self.show_diagnostics:
                if reasoning:
                    _print_reasoning_block(reasoning)
                rsn_part = f"  rsn {reasoning_tokens:,}" if reasoning_tokens else ""
                cache_part = (
                    f"  cache_write {cache_creation_tokens:,}  cache_read {cache_read_tokens:,}"
                    if cache_creation_tokens or cache_read_tokens else ""
                )
                print(
                    f"    usage  in {input_tokens:,}  "
                    f"out {output_tokens:,}{rsn_part}{cache_part}  "
                    f"total {input_tokens + cache_creation_tokens + cache_read_tokens + output_tokens:,}"
                )

            self._emit(
                {
                    "event": "model_response",
                    "run_id": run_id,
                    "iteration": iteration + 1,
                    "duration_ms": round(model_timer.ms, 3),
                    "text_chars": len(text),
                    "tool_calls": len(tool_calls),
                    "usage": usage,
                    "model_text": text[:500] if text else None,
                    "model_reasoning": reasoning[:500] if reasoning else None,
                }
            )

            # ReAct rule: if tool calls exist, execute them even if some text is also present.
            if tool_calls:
                if (
                    int(self._state.get("tool_calls_total", 0))
                    >= self._max_tool_calls_total
                ):
                    return (
                        f"[Agent stopped: tool_calls_total={self._state.get('tool_calls_total')} "
                        f"reached budget={self._max_tool_calls_total} without a final answer]"
                    )

                limited_calls = tool_calls[: self._max_tool_calls_per_iteration]
                skipped = len(tool_calls) - len(limited_calls)

                outputs: List[str] = []
                executed_calls: List[Dict[str, Any]] = []

                for call in limited_calls:
                    call_name = call.get("name", "")
                    call_args = call.get("arguments", {})

                    # Preserve non-dict arguments for better self-correction.
                    raw_args = call.get("_raw_arguments")
                    raw_args_err = call.get("_raw_arguments_error")

                    if not isinstance(call_args, dict):
                        call_args = {}

                    # Balanced repetition policy:
                    # - Allow more repeats for read (often used for paging / post-edit verification)
                    # - Reset repeat counts after successful edit/write (workspace changed)
                    max_repeats = (
                        (self._max_repeated_calls * 3)
                        if call_name == "read"
                        else self._max_repeated_calls
                    )

                    key = _tool_call_key(call_name, call_args)
                    counts = self._state.get("call_counts", {})
                    counts[key] = int(counts.get(key, 0)) + 1
                    self._state["call_counts"] = counts

                    if counts[key] > max_repeats:
                        hint = (
                            f"Error: repeated tool call blocked after {max_repeats} tries. "
                            "Change arguments (e.g., different offset/limit/path) or change approach."
                        )
                        summary, _ = self._record_tool_result(
                            call_name, call_args, hint
                        )
                        outputs.append(summary)
                        executed_calls.append(call)
                        continue

                    if self.show_diagnostics:
                        args_preview = _fmt_args(call_name, call_args)
                        print(
                            f"    ▸ {call_name:<5}  {args_preview:<60}",
                            end="",
                            flush=True,
                        )

                    # If the provider emitted invalid JSON arguments, surface that clearly.
                    if raw_args_err:
                        output = (
                            "Error: tool call arguments were not valid JSON and could not be parsed.\n"
                            f"tool={call_name!r}\n"
                            f"parse_error={raw_args_err}\n"
                            f"raw_arguments={raw_args!r}\n"
                            "Fix: emit a tool call with a JSON object matching the tool schema."
                        )
                    else:
                        output = self._execute(
                            call_name, call_args, run_id=run_id, iteration=iteration + 1,
                            model_text=text or None,
                        )

                    # Count only real tool executions against the total budget.
                    if not raw_args_err:
                        self._state["tool_calls_total"] = (
                            int(self._state.get("tool_calls_total", 0)) + 1
                        )

                    self._record_tool_result(call_name, call_args, output)

                    # If workspace changed, allow repeats again (read-after-edit, re-run bash, etc.).
                    if (not _is_error_output(output or "")) and call_name in (
                        "edit",
                        "write",
                    ):
                        self._state["call_counts"] = {}

                    # Cap very large outputs in the message history to prevent
                    # the context window from growing unboundedly across iterations.
                    # Errors and small outputs are always passed in full.
                    _MAX_HIST_CHARS = 8000
                    if not _is_error_output(output) and len(output) > _MAX_HIST_CHARS:
                        msg_output = (
                            output[:_MAX_HIST_CHARS]
                            + f"\n…[output truncated: {len(output) - _MAX_HIST_CHARS} chars omitted."
                            " Use read(path, offset=N) to page through the rest.]"
                        )
                    else:
                        msg_output = output
                    outputs.append(msg_output)
                    executed_calls.append(call)

                    if self.show_diagnostics:
                        print(f"  {_diagnostic_result_hint(call_name, output)}")

                if skipped > 0:
                    outputs.append(
                        f"Note: {skipped} tool call(s) were skipped this iteration due to max_tool_calls_per_iteration={self._max_tool_calls_per_iteration}."
                    )
                    executed_calls.append(
                        {
                            "id": "skipped_tool_calls_note",
                            "name": "note",
                            "arguments": {},
                        }
                    )

                messages.extend(
                    self.model.format_tool_result_messages(
                        executed_calls,
                        outputs,
                        reasoning_blocks=response.get("reasoning_blocks"),
                    )
                )

                # Stuck-loop detection: count consecutive iterations where every
                # tool call failed; nudge the agent to emit a BLOCKED answer.
                real_outputs = [o for o in outputs if not o.startswith("Note:")]
                if real_outputs and all(_is_error_output(o) for o in real_outputs):
                    self._state["consecutive_error_iters"] = self._state.get("consecutive_error_iters", 0) + 1
                else:
                    self._state["consecutive_error_iters"] = 0

                if self._state.get("consecutive_error_iters", 0) >= self._max_consecutive_error_iters:
                    self._state["consecutive_error_iters"] = 0
                    _stuck = (
                        "Every tool call for several consecutive iterations has failed. "
                        "Stop attempting tool calls and output a BLOCKED: section "
                        "listing exactly what is preventing progress and what the user must resolve."
                    )
                    last = messages[-1]
                    if isinstance(last.get("content"), str):
                        messages[-1] = dict(last, content=last["content"] + "\n\n" + _stuck)
                    else:
                        messages.append({"role": "user", "content": _stuck})

                self._emit(
                    {
                        "event": "iteration_end",
                        "run_id": run_id,
                        "iteration": iteration + 1,
                        "stop_reason": "tool_calls",
                    }
                )
                continue

            if text:
                if self.show_diagnostics:
                    print()
                    total = total_input_tokens + total_cache_creation_tokens + total_cache_read_tokens + total_output_tokens
                    rsn_part = f"  rsn {total_reasoning_tokens:,}" if total_reasoning_tokens else ""
                    cache_part = (
                        f"  cache_write {total_cache_creation_tokens:,}  cache_read {total_cache_read_tokens:,}"
                        if total_cache_creation_tokens or total_cache_read_tokens else ""
                    )
                    print(
                        f"  tokens  in {total_input_tokens:,}  "
                        f"out {total_output_tokens:,}{rsn_part}{cache_part}  "
                        f"total {total:,}"
                    )

                self._emit(
                    {
                        "event": "run_end",
                        "run_id": run_id,
                        "iteration": iteration + 1,
                        "stop_reason": "final_text",
                        "total_input_tokens": total_input_tokens,
                        "total_output_tokens": total_output_tokens,
                        "total_reasoning_tokens": total_reasoning_tokens,
                        "total_cache_creation_tokens": total_cache_creation_tokens,
                        "total_cache_read_tokens": total_cache_read_tokens,
                    }
                )
                return text

            if not empty_reply_nudged:
                empty_reply_nudged = True
                recent_errors = self._state.get("recent_errors", [])
                if any("JSON" in e or "not valid JSON" in e for e in recent_errors):
                    nudge = (
                        "Your last tool call could not be parsed because the arguments "
                        "were not valid JSON. Please re-emit the tool call with a properly "
                        "formed JSON object matching the tool schema."
                    )
                else:
                    nudge = (
                        "Reply with either tool_calls (to take an action) "
                        "or a final answer as text."
                    )
                last = messages[-1]
                if isinstance(last.get("content"), str):
                    messages[-1] = dict(last, content=last["content"] + "\n\n" + nudge)
                else:
                    messages.append({"role": "user", "content": nudge})
                continue

        if self.show_diagnostics:
            total = total_input_tokens + total_output_tokens
            rsn_part = f"  rsn {total_reasoning_tokens:,}" if total_reasoning_tokens else ""
            cache_part = (
                f"  cache_write {total_cache_creation_tokens:,}  cache_read {total_cache_read_tokens:,}"
                if total_cache_creation_tokens or total_cache_read_tokens else ""
            )
            print(
                f"  tokens  in {total_input_tokens:,}  "
                f"out {total_output_tokens:,}{rsn_part}{cache_part}  "
                f"total {total:,}"
            )

        self._emit(
            {
                "event": "run_end",
                "run_id": run_id,
                "iteration": self.max_iterations,
                "stop_reason": "max_iterations",
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_reasoning_tokens": total_reasoning_tokens,
                "total_cache_creation_tokens": total_cache_creation_tokens,
                "total_cache_read_tokens": total_cache_read_tokens,
            }
        )

        return f"[Agent stopped: max_iterations={self.max_iterations} reached without a final answer]"
