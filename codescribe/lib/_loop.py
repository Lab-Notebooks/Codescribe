"""_loop

Prompt-loop implementation with in-memory cross-loop state.

State relay design:
  - Within a loop (iteration → iteration): message history + WORKSPACE CONTEXT block.
  - Across loops (loop N → loop N+1): Python objects held in prompt_loop().
    The harness computes LoopSummary from the TOML event log after each execution
    and injects it directly into the next loop's task string.
    Agents never read state files to orient themselves.

Persistent files (for inspection / crash-resume only):
  run.toml        — run configuration
  state.toml      — current loop index + phase
  execution.toml  — raw event log for the most recent execution phase
  review_output.toml — structured output from the review agent (pending items)
"""

from __future__ import annotations

import os
import toml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from codescribe import lib

__all__ = [
    "LoopPaths",
    "get_loop_paths",
    "load_state",
    "write_state",
    "LoopSummary",
    "build_system_prompt",
    "build_execution_task",
    "build_review_task",
    "prompt_loop",
]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

@dataclass
class LoopPaths:
    """Paths under `.codescribe/loop/` for a single shared run."""

    run_dir: Path
    run_toml: Path
    state_toml: Path
    execution_toml: Path       # raw event log (overwritten each execution phase)
    review_output_toml: Path   # review agent's structured output (overwritten each review)


def get_loop_paths(workdir: Path) -> LoopPaths:
    run_dir = workdir / ".codescribe" / "loop"
    return LoopPaths(
        run_dir=run_dir,
        run_toml=run_dir / "run.toml",
        state_toml=run_dir / "state.toml",
        execution_toml=run_dir / "execution.toml",
        review_output_toml=run_dir / "review_output.toml",
    )


# ---------------------------------------------------------------------------
# State persistence (TOML)
# ---------------------------------------------------------------------------

_VALID_PHASES = frozenset({"idle", "execution", "review"})


def load_state(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    data = lib.read_toml(path)
    return data or None


def write_state(path: Path, state: Dict[str, Any]) -> None:
    state = dict(state)
    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"state['run_id'] must be a non-empty str, got {run_id!r}")
    loop_index = state.get("loop_index")
    if not isinstance(loop_index, int) or isinstance(loop_index, bool):
        raise ValueError(f"state['loop_index'] must be an int, got {loop_index!r}")
    phase = state.get("phase")
    if phase not in _VALID_PHASES:
        raise ValueError(f"state['phase'] must be one of {sorted(_VALID_PHASES)}, got {phase!r}")
    state["updated_at"] = lib.iso_utc_now()
    lib.atomic_write_toml(path, state)


def _init_state(*, run_id: str, workdir: Path, task_file: Path) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "workdir": str(workdir),
        "task_file": str(task_file),
        "loop_index": 0,
        "phase": "idle",
        "updated_at": lib.iso_utc_now(),
    }


# ---------------------------------------------------------------------------
# In-memory cross-loop state
# ---------------------------------------------------------------------------

@dataclass
class LoopSummary:
    """Harness-computed summary of one execution phase.

    Built deterministically from the TOML event log — no LLM involved.
    Carried in-memory by prompt_loop() and injected into subsequent task prompts.
    """

    loop_index: int
    files_written: List[str] = field(default_factory=list)
    files_edited: List[str] = field(default_factory=list)
    files_read: List[str] = field(default_factory=list)
    commands_run: List[str] = field(default_factory=list)   # "cmd → exit_code N"
    errors: List[str] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0


