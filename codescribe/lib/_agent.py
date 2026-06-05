"""Standalone baremetal coding agent with tool-use support across LLM backends."""

import copy
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

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

__all__ = [
    "AgentTool",
    "ReadTool",
    "BashTool",
    "EditTool",
    "WriteTool",
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
    def __init__(self) -> None:
        super().__init__(
            name="read",
            description="Read a text file. Supports optional 1-indexed offset and line limit.",
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

    def run(self, args: Dict[str, Any]) -> str:
        path = args.get("path")
        offset = args.get("offset")
        limit = args.get("limit")

        if not path:
            return "Error: missing required argument 'path'"
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
    def __init__(self) -> None:
        super().__init__(
            name="bash",
            description="Execute a bash command in the current working directory.",
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

    def run(self, args: Dict[str, Any]) -> str:
        cmd = args.get("command")
        timeout = int(args.get("timeout", 30))
        if not cmd:
            return "Error: missing required argument 'command'"

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"Error: command timed out ({timeout} s)"
        except Exception as exc:
            return f"Error: {exc}"

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


class EditTool(AgentTool):
    def __init__(self) -> None:
        super().__init__(
            name="edit",
            description=(
                "Edit a file using exact text replacement. "
                "Provide path and edits:[{oldText,newText}, ...]. "
                "Each oldText must match the original file exactly."
            ),
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

    def run(self, args: Dict[str, Any]) -> str:
        path = args.get("path")
        edits = args.get("edits")

        if not path:
            return "Error: missing required argument 'path'"
        if not isinstance(edits, list) or not edits:
            return "Error: 'edits' must be a non-empty list"
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
    def __init__(self) -> None:
        super().__init__(
            name="write",
            description="Create or overwrite a file with the provided content.",
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

    def run(self, args: Dict[str, Any]) -> str:
        path = args.get("path")
        content = args.get("content")
        if not path:
            return "Error: missing required argument 'path'"
        if content is None:
            return "Error: missing required argument 'content'"

        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w") as fh:
                fh.write(content)
            return f"Wrote {path} ({len(content)} bytes)"
        except Exception as exc:
            return f"Error: {exc}"


DEFAULT_TOOLS: List[AgentTool] = [
    ReadTool(),
    BashTool(),
    EditTool(),
    WriteTool(),
]


class Agent:
    """Standalone coding agent that works with any backend in lib._llm."""

    def __init__(
        self,
        model: Any,
        tools: Optional[List[AgentTool]] = None,
        max_iterations: int = 20,
        show_thinking: bool = False,
    ) -> None:
        self.model = model
        source = tools if tools is not None else DEFAULT_TOOLS
        self._tools: Dict[str, AgentTool] = {t.name: copy.copy(t) for t in source}
        self.max_iterations = max_iterations
        self.show_thinking = show_thinking

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

    def _execute(self, name: str, args: Dict[str, Any]) -> str:
        if name not in self._tools:
            return f"Error: unknown tool {name!r}"
        tool = self._tools[name]
        if not tool.enabled:
            return f"Error: tool {name!r} is disabled"
        if not isinstance(args, dict):
            return f"Error: tool {name!r} arguments must be an object"
        return tool.run(args)

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

    def _print_thinking(self, iteration: int, response: str) -> None:
        """Print a formatted summary of one agent iteration."""
        print(f"\n[Agent] iteration {iteration}")
        # Show the model's reasoning text (everything outside the protocol tags)
        thinking = re.sub(r"<tool_call>.*?</tool_call>", "", response, flags=re.DOTALL)
        thinking = re.sub(r"<final_answer>.*?</final_answer>", "", thinking, flags=re.DOTALL).strip()
        if thinking:
            for line in thinking.splitlines():
                print(f"  {line}")

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

        tool_calls_ever_made = False
        final_without_tools_pushed = False

        for iteration in range(self.max_iterations):
            response = self.model.chat(messages)

            if self.show_thinking:
                self._print_thinking(iteration + 1, response)

            # Check tool calls FIRST. Execute them even if <final_answer> is also
            # present in the same response — the model must not skip tool execution.
            tool_calls = self._parse_tool_calls(response)
            if tool_calls:
                tool_calls_ever_made = True
                messages.append({"role": "assistant", "content": response})

                result_blocks: List[str] = []
                for call in tool_calls:
                    if "_parse_error" in call:
                        call_name = "?"
                        output = f"Error parsing tool call: {call['_parse_error']}"
                        if self.show_thinking:
                            print(f"  [tool] parse error: {call['_parse_error']}")
                    else:
                        call_name = call.get("name", "")
                        call_args = call.get("args", {})
                        if self.show_thinking:
                            args_str = json.dumps(call_args, ensure_ascii=False)
                            if len(args_str) > 120:
                                args_str = args_str[:117] + "..."
                            print(f"  [tool] {call_name}: {args_str}")
                        output = self._execute(call_name, call_args)
                        if self.show_thinking:
                            lines = output.splitlines()
                            preview = lines[0] if lines else "(no output)"
                            suffix = f" (+{len(lines) - 1} lines)" if len(lines) > 1 else ""
                            print(f"  [result] {preview}{suffix}")

                    result_blocks.append(
                        "<tool_result>\n"
                        + json.dumps({"name": call_name, "output": output}, ensure_ascii=False)
                        + "\n</tool_result>"
                    )

                messages.append({"role": "user", "content": "\n".join(result_blocks)})
                continue

            final = self._parse_final_answer(response)
            if final is not None:
                if not tool_calls_ever_made and not final_without_tools_pushed:
                    # Model jumped straight to <final_answer> without calling any tools.
                    # Give it one opportunity to actually use tools before accepting.
                    final_without_tools_pushed = True
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "You emitted <final_answer> without calling any tools. "
                            "If this task requires creating files, running commands, or "
                            "reading files, use <tool_call> blocks to actually perform "
                            "those actions — do not simulate results. "
                            "Only emit <final_answer> after all required tool calls are complete."
                        ),
                    })
                    continue
                if self.show_thinking:
                    print(f"\n[Agent] done\n")
                return final

            # No tool calls and no final answer: push back.
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": (
                    "You must use a <tool_call> block to take any action, "
                    "or wrap your final response in <final_answer> tags. "
                    "Do not describe actions — execute them via tools."
                ),
            })

        return f"[Agent stopped: max_iterations={self.max_iterations} reached without a final answer]"

    def run(
        self,
        task: str,
        system: str = "",
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Run the agent on a task and return its final answer."""
        return self._run_text_protocol(task=task, system=system, chat_history=chat_history)
