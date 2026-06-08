# Loop mode internals (`codescribe/lib/_loop.py`)

`code-scribe loop` runs a repeated **execution → review** cycle over a task file.
Cross-loop state is carried entirely **in-memory** inside `prompt_loop()`.
On-disk artifacts under `.codescribe/loop/` exist for inspection and crash-resume
only — agents do not read them to orient themselves.

This document is a guide to the implementation in `codescribe/lib/_loop.py`.

## High-level behavior

Per loop iteration:

1. **EXECUTION phase**
   - A fresh `Agent` instance receives a task string that includes the harness-injected
     context block: current loop index, a summary of the previous loop's verified
     actions, and the pending next steps.
   - The agent reads the task file for the full specification and does work using
     bounded tools.
   - The agent's `<final_answer>` must include verbatim command output and a
     `NEXT STEPS:` bullet list.
   - The harness computes a `LoopSummary` deterministically from the TOML event log
     (no LLM involved) and prepends it to the next loop's context.

2. **REVIEW phase**
   - A separate `Agent` instance receives the harness-computed `LoopSummary` (a
     text block of verified actions extracted from the event log) and the execution
     agent's `<final_answer>` via `chat_history`.
   - The review agent cross-checks `<final_answer>` claims against verified actions
     and writes a structured `review_output.toml` with `pending` next steps.
   - The harness reads `review_output.toml` and updates the in-memory `pending_items`
     list for the next loop.

The key design choice: **context is injected into task strings** — agents do not read
state files to orient themselves. The only durable memory is what the harness computes
from the event log and injects explicitly.

## On-disk artifacts

`get_loop_paths()` defines a shared directory under `.codescribe/loop/`:

- `run.toml` — run metadata (run_id, created_at, model, limits)
- `state.toml` — mutable loop state (`loop_index`, `phase`); updated each phase transition
- `execution.toml` — TOML event log for the most recent execution phase (overwritten each loop)
- `review_output.toml` — review agent's structured TOML output (overwritten each review)
- `review.toml` — TOML event log for the review agent (for diagnostics)

The `execution.toml` and `review_output.toml` files are machine-readable; they are not
consumed by agents in the next loop.

## Task file format and tool allowlist

The loop task file is loaded via `lib.load_chat_template()`.

It is primarily a TOML chat prompt, with optional metadata allowing a tighter
bounded-bash allowlist:

```toml
[tools]
bash = ["rg", "python", "python3"]
```

In `_loop.py`, this list is passed into `lib.make_tools(workdir, bash_allow=...)`.

## Prompts: system + phase tasks

- `build_system_prompt()`: global safety + grounding rules (stay inside workdir,
  never fabricate command results).
- `_fmt_loop_context(loop_idx, agent_loops, loop_summaries, pending_items)`: builds
  the injected context block — loop progress, last-loop summary, pending next steps.
  This replaces the agent needing to read history files.
- `build_execution_task(...)`: prepends the context block and describes the execution
  protocol (read task file → inspect → do work → run checks → report NEXT STEPS).
- `build_review_task(...)`: presents the harness-computed verified-actions block and
  instructs the review agent to write `review_output.toml`.

## In-memory cross-loop state

`prompt_loop()` holds two Python lists across all loop iterations:

- `loop_summaries: List[LoopSummary]` — one entry per completed execution phase.
  `LoopSummary` is a dataclass computed by `_compute_loop_summary()` from the TOML
  event log. Fields: `files_written`, `files_edited`, `commands_run`, `errors`,
  `total_input_tokens`, `total_output_tokens`.
- `pending_items: List[str]` — concrete next steps for the upcoming execution phase.
  Initially extracted from the execution agent's `NEXT STEPS:` section via
  `_extract_pending_items()`; overwritten by the review agent's `review_output.toml`
  if that file contains non-empty `[[pending]]` entries.

Neither list is written to disk between loops.

## Logging

- Execution always writes to `.codescribe/loop/execution.toml` (overwritten at the
  start of each execution phase so it contains only that loop's events).
- When `--log`/`--log-path` is also provided, events are fanned out to both sinks
  via `MultiToolLogSink`.
- Each `tool_end` event includes `output_preview` (first 500 chars of actual output)
  and `model_reasoning` (first 500 chars of the model's preceding text before the
  tool call).

## Anti-hallucination design

Several layers work together to reduce fabricated results:

1. **System prompt**: "NEVER fabricate command results, test output, or file contents —
   if you need information, read a file or run a command and report verbatim output."
   The anti-hallucination rule is stated first.
2. **Execution task prompt**: requires verbatim command output in `<final_answer>` and a
   concrete `NEXT STEPS:` list.
3. **Harness-computed `LoopSummary`**: the review agent receives a deterministic summary
   derived from `tool_end` events — not the execution agent's self-report. It cannot
   claim success for actions that didn't happen.
4. **Review task prompt**: instructs the review agent to flag any `<final_answer>` claim
   not backed by a verified action in the harness summary.
5. **Review agent gets only `read`, `glob`, `write`**: no `bash` or `edit`, keeping the
   review phase narrow. Its `chat_history` includes the execution agent's final answer so
   it can cross-check claims.

## Safety model

Loop mode uses **bounded tools rooted at the working directory**.
This is enforced by the agent/tool layer (see `docs/agent.md`).

Loop mode additionally rejects task files outside the workdir via
`_ensure_within_workdir()`.