def _compute_loop_summary(loop_index: int, events: List[Dict[str, Any]]) -> LoopSummary:
    """Build a LoopSummary from TOML event log entries."""

    # Collect args previews keyed by tool_start order within each iteration.
    # Map: iteration → list of (tool, args_preview) in call order.
    starts: Dict[int, List[tuple]] = {}
    for ev in events:
        if ev.get("event") != "tool_start":
            continue
        it = ev.get("iteration")
        if not isinstance(it, int):
            continue
        tool = ev.get("tool") or "?"
        args = ev.get("args") or {}
        if isinstance(args, dict):
            if tool == "bash":
                ap = (args.get("command") or "").replace("\n", " ").strip()[:80]
            elif tool in ("read", "write"):
                ap = str(args.get("path", ""))
            elif tool == "edit":
                ap = str(args.get("path", ""))
            else:
                ap = ""
        else:
            ap = str(args)[:60]
        starts.setdefault(it, []).append((tool, ap))

    # Consume starts queue as we process tool_end events.
    starts_q: Dict[int, List[tuple]] = {k: list(v) for k, v in starts.items()}

    summary = LoopSummary(loop_index=loop_index)

    for ev in events:
        if ev.get("event") == "tool_end":
            it = ev.get("iteration")
            tool = ev.get("tool") or "?"
            preview = (ev.get("output_preview") or "").strip()
            output_is_error = preview.startswith("Error:")
            ok = ev.get("ok") and not output_is_error

            ap = ""
            if isinstance(it, int) and starts_q.get(it):
                _, ap = starts_q[it].pop(0)

            if not ok:
                err_msg = preview[:80] if preview else (ev.get("error") or "unknown error")
                summary.errors.append(f"{tool}({ap}): {err_msg}")
            elif tool == "write":
                summary.files_written.append(ap)
            elif tool == "edit":
                summary.files_edited.append(ap)
            elif tool == "read":
                summary.files_read.append(ap)
            elif tool == "bash":
                first = (preview.splitlines() or [""])[0][:60]
                summary.commands_run.append(f"{ap}  →  {first}")

        elif ev.get("event") == "run_end":
            summary.total_input_tokens = int(ev.get("total_input_tokens") or 0)
            summary.total_output_tokens = int(ev.get("total_output_tokens") or 0)

    return summary


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_system_prompt(*, workdir: Path) -> str:
    return (
        "You are an autonomous coding agent specializing in test-driven repair. "
        "NEVER fabricate command results, test output, or file contents — "
        "if you need information, read a file or run a command and report verbatim output. "
        "Determine project state by reading files and running commands; never assume or infer. "
        "IMPORTANT: Only access files and paths within the working directory. "
        "In bash commands, only use relative paths or paths under the working directory. "
        "Never target system directories or paths outside the working directory. "
        "Avoid unnecessary file re-reads, but re-read whenever you need exact text, "
        "line context, or verification before/after edits."
    )


def _fmt_loop_context(
    *,
    loop_idx: int,
    agent_loops: int,
    loop_summaries: List[LoopSummary],
    pending_items: List[str],
) -> str:
    """Build the injected context block that orients the execution agent.

    This replaces the agent having to read state/history/plan files.
    """
    lines = [f"Loop {loop_idx} of {agent_loops}."]

    # Accumulate the complete file inventory across ALL prior loops so the
    # agent knows what exists without re-globbing or re-reading orientation files.
    all_written: List[str] = []
    all_edited: List[str] = []
    seen_w: set = set()
    seen_e: set = set()
    for s in loop_summaries:
        for f in s.files_written:
            if f not in seen_w:
                seen_w.add(f)
                all_written.append(f)
        for f in s.files_edited:
            if f not in seen_e:
                seen_e.add(f)
                all_edited.append(f)

    if all_written:
        lines.append("Files created across all prior loops: " + ", ".join(all_written))
    if all_edited:
        lines.append("Files edited across all prior loops: " + ", ".join(all_edited))

    # Show last loop's commands/errors for immediate context.
    if loop_summaries:
        last = loop_summaries[-1]
        parts: List[str] = []
        if last.commands_run:
            parts.append("ran: " + "; ".join(last.commands_run[:3]))
        if last.errors:
            parts.append("errors: " + "; ".join(last.errors[:3]))
        if parts:
            lines.append("Last loop — " + " | ".join(parts) + ".")

    if pending_items:
        lines.append("Pending next steps:")
        for item in pending_items[:5]:
            lines.append(f"  - {item}")
    else:
        lines.append("No pending steps recorded — determine next action from the task file.")

    return "\n".join(lines)


