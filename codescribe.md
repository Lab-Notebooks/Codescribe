---
language:
- en
tags:
- project:genesis
- team:AI4HPC
- type:agent
- science:computational-science
- risk:general
license: Apache 2.0

base_model: N/A
new_version:
datasets:
    - Scientific/HPC codebases (eg. Fortran legacy codes, AMReX-based applications)
metrics:
    - regression tests (in progress)

agent_card:
  schema_version: "2.0"
  name: "CodeScribe"
  title: "CodeScribe — agent card"
  description: "An AI-assisted framework for scientific software development: incremental Fortran→C++ translation plus code inspection/generation/update and tool-using agent workflows."
  provider:
    organization: "Lab Notebooks"
    url: "https://github.com/Lab-Notebooks/CodeScribe"
  version: "2026.dev"
  documentation_url: ""
  protocol_version: "0.1.0"
  preferred_transport: "local/CLI"
  capabilities:
    streaming: "true"   # Anthropic backend prefers the streaming API
    push_notifications: "false"
    state_transition_history: "true"  # bounded loop writes on-disk artifacts under .codescribe/loop/

authentication:
  schemes:
    - "API key (per-backend env var)"
  credentials: "ANTHROPIC_API_KEY / OPENAI_API_KEY / OPENAI_COMP_APIKEY / ARGO_USER (depending on backend); none for local Transformers checkpoints"
  default_input_modes:
    - "text/plain"
  default_output_modes:
    - "text/plain"

  skills:
    - id: "translate"
      name: "Incremental Fortran → C++ Translation"
      description: "Incrementally translate Fortran codebases to C++, generating C++ source files and Fortran-C++ interface layers for interoperability."
      tags: [Fortran, C++, HPC, LLM, translation, interface-layer]
      examples:
        - "Generate draft C++ files and interface layers for a list of Fortran sources"
        - "Translate a module using a seed prompt template and a chosen model backend"
      input_modes: ["text/plain"]
      output_modes: ["text/plain"]

    - id: "code_assist"
      name: "Code Inspection, Generation, and Update"
      description: "Inspect, generate, and update scientific source files from natural-language prompts or seed prompt files."
      tags: [LLM, code-generation, inspection, update, scientific-computing]
      examples:
        - "Summarize a repo and list key entry points (inspect)"
        - "Generate a new source file from a natural-language prompt with reference files"
      input_modes: ["text/plain"]
      output_modes: ["text/plain"]

    - id: "agentic_coding"
      name: "Tool-Using Coding Agent Workflows"
      description: "Run iterative tool-using agents (read/glob/bash/edit/write), including a bounded execution→review loop over a task file with durable on-disk state."
      tags: [agent, ReAct, tools, bounded-loop, review]
      examples:
        - "Run a single agent session: code-scribe agent \"Fix failing tests\""
        - "Run a bounded multi-session loop over a task file: code-scribe loop task.toml"
      input_modes: ["text/plain"]
      output_modes: ["text/plain"]

Extensions:
  agent_runtime:
    framework: "Custom Python + multi-backend LLM pipeline (OpenAI / Anthropic / OpenAI-compatible / ARGO / local Transformers)"
    service_endpoint: "local/CLI execution (code-scribe)"
    rate_limits: "None imposed locally; subject to upstream provider limits"
    logging: "Local console logs (--verbose) and append-only TOML diagnostic events (--log/--log-path; default .codescribe/logs/toolusage.toml)"
    memory: "Per-session stateless inner agent; loop carries cross-cycle state in-memory, with on-disk artifacts under .codescribe/loop/ for inspection and crash-resume"

---

# CodeScribe

*Last Updated*: **2026-06-16**

## Developed by
CodeScribe Contributors

## Contributed by
CodeScribe Contributors.

## Agent Changelog
+ **2026-06-16** – https://github.com/Lab-Notebooks/CodeScribe/commit/490840fc6ed0f24b81e0fe47ad4587629b1e9a85


## Agent short description
An AI-assisted framework for scientific software development that combines multi-backend LLMs with tool-using coding agents to perform incremental Fortran→C++ translation, code inspection/generation/update, and bounded agentic workflows.

