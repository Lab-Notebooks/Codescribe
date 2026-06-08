"""Standalone baremetal coding agent with tool-use support across LLM backends."""

import copy
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from codescribe import lib

# ---------------------------------------------------------------------------
# Text fallback tool protocol
# ---------------------------------------------------------------------------
# Models without native tool-calling should emit:
#
#   <tool_call>
#   {"name": "<tool>", "args": {...}}
#   </tool_call>
#
# Tool results are returned as:
#
#   <tool_result>
#   {"name": "<tool>", "output": "..."}
#   </tool_result>
#
# Completion:
#
#   <final_answer>
#   ...
#   </final_answer>
# ---------------------------------------------------------------------------

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_FINAL_ANSWER_RE = re.compile(r"<final_answer>\s*(.*?)\s*</final_answer>", re.DOTALL)

_TEXT_PROTOCOL_PREAMBLE = """\
You are a standalone baremetal coding agent.

You can inspect files, run shell commands, edit files precisely, and write files.
IMPORTANT: You MUST use tools to perform any action. Never describe what you would do —
actually execute it by calling the appropriate tool. Do not fabricate file contents,
command output, or any other results.
Available tools:
{tool_list}

To call a tool, emit EXACTLY this block (no other format is accepted):

<tool_call>
{{"name": "<tool_name>", "args": {{...}}}}
</tool_call>

You may emit multiple tool calls in one response.
After tool results are returned, continue working until the task is fully complete.
Only after ALL required tool calls are done, emit:

<final_answer>
Your final response here.
</final_answer>

CRITICAL: Do NOT emit <final_answer> until all necessary tool calls have been made and confirmed.
Do not emit tool calls after <final_answer>.
"""

# ---------------------------------------------------------------------------
# Native tool-calling (chat_with_tools) ReAct nudge
# ---------------------------------------------------------------------------
# Keep this short and non-format-prescriptive: native tool calls are the "Action"
# and tool result messages are the "Observation".
_NATIVE_REACT_NUDGE = """\
You are a coding agent with access to tools.

Rules:
- Use tools whenever you need to inspect files, run commands, or change the filesystem.
- Do NOT fabricate tool outputs. If you need info, call a tool.
- Prefer batching: when possible, call multiple tools in one turn.
- When you have enough information and all required actions are complete, respond with the final answer as normal text.
"""

__all__ = [
    "AgentTool",
    "ReadTool",
    "BashTool",
    "EditTool",
    "WriteTool",
    "make_bounded_tools",
    "DEFAULT_TOOLS",
    "Agent",
]


