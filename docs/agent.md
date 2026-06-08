# Agent internals (`codescribe/lib/_agent.py`)

This document is a *practical map* of the standalone coding agent.
It explains what the agent does, how tool calling works, and where the
safety boundaries are, without re-stating the entire source file.

If you're modifying behavior, treat the code as authoritative:
`codescribe/lib/_agent.py`.

## What the agent is

The agent is a small runtime that:

1. sends a task to an LLM,
2. lets the model request tool executions (`read`, `glob`, `bash`, `edit`, `write`),
3. feeds tool results back to the model,
4. repeats until a final answer (or iteration limit).

It is backend-agnostic: the model implementation lives in
`codescribe/lib/_llm.py`.

## Tool-calling protocol

All backends implement a common `chat_with_tools()` interface that the agent
calls each iteration. What differs is how each backend translates that into a
provider request:

### Provider-native tool calling

OpenAI (`openai-*`), Anthropic (`anthropic-*`), and OpenAI-compatible endpoints
(`oaic-*`) pass tool schemas to the provider and receive structured tool call
responses. This is the preferred path.

Completion rule: a model response with **no tool calls** is treated as the
final answer.

### Strict-JSON emulation

ARGO (`argo-*`) and local Transformers checkpoints (path) do not support
provider-native tool calling. Their `chat_with_tools()` implementations inject
a system prompt that enforces a strict JSON output schema:

```json
{
  "text": "optional explanation",
  "tool_calls": [{"id": "...", "name": "...", "arguments": {...}}]
}
```

The provider response is parsed by `_parse_strict_tool_json()` in `_llm.py`.
The agent itself does not differentiate between native and emulated tool
calls — both paths normalize to the same `{"text", "tool_calls", "usage"}`
dict.

## Tools and safety boundaries

Tool implementations live in `codescribe/lib/_tools.py`.

### File tools (`read`, `glob`, `edit`, `write`)

In **bounded** mode (used by `code-scribe loop`), paths are resolved under a
configured root and attempts to escape the root are rejected.

`edit` performs **exact** `oldText → newText` replacement and requires
`oldText` to be unique and non-overlapping.

### `bash`

- Unbounded mode: runs arbitrary shell commands.
- Bounded mode: validates an allowlisted command set and rejects common shell
  metacharacters and path escapes.

Bounded mode is a constraint layer for "stay in the working tree" workflows.
It is **not** an OS sandbox.

Default bounded allowlist: `ls`, `pwd`, `find`, `grep`, `head`, `tail`, `wc`,
`git`, `test`, `echo`, `sed`. Loop task files can extend this via a
`[tools] bash = [...]` TOML section.

## Workspace context injection

Each iteration the agent injects a compact `WORKSPACE CONTEXT` system
message with the current iteration count, total tool-call budget used, recent
tool results, and recent errors. This gives the model lightweight grounding
without growing the conversation unboundedly.

## Where this shows up in the CLI

- `code-scribe agent`: single agent run (unbounded tools)
- `code-scribe loop`: repeated fresh sessions (bounded tools; writes reports)

## Key extension points

- Add a new tool: implement an `AgentTool` subclass in `_tools.py` and include
  it in the tool list.
- Adjust bounded policy: update bounded `bash` allowlist / blocked characters,
  or path resolution rules in `_resolve_within_root()`.
- Change tool output truncation: see `_truncate_for_model()`.
- Add a logging sink: implement a class with an `.emit(dict)` method and pass
  it as `logging=` to `Agent()`.