## Agent description
CodeScribe interprets developer intent from CLI prompts, seed prompt files, or task files, and acts on a scientific codebase through a small set of file and shell tools (`read`, `glob`, `bash`, `edit`, `write`). Its original focus is incremental Fortran-to-C++ translation — indexing the project tree, generating draft C++ files and Fortran-C++ interface layers, and translating sources using chat-template seed prompts — but the current codebase also supports general code inspection, generation, and update, as well as tool-using agent loops. The inner agent follows a ReAct-style thought→action→observation cycle with a compact, fixed-size workspace-context grounding block, and a structurally separate review agent evaluates harness-computed evidence (not a rendered transcript) during bounded loops. This lets CodeScribe modernize legacy scientific codes and assist broader code-generation and maintenance tasks while keeping the action space auditable.

## Underlying model(s) (optional)
CodeScribe does not depend on a single fixed model. It selects an LLM backend from the prefix of the `-m/--model` argument and supports interchangeable backends: OpenAI (`openai-*`), Anthropic (`anthropic-*`), OpenAI-compatible endpoints (`oaic-*`, e.g. Ollama or ALCF), ARGO (`argo-*`), and local Hugging Face / Transformers checkpoints (filesystem path). Anthropic models are recommended for agent and loop commands because native tool calling, streaming, and adaptive reasoning are all supported.

## Inputs and outputs
1. Input: Text prompts from the CLI, seed prompt files (TOML chat templates), reference files, and task files.
2. Output: Text/code responses, generated or modified source files, Fortran-C++ interface layers, and TOML diagnostic/state artifacts.

### Default interaction modes
- defaultInputModes: ["text/plain"]
- defaultOutputModes: ["text/plain"]

### Skills
- **Skill ID**: translate
  **Name**: Incremental Fortran → C++ Translation
  **Description**: Incrementally translate Fortran codebases to C++, generating C++ source files and Fortran-C++ interface layers for interoperability.
  **Tags**: Fortran, C++, HPC, LLM, translation, interface-layer
  **Examples**:
    -- Generate draft C++ files (`.scribe`) and interface layers for a list of Fortran sources
    -- Translate a module using a seed prompt template and a chosen model backend
  **Input/Output Modes**: text/plain / text/plain

- **Skill ID**: code_assist
  **Name**: Code Inspection, Generation, and Update
  **Description**: Inspect, generate, and update scientific source files from natural-language prompts or seed prompt files.
  **Tags**: LLM, code-generation, inspection, update, scientific-computing
  **Examples**:
    -- Summarize a repo and list key entry points (`inspect`)
    -- Generate a new source file from a natural-language prompt with read-only reference files (`generate`)
    -- Update existing files from a prompt while using additional reference files (`update`)
  **Input/Output Modes**: text/plain / text/plain

- **Skill ID**: agentic_coding
  **Name**: Tool-Using Coding Agent Workflows
  **Description**: Run iterative tool-using agents (`read`/`glob`/`bash`/`edit`/`write`), including a bounded execution→review loop over a task file with durable on-disk state.
  **Tags**: agent, ReAct, tools, bounded-loop, review
  **Examples**:
    -- Single agent session: `code-scribe agent "Fix failing tests"`
    -- Bounded multi-session loop over a task file: `code-scribe loop task.toml`
  **Input/Output Modes**: text/plain / text/plain

### Tools and permissions
- Tool: `read`
  - Purpose: Read file contents with optional line offsets/limits
  - Inputs: File path, optional `offset`/`limit`/`with_line_numbers`
  - Outputs: File text (optionally line-numbered)
  - Side effects: None (read-only)
  - Required permissions: Filesystem read (restricted to the working tree in bounded mode)

- Tool: `glob`
  - Purpose: List files matching a glob pattern (supports `**`)
  - Inputs: `pattern`, optional `root`/`include_dirs`/`limit`
  - Outputs: List of matching paths
  - Side effects: None (read-only)
  - Required permissions: Filesystem read (restricted to the configured root in bounded mode)

- Tool: `bash`
  - Purpose: Run shell commands (arbitrary in unbounded mode; allowlisted in bounded mode)
  - Inputs: Command string
  - Outputs: Normalized block with `exit_code`, `STDOUT`, `STDERR`
  - Side effects: Executes shell commands; may modify the system in unbounded mode
  - Required permissions: Local execution. Bounded mode rejects shell metacharacters and explicit/absolute/`..` paths, and allows only an allowlist (`ls`, `pwd`, `find`, `grep`, `head`, `tail`, `wc`, `git`, `test`, `echo`, `sed`), extensible via a task-file `[tools] bash = [...]` section.

- Tool: `edit`
  - Purpose: Perform exact `oldText → newText` replacements in files
  - Inputs: `path`, `edits` (each `oldText` must match exactly once)
  - Outputs: JSON report with before/after snippets
  - Side effects: Writes the updated file
  - Required permissions: Filesystem write (restricted to the tool root in bounded mode)

