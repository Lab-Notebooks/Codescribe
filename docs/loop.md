# Loop mode internals (`codescribe/lib/_loop.py`)

`code-scribe loop` runs a repeated **execution → review** cycle over a task file.
Each cycle starts a fresh agent session and persists state + artifacts under
`.codescribe/loop/`.

This document is a guide to the implementation in `codescribe/lib/_loop.py`.

## High-level behavior

Per loop iteration:

1. **EXECUTION phase**
   - Reads the task file + current `plan.md`.
   - Performs the *next planned step* using bounded tools.
   - Runs a “closest available check” (tests/lint/typecheck) or falls back to
     `python -m compileall .`.
   - Produces a final text answer.
   - Writes a structured JSONL log (`execution.jsonl`) and renders it into
     a human-readable `previous.md` transcript.

2. **REVIEW phase**
   - Reads `previous.md`.
   - Appends a concise summary to `history.md`.
   - Overwrites `plan.md` with an updated, ordered checklist for the next
     execution phase.

The key design choice: **each session is intentionally stateless**; the only
durable memory is what is written to files in `.codescribe/loop/`.

## On-disk artifacts

`get_loop_paths()` defines a shared directory:

- `.codescribe/loop/run.json`: run metadata (created_at, model, limits)
- `.codescribe/loop/state.json`: minimal mutable loop state (`loop_index`, `phase`)
- `.codescribe/loop/execution.jsonl`: execution-phase tool/model events (source of truth)
- `.codescribe/loop/previous.md`: rendered transcript for the last execution phase
- `.codescribe/loop/history.md`: append-only summaries (one section per loop)
- `.codescribe/loop/plan.md`: current plan (overwritten each review)

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
  don’t fabricate command output).
- `build_execution_task(...)`: describes inputs (task/state/history/plan paths)
  and the execution protocol.
- `build_review_task(...)`: instructs the review agent to summarize and update
  `history.md` + `plan.md`.

## Logging and transcript rendering

- Execution uses `ToolLogJsonl` to emit structured events.
- `_render_previous_md()` reconstructs a console-like transcript by grouping
  events by iteration and attaching best-effort argument previews from
  `tool_start` events.

If you want to change what appears in `previous.md`, modify
`_render_previous_md()`.

## Safety model

Loop mode uses **bounded tools rooted at the working directory**.
This is enforced by the agent/tool layer (see `docs/agent.md`).

Loop mode additionally rejects task files outside the workdir via
`_ensure_within_workdir()`.
