# CodeScribe — AGENT card

## What this repo is
CodeScribe is an AI-assisted framework for scientific software development:

- Incremental Fortran → C++ translation (with interface layers)
- Code inspection / generation / update
- Tool-using “coding agent” workflows (`read`, `bash`, `edit`, `write`)

Use this repo when you need automated, repo-aware code changes with an auditable tool loop.

## Install (sandboxed)
Recommended: use a virtual environment.

```bash
python3 -m venv env
source env/bin/activate
pip install --upgrade pip
pip install -e .

code-scribe --help
```

## Model setup (OpenAI-compatible endpoints)
CodeScribe supports OpenAI-compatible backends via the `oaic-` model prefix.

Set:

```bash
# Required: base URL of the OpenAI-compatible API (must include /v1)
export OPENAI_COMP_BASEURL="http://localhost:11434/v1"

# Required: provider label (used internally for auth routing)
export OPENAI_COMP_PROVIDER="ollama"

# Required by the current implementation (even if the endpoint itself needs no auth)
export OPENAI_COMP_APIKEY="placeholder"
```

Example:

```bash
code-scribe inspect README.rst -m oaic-llama3.1 -q "Summarize this project and list key entry points."
```

For other backends/env vars, see `docs/models.md`.

## Discover capabilities via help
CodeScribe workflows are exposed as CLI subcommands:

```bash
code-scribe --help
code-scribe agent --help
code-scribe loop --help
code-scribe inspect --help
code-scribe generate --help
code-scribe update --help
code-scribe translate --help
code-scribe index --help
```

## Safety: bounded vs unbounded agent runs

### Bounded (recommended): `loop`
`code-scribe loop` runs repeated fresh sessions over a task file and uses bounded tools rooted at the working tree. This reduces risk from arbitrary shell commands and path escapes.

Artifacts are written under:
- `.codescribe/loop/status.json`
- `.codescribe/loop/report.md`

### More flexible: `agent`
`code-scribe agent` runs a single tool-using session. It is useful for interactive, one-off tasks and may be less restricted than loop mode.

Bounded mode is a practical constraint layer, not an OS sandbox; see `docs/agent.md` for details.

## Minimal agent workflows

### 1) Single agent session
```bash
code-scribe agent "Find failing tests and propose a minimal fix." -m oaic-llama3.1
```

### 2) Bounded loop over a task file
```bash
code-scribe loop task.md -m oaic-llama3.1
```

## Considerations
- Agent runs are capped by an iteration limit; tasks may stop early if not completed.
- Bounded `bash` is allowlisted and rejects shell metacharacters; some commands will fail by design.
- Prefer `edit` for precise changes to existing files; use `write` for new/fully replaced files.