- Tool: `write`
  - Purpose: Create or overwrite a whole file
  - Inputs: `path`, `content`
  - Outputs: Confirmation of written file
  - Side effects: Writes data
  - Required permissions: Filesystem write (path must stay within the tool root in bounded mode)

- Tool: LLM backends (OpenAI / Anthropic / OpenAI-compatible / ARGO / local Transformers)
  - Purpose: Natural language understanding, code generation, translation, and tool-call planning
  - Inputs: Prompts, chat templates, tool schemas
  - Outputs: Generated text/code and structured tool calls
  - Side effects: Network calls for hosted backends; local inference for Transformers checkpoints
  - Required permissions: Per-backend API key (network access), or local execution for Transformers

### Service endpoint and discovery
- Base URL: https://github.com/Lab-Notebooks/CodeScribe
- A2A discovery path(s): N/A (not deployed as a service)
- Invocation endpoint (example): N/A (invoked via the `code-scribe` CLI)

## Runtime Infrastructure

CodeScribe is a Python package installed via `pyproject.toml`/`pip`. It runs wherever Python runs — no daemon, no REST API, and no Docker dependency. Hosted backends require network access and an API key; local Transformers checkpoints require the optional `transformers` extra and (typically) a GPU.

### Hardware
- Any machine that runs Python 3.8+ for hosted/OpenAI-compatible backends
- GPU recommended for local Hugging Face / Transformers checkpoints
- Local storage for model caches when using local checkpoints

### Software
- **Python**: 3.8+, virtual environment recommended.
- **Core Python dependencies** (installed via `pip install -e .`):
  - `click`, `requests`, `toml`, `pyyaml`, `alive-progress==3.1.4`, `openai`, `anthropic`
- **Optional extra** (`pip install -e ".[transformers]"`):
  - `torch`, `transformers`

```bash
# Setup Python environment
python3 -m venv env
source env/bin/activate
pip install --upgrade pip

# Core install (editable)
pip install -e .

# Optional: local Hugging Face / Transformers backend
pip install -e ".[transformers]"

code-scribe --help
```

## Papers and Scientific Outputs

1. Akash Dhruv, Anshu Dubey, "Leveraging Large Language Models for Code Translation and Software Development in Scientific Computing," Proceedings of the Platform for Advanced Scientific Computing Conference (2025). https://doi.org/10.1145/3732775.3733572
2. Preprint: https://arxiv.org/abs/2410.24119
3. Demo: https://doi.org/10.5281/zenodo.18853292

## Agent License

Apache 2.0

## Contact Info and Card Authors

- Akash Dhruv

## Intended Uses

### Intended Use

- Incremental translation of legacy Fortran codebases to C++, including generation of Fortran-C++ interface layers
- Indexing a project directory tree (`scribe.yaml`) to give models structural context
- Code inspection, generation, and update from natural-language prompts or seed prompt files
- Tool-using agentic coding (single session) and bounded multi-session loops over a task file

### Primary Intended Users

Scientific software developers and HPC engineers modernizing legacy codes and performing broader code-generation and maintenance tasks.

### Mission Relevance

CodeScribe supports scientific-computing modernization by automating incremental Fortran→C++ translation and assisting generative AI workflows, helping teams leverage modern libraries and ensure performance portability across heterogeneous HPC platforms while maintaining functionality through testing and iterative conversion.

### Out-of-Scope Use Cases

- Fully autonomous code generation without human review
- Treating bounded mode as an OS-level sandbox (it is a constraint layer, not isolation)
- High-level architecture/design decisions
- Bulk, non-incremental translation of entire codebases in a single pass

## How to Use

### Install Instructions
Detailed step-by-step instructions are provided in the README of the GitHub repository — https://github.com/Lab-Notebooks/CodeScribe. In short: create a virtual environment and `pip install -e .` (add `".[transformers]"` for the local backend).

### Agent Configuration

- **System and prompt instructions**: Combines static system prompts (including a ReAct-style nudge) with dynamic user input — CLI tasks, seed prompt TOML chat templates, reference files, and task files — to guide LLM behavior and scoped code edits.
- **Tool integration**: Invoked via the local `code-scribe` CLI. The agent uses native tool calling on `openai-*`/`anthropic-*`/`oaic-*` backends, and a strict-JSON emulation fallback on `argo-*` and local Transformers checkpoints.
- **Policy settings**: Bounded mode restricts file tools to the working tree and `bash` to an allowlist with rejected shell metacharacters/path escapes; the allowlist is extensible via a task-file `[tools] bash = [...]` section.
- **Memory and state management**: The inner agent is stateless per session. In loop mode, cross-cycle state is carried in-memory while on-disk artifacts under `.codescribe/loop/` exist for inspection and crash-resume.

