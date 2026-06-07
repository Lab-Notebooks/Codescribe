# Agent internals: `codescribe/lib/_agent.py`

This document explains how the standalone coding agent in `codescribe/lib/_agent.py` works, why it is structured the way it is, and what design constraints shape its behavior.

The goal is to give a full mental model without drowning in detail: after reading this, you should be able to follow the control flow, understand the safety boundaries, and modify the implementation with confidence.

## Table of contents

- [1. What this module is for](#1-what-this-module-is-for)
- [2. Core design idea](#2-core-design-idea)
- [3. Big-picture structure](#3-big-picture-structure)
- [4. The text fallback protocol](#4-the-text-fallback-protocol)
- [5. Regex parsing layer](#5-regex-parsing-layer)
- [6. `_TEXT_PROTOCOL_PREAMBLE`: the fallback system prompt](#6-_text_protocol_preamble-the-fallback-system-prompt)
- [7. Exported symbols](#7-exported-symbols)
- [8. Tool abstraction: `AgentTool`](#8-tool-abstraction-agenttool)
- [9. `ReadTool`](#9-readtool)
- [10. `BashTool`](#10-bashtool)
- [11. `EditTool`](#11-edittool)
- [12. `WriteTool`](#12-writetool)
- [13. Path safety: `_resolve_within_root()`](#13-path-safety-_resolve_within_root)
- [14. Tool factory: `make_bounded_tools()`](#14-tool-factory-make_bounded_tools)
- [15. `DEFAULT_TOOLS`](#15-default_tools)
- [16. Token estimation utilities](#16-token-estimation-utilities)
- [17. Display helpers for verbose mode](#17-display-helpers-for-verbose-mode)
- [18. Schema validation: `_validate_schema_value()`](#18-schema-validation-_validate_schema_value)
- [19. Output control: `_truncate_for_model()`](#19-output-control-_truncate_for_model)
- [20. The `Agent` class: overall responsibility](#20-the-agent-class-overall-responsibility)
- [21. `Agent.__init__()`](#21-agent__init__)
- [22. Tool enable/disable controls](#22-tool-enabledisable-controls)
- [23. Prompt and schema generation](#23-prompt-and-schema-generation)
- [24. Tool execution gateway: `_execute()`](#24-tool-execution-gateway-_execute)
- [25. Parsing helpers inside `Agent`](#25-parsing-helpers-inside-agent)
- [26. `_print_thinking()`](#26-_print_thinking)
- [27. Native tool loop: `_run_native_tools()`](#27-native-tool-loop-_run_native_tools)
- [28. Fallback text loop: `_run_text_protocol()`](#28-fallback-text-loop-_run_text_protocol)
- [29. Public entry point: `run()`](#29-public-entry-point-run)
- [30. Invariants the module tries to maintain](#30-invariants-the-module-tries-to-maintain)
- [31. Failure behavior](#31-failure-behavior)
- [32. Safety model: what this file does and does not guarantee](#32-safety-model-what-this-file-does-and-does-not-guarantee)
- [33. Relationship to the rest of Codescribe](#33-relationship-to-the-rest-of-codescribe)
- [34. Common extension points](#34-common-extension-points)
- [35. Practical reading guide to the source](#35-practical-reading-guide-to-the-source)
- [36. Summary](#36-summary)

---

## 1. What this module is for

`codescribe/lib/_agent.py` implements a **small, backend-agnostic coding agent**.

At a high level, the agent does three things:

1. sends a task to an LLM,
2. lets the LLM request tool executions such as reading files or running shell commands,
3. repeats this loop until the model returns a final answer.

This module is intentionally narrow in scope. It does **not** define model backends itself; instead, it expects a model object from `codescribe/lib/_llm.py` that exposes a chat interface. The agent is therefore a coordination layer between:

- a language model,
- a set of local tools,
- and an iterative control loop.

In practice, this is the part of Codescribe that powers agentic workflows like:

- inspecting a project,
- reading files before answering,
- making exact file edits,
- writing new files,
- and operating in either unrestricted or bounded project mode.

---

## 2. Core design idea

The module is built around a simple principle:

> **The model decides what to do next, but the Python code remains the source of truth for tool execution, validation, and filesystem effects.**

That principle leads to the main design choices:

- tools are represented as Python classes,
- tool arguments are schema-checked before execution,
- tool output is always fed back into the loop as plain text,
- the loop is capped by `agent_iterations`,
- and there are two execution modes depending on backend capability:
  - **native tool calling**, if the model supports it,
  - **text-protocol fallback**, if it does not.

This split is the most important architectural feature in the file.

---

## 3. Big-picture structure

From top to bottom, the file contains:

1. **text-protocol definitions** for models without native tool support,
2. **tool base class and concrete tool implementations**,
3. **path-bounding and tool factory helpers**,
4. **small utility functions** for token counting, summaries, validation, and truncation,
5. the **`Agent` class**, which runs the control loop.

A readable mental model is:

```text
User task
   |
   v
Agent.run(...)
   |
   +--> native tool mode? ---- yes ---> _run_native_tools()
   |                                 |
   |                                 v
   |                         model requests tool calls
   |                                 |
   |                                 v
   |                           _execute(tool,args)
   |                                 |
   |                                 v
   |                          tool results returned
   |                                 |
   |                                 v
   |                           final text answer
   |
   +--> no ---> _run_text_protocol()
                                     |
                                     v
                           model emits <tool_call> blocks
                                     |
                                     v
                               _execute(tool,args)
                                     |
                                     v
                           <tool_result> blocks returned
                                     |
                                     v
                         model emits <final_answer> block
```

Markdown cannot natively render a true diagram beyond fenced text, so the code block above is the simplest portable diagram for GitHub-style Markdown.

---

## 4. The text fallback protocol

Not every model backend can perform structured tool calling. To support those models, the module defines a lightweight text protocol.

The model is instructed to emit one of three tagged blocks:

- `<tool_call> ... </tool_call>`
- `<tool_result> ... </tool_result>`
- `<final_answer> ... </final_answer>`

### 4.1 Tool-call format

The expected payload is JSON:

```text
<tool_call>
{"name": "read", "args": {"path": "README.rst"}}
</tool_call>
```

### 4.2 Tool-result format

After the Python side executes a tool, it sends the result back like this:

```text
<tool_result>
{"name": "read", "output": "...file contents..."}
</tool_result>
```

### 4.3 Final-answer format

Once all needed tool work is done, the model must return:

```text
<final_answer>
Done.
</final_answer>
```

### 4.4 Why tagged blocks are used

The fallback protocol uses explicit tags because they are:

- easy to detect with regex,
- easy to explain in a system prompt,
- backend-independent,
- and robust enough for simple iterative tool use.

This is not as strict as a full parser-driven protocol, but it is intentionally minimal.

---

## 5. Regex parsing layer

Two module-level regex patterns support the text protocol:

- `_TOOL_CALL_RE`
- `_FINAL_ANSWER_RE`

They are both compiled with `re.DOTALL`, which means `.` matches across line breaks. That matters because tool payloads and final answers may span multiple lines.

This design keeps parsing simple:

- find all `<tool_call>` blocks,
- try to `json.loads(...)` each payload,
- find the first `<final_answer>` block if present.

The parser is intentionally permissive in one sense and strict in another:

- permissive about whitespace and multiline content,
- strict that the payload itself must decode as JSON object data.

---

## 6. `_TEXT_PROTOCOL_PREAMBLE`: the fallback system prompt

`_TEXT_PROTOCOL_PREAMBLE` is the instruction template injected into the system message when using fallback mode.

It explains:

- what the agent is,
- what tools exist,
- the exact required tool-call format,
- that multiple tool calls may appear in one response,
- that the model must continue after receiving tool results,
- and that `<final_answer>` must only appear after all required tool use is complete.

The preamble is important because fallback mode has no API-level enforcement. The prompt is doing protocol specification work that native tool APIs would otherwise handle.

---

## 7. Exported symbols

The module-level `__all__` exposes the public API:

- `AgentTool`
- `ReadTool`
- `BashTool`
- `EditTool`
- `WriteTool`
- `make_bounded_tools`
- `DEFAULT_TOOLS`
- `Agent`

This tells readers which names are intended as reusable building blocks.

---

## 8. Tool abstraction: `AgentTool`

`AgentTool` is the base class for all tools.

It stores four pieces of metadata:

- `name`
- `description`
- `parameters`
- `enabled`

and defines three methods:

- `run(args)` — to be implemented by subclasses,
- `to_openai_tool()` — converts the tool into a function schema for native tool-calling APIs,
- `describe_for_prompt()` — renders a human-readable description plus JSON schema for prompt injection.

### Why this abstraction exists

The agent must support the same tools in two very different contexts:

1. as structured schemas passed to a native tool-calling backend,
2. as plain-text descriptions embedded in a fallback prompt.

`AgentTool` centralizes the information needed for both.

---

## 9. `ReadTool`

`ReadTool` reads text files.

### Inputs

- `path` — required
- `offset` — optional, 1-indexed line start
- `limit` — optional maximum line count

### Behavior

`run()` performs the following steps:

1. validate that `path` exists,
2. if a root is configured, resolve the path through `_resolve_within_root()`,
3. ensure the path exists and is a file,
4. open with `errors="replace"`,
5. read all lines,
6. slice lines according to `offset` and `limit`,
7. return the selected text.

### Important details

- `offset` is treated as **1-indexed**, which is more natural for users.
- `errors="replace"` favors robustness over strict encoding failure.
- if the slice is empty, the tool returns `""` rather than an error.

### Why this tool is simple

The tool does not attempt syntax-aware reading, binary safety, or pagination metadata. It is intentionally plain: the agent can call it repeatedly if it needs more context.

---

## 10. `BashTool`

`BashTool` executes shell commands.

This is the most powerful and potentially risky tool in the file, so it has two operating modes.

### 10.1 Unbounded mode

In normal mode:

- the command is passed to `subprocess.run(..., shell=True, ...)`,
- the current working directory may be set,
- stdout and stderr are captured,
- a timeout is applied.

This is flexible but deliberately trusts the surrounding environment.

### 10.2 Bounded mode

In bounded mode:

- the command is first validated by `_validate_bounded_command()`,
- then executed with `shell=False` and `shlex.split(cmd)`,
- only a small allowlist of commands is accepted,
- shell metacharacters are rejected,
- path escapes are rejected.

This mode is designed for safer project-local loops.

### 10.3 Blocked shell features

Bounded `bash` rejects a small set of shell metacharacters.

The exact set is an implementation detail (see `BashTool._BLOCKED_CHARS` in
`codescribe/lib/_agent.py`) and may evolve.

These are rejected in bounded mode because they enable piping, redirection, command chaining, interpolation, or escaping behavior that would make command validation much weaker.

### 10.4 Allowed commands

Bounded `bash` uses a small allowlist.

The exact allowlist is an implementation detail (see `BashTool._DEFAULT_ALLOWED` in
`codescribe/lib/_agent.py`) and may evolve.

The allowlist keeps the tool useful for inspection while preventing general arbitrary program execution.

### 10.5 Path checks in bounded mode

For non-option tokens, bounded validation rejects:

- tokens containing `..`
- absolute paths starting with `/`
- explicit executable paths containing `/`

This does not create a perfect sandbox, but it enforces a practical “stay inside the working tree” rule.

### 10.6 Output formatting

`_format_result()` returns a normalized string such as:

```text
exit_code: 0

STDOUT:
...

STDERR:
...
```

This textual form is easy for the model to consume in both native and fallback loops.

### Design tradeoff

`BashTool` chooses **predictable text output** over rich structured output. That makes downstream logic simpler, but it means the model must parse plain text if it wants detailed shell semantics.

---

## 11. `EditTool`

`EditTool` performs exact text replacement inside an existing file.

It is intentionally conservative.

### Inputs

- `path`
- `edits`, where each entry contains:
  - `oldText`
  - `newText`

### Execution model

All replacements are matched against the **original file contents**, not incrementally against prior edits in the same request.

This is a major design choice.

### Why this matters

It prevents order-dependent behavior. If edits were applied one by one and later edits matched the already-modified file, then the result could depend on edit ordering. This implementation avoids that.

### Validation steps

For each edit, the tool ensures:

- the edit entry is an object,
- both `oldText` and `newText` are present,
- `oldText` exists in the original file,
- `oldText` is unique in the original file,
- matched spans do not overlap each other.

If any condition fails, the whole edit call fails.

### Reconstruction strategy

After locating all matches, the tool:

1. sorts matches by start offset,
2. checks for overlap,
3. rebuilds the file from untouched slices plus replacement text,
4. writes the updated file back.

### Why exact replacement is valuable

This tool is safer than “rewrite arbitrary file fragment” logic because it requires the model to anchor edits to known original text. That reduces accidental corruption and makes failures explicit when context is stale.

---

## 12. `WriteTool`

`WriteTool` creates or overwrites a file with full contents.

### Inputs

- `path`
- `content`

### Behavior

It:

1. validates arguments,
2. resolves the path within the configured root if needed,
3. blocks writes to protected paths,
4. creates parent directories with `os.makedirs(..., exist_ok=True)`,
5. writes the provided content.

### Role in the tool set

`WriteTool` complements `EditTool`:

- use `edit` when modifying an existing file precisely,
- use `write` when creating a new file or replacing an entire file.

This separation is important because it nudges the model toward more controlled updates when a file already exists.

---

## 13. Path safety: `_resolve_within_root()`

This helper is central to bounded file access.

Given a root directory and a user-supplied target path, it:

1. resolves the root,
2. resolves the candidate path, interpreting relative paths under the root,
3. checks that the resolved candidate is still inside the root using `relative_to(root)`.

If that last step fails, it raises:

- `ValueError("Path escapes working directory: ...")`

### Why this method is effective

It protects against common escape patterns such as:

- `../outside.txt`
- nested relative traversal
- absolute paths outside the root

This is the main filesystem-boundary mechanism for `read`, `edit`, and `write` in bounded mode.

---

## 14. Tool factory: `make_bounded_tools()`

`make_bounded_tools()` is a convenience constructor for bounded agent sessions.

It always includes:

- `ReadTool(root=root)`
- `BashTool(cwd=root, bounded=True)`

and conditionally includes:

- `EditTool(root=root, protected_paths=...)`
- `WriteTool(root=root, protected_paths=...)`

depending on `allow_write`.

### Why a factory function exists

The same bounded configuration is needed repeatedly by higher-level workflows like loop mode. Packaging it in one function avoids duplicated setup logic and keeps the policy explicit.

---

## 15. `DEFAULT_TOOLS`

`DEFAULT_TOOLS` is the unbounded tool set:

- `ReadTool()`
- `BashTool()`
- `EditTool()`
- `WriteTool()`

This is what `Agent` uses if no custom tool list is provided.

---

## 16. Token estimation utilities

The module includes lightweight token accounting helpers:

- `_count_tokens(text)`
- `_count_message_tokens(messages)`
- `_usage_in_out(usage)`

### 16.1 `_count_tokens()`

This estimates token count as roughly 1 token per 4 characters.

That is a heuristic, not a tokenizer. Its purpose is operational visibility, not billing precision.

### 16.2 `_count_message_tokens()`

This sums estimated token counts across message contents. It supports both:

- string content,
- list content serialized through JSON.

### 16.3 `_usage_in_out()`

This normalizes usage dictionaries from different backend naming conventions:

- `prompt_tokens` or `input_tokens`
- `completion_tokens` or `output_tokens`

### Why these helpers exist

Model backends do not always report token usage uniformly, and some may report nothing at all. These helpers let the agent show approximate usage in verbose mode either from true backend data or from fallback estimates.

---

## 17. Display helpers for verbose mode

Two helpers exist mainly to keep console output readable:

- `_fmt_args(name, args)`
- `_fmt_result(name, output)`

They produce short previews such as:

- the path being read,
- the number of edits in an edit call,
- a summarized bash result,
- or a shortened error message.

These functions do not affect correctness. They improve observability.

---

## 18. Schema validation: `_validate_schema_value()`

This helper validates tool arguments against a simplified JSON-schema-like structure.

Supported schema types are:

- `object`
- `array`
- `string`
- `integer`

It checks things like:

- required keys,
- unexpected extra keys when `additionalProperties=False`,
- integer minimum values,
- array minimum length,
- nested item validation.

### Why validate here if tools also validate internally?

Because there are two layers of defense:

1. **schema-level validation** catches malformed requests early and consistently,
2. **tool-level validation** handles semantic checks specific to the tool implementation.

For example:

- schema validation can say `args.limit must be >= 1`,
- tool logic can say `file not found` or `oldText is not unique`.

This split is clean and useful.

---

## 19. Output control: `_truncate_for_model()`

Large tool outputs can overwhelm model context windows. `_truncate_for_model()` limits returned text to a maximum number of characters, defaulting to `4000`.

If truncation is needed, it keeps:

- the beginning,
- the end,
- and inserts a middle marker describing how many characters were removed.

This is a pragmatic choice: the beginning and end of command output or file content are often the most informative parts.

---

## 20. The `Agent` class: overall responsibility

`Agent` orchestrates everything.

It owns:

- a model object,
- a private map of tools,
- iteration limits,
- verbose/thinking display settings.

The class is not a tool itself and not an LLM backend. It is the controller that connects both sides.

---

## 21. `Agent.__init__()`

Constructor inputs are:

- `model`
- `tools=None`
- `max_iterations=20`
- `show_diagnostics=False`
- `tool_output_max_chars=4000`
- `diagnostics=None`

### Important design detail: tool copying

The constructor builds:

```python
self._tools = {t.name: copy.copy(t) for t in source}
```

This means the agent gets shallow copies of the provided tool objects rather than reusing them directly.

### Why that matters

It prevents one agent instance from accidentally toggling `enabled` state on shared tool instances used elsewhere.

The copy is shallow, which is enough here because the main mutable runtime field of concern is `enabled`.

---

## 22. Tool enable/disable controls

The methods:

- `enable_tool(name)`
- `disable_tool(name)`

toggle tool availability.

If a tool name is unknown, they raise `ValueError`.

This provides a simple policy knob at runtime without rebuilding the whole agent.

---

## 23. Prompt and schema generation

Two methods derive representations of enabled tools:

- `_system_prompt(extra="")`
- `_tool_schemas()`

### `_system_prompt()`

Used in fallback mode. It renders the text preamble plus a list of tools and their JSON schemas.

### `_tool_schemas()`

Used in native mode. It emits structured tool definitions via `to_openai_tool()`.

These two methods reflect the same underlying tool metadata in different forms.

---

## 24. Tool execution gateway: `_execute()`

All tool invocations pass through `_execute(name, args)`.

This method is a critical choke point.

It enforces, in order:

1. the tool name must exist,
2. the tool must be enabled,
3. arguments must be a dictionary,
4. arguments must satisfy schema validation,
5. only then is `tool.run(args)` called.

### Why centralization matters

Without this gateway, each loop implementation would need to duplicate execution checks. Centralizing execution ensures that native and fallback modes obey the same rules.

---

## 25. Parsing helpers inside `Agent`

Two static methods support fallback mode:

- `_parse_tool_calls(text)`
- `_parse_final_answer(text)`

### `_parse_tool_calls()`

It finds all `<tool_call>` blocks, decodes JSON payloads, and returns a list.

If JSON decoding fails, it does not crash. Instead it returns a synthetic record containing `_parse_error` and `_raw`.

That is a good design choice because malformed model output becomes recoverable conversational state instead of a Python exception.

### `_parse_final_answer()`

It returns the stripped text inside the first `<final_answer>` block, or `None` if absent.

---

## 26. `_print_thinking()`

This currently prints only:

```text
  iter N
```

It is intentionally minimal and acts as a hook for verbose tracing. Most of the rich printing happens in the loop methods themselves.

---

## 27. Native tool loop: `_run_native_tools()`

This method is used when the model backend advertises native tool support.

### 27.1 Message initialization

The conversation begins with:

- optional system message,
- optional chat history,
- current user task.

### 27.2 Main loop

For each iteration up to `agent_iterations`:

1. call `self.model.chat_with_tools(messages, self._tool_schemas())`,
2. extract returned text and `tool_calls`,
3. account for token usage,
4. if tool calls are present:
   - execute each through `_execute()`,
   - truncate outputs for model safety,
   - convert results back into backend-specific message format using `self.model.format_tool_result_messages(...)`,
   - append those messages and continue,
5. if plain text is present with no tool calls, return it as the final answer.

If the loop exhausts its iteration budget, it returns a stop message.

### 27.3 Notable design choices

#### Backend abstraction

The agent assumes the model provides:

- `chat_with_tools(...)`
- `format_tool_result_messages(...)`

That keeps this module independent of backend-specific wire formats.

#### Tool results are truncated before re-injection

This prevents giant outputs from dominating context.

#### Final-answer semantics are simpler than fallback mode

In native mode, any non-empty text response without tool calls is treated as completion. There is no `<final_answer>` wrapper because the backend already gives a structured tool-call channel.

---

## 28. Fallback text loop: `_run_text_protocol()`

This method implements the same idea as native mode, but using prompt discipline and regex parsing.

### 28.1 Initial messages

The first system message is always the generated text-protocol prompt from `_system_prompt(system)`.

Then optional chat history and the user task are appended.

### 28.2 Extra loop state

Fallback mode tracks two additional booleans:

- `tool_calls_ever_made`
- `final_without_tools_pushed`

These exist because text-only models often try to answer directly without actually using tools.

### 28.3 Main loop behavior

On each iteration:

1. estimate input token cost for the full current context,
2. call `self.model.chat(messages)`,
3. estimate output tokens,
4. parse tool calls first,
5. if tool calls exist:
   - mark that tools have been used,
   - append the assistant response to history,
   - execute each call,
   - create `<tool_result>` blocks,
   - append them as a user message,
   - continue,
6. otherwise parse `<final_answer>`,
7. if a final answer is found before any tool was ever used:
   - push back once with a corrective reminder,
   - allow the model another chance,
8. if a valid final answer is accepted, return it,
9. otherwise push back with a general nudge requiring either tool use or `<final_answer>`.

### 28.4 Why tool calls are checked before final answer

A single model response might include both a tool call and a `<final_answer>`. The implementation executes tool calls first and ignores the final answer for that turn.

That is the correct choice: otherwise the model could claim completion before performing required actions.

### 28.5 Why the “one pushback” logic exists

If the first response is just a final answer, the agent gives one explicit reminder not to simulate actions. This improves compliance without creating an endless argument loop.

---

## 29. Public entry point: `run()`

`Agent.run()` is the only method most callers need.

It selects execution mode based on backend capabilities:

- if `model.supports_native_tools` is true and `chat_with_tools` exists, use `_run_native_tools()`,
- otherwise use `_run_text_protocol()`.

This makes the agent backend-adaptive while keeping the external API small.

---

## 30. Invariants the module tries to maintain

Several important invariants shape the implementation.

### Tool effects happen only through Python

The model may request actions, but it never performs them directly. Every file read, edit, write, or shell command is executed by Python code.

### Tool arguments are validated before execution

Malformed calls should fail as tool errors, not crash the agent loop.

### Bounded file access stays under a root

For file tools, path resolution must remain inside the configured root.

### Edit operations are anchored to original text

All replacements are based on the original file snapshot for that call.

### Agent loops must terminate

`agent_iterations` prevents infinite back-and-forth.

These invariants are more important than any individual helper function.

---

## 31. Failure behavior

The module generally prefers **returning explicit error strings** over raising exceptions into the outer loop.

Examples include:

- missing tool arguments,
- file not found,
- schema mismatch,
- parse errors in fallback tool calls,
- bounded-command validation failures,
- command timeouts.

This design is agent-friendly. The model can read the error and adapt its next step.

The tradeoff is that callers must not mistake a returned string for a successful structured result. Inside this module, that is acceptable because tool outputs are always treated as text.

---

## 32. Safety model: what this file does and does not guarantee

This module adds useful guardrails, but it is not a hardened sandbox.

### It does provide

- working-tree confinement for `read`, `edit`, and `write` in bounded mode,
- a restrictive command allowlist for bounded `bash`,
- rejection of common shell metacharacters,
- protected-path support for read-only files.

### It does not provide

- OS-level sandboxing,
- resource isolation beyond subprocess timeout,
- complete prevention of all shell abuse in unbounded mode,
- complete semantic understanding of every shell token.

So the right mental model is:

> bounded mode is a practical constraint layer for agent workflows, not a security boundary equivalent to a container or VM.

---

## 33. Relationship to the rest of Codescribe

`codescribe/lib/_agent.py` is intentionally decoupled from translation-specific logic.

That makes it reusable across multiple CLI commands and workflows. The surrounding codebase can decide:

- which model to instantiate,
- whether tools should be bounded,
- which files should be protected,
- whether writes should be allowed,
- how verbose the run should be.

This separation is good design: the agent handles **how to run a tool-using loop**, while higher-level commands decide **what policy and task to apply**.

---

## 34. Common extension points

If you want to evolve this module, the most natural extension points are:

### Add a new tool

Create a new `AgentTool` subclass with:

- a name,
- a description,
- a parameter schema,
- a `run()` implementation.

Then include it in a tool list passed to `Agent` or a custom factory.

### Tighten bounded bash rules

Modify:

- `_DEFAULT_ALLOWED`,
- `_BLOCKED_CHARS`,
- or `_validate_bounded_command()`.

### Improve fallback parsing

Replace regex parsing with a stricter parser if needed.

### Improve token accounting

Swap heuristic counting for tokenizer-specific accounting if backend consistency becomes important.

---

## 35. Practical reading guide to the source

If you are opening the code for the first time, a good reading order is:

1. `Agent.run()`
2. `_run_native_tools()` and `_run_text_protocol()`
3. `_execute()`
4. the four concrete tool classes
5. `_resolve_within_root()` and `make_bounded_tools()`
6. utility helpers

That order follows the runtime flow rather than file order.

---

## 36. Summary

`codescribe/lib/_agent.py` implements a compact but carefully structured coding agent.

Its main ideas are:

- represent tools as Python objects with schemas,
- validate every tool call centrally,
- support both native-tool and text-protocol backends,
- keep tool output textual and model-readable,
- provide bounded-mode restrictions for project-local loops,
- and guarantee termination through iteration limits.

In short, the module is best understood as a **portable agent runtime**: small enough to read in one sitting, but rich enough to support real file- and shell-based coding workflows.
