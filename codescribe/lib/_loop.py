"""_loop

Prompt-loop implementation + durable loop state helpers.

This module intentionally owns *loop-specific* state, prompts, and persistence.
Telemetry/diagnostics sinks live in `_telemetry.py`.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from codescribe import lib


@dataclass
class LoopPaths:
    """Single-shared loop paths under `.codescribe/loop/`.

    We intentionally keep these files *shared* (not per-run) for now.
    """

    run_dir: Path
    run_json: Path
    state_json: Path

    # Execution phase artifacts (overwritten each loop)
    execution_jsonl: Path
    previous_md: Path

    # Review artifacts
    history_md: Path
    plan_md: Path


def get_loop_paths(workdir: Path) -> LoopPaths:
    run_dir = workdir / ".codescribe" / "loop"
    return LoopPaths(
        run_dir=run_dir,
        run_json=run_dir / "run.json",
        state_json=run_dir / "state.json",
        execution_jsonl=run_dir / "execution.jsonl",
        previous_md=run_dir / "previous.md",
        history_md=run_dir / "history.md",
        plan_md=run_dir / "plan.md",
    )


def load_state(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_state(path: Path, state: Dict[str, Any]) -> None:
    state = dict(state)
    state["updated_at"] = lib.iso_utc_now()
    lib.atomic_write_json(path, state)


def _init_state(*, run_id: str, workdir: Path, task_file: Path) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "workdir": str(workdir),
        "task_file": str(task_file),
        "loop_index": 0,
        "phase": "idle",  # idle|execution|review
        "updated_at": lib.iso_utc_now(),
    }


def _fmt_int(n: Optional[int]) -> str:
    return "?" if n is None else f"{int(n):,}"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                # Best-effort: keep going even if one line is corrupt.
                continue
    return out


def _render_previous_md(*, events: List[Dict[str, Any]], final_text: str) -> str:
    """Render console-like verbose transcript as markdown.

    Source of truth is the agent's JSONL log (ToolLogJsonl events).
    """

    # Group events by iteration.
    by_iter: Dict[int, Dict[str, Any]] = {}

    total_in: Optional[int] = None
    total_out: Optional[int] = None

    for ev in events:
        it = ev.get("iteration")
        if isinstance(it, int) and it >= 1:
            by_iter.setdefault(it, {"usage": None, "tools": []})

        if ev.get("event") == "model_response":
            usage = ev.get("usage") or {}
            in_tok = usage.get("prompt_tokens", usage.get("input_tokens"))
            out_tok = usage.get("completion_tokens", usage.get("output_tokens"))
            if isinstance(it, int) and it >= 1:
                by_iter[it]["usage"] = (in_tok, out_tok)

        if ev.get("event") == "tool_end":
            tool = ev.get("tool")
            ok = ev.get("ok")
            err = ev.get("error")
            # args preview isn't in tool_end; we use tool_start if available.
            # We'll stitch a best-effort args_preview by looking backwards.
            args_preview = None
            if isinstance(it, int) and it >= 1:
                by_iter[it]["tools"].append(
                    {
                        "tool": tool,
                        "ok": ok,
                        "error": err,
                        "duration_ms": ev.get("duration_ms"),
                        "output_chars": ev.get("output_chars"),
                    }
                )

        if ev.get("event") == "run_end":
            total_in = ev.get("total_input_tokens")
            total_out = ev.get("total_output_tokens")

    # We also want tool argument previews. These are in tool_start events.
    # Add them onto the *next* tool_end in the same iteration (best-effort).
    pending_starts: Dict[int, List[Dict[str, Any]]] = {}
    for ev in events:
        if ev.get("event") != "tool_start":
            continue
        it = ev.get("iteration")
        if not isinstance(it, int) or it < 1:
            continue
        pending_starts.setdefault(it, []).append(ev)

    # Build a map iteration -> queue of args previews.
    args_q: Dict[int, List[str]] = {}
    for it, starts in pending_starts.items():
        args_q[it] = []
        for s in starts:
            tool = s.get("tool")
            args = s.get("args") or {}
            if isinstance(args, dict):
                # Mirror the same preview style as the agent console.
                if tool == "bash":
                    cmd = (args.get("command") or "").replace("\n", " ").strip()
                    args_q[it].append((cmd[:60] + "…") if len(cmd) > 60 else cmd)
                elif tool in ("read", "write"):
                    args_q[it].append(str(args.get("path", "")))
                elif tool == "edit":
                    path = str(args.get("path", ""))
                    n = len(args.get("edits") or [])
                    args_q[it].append(f"{path}  ({n} edit{'s' if n != 1 else ''})")
                else:
                    args_q[it].append(json.dumps(args, ensure_ascii=False)[:60])
            else:
                args_q[it].append(str(args))

    lines: List[str] = []

    for it in sorted(by_iter.keys()):
        usage = by_iter[it].get("usage")
        lines.append(f"iter {it}")
        if usage and isinstance(usage, tuple) and len(usage) == 2:
            in_tok, out_tok = usage
            total = (in_tok or 0) + (out_tok or 0)
            lines.append(
                f"  usage  in {_fmt_int(in_tok)}  out {_fmt_int(out_tok)}  total {_fmt_int(total)}"
            )
        tools_list = by_iter[it].get("tools") or []
        for tool_ev in tools_list:
            tool = tool_ev.get("tool") or "?"
            args_preview = ""
            if it in args_q and args_q[it]:
                args_preview = args_q[it].pop(0)
            ok = tool_ev.get("ok")
            err = tool_ev.get("error")

            suffix = ""
            if tool == "bash":
                # bash tool outputs embed exit_code on line1 in actual tool output,
                # but we don't have tool output here. We'll print ok/error.
                suffix = "bash ok" if ok else "bash error"
            elif tool in ("read", "write", "edit", "glob"):
                suffix = "ok" if ok else "error"
            else:
                suffix = "ok" if ok else "error"

            if err:
                suffix = f"error={err}"

            # console-ish alignment similar to your sample
            lines.append(f"  ▸ {tool:<5}  {args_preview:<60}  {suffix}")

        lines.append("")

    if total_in is not None or total_out is not None:
        total = (total_in or 0) + (total_out or 0)
        lines.append(
            f"tokens  in {_fmt_int(total_in)}  out {_fmt_int(total_out)}  total {_fmt_int(total)}"
        )
        lines.append("")

    if final_text:
        lines.append("<final_answer>")
        lines.append(final_text.rstrip())
        lines.append("</final_answer>")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"

# ---------------------------------------------------------------------------
# Prompt builders (system + phase tasks)
# ---------------------------------------------------------------------------


def build_system_prompt(*, workdir: Path) -> str:
    return (
        "You are an autonomous coding agent specializing in test-driven repair. "
        "Infer project state from files and command output within the working directory. "
        "IMPORTANT: Only access files and paths within the working directory. "
        "In bash commands, only use relative paths or paths under the working directory. "
        "Never target system directories or paths outside the working directory. "
        "NEVER fabricate test output or command results — always run actual commands "
        "and report their real output verbatim. "
        "Avoid unnecessary file re-reads, but re-read whenever you need exact text, "
        "line context, or verification before/after edits."
    )


def build_execution_task(
    *,
    workdir: Path,
    task_rel: str,
    state_rel: str,
    history_rel: str,
    plan_rel: str,
) -> str:
    return (
        f"Working directory: {workdir}\n"
        f"Task file: {task_rel} (read-only)\n"
        f"Loop state (json): {state_rel} (read + update)\n"
        f"History: {history_rel} (read-only; may be large)\n"
        f"Current plan: {plan_rel} (read-only)\n\n"
        "PHASE: EXECUTION\n\n"
        "Goal: make the most useful concrete progress on the task, guided by plan.md.\n\n"
        "Protocol:\n"
        "1. Read the task file, plan.md (if it exists), and state.json.\n"
        "2. Do the next planned step (or propose a better one if plan is empty/wrong).\n"
        "3. Use tools to inspect/edit files and run checks.\n"
        "4. Run the closest available check (tests, lint, typecheck). If none, run `python -m compileall .`.\n"
        "5. Update state.json with loop_index/phase only (or add small keys if truly needed).\n\n"
        "Finish with <final_answer> describing what you did and what you observed.\n"
    )


def build_review_task(
    *,
    workdir: Path,
    task_rel: str,
    state_rel: str,
    previous_rel: str,
    history_rel: str,
    plan_rel: str,
    loop_index: int,
) -> str:
    return (
        f"Working directory: {workdir}\n"
        f"Task file: {task_rel} (read-only)\n"
        f"Loop state (json): {state_rel} (read + update)\n"
        f"Previous execution transcript: {previous_rel} (read-only)\n"
        f"History log: {history_rel} (append-only)\n"
        f"Plan file: {plan_rel} (overwrite/update)\n\n"
        "PHASE: REVIEW\n\n"
        "You are the review agent. Your job is to:\n"
        "1) Read previous.md and extract what happened (tool actions, errors, files changed, outcomes).\n"
        "2) Append a concise summary to history.md.\n"
        "3) Produce/refresh plan.md: concrete next steps for the execution agent.\n\n"
        "Rules:\n"
        "- Ground summaries in what is actually in previous.md. Do not fabricate results.\n"
        "- The plan must be actionable and ordered (bulleted checklist is fine).\n"
        "- Keep history entries short (aim ~10-25 lines).\n\n"
        f"When writing history.md, append a new section headed: ## loop {loop_index}\n"
        "When writing plan.md, overwrite the whole file with the current best plan.\n\n"
        "Finish with <final_answer> confirming you updated history.md and plan.md.\n"
    )


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




def prompt_loop(
    task_file: Union[Path, str],
    model: Union[Path, str],
    agent_loops: int = 5,
    agent_iterations: int = 12,
    verbose: bool = False,
    logging: Optional[Union[Path, str]] = None,
    workdir: Optional[Union[Path, str]] = None,
) -> str:
    """Run a bounded execution→review loop.

    Per loop:
      1) EXECUTION agent performs the next step and produces a final answer.
      2) REVIEW agent summarizes `previous.md` into `history.md` and updates `plan.md`.

    Artifacts under `.codescribe/loop/` (single shared):
      - previous.md (overwritten each loop)
      - history.md (appended each loop)
      - plan.md (overwritten each loop)
      - execution.jsonl (raw structured log for the most recent execution phase)
      - run.json, state.json
    """

    workdir_path = Path(workdir).resolve() if workdir else Path.cwd().resolve()
    task_path = _ensure_within_workdir(Path(task_file), workdir_path)

    neural_model = lib.set_neural_model(model)  # type: ignore[attr-defined]

    # Task file is a TOML chat prompt. Also supports optional:
    #
    #   [tools]
    #   bash = ["python3.8", "rg"]
    #
    chat_history, meta = lib.load_chat_template(task_path, return_meta=True)
    bash_allow = set((meta.get("tools") or {}).get("bash") or [])
    tools = lib.make_tools(workdir_path, bash_allow=bash_allow)

    run_id = lib.new_run_id()
    paths = get_loop_paths(workdir_path)
    os.makedirs(paths.run_dir, exist_ok=True)

    task_rel = str(task_path.relative_to(workdir_path))
    state_rel = str(paths.state_json.relative_to(workdir_path))
    history_rel = str(paths.history_md.relative_to(workdir_path))
    plan_rel = str(paths.plan_md.relative_to(workdir_path))
    previous_rel = str(paths.previous_md.relative_to(workdir_path))

    lib.atomic_write_json(
        paths.run_json,
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
    write_state(paths.state_json, state)

    system = build_system_prompt(workdir=workdir_path)

    loops_completed = 0

    for loop_idx in range(1, agent_loops + 1):
        # Reload prompt in case user edits it while loop runs.
        chat_history, meta = lib.load_chat_template(task_path, return_meta=True)

        # ----------------------
        # Phase 1: EXECUTION
        # ----------------------
        if verbose:
            print(f"\n▶  loop {loop_idx} [execution]")

        state = load_state(paths.state_json) or state
        state["run_id"] = run_id
        state["loop_index"] = loop_idx
        state["phase"] = "execution"
        write_state(paths.state_json, state)

        # Execution JSONL log (this is the source-of-truth for previous.md).
        exec_log = lib.ToolLogJsonl(path=str(paths.execution_jsonl))

        # Optional extra logging sink provided by CLI.
        # (We do not merge sinks here; if requested later, we can add a MultiSink.)
        if logging is not None:
            exec_log = lib.ToolLogJsonl(path=str(logging) if str(logging) else None)

        exec_agent = lib.Agent(
            neural_model,
            tools=tools,
            max_iterations=agent_iterations,
            show_diagnostics=verbose,
            tool_output_max_chars=None,
            logging=exec_log,
        )

        exec_task = build_execution_task(
            workdir=workdir_path,
            task_rel=task_rel,
            state_rel=state_rel,
            history_rel=history_rel,
            plan_rel=plan_rel,
        )

        exec_answer = exec_agent.run(exec_task, system=system, chat_history=chat_history)

        # Render previous.md from the execution JSONL.
        events = _read_jsonl(paths.execution_jsonl)
        prev_md = _render_previous_md(events=events, final_text=exec_answer or "")
        lib.atomic_write_text(paths.previous_md, prev_md)

        loops_completed = loop_idx

        # ----------------------
        # Phase 2: REVIEW
        # ----------------------
        if verbose:
            print(f"\n▶  loop {loop_idx} [review]")

        state = load_state(paths.state_json) or state
        state["run_id"] = run_id
        state["loop_index"] = loop_idx
        state["phase"] = "review"
        write_state(paths.state_json, state)

        review_agent = lib.Agent(
            neural_model,
            tools=tools,
            max_iterations=max(6, agent_iterations // 2),
            show_diagnostics=verbose,
            tool_output_max_chars=None,
            logging=lib.ToolLogJsonl(path=str(paths.run_dir / "review.jsonl")),
        )

        review_task = build_review_task(
            workdir=workdir_path,
            task_rel=task_rel,
            state_rel=state_rel,
            previous_rel=previous_rel,
            history_rel=history_rel,
            plan_rel=plan_rel,
            loop_index=loop_idx,
        )

        _ = review_agent.run(review_task, system=system, chat_history=chat_history)

    return (
        f"completed {loops_completed}/{agent_loops} loop(s) "
        f"— run: {run_id} "
        f"— previous: {paths.previous_md} "
        f"— history: {paths.history_md} "
        f"— plan: {paths.plan_md}"
    )