def build_execution_task(
    *,
    workdir: Path,
    task_rel: str,
    loop_idx: int,
    agent_loops: int,
    loop_summaries: List[LoopSummary],
    pending_items: List[str],
) -> str:
    context = _fmt_loop_context(
        loop_idx=loop_idx,
        agent_loops=agent_loops,
        loop_summaries=loop_summaries,
        pending_items=pending_items,
    )
    # In the first loop, direct the agent to read the task file.  In subsequent
    # loops the spec is already in the chat history and the file inventory above
    # describes all work done — re-reading wastes 2-3 iterations per loop.
    if loop_idx == 1:
        orient_step = "1. Read the task file to orient yourself on the specification.\n"
    else:
        orient_step = (
            "1. The specification and all prior work are already summarised above — "
            "do NOT re-read the task file or re-glob the workspace to orient yourself.\n"
        )
    return (
        f"{context}\n\n"
        f"Working directory: {workdir}\n"
        f"Task file: {task_rel} (read-only — contains the full specification)\n\n"
        "PHASE: EXECUTION\n\n"
        "Goal: make the most useful concrete progress on the task.\n\n"
        "Protocol:\n"
        + orient_step +
        "2. Write a short PLAN (3–7 bullets) covering what you will do next.\n"
        "3. Execute the plan autonomously — do NOT ask for confirmation.\n"
        "4. Before each set of tool calls, write one or two sentences stating what you are about to do and why.\n"
        "5. Inspect the current state of relevant files before editing them.\n"
        "6. Do the work described in the pending next steps (or the highest-value action if none are listed).\n"
        "7. Run the closest available check (tests, lint, typecheck). If none, run `python -m compileall .`.\n\n"
        "Finish with <final_answer> that includes:\n"
        "- The PLAN you followed (final form).\n"
        "- Exact output of every command you ran (verbatim, not paraphrased).\n"
        "- A bulleted list of NEXT STEPS (3-5 concrete items) for the following loop.\n"
        "  Begin that section with the exact line: NEXT STEPS:\n"
    )