### Invocation / Integration

- **CLI execution**: Run any of `index`, `draft`, `translate`, `inspect`, `generate`, `update`, `agent`, `loop`, or `format` via `code-scribe`. Output is to the terminal, to generated/modified source files, or to TOML artifacts depending on the command.
- **Agent mode**: A single tool-using session with unbounded tools (use with care).
- **Loop mode**: Repeated fresh, bounded sessions over a task file — each session reads the task file, performs one important pending task, writes a concise report, and exits. An execution agent and a structurally separate review agent alternate; the loop exits early when the reviewer reports no pending items and no blocker.

### Code Snippets of How to Use the Agent
```bash
# One-shot tool-using agent
export ANTHROPIC_API_KEY="sk-ant-..."
code-scribe agent "Write a hello world Python script to hello.py" \
    -m anthropic-claude-sonnet-4-6 --verbose

# Enable adaptive thinking (Anthropic backends only)
code-scribe agent "Fix failing tests" -m anthropic-claude-sonnet-4-6 --reason

# Bounded multi-session loop over a task file
code-scribe loop task.toml -m anthropic-claude-sonnet-4-6 --verbose

# Incremental translation pipeline
code-scribe index <project_root_dir>
code-scribe draft <filelist>
code-scribe translate <filelist> -m anthropic-claude-opus-4-8 -p seed_prompt.toml

# Inspect a repo with an OpenAI-compatible endpoint
code-scribe inspect README.rst -m oaic-llama3.1 -q "Summarize this repo and list key entry points."
```

Key flags for `agent`/`loop`: `--verbose/-v` (stream per-iteration tool calls and token usage), `--log`/`--log-path PATH` (write TOML diagnostics), `--reason` (adaptive thinking on Anthropic backends; silently ignored elsewhere). Loop adds `--workdir DIR`, `--agent-loops/-nloop N` (default 5), and `--agent-iterations/-niter N` (default 30).

# Limitations

## Risks

- **Code edits**: Generated edits may introduce syntax or logic errors; always review before committing.
- **Prompt issues**: Malformed or malicious prompts/task files can lead to incorrect edits.
- **Unbounded agent mode**: The single-session `agent` runs with unbounded tools (including arbitrary `bash`); use with care.
- **Bounded mode is not a sandbox**: It is a practical constraint layer, not OS-level isolation.
- **Data handling**: Hosted backends transmit prompts and code to third-party APIs; manage sensitive or proprietary code accordingly. Local Transformers checkpoints avoid network exposure.

## Limitations

- **Language support**: Focused on Fortran→C++ translation; results vary for other languages and structurally complex code.
- **LLM variability**: Quality of suggestions depends on the underlying model and prompt; results may be inconsistent.
- **Context dependence**: The agent operates on scoped regions with a fixed-size workspace-context block; insufficient context can lead to incomplete or incorrect edits.
- **No guarantees**: Automated edits are not guaranteed to be semantically correct or optimal; human review is required.
- **Known gaps**: No streaming for non-Anthropic backends, no model-failure retry, no wall-clock timeout, and no OS-level sandbox.
- **Biases**: LLM suggestions may reflect biases or gaps in training data, examples, or repository history.

# Agent Evaluation Details (Optional)
The plan is the following.

- **Tool-call correctness**: evaluation against test prompts, cross-checked against verified tool outputs (`output_preview`) in the TOML event log
- **Latency**: depends on the selected backend and inference speed
- **Task success**: correctness and compilability of translated/generated code
- **Regression tests**: automated tests on translation, scaffolding, and agentic edits (in progress)
- **Human-in-the-loop**: recommended for final code merges; the bounded loop's review agent flags any `<final_answer>` claim not backed by a verified action

# More Information (Optional)

- Repository: https://github.com/Lab-Notebooks/CodeScribe
- In-tree docs: `docs/agent.md` (agent architecture and bounded-mode policy), `docs/loop.md` (loop internals and on-disk artifacts), `docs/tools.md` (tool implementations), `docs/models.md` (backends and env vars), `docs/cmd.md`
- Agent card: `AGENT.json`
