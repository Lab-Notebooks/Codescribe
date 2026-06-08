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
- Add a logging sink: implement a class with an `.emit(dict)` method and pass
  it as `logging=` to `Agent()`. Use `MultiToolLogSink([sink1, sink2])` to fan
  out to multiple sinks simultaneously (e.g. two TOML log files, or a TOML file
  + a custom telemetry sink).
- Each `tool_end` event includes `output_preview` (first 500 chars of actual
  output) and `model_reasoning` (first 500 chars of the model's preceding text).
  Downstream consumers such as the loop review agent can use these to cross-check
  model-reported results against real tool outputs.
- Tool outputs are passed to the model as-is — no summarization, no truncation,
  no `RAW:` wrapper. The `_summarize_tool_output()` helper is used only to
  populate the compact `WORKSPACE CONTEXT` grounding block, not the model messages.

## Relation to existing agent frameworks

CodeScribe's agent is a deliberate design point in a space occupied by several well-studied frameworks. The sections below place it against the most relevant ones, noting where it converges, where it diverges, and where the divergence is intentional.

### ReAct (Yao et al., 2022)

ReAct ("Synergizing Reasoning and Acting in Language Models", arXiv:2210.03629) is the direct ancestor of CodeScribe's inner loop. The ReAct pattern interleaves *thought* (a chain-of-thought reasoning trace), *action* (a tool call), and *observation* (the tool's return value), cycling until the task is resolved. CodeScribe follows this faithfully: native tool calls are the Action, and tool result messages are the Observation. The system prompt comment in `_agent.py` (`_REACT_NUDGE`) explicitly references this framing.

The difference is operational rather than conceptual. ReAct as described in the paper accumulates the full thought–action–observation trajectory in the prompt context across all steps. CodeScribe does **not** grow the conversation unboundedly: instead, each iteration replaces a compact `WORKSPACE CONTEXT` system message that summarises iteration count, total tool-call budget, recent tool results, and recent errors. The full message list is still passed to the model, but the grounding block stays fixed-size. This trades a fraction of per-step context richness for predictable context growth, which matters when agents run for tens of iterations on large codebases.

### Reflexion (Shinn et al., 2023)

Reflexion (arXiv:2303.11366) adds a verbal self-reflection step after each failed episode: the agent produces a natural-language critique of what went wrong, stores it in an episodic memory buffer, and carries that buffer into the next attempt. The reinforcement signal is linguistic rather than gradient-based.

CodeScribe's review agent in loop mode is structurally similar but architecturally separate. The review agent is a *different agent instance* that receives a harness-computed summary of verified actions (derived deterministically from the TOML event log — no LLM involved) and writes a structured `review_output.toml` with pending next steps. It is not the same model reflecting on its own output — it is a second model evaluating an external evidence record. This separation is intentional: it reduces the risk of the reviewer rationalising the executor's mistakes and enforces a strict evidential standard (the review task prompt instructs the reviewer to flag any `<final_answer>` claim not backed by a verified action). Reflexion collapses executor and reflector into a single agent; CodeScribe keeps them structurally distinct.

### SWE-agent (Yang et al., 2024)

SWE-agent (arXiv:2405.15793) introduces the concept of an Agent-Computer Interface (ACI): a purpose-built toolset designed specifically for the needs of an LM agent rather than a human developer. The ACI includes a custom file viewer that shows ~100 lines per turn with scroll and in-file search commands, linting on edit submission, and a directory-search tool that returns only filenames (not match context). SWE-agent runs a single agent instance against a bash shell.

CodeScribe's tool design is more minimal. It provides `read`, `glob`, `bash`, `edit`, and `write` without ACI-style scaffolding: no built-in scroll command, no automatic linting on edit, no specialised file viewer. The tradeoff is flexibility — CodeScribe's tools are general-purpose and provider-agnostic — at the cost of not having the ergonomic guardrails that SWE-agent's ACI provides. One area where CodeScribe is more careful than SWE-agent's default: repetition detection. The agent tracks a `call_counts` dict per run and blocks repeated identical tool calls (with a higher limit for `read` and a reset after successful `edit`/`write`), preventing the model from spinning in a read loop.