def build_review_task(
    *,
    workdir: Path,
    task_rel: str,
    review_output_rel: str,
    loop_index: int,
    loop_summary: LoopSummary,
    exec_answer: str = "",
) -> str:
    # Build a text representation of the harness-computed summary so the
    # review agent has verified facts without needing to parse any transcript.
    summary_lines = [f"## Verified actions from loop {loop_index} (harness-computed)"]
    if loop_summary.files_read:
        summary_lines.append("Files read: " + ", ".join(loop_summary.files_read))
    if loop_summary.files_written:
        summary_lines.append("Files written: " + ", ".join(loop_summary.files_written))
    if loop_summary.files_edited:
        summary_lines.append("Files edited: " + ", ".join(loop_summary.files_edited))
    if loop_summary.commands_run:
        summary_lines.append("Commands run:")
        for c in loop_summary.commands_run:
            summary_lines.append(f"  {c}")
    if loop_summary.errors:
        summary_lines.append("Errors:")
        for e in loop_summary.errors:
            summary_lines.append(f"  {e}")
    if not (loop_summary.files_read or loop_summary.files_written or loop_summary.files_edited
            or loop_summary.commands_run or loop_summary.errors):
        summary_lines.append("  (no verified actions)")
    verified_block = "\n".join(summary_lines)

    return (
        f"Working directory: {workdir}\n"
        f"Task file: {task_rel} (read-only)\n"
        f"Review output: {review_output_rel} (write here)\n\n"
        "PHASE: REVIEW\n\n"
        f"{verified_block}\n\n"
        + (
            f"\n[Execution agent report — loop {loop_index}]\n\n{exec_answer}\n\n"
            if exec_answer else ""
        )
        + "Your job:\n"
        "1. Cross-reference the execution report's claims against the verified actions above.\n"
        "   File reads listed above are verified — treat the agent's claims about those\n"
        "   files as trustworthy. Only flag claims about files NOT in the verified list.\n"
        "2. Write your assessment to the review output file in TOML format:\n\n"
        "   ```toml\n"
        f"   loop = {loop_index}\n"
        "   summary = \"One paragraph describing what actually happened.\"\n"
        "   blocker = \"Main current blocker, or empty string if none.\"\n\n"
        "   [[pending]]\n"
        "   item = \"First concrete next step\"\n"
        "   ```\n\n"
        "Rules:\n"
        "- If tests passed and no errors are listed above, set blocker = \"\" and leave pending empty.\n"
        "- pending items must be concrete and actionable (not 'continue working').\n"
        "- Limit to 5 pending items maximum.\n\n"
        "Finish with <final_answer> confirming you wrote the review output file.\n"
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# prompt_loop command
# ---------------------------------------------------------------------------

def _ensure_within_workdir(path: Path, workdir: Path) -> Path:
    path = path.resolve()
    workdir = workdir.resolve()
    try:
        path.relative_to(workdir)
    except ValueError:
        raise ValueError(f"Path {path} is outside working directory {workdir}")
    return path


def _extract_pending_items(final_text: str) -> List[str]:
    """Parse NEXT STEPS: section from an execution agent's final_answer."""
    items: List[str] = []
    in_section = False
    for line in (final_text or "").splitlines():
        if line.strip().upper().startswith("NEXT STEPS"):
            in_section = True
            continue
        if in_section:
            stripped = line.strip()
            if not stripped:
                continue
            # Stop at the next markdown heading
            if stripped.startswith("#"):
                break
            if stripped.startswith("-") or stripped.startswith("*"):
                items.append(stripped.lstrip("-* ").strip())
            elif stripped[0].isdigit() and stripped[1:3] in (". ", ") "):
                items.append(stripped[2:].strip() if len(stripped) > 2 else stripped)
    return items[:5]


def _read_review_output(path: Path) -> Dict[str, Any]:
    """Read the review agent's structured TOML output."""
    data = lib.read_toml(path)
    return data


def prompt_loop(
    task_file: Union[Path, str],
    model: Union[Path, str],
    agent_loops: int = 5,
    agent_iterations: int = 12,
    verbose: bool = False,
    logging: Optional[Union[Path, str]] = None,
    workdir: Optional[Union[Path, str]] = None,
    reasoning: bool = False,
) -> str:
    """Run a bounded execution → review loop.

    Cross-loop state is carried entirely in-memory (loop_summaries, pending_items).
    Agents receive context injected into their task strings — they do not read
    state or history files to orient themselves.

    Per loop:
      1) EXECUTION agent: reads task file + does work + reports NEXT STEPS.
      2) REVIEW agent: receives harness-computed action summary + writes review_output.toml.

    Persistent files under `.codescribe/loop/` (for inspection / crash-resume):
      run.toml             — run configuration
      state.toml           — current loop index + phase
      execution.toml       — raw TOML event log for the most recent execution phase
      review_output.toml   — review agent's structured output
    """

    workdir_path = Path(workdir).resolve() if workdir else Path.cwd().resolve()
    task_path = _ensure_within_workdir(Path(task_file), workdir_path)

    neural_model = lib.set_neural_model(model, reasoning=reasoning)  # type: ignore[attr-defined]

    chat_history, meta = lib.load_chat_template(task_path, return_meta=True)
    bash_allow = set((meta.get("tools") or {}).get("bash") or [])
    tools = lib.make_tools(workdir_path, bash_allow=bash_allow)

    run_id = lib.new_run_id()
    paths = get_loop_paths(workdir_path)
    os.makedirs(paths.run_dir, exist_ok=True)

    task_rel = str(task_path.relative_to(workdir_path))
    review_output_rel = str(paths.review_output_toml.relative_to(workdir_path))

    lib.atomic_write_toml(
        paths.run_toml,
        {
            "run_id": run_id,
            "created_at": lib.iso_utc_now(),
            "workdir": str(workdir_path),
            "task_file": str(task_path),
            "model": str(model),
            "agent_loops": int(agent_loops),
            "agent_iterations": int(agent_iterations),
        },
    )

    state = _init_state(run_id=run_id, workdir=workdir_path, task_file=task_path)
    write_state(paths.state_toml, state)

    system = build_system_prompt(workdir=workdir_path)

    # -----------------------------------------------------------------
    # In-memory cross-loop state — never written to files between loops.
    # -----------------------------------------------------------------
    loop_summaries: List[LoopSummary] = []
    pending_items: List[str] = []

    loops_completed = 0
    _task_mtime: float = 0.0  # track mtime to avoid re-parsing unchanged task file

    for loop_idx in range(1, agent_loops + 1):
        # Re-load only when the task file has actually changed on disk.
        try:
            current_mtime = task_path.stat().st_mtime
        except OSError:
            current_mtime = 0.0
        if current_mtime != _task_mtime:
            chat_history, meta = lib.load_chat_template(task_path, return_meta=True)
            bash_allow = set((meta.get("tools") or {}).get("bash") or [])
            tools = lib.make_tools(workdir_path, bash_allow=bash_allow)
            _task_mtime = current_mtime

        # ----------------------
        # Phase 1: EXECUTION
        # ----------------------
        if verbose:
            print(f"\n▶  loop {loop_idx} [execution]")

        state["run_id"] = run_id
        state["loop_index"] = loop_idx
        state["phase"] = "execution"
        write_state(paths.state_toml, state)

        # Clear the TOML event log so it contains only this loop's events.
        lib.atomic_write_text(paths.execution_toml, "")

        exec_log: lib.ToolLogSink = lib.ToolLogToml(path=str(paths.execution_toml))
        if logging is not None:
            extra_log = lib.ToolLogToml(path=str(logging) if str(logging) else None)
            exec_log = lib.MultiToolLogSink([exec_log, extra_log])

        exec_agent = lib.Agent(
            neural_model,
            tools=tools,
            max_iterations=agent_iterations,
            show_diagnostics=verbose,
            logging=exec_log,
        )

        exec_task = build_execution_task(
            workdir=workdir_path,
            task_rel=task_rel,
            loop_idx=loop_idx,
            agent_loops=agent_loops,
            loop_summaries=loop_summaries,
            pending_items=pending_items,
        )

        exec_answer = exec_agent.run(exec_task, system=system, chat_history=chat_history)

        # Compute the loop summary from the TOML event log (deterministic — no LLM).
        events = lib.read_toml_events(paths.execution_toml)
        loop_summary = _compute_loop_summary(loop_idx, events)
        loop_summaries.append(loop_summary)

        # Optimistically extract NEXT STEPS from the final answer so the review
        # agent has a starting point even if it can't improve on them.
        pending_items = _extract_pending_items(exec_answer or "")

        loops_completed = loop_idx

        # ----------------------
        # Phase 2: REVIEW
        # ----------------------
        if verbose:
            print(f"\n▶  loop {loop_idx} [review]")

        state["phase"] = "review"
        write_state(paths.state_toml, state)

        # Review agent: read/glob/write for state file handoff + restricted bash for diagnostics.
        review_bash_allow = {"ls", "stat", "pwd", "find", "grep", "head", "tail", "which", "env", "rg"}
        review_tools = [t for t in tools if t.name in ("read", "glob", "write")]
        review_tools.append(lib.BashTool(cwd=workdir_path, bounded=True, allowed_commands=review_bash_allow))
        review_agent = lib.Agent(
            neural_model,
            tools=review_tools,
            max_iterations=max(6, agent_iterations // 2),
            show_diagnostics=verbose,
            logging=lib.ToolLogToml(path=str(paths.run_dir / "review.toml")),
        )

        review_task = build_review_task(
            workdir=workdir_path,
            task_rel=task_rel,
            review_output_rel=review_output_rel,
            loop_index=loop_idx,
            loop_summary=loop_summary,
            exec_answer=exec_answer or "",
        )

        _ = review_agent.run(review_task, system=system)

        # Read the review agent's structured output and update in-memory state.
        review_data = _read_review_output(paths.review_output_toml)
        if review_data:
            raw_pending = review_data.get("pending") or []
            if isinstance(raw_pending, list):
                reviewed_items = [
                    p.get("item", "") if isinstance(p, dict) else str(p)
                    for p in raw_pending
                    if p
                ]
                pending_items = [x for x in reviewed_items if x]

            # Early exit: if the review reports no pending items and no blocker,
            # the task is done — no need to consume the remaining loop budget.
            blocker = review_data.get("blocker", "")
            if not pending_items and not blocker:
                if verbose:
                    print(
                        f"\n✓ No pending items and no blocker after loop {loop_idx} "
                        "— task complete, stopping early."
                    )
                break

    return (
        f"completed {loops_completed}/{agent_loops} loop(s) "
        f"— run: {run_id} "
        f"— artifacts: {paths.run_dir}"
    )