class AgentTool:
    """Base tool for the standalone coding agent."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.enabled = enabled

    def run(self, args: Dict[str, Any]) -> str:
        raise NotImplementedError(f"{self.name}.run() is not implemented")

    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def describe_for_prompt(self) -> str:
        return (
            f"- {self.name}: {self.description}\n"
            f"  JSON schema: {json.dumps(self.parameters, ensure_ascii=False)}"
        )


class ReadTool(AgentTool):
    def __init__(self, root: Optional[Path] = None) -> None:
        desc = "Read a text file. Supports optional 1-indexed offset and line limit."
        if root is not None:
            desc += " Access is restricted to the working directory tree."
        super().__init__(
            name="read",
            description=desc,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read."},
                    "offset": {
                        "type": "integer",
                        "description": "1-indexed starting line number.",
                        "minimum": 1,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read.",
                        "minimum": 1,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            enabled=True,
        )
        self.root = Path(root).resolve() if root is not None else None

    def run(self, args: Dict[str, Any]) -> str:
        path = args.get("path")
        offset = args.get("offset")
        limit = args.get("limit")

        if not path:
            return "Error: missing required argument 'path'"

        if self.root is not None:
            try:
                path = str(_resolve_within_root(self.root, path))
            except Exception as exc:
                return f"Error: {exc}"

        if not os.path.exists(path):
            return f"Error: file not found: {path}"
        if not os.path.isfile(path):
            return f"Error: not a file: {path}"

        try:
            with open(path, "r", errors="replace") as fh:
                lines = fh.readlines()
        except Exception as exc:
            return f"Error: {exc}"

        start = max(int(offset or 1), 1) - 1
        end = len(lines) if limit is None else start + max(int(limit), 1)
        chunk = lines[start:end]

        if not chunk:
            return ""
        return "".join(chunk)


class BashTool(AgentTool):
    _BLOCKED_CHARS = set("|&;><`$\\")
    _DEFAULT_ALLOWED = {
        "ls",
        "pwd",
        "find",
        "grep",
        "head",
        "tail",
        "wc",
        "git",
        "test",
        "echo",
        "sed",
    }

    def __init__(
        self,
        cwd: Optional[Path] = None,
        bounded: bool = False,
        allowed_commands: Optional[set] = None,
    ) -> None:
        desc = "Execute a bash command in the current working directory."
        if cwd is not None:
            desc += (
                " Commands execute with the working directory set to the bounded root."
                " Only access files and paths within the working directory;"
                " do not navigate to or read from paths outside it."
            )
        if bounded:
            desc += (
                " In bounded mode, commands are validated before execution, shell metacharacters"
                " are rejected, and only a small allowlist of commands is permitted."
            )
        super().__init__(
            name="bash",
            description=desc,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds.",
                        "minimum": 1,
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            enabled=True,
        )
        self.cwd = str(Path(cwd).resolve()) if cwd is not None else None
        self.cwd_path = Path(cwd).resolve() if cwd is not None else None
        self.bounded = bounded
        self.allowed_commands = allowed_commands or set(self._DEFAULT_ALLOWED)

    def _validate_bounded_command(self, cmd: str) -> Optional[str]:
        if any(ch in cmd for ch in self._BLOCKED_CHARS):
            return "shell metacharacters are not allowed in bounded mode"

        try:
            argv = shlex.split(cmd)
        except ValueError as exc:
            return f"invalid shell syntax: {exc}"

        if not argv:
            return "empty command"

        prog = argv[0]
        if "/" in prog:
            return "explicit executable paths are not allowed in bounded mode"
        if prog not in self.allowed_commands:
            return f"command {prog!r} is not allowed in bounded mode"

        for token in argv[1:]:
            if token.startswith("-"):
                continue
            if token == ".":
                continue
            if ".." in token:
                return f"path escape not allowed in bounded mode: {token!r}"
            if token.startswith("/"):
                return f"absolute paths not allowed in bounded mode: {token!r}"

        return None

    def _format_result(self, proc: subprocess.CompletedProcess) -> str:
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        parts = [f"exit_code: {proc.returncode}"]
        if stdout.strip():
            parts.append(f"STDOUT:\n{stdout.rstrip()}")
        if stderr.strip():
            parts.append(f"STDERR:\n{stderr.rstrip()}")
        if len(parts) == 1:
            parts.append("(no output)")
        return "\n\n".join(parts)

    def run(self, args: Dict[str, Any]) -> str:
        cmd = args.get("command")
        timeout = int(args.get("timeout", 30))
        if not cmd:
            return "Error: missing required argument 'command'"

        try:
            if self.bounded:
                validation_error = self._validate_bounded_command(cmd)
                if validation_error:
                    return f"Error: {validation_error}"
                proc = subprocess.run(
                    shlex.split(cmd),
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(self.cwd_path) if self.cwd_path is not None else None,
                )
            else:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self.cwd,
                )
        except subprocess.TimeoutExpired:
            return f"Error: command timed out ({timeout} s)"
        except Exception as exc:
            return f"Error: {exc}"

        return self._format_result(proc)


class EditTool(AgentTool):
    def __init__(
        self,
        root: Optional[Path] = None,
        protected_paths: Optional[set] = None,
    ) -> None:
        desc = (
            "Edit a file using exact text replacement. "
            "Provide path and edits:[{oldText,newText}, ...]. "
            "Each oldText must match the original file exactly."
        )
        if root is not None:
            desc += " Access is restricted to the working directory tree."
        super().__init__(
            name="edit",
            description=desc,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to edit."},
                    "edits": {
                        "type": "array",
                        "description": "List of exact text replacements applied against the original file.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "oldText": {"type": "string"},
                                "newText": {"type": "string"},
                            },
                            "required": ["oldText", "newText"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                    },
                },
                "required": ["path", "edits"],
                "additionalProperties": False,
            },
            enabled=True,
        )
        self.root = Path(root).resolve() if root is not None else None
        self.protected_paths: set = protected_paths or set()

    def run(self, args: Dict[str, Any]) -> str:
        path = args.get("path")
        edits = args.get("edits")

        if not path:
            return "Error: missing required argument 'path'"
        if not isinstance(edits, list) or not edits:
            return "Error: 'edits' must be a non-empty list"

        if self.root is not None:
            try:
                path = str(_resolve_within_root(self.root, path))
            except Exception as exc:
                return f"Error: {exc}"
        if self.protected_paths and Path(path).resolve() in self.protected_paths:
            return f"Error: {args.get('path')!r} is read-only and cannot be edited"

        if not os.path.exists(path):
            return f"Error: file not found: {path}"
        if not os.path.isfile(path):
            return f"Error: not a file: {path}"

        try:
            with open(path, "r", errors="replace") as fh:
                original = fh.read()
        except Exception as exc:
            return f"Error: {exc}"

        matches = []
        for idx, edit in enumerate(edits):
            if not isinstance(edit, dict):
                return f"Error: edit #{idx + 1} is not an object"
            old = edit.get("oldText")
            new = edit.get("newText")
            if old is None or new is None:
                return f"Error: edit #{idx + 1} must contain 'oldText' and 'newText'"

            start = original.find(old)
            if start == -1:
                return f"Error: edit #{idx + 1} oldText not found in {path!r}"
            second = original.find(old, start + 1)
            if second != -1:
                return f"Error: edit #{idx + 1} oldText is not unique in {path!r}"
            end = start + len(old)
            matches.append((start, end, new, idx + 1))

        matches.sort(key=lambda item: item[0])
        for i in range(len(matches) - 1):
            _, end_a, _, idx_a = matches[i]
            start_b, _, _, idx_b = matches[i + 1]
            if start_b < end_a:
                return f"Error: edit #{idx_a} overlaps edit #{idx_b}"

        pieces = []
        cursor = 0
        for start, end, new_text, _ in matches:
            pieces.append(original[cursor:start])
            pieces.append(new_text)
            cursor = end
        pieces.append(original[cursor:])
        updated = "".join(pieces)

        try:
            with open(path, "w") as fh:
                fh.write(updated)
        except Exception as exc:
            return f"Error: {exc}"

        return f"Edited {path} with {len(edits)} replacement(s)"


class WriteTool(AgentTool):
    def __init__(
        self,
        root: Optional[Path] = None,
        protected_paths: Optional[set] = None,
    ) -> None:
        desc = "Create or overwrite a file with the provided content."
        if root is not None:
            desc += " Access is restricted to the working directory tree."
        super().__init__(
            name="write",
            description=desc,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to write."},
                    "content": {"type": "string", "description": "Full file contents."},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            enabled=True,
        )
        self.root = Path(root).resolve() if root is not None else None
        self.protected_paths: set = protected_paths or set()

    def run(self, args: Dict[str, Any]) -> str:
        path = args.get("path")
        content = args.get("content")
        if not path:
            return "Error: missing required argument 'path'"
        if content is None:
            return "Error: missing required argument 'content'"

        if self.root is not None:
            try:
                path = str(_resolve_within_root(self.root, path))
            except Exception as exc:
                return f"Error: {exc}"
        if self.protected_paths and Path(path).resolve() in self.protected_paths:
            return f"Error: {args.get('path')!r} is read-only and cannot be written"

        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w") as fh:
                fh.write(content)
            return f"Wrote {path} ({len(content)} bytes)"
        except Exception as exc:
            return f"Error: {exc}"


def _resolve_within_root(root: Path, target: str) -> Path:
    root = root.resolve()
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(f"Path escapes working directory: {target}")

    return candidate


def make_bounded_tools(
    root: Path,
    protected_paths: Optional[List[Path]] = None,
    allow_write: bool = True,
    bash_allow: Optional[set] = None,
) -> List[AgentTool]:
    allowed = set(BashTool._DEFAULT_ALLOWED)
    if bash_allow:
        allowed |= set(bash_allow)

    tools: List[AgentTool] = [
        ReadTool(root=root),
        BashTool(cwd=root, bounded=True, allowed_commands=allowed),
    ]
    if allow_write:
        _protected = {p.resolve() for p in (protected_paths or [])}
        tools.extend(
            [
                EditTool(root=root, protected_paths=_protected),
                WriteTool(root=root, protected_paths=_protected),
            ]
        )
    return tools


DEFAULT_TOOLS: List[AgentTool] = [
    ReadTool(),
    BashTool(),
    EditTool(),
    WriteTool(),
]


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


def _usage_in_out(usage: Optional[Dict[str, Any]]) -> Tuple[int, int]:
    if not usage:
        return 0, 0
    input_tokens = usage.get("prompt_tokens")
    if input_tokens is None:
        input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("completion_tokens")
    if output_tokens is None:
        output_tokens = usage.get("output_tokens", 0)
    return int(input_tokens or 0), int(output_tokens or 0)


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


def _fmt_result(name: str, output: str) -> str:
    """Short human-readable summary of tool output."""
    if output.startswith("Error:"):
        msg = output[6:].strip()
        return "err  " + ((msg[:50] + "…") if len(msg) > 50 else msg)
    if name == "bash":
        lines = output.splitlines()
        code_str = (lines[0] if lines else "").replace("exit_code:", "exit").strip()
        content = [l for l in lines[1:] if l and l not in ("STDOUT:", "STDERR:")]
        n = len(content)
        if "exit 0" in code_str:
            return f"{code_str}  {n} lines" if n > 0 else code_str
        hint = content[0] if content else ""
        hint = (hint[:40] + "…") if len(hint) > 40 else hint
        return f"{code_str}  {hint}" if hint else code_str
    if name == "read":
        n = len(output.splitlines()) if output.strip() else 0
        return f"{n} line{'s' if n != 1 else ''}" if n > 0 else "(empty)"
    if name == "write":
        m = re.search(r"\((\d+) bytes\)", output)
        return f"{m.group(1)} B" if m else output.strip()[:30]
    if name == "edit":
        m = re.search(r"(\d+) replacement", output)
        n = int(m.group(1)) if m else 0
        return f"{n} edit{'s' if n != 1 else ''}"
    return (output.splitlines()[0][:40]) if output else "(empty)"


def _validate_schema_value(schema: Dict[str, Any], value: Any, path: str = "args") -> Optional[str]:
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


def _truncate_for_model(text: str, max_chars: Optional[int] = 4000) -> str:
    """Compact tool output to fit within a model context budget.

    If max_chars is None or <= 0, truncation is disabled.

    This prefers line-aware compaction (keep head/tail lines) and falls back
    to character slicing for extremely long single-line outputs.
    """

    if max_chars is None or max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text

    # Normalize newlines so line accounting is stable.
    text_n = text.replace("\r\n", "\n").replace("\r", "\n")

    # If it's essentially a single line (or very few), do a head/tail char slice.
    if text_n.count("\n") <= 1:
        head = max_chars // 2
        tail = max_chars - head
        omitted = len(text_n) - max_chars
        return (
            text_n[:head]
            + f"\n\n...[truncated {omitted} chars]...\n\n"
            + text_n[-tail:]
        )

    lines = text_n.split("\n")
    total_lines = len(lines)

    # Budget for the marker line and surrounding newlines.
    marker_template = "...[truncated {omitted_lines} lines / {omitted_chars} chars]..."

    # Start with a reasonable split, then adjust to fit.
    head_lines = max(5, min(200, total_lines // 4))
    tail_lines = max(5, min(200, total_lines // 4))

    def render(h: int, t: int) -> str:
        h = max(0, min(h, total_lines))
        t = max(0, min(t, total_lines - h))
        head_part = "\n".join(lines[:h])
        tail_part = "\n".join(lines[-t:]) if t else ""
        kept = head_part + ("\n" if head_part and (tail_part or True) else "") + tail_part
        omitted_lines = max(0, total_lines - (h + t))
        omitted_chars = max(0, len(text_n) - len(head_part) - len(tail_part))
        marker = marker_template.format(omitted_lines=omitted_lines, omitted_chars=omitted_chars)
        if tail_part:
            return head_part + "\n\n" + marker + "\n\n" + tail_part
        return head_part + "\n\n" + marker

    out = render(head_lines, tail_lines)

    # Shrink until within budget.
    # Prefer shrinking tail first (often repetitive), then head.
    while len(out) > max_chars and (head_lines > 1 or tail_lines > 1):
        if tail_lines > 1:
            tail_lines = max(1, int(tail_lines * 0.8))
        elif head_lines > 1:
            head_lines = max(1, int(head_lines * 0.8))
        out = render(head_lines, tail_lines)

    # If still too large (e.g., gigantic lines), fall back to safe char slicing.
    if len(out) > max_chars:
        head = max_chars // 2
        tail = max_chars - head
        omitted = len(text_n) - max_chars
        return (
            text_n[:head]
            + f"\n\n...[truncated {omitted} chars]...\n\n"
            + text_n[-tail:]
        )

    return out


class Agent:
    """Standalone coding agent that works with any backend in lib._llm."""

    def __init__(
        self,
        model: lib.Model,
        tools: Optional[List[AgentTool]] = None,
        max_iterations: int = 20,
        show_diagnostics: bool = False,
        tool_output_max_chars: Optional[int] = 4000,
        logging: Optional[Any] = None,
    ) -> None:

        if not isinstance(model, lib.ALLOWED_MODEL_TYPES):
            allowed = ", ".join(t.__name__ for t in lib.ALLOWED_MODEL_TYPES)
            raise TypeError(
                f"Invalid model type: {type(model).__name__}. Expected one of: {allowed}"
            )

        self.model = model
        source = tools if tools is not None else DEFAULT_TOOLS
        self._tools: Dict[str, AgentTool] = {t.name: copy.copy(t) for t in source}
        self.max_iterations = max_iterations
        self.show_diagnostics = show_diagnostics
        self.tool_output_max_chars = tool_output_max_chars

        # Logging sink (JSONL recommended). Must expose .emit(dict).
        self.logging = logging if logging is not None else lib.NullDiagnosticsSink()

    def enable_tool(self, name: str) -> None:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name!r}")
        self._tools[name].enabled = True

    def disable_tool(self, name: str) -> None:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name!r}")
        self._tools[name].enabled = False

    def _enabled_tools(self) -> List[AgentTool]:
        return [tool for tool in self._tools.values() if tool.enabled]

    def _system_prompt(self, extra: str = "") -> str:
        tool_list = "\n".join(tool.describe_for_prompt() for tool in self._enabled_tools())
        body = _TEXT_PROTOCOL_PREAMBLE.format(tool_list=tool_list)
        return f"{extra}\n\n{body}".lstrip() if extra else body

    def _tool_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._enabled_tools()]

    def _execute(self, name: str, args: Dict[str, Any], *, run_id: Optional[str] = None, iteration: Optional[int] = None) -> str:
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
                    try:
                        self.logging.emit(
                            {
                                "event": "tool_start",
                                "run_id": run_id,
                                "iteration": iteration,
                                "tool": name,
                                "args": args,
                            }
                        )
                    except Exception:
                        pass

                    try:
                        output = tool.run(args)
                    except Exception as exc:
                        ok = False
                        error = repr(exc)
                        output = f"Error: {exc}"

        truncated = False
        if self.tool_output_max_chars is not None and self.tool_output_max_chars > 0:
            truncated = len(output) > self.tool_output_max_chars

        try:
            self.logging.emit(
                {
                    "event": "tool_end",
                    "run_id": run_id,
                    "iteration": iteration,
                    "tool": name,
                    "ok": ok,
                    "error": error,
                    "duration_ms": round(t.ms, 3),
                    "output_chars": len(output),
                    "output_truncated": truncated,
                }
            )
        except Exception:
            pass

        return output

    @staticmethod
    def _parse_tool_calls(text: str) -> List[Dict[str, Any]]:
        calls: List[Dict[str, Any]] = []
        for match in _TOOL_CALL_RE.finditer(text):
            raw = match.group(1)
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                calls.append({"_parse_error": str(exc), "_raw": raw})
                continue
            if isinstance(parsed, dict):
                calls.append(parsed)
            else:
                calls.append({"_parse_error": "tool call payload must be a JSON object", "_raw": raw})
        return calls

    @staticmethod
    def _parse_final_answer(text: str) -> Optional[str]:
        match = _FINAL_ANSWER_RE.search(text)
        return match.group(1).strip() if match else None


    def _run_native_tools(
        self,
        task: str,
        system: str = "",
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        messages: List[Dict[str, Any]] = []

        # Native tool-calling ReAct: keep the contract minimal and rely on
        # tool_calls + tool result messages for Act/Observe.
        sys_parts = []
        if system:
            sys_parts.append(system.strip())
        sys_parts.append(_NATIVE_REACT_NUDGE.strip())
        messages.append({"role": "system", "content": "\n\n".join(p for p in sys_parts if p)})

        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": task})

        total_input_tokens = 0
        total_output_tokens = 0

        empty_reply_nudged = False

        run_id = lib.new_run_id()
        try:
            self.logging.emit(
                {
                    "event": "run_start",
                    "run_id": run_id,
                    "mode": "native_tools",
                    "max_iterations": self.max_iterations,
                }
            )
        except Exception:
            pass

        for iteration in range(self.max_iterations):
            try:
                self.logging.emit(
                    {
                        "event": "iteration_start",
                        "run_id": run_id,
                        "iteration": iteration + 1,
                    }
                )
            except Exception:
                pass

            model_timer = lib.Timer()
            response = self.model.chat_with_tools(messages, self._tool_schemas())
            text = (response.get("text") or "").strip()
            tool_calls = response.get("tool_calls") or []
            usage = response.get("usage") or getattr(self.model, "last_usage", None)
            input_tokens, output_tokens = _usage_in_out(usage)
            if usage:
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
            else:
                total_input_tokens += _count_message_tokens(messages)
                output_text = text
                if not output_text and tool_calls:
                    output_text = json.dumps(tool_calls, ensure_ascii=False)
                total_output_tokens += _count_tokens(output_text) if output_text else 0

            if self.show_diagnostics:
                print(f"  iter {iteration + 1}")
                print(
                    f"    usage  in {input_tokens:,}  "
                    f"out {output_tokens:,}  "
                    f"total {input_tokens + output_tokens:,}"
                )

            try:
                self.logging.emit(
                    {
                        "event": "model_response",
                        "run_id": run_id,
                        "iteration": iteration + 1,
                        "duration_ms": round(model_timer.ms, 3),
                        "text_chars": len(text),
                        "tool_calls": len(tool_calls),
                        "usage": usage,
                    }
                )
            except Exception:
                pass

            # ReAct rule: if tool calls exist, execute them even if some text is also present.
            if tool_calls:
                outputs: List[str] = []
                for call in tool_calls:
                    call_name = call.get("name", "")
                    call_args = call.get("arguments", {})
                    if self.show_diagnostics:
                        args_preview = _fmt_args(call_name, call_args)
                        print(f"    ▸ {call_name:<5}  {args_preview:<60}", end="", flush=True)
                    output = self._execute(call_name, call_args, run_id=run_id, iteration=iteration + 1)
                    outputs.append(_truncate_for_model(output, self.tool_output_max_chars))
                    if self.show_diagnostics:
                        print(f"  {_fmt_result(call_name, output)}")
                messages.extend(self.model.format_tool_result_messages(tool_calls, outputs))

                try:
                    self.logging.emit(
                        {
                            "event": "iteration_end",
                            "run_id": run_id,
                            "iteration": iteration + 1,
                            "stop_reason": "tool_calls",
                        }
                    )
                except Exception:
                    pass
                continue

            if text:
                if self.show_diagnostics:
                    print()
                    total = total_input_tokens + total_output_tokens
                    print(
                        f"  tokens  in {total_input_tokens:,}  "
                        f"out {total_output_tokens:,}  "
                        f"total {total:,}"
                    )

                try:
                    self.logging.emit(
                        {
                            "event": "run_end",
                            "run_id": run_id,
                            "iteration": iteration + 1,
                            "stop_reason": "final_text",
                            "total_input_tokens": total_input_tokens,
                            "total_output_tokens": total_output_tokens,
                        }
                    )
                except Exception:
                    pass
                return text

            # Degenerate turn: neither tool calls nor usable text.
            if not empty_reply_nudged:
                empty_reply_nudged = True
                messages.append(
                    {
                        "role": "user",
                        "content": "Reply with either tool_calls (to take an action) or a final answer as text.",
                    }
                )
                continue

        if self.show_diagnostics:
            total = total_input_tokens + total_output_tokens
            print(
                f"  tokens  in {total_input_tokens:,}  "
                f"out {total_output_tokens:,}  "
                f"total {total:,}"
            )

        try:
            self.logging.emit(
                {
                    "event": "run_end",
                    "run_id": run_id,
                    "iteration": self.max_iterations,
                    "stop_reason": "max_iterations",
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                }
            )
        except Exception:
            pass

        return f"[Agent stopped: max_iterations={self.max_iterations} reached without a final answer]"

    def _run_text_protocol(
        self,
        task: str,
        system: str = "",
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._system_prompt(system)}
        ]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": task})

        run_id = lib.new_run_id()
        try:
            self.logging.emit(
                {
                    "event": "run_start",
                    "run_id": run_id,
                    "mode": "text_protocol",
                    "max_iterations": self.max_iterations,
                }
            )
        except Exception:
            pass

        tool_calls_ever_made = False
        final_without_tools_pushed = False
        current_context_tokens = _count_message_tokens(messages)
        total_input_tokens = 0
        total_output_tokens = 0

        for iteration in range(self.max_iterations):
            try:
                self.logging.emit(
                    {
                        "event": "iteration_start",
                        "run_id": run_id,
                        "iteration": iteration + 1,
                    }
                )
            except Exception:
                pass
            # Full context is sent on every call; accumulate before calling.
            total_input_tokens += current_context_tokens
            model_timer = lib.Timer()
            response = self.model.chat(messages)
            total_output_tokens += _count_tokens(response)

            try:
                self.logging.emit(
                    {
                        "event": "model_response",
                        "run_id": run_id,
                        "iteration": iteration + 1,
                        "duration_ms": round(model_timer.ms, 3),
                        "text_chars": len(response or ""),
                        "usage": getattr(self.model, "last_usage", None),
                    }
                )
            except Exception:
                pass

            if self.show_diagnostics:
                print(f"  iter {iteration + 1}")

            # Check tool calls FIRST. Execute them even if <final_answer> is also
            # present in the same response — the model must not skip tool execution.
            tool_calls = self._parse_tool_calls(response)
            if tool_calls:
                tool_calls_ever_made = True
                messages.append({"role": "assistant", "content": response})
                current_context_tokens += _count_tokens(response)

                result_blocks: List[str] = []
                for call in tool_calls:
                    if "_parse_error" in call:
                        call_name = "?"
                        output = f"Error parsing tool call: {call['_parse_error']}"
                        if self.show_diagnostics:
                            print(f"    ✗ parse error: {call['_parse_error'][:80]}")
                    else:
                        call_name = call.get("name", "")
                        call_args = call.get("args", {})
                        if self.show_diagnostics:
                            args_preview = _fmt_args(call_name, call_args)
                            print(f"    ▸ {call_name:<5}  {args_preview:<60}", end="", flush=True)
                        output = self._execute(call_name, call_args, run_id=run_id, iteration=iteration + 1)
                        if self.show_diagnostics:
                            print(f"  {_fmt_result(call_name, output)}")

                    result_blocks.append(
                        "<tool_result>\n"
                        + json.dumps(
                            {
                                "name": call_name,
                                "output": _truncate_for_model(output, self.tool_output_max_chars),
                            },
                            ensure_ascii=False,
                        )
                        + "\n</tool_result>"
                    )

                tool_results_text = "\n".join(result_blocks)
                messages.append({"role": "user", "content": tool_results_text})
                current_context_tokens += _count_tokens(tool_results_text)

                try:
                    self.logging.emit(
                        {
                            "event": "iteration_end",
                            "run_id": run_id,
                            "iteration": iteration + 1,
                            "stop_reason": "tool_calls",
                        }
                    )
                except Exception:
                    pass

                continue

            final = self._parse_final_answer(response)
            if final is not None:
                if not tool_calls_ever_made and not final_without_tools_pushed:
                    # Model jumped straight to <final_answer> without calling any tools.
                    # Give it one opportunity to actually use tools before accepting.
                    final_without_tools_pushed = True
                    nudge = (
                        "You emitted <final_answer> without calling any tools. "
                        "If this task requires creating files, running commands, or "
                        "reading files, use <tool_call> blocks to actually perform "
                        "those actions — do not simulate results. "
                        "Only emit <final_answer> after all required tool calls are complete."
                    )
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content": nudge})
                    current_context_tokens += _count_tokens(response) + _count_tokens(nudge)
                    continue
                if self.show_diagnostics:
                    print()
                    total = total_input_tokens + total_output_tokens
                    print(
                        f"  tokens  in {total_input_tokens:,}  "
                        f"out {total_output_tokens:,}  "
                        f"total {total:,}"
                    )
                try:
                    self.logging.emit(
                        {
                            "event": "run_end",
                            "run_id": run_id,
                            "iteration": iteration + 1,
                            "stop_reason": "final_answer",
                            "total_input_tokens": total_input_tokens,
                            "total_output_tokens": total_output_tokens,
                        }
                    )
                except Exception:
                    pass

                return final

            # No tool calls and no final answer: push back.
            nudge = (
                "You must use a <tool_call> block to take any action, "
                "or wrap your final response in <final_answer> tags. "
                "Do not describe actions — execute them via tools."
            )
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": nudge})
            current_context_tokens += _count_tokens(response) + _count_tokens(nudge)

        if self.show_diagnostics:
            total = total_input_tokens + total_output_tokens
            print(
                f"  tokens  in {total_input_tokens:,}  "
                f"out {total_output_tokens:,}  "
                f"total {total:,}"
            )

        try:
            self.logging.emit(
                {
                    "event": "run_end",
                    "run_id": run_id,
                    "iteration": self.max_iterations,
                    "stop_reason": "max_iterations",
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                }
            )
        except Exception:
            pass

        return f"[Agent stopped: max_iterations={self.max_iterations} reached without a final answer]"

    def run(
        self,
        task: str,
        system: str = "",
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Run the agent on a task and return its final answer."""
        if getattr(self.model, "supports_native_tools", False) and hasattr(self.model, "chat_with_tools"):
            return self._run_native_tools(task=task, system=system, chat_history=chat_history)
        return self._run_text_protocol(task=task, system=system, chat_history=chat_history)
