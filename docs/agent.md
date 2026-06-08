# Agent internals (`codescribe/lib/_agent.py`)

This document is a *practical map* of the standalone coding agent.
It explains what the agent does, how tool calling works, and where the
safety boundaries are, without re-stating the entire source file.

If you’re modifying behavior, treat the code as authoritative:
`codescribe/lib/_agent.py`.

## What the agent is

The agent is a small runtime that:

1. sends a task to an LLM,
2. lets the model request tool executions (`read`, `bash`, `edit`, `write`),
3. feeds tool results back to the model,
4. repeats until a final answer (or iteration limit).

It is backend-agnostic: the model implementation lives in
`codescribe/lib/_llm.py`.

## Two tool-calling modes

### 1) Native tool calling (preferred)

If the backend supports native tools, the agent passes tool schemas to the
provider and receives structured tool call requests.

Completion rule in this mode: a model response with **no tool calls** is treated
as the final answer.

### 2) Text-protocol fallback

For backends without native tool calling, the agent uses a minimal tagged text
protocol:

- `<tool_call>{"name":"read","args":{...}}</tool_call>`
- `<tool_result>{"name":"read","output":"..."}</tool_result>`
- `<final_answer>...</final_answer>`

The agent parses `<tool_call>` blocks with regex + `json.loads`, executes them,
and injects `<tool_result>` blocks back into the conversation.

## Tools and safety boundaries

### File tools (`read`, `edit`, `write`)

In **bounded** mode (used by `code-scribe loop`), paths are resolved under a
configured root and attempts to escape the root are rejected.

Edits are anchored: `edit` performs **exact** `oldText → newText` replacement and
requires `oldText` to be unique and non-overlapping.

### `bash`

- Unbounded mode: runs arbitrary shell commands.
- Bounded mode: validates an allowlisted command set and rejects common shell
  metacharacters and path escapes.

Bounded mode is a constraint layer for “stay in the working tree” workflows.
It is **not** an OS sandbox.

## Where this shows up in the CLI

- `code-scribe agent`: single agent run (unbounded tools)
- `code-scribe loop`: repeated fresh sessions (bounded tools; writes reports)

## Key extension points

- Add a new tool: implement an `AgentTool` subclass and include it in the tool
  list.
- Adjust bounded policy: update bounded `bash` allowlist / blocked characters, or
  path resolution rules.
- Change truncation / diagnostics: see tool output truncation and logging hooks.