### CodeAct (Wang et al., 2024)

CodeAct (arXiv:2402.01030) replaces structured tool calls with executable Python: the model emits a Python snippet, which runs in an integrated interpreter, and stdout/stderr feed back as the next observation. This collapses the distinction between "tool schema" and "action" — any library-level operation is available, and the agent can self-debug by inspecting interpreter output.

CodeScribe takes the opposite position. Tool calls are schema-validated, named, and bounded; `bash` is the escape hatch for arbitrary shell work, but it operates under an allowlist in loop mode. The CodeAct approach grants a significantly larger action space at the cost of safety: arbitrary code execution in a shared interpreter is difficult to bound. CodeScribe's bounded bash allowlist (`ls`, `pwd`, `find`, `grep`, `git`, etc., extensible via TOML) is a weaker sandbox — it is a constraint layer, not an OS-level isolation — but it makes the action space auditable and prevents the most common classes of runaway filesystem damage during unattended loop runs.

### OpenHands / OpenDevin (Wang et al., 2024)

OpenHands (arXiv:2407.16741, formerly OpenDevin) is a platform-scale system built around a persistent event stream. All agent observations and actions are appended to a shared event log; agents consume from this stream and emit new events. The architecture supports multi-agent delegation: a primary orchestrator agent can spawn sub-agents for subtasks, and sub-agents report back through the same event stream. Execution happens inside a Docker sandbox, and the platform supports thousands of concurrent sessions.

CodeScribe's scope is narrower in almost every dimension. There is no event stream beyond the per-run TOML event log; there is no runtime agent delegation (the two-agent loop is static: executor then reviewer, in sequence, no dynamic spawning); there is no container sandbox. The session boundary is a Python process lifetime — cross-loop state is carried in-memory by `prompt_loop()` and on-disk artifacts under `.codescribe/loop/` are for inspection and crash-resume only. This is a constraint, but it is also a deployability property: CodeScribe has no daemon, no REST API, and no Docker dependency. It runs wherever Python runs.

### LangGraph

LangGraph structures agent execution as a directed graph with a central `StateGraph` object. Nodes are functions (LLM calls or tool runs); edges route between them, with conditional edges enabling the cyclical patterns that agents require. State is a typed dictionary updated incrementally at each node. Persistence, human-in-the-loop checkpoints, and multi-agent composition are first-class features of the graph runtime.

CodeScribe does not use a graph runtime. Its loop is a Python `for` loop over `range(agent_loops)`, with the execution/review alternation expressed as sequential function calls inside that loop. This is less expressive for complex branching logic — there is no conditional routing, no checkpoint/resume, and no dynamic graph rewriting — but it is also significantly simpler to audit, extend, and embed in other Python code. LangGraph's state management is richer; CodeScribe's equivalent is the `_state` dict inside a single `Agent.run()` call (ephemeral, per-run) plus the `loop_summaries` and `pending_items` lists held in-memory by `prompt_loop()` across loop iterations. On-disk files under `.codescribe/loop/` exist for inspection and crash-resume, not as the primary state relay.

### Summary

CodeScribe occupies a specific point in this design space: a **minimal, in-memory-state, two-agent loop** with a stateless-per-session inner agent. It inherits ReAct's reasoning structure, applies a Reflexion-like review phase via a structurally separate second agent that evaluates harness-computed evidence rather than a rendered transcript, and enforces a bounded tool policy similar in spirit to SWE-agent's ACI but simpler in implementation. Relative to OpenHands and LangGraph it forgoes platform features (delegation, event streams, graph routing, container isolation) in exchange for zero infrastructure dependencies and a codebase small enough to read in one sitting. The known gaps — no streaming, no model-failure retry, no wall-clock timeout, no OS-level sandbox — are areas where the more platform-oriented frameworks have already invested.
