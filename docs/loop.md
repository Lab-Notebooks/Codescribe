# Loop mode

This page documents the current implementation in `codescribe/lib/_loop.py`.

## Overview

`code-scribe loop` runs a bounded execution/review workflow over a task file.

The public entry point is:

- `codescribe/lib/_loop.py: prompt_loop()`

The implementation is centered on `PromptLoopRunner`.

## Current execution model

For each loop iteration:

1. Reload task metadata if the task file changed.
2. Run an execution-phase agent.
3. Build a harness-computed `LoopSummary` from the execution `RunResult`.
4. If the execution agent reported `STATUS: COMPLETE`, stop early.
5. Otherwise run a review-phase agent.
6. Read `review_output.toml` and update pending items.
7. Stop early if review reports no pending items and no blocker.

Important correction:

- The current execution prompt tells the agent to complete as much work as
  possible in one session. It is not a strict “do exactly one task and exit”
  loop.

## In-memory cross-loop state

Cross-loop state lives in the `PromptLoopRunner` instance, not primarily in
files:

- `loop_summaries`
- `review_summaries`
- `pending_items`
- `loops_completed`

The harness injects these summaries back into later prompts.

## Persistent artifacts

The loop also writes files under `.codescribe/loop/`:

- `run.toml`
  - run metadata and cumulative token counters
- `state.toml`
  - current `run_id`, `loop_index`, and `phase`
- `execution.toml`
  - execution-phase event log for the most recent loop
- `review_output.toml`
  - structured output from the review agent
- `review.toml`
  - review-phase event log

These files are useful for inspection and recovery, but the main state relay is
still in memory.

## Task loading and tool configuration

`PromptLoopRunner.__post_init__()`:

- resolves `workdir`,
- ensures the task file is inside the workdir,
- constructs the model with `set_neural_model(..., reasoning=reason)`,
- loads the task chat template with `load_chat_template(..., return_meta=True)`,
- reads optional task metadata:

```toml
[tools]
bash = ["rg", "python", "python3"]
```

That `bash` list extends the bounded execution-phase bash allowlist.

## Execution phase

The execution phase uses:

- `Agent(...)`
- `tools = make_tools(workdir, bash_allow=...)`
- logging to `.codescribe/loop/execution.toml`

If `--log` or `--log-path` is also provided, logs are fanned out through
`MultiToolLogSink` to both the execution log and the requested extra log path.

### Execution task prompt

`build_execution_task(...)` injects:

- loop progress,
- files created/edited in prior loops,
- recent commands and errors,
- pending items.

Behavior differs slightly on the first loop:

- if the task file can be read up front, its full contents are injected and the
  agent is told not to re-read it,
- otherwise the agent is told to read the task file.

Later loops are explicitly told not to re-read the task file or re-glob the
workspace just for orientation.

### Completion contract

The execution agent is asked to finish with `<final_answer>` containing:

- `STATUS: COMPLETE` or `STATUS: INCOMPLETE`
- the plan followed
- exact check output
- when incomplete, a `NEXT STEPS:` section

The harness parses:

- `STATUS:` via `extract_status(...)`
- `NEXT STEPS:` via `extract_pending_items(...)`

## Review phase

The review phase runs a separate fresh agent.

Current review toolset:

- `read`
- `glob`
- `write`
- bounded `bash`

The review bash allowlist is tighter than execution:

- `ls`
- `stat`
- `pwd`
- `find`
- `grep`
- `head`
- `tail`
- `which`
- `env`
- `rg`

Important correction:

- The review phase is not limited to only `read/glob/write`; it also has a
  restricted `bash` tool.

### Review input

`build_review_task(...)` gives the review agent:

- a harness-computed summary of verified actions,
- any rejected tool calls,
- the execution agent’s final report,
- the path where it must write `review_output.toml`.

### Review output format

The review agent is instructed to write TOML like:

```toml
loop = 2
summary = "What actually happened"
blocker = ""

[[pending]]
item = "Concrete next step"
```

The harness then reads `pending` and `blocker` from that file.

## Loop summaries

`loop_summary_from_result(...)` builds a `LoopSummary` from the structured
`RunResult` rather than reparsing the event log.

It tracks:

- `files_written`
- `files_edited`
- `files_read`
- `commands_run`
- `errors`
- `rejected`
- token counts

This means the loop depends directly on `Agent.run()` output semantics.

## Early exit conditions

The loop stops early in either of these cases:

1. The execution agent emits `STATUS: COMPLETE`.
2. The review output contains:
   - no pending items, and
   - an empty blocker.

## Safety model

Loop mode is bounded to the configured working directory.

Current enforcement includes:

- task file must be inside `workdir`,
- file tools resolve paths within the root,
- bash runs with a bounded allowlist,
- review bash is even more restrictive.

This is a policy layer, not an OS sandbox.

## Defaults currently exposed by the CLI

`code-scribe loop` defaults today:

- `agent_loops = 5`
- `agent_iterations = 30`

Those defaults differ from some older docs that mentioned smaller iteration
budgets.
