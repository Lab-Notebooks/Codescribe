# Command layer (`codescribe/lib/_cmd.py`)

This module is the bridge between the CLI entry points and the library
internals. Each `prompt_*` function corresponds to one CLI command and is
responsible for constructing the model input, invoking the model or agent,
and writing outputs back to disk.

If you're modifying behaviour, treat the code as authoritative:
`codescribe/lib/_cmd.py`.

## Role in the call stack

```
CLI (code-scribe <cmd>)
  └── prompt_<cmd>(...)          # _cmd.py — assembles context, calls lib
        ├── lib.set_neural_model  # _llm.py — constructs backend
        ├── lib.Agent             # _agent.py — tool-using agent loop
        └── lib.make_*_tools      # _tools.py — bounded/unbounded tool sets
```

The cmd layer does not implement any LLM or tool logic itself.

---

## `prompt_translate`

**CLI command**: `code-scribe translate`

Drives the Fortran-to-C++ translation loop over a file mapping produced by
`code-scribe draft`.

### Inputs

| Parameter | Type | Description |
|---|---|---|
| `mapping` | `List[List[str]]` | Six parallel lists: `[fsource, csource, finterface, cdraft, promptfile, cheader]` |
| `seed_prompt` | `Path` | TOML chat template used as the conversation seed |
| `model` | `str \| Path` | Model identifier (optional; skips inference if omitted) |

### Behaviour

For each file tuple:

1. **Skip if the output already exists** — if `csource` is present on disk the
   file is skipped. This makes the loop idempotent and safe to resume.
2. **Fortran comment stripping** — lines beginning with `c`, `!!`, or `!`
   (case-insensitive, excluding `complex`) are dropped before the source is
   injected into the prompt. This reduces noise for the model.
3. **Context injection** — the Fortran source is appended inside `<source>`
   tags; if a `.scribe` draft file exists it is appended inside `<draft>`
   tags. Both are added to the last user turn of the chat template.
4. **XML output parsing** — the model response is searched for three tagged
   regions: `<csource>`, `<cheader>`, and `<fsource>`. Matched regions are
   written to the corresponding output files. If a tag is absent the raw
   model output is written instead.
5. **Template reset** — after each file the last user turn's content is
   restored from a cached copy so the next file starts from a clean template.

---

## `prompt_inspect`

**CLI command**: `code-scribe inspect`

Runs an inspection agent in bounded read-only mode over a list of files or
directories.

### Inputs

| Parameter | Type | Description |
|---|---|---|
| `filelist` | `List[Path]` | Files or directories to inspect |
| `query_prompt` | `str` | Natural-language query to answer |
| `file_index` | `Dict[str, str]` | Optional project index (symbol → file path) |
| `model` | `str \| Path` | Required; no default |
| `verbose` | `bool` | Stream agent diagnostics to stdout |

### Behaviour

1. **Common root resolution** — directories contribute themselves; files
   contribute their parent directory. The common root of all entries becomes
   the agent's bounded working directory.
2. **Task assembly** — the agent is given a structured task listing the
   relative file paths, the filtered project index (if any), and the query.
   It is instructed to finish with a `<final_answer>` block.
3. **Read-only tools** — the agent is created with `lib.make_readonly_tools`,
   which excludes `edit` and `write`. `bash` is also excluded; only `read`
   and `glob` are available.
4. The agent's final answer is printed to stdout.

---

## `prompt_generate`

**CLI command**: `code-scribe generate`

Generates new source files from a seed prompt or a natural-language string.

### Inputs

| Parameter | Type | Description |
|---|---|---|
| `seed_prompt` | `str \| Path` | TOML chat template **or** a plain string prompt |
| `model` | `str \| Path` | Model identifier |
| `reference_existing` | `List[Path]` | Files to include as read-only context |

### Behaviour

1. **Prompt resolution** — if `seed_prompt` is a path that exists on disk it
   is loaded as a TOML chat template; otherwise it is treated as a
   natural-language user message directly.
2. **Reference injection** — each reference file is appended to the last user
   turn wrapped in `<filename>...</filename>` tags, with an instruction not to
   modify them.
3. **XML output parsing** — the model response is scanned with a greedy regex
   for any `<tag>...</tag>` pair. Each match is written to a file whose path
   is the tag name, creating intermediate directories as needed. This allows
   the model to generate multiple files in a single response.

---

## `prompt_update`

**CLI command**: `code-scribe update`

Updates existing source files in place, using a seed prompt and optional
reference files.

### Inputs

| Parameter | Type | Description |
|---|---|---|
| `filelist` | `List[Path]` | Files to update (written back to disk) |
| `seed_prompt` | `Path` | TOML chat template (optional) |
| `query_prompt` | `str` | Natural-language instruction (optional) |
| `model` | `str \| Path` | Model identifier |
| `reference_existing` | `List[Path]` | Read-only context files |

### Behaviour

Similar pipeline to `prompt_generate` with two differences:

1. **Disjointness check** — raises `ValueError` if any file appears in both
   `filelist` and `reference_existing`. This prevents the model from being
   asked to both update and treat a file as read-only.
2. **Existing content injection** — each target file is read and injected into
   the prompt inside `<filename>` tags with an instruction to update it.
   Reference files follow with a "do not edit" instruction. The model is
   expected to return the updated content in the same tag format.

Output parsing and file writing follow the same XML-tag regex as
`prompt_generate`.

---

## `prompt_agent`

**CLI command**: `code-scribe agent`

Runs a single open-ended tool-using agent session on an arbitrary task.

### Inputs

| Parameter | Type | Description |
|---|---|---|
| `task` | `str` | Natural-language task description |
| `model` | `str \| Path` | Model identifier |
| `agent_iterations` | `int` | Tool-call iteration budget (default 20) |
| `verbose` | `bool` | Stream per-iteration diagnostics to stdout |
| `logging` | `Path \| str \| None` | Path for TOML event log; empty string uses default location |
| `reason` | `bool` | Enable adaptive thinking (Anthropic backends only) |

### Behaviour

1. **Unbounded tools** — unlike `prompt_inspect`, the agent is created with
   `lib.make_tools(Path.cwd())`, which includes `edit` and `write` in addition
   to `read`, `glob`, and `bash`. The working directory root is still
   respected for path resolution, but the command allowlist is not applied.
2. **Optional TOML logging** — if `logging` is set, a `ToolLogToml` sink is
   attached to the agent. Passing an empty string uses the default path
   (`.codescribe/logs/toolusage.toml`). The log captures every `tool_start`
   and `tool_end` event for post-run inspection.
3. Returns the agent's final answer string (the content of the `<final_answer>`
   block, or an error string if the iteration limit is reached).

---

## XML output format

`prompt_generate` and `prompt_update` both rely on the model returning one or
more files wrapped in XML-style tags:

```
<path/to/file.py>
... file contents ...
</path/to/file.py>
```

The parsing regex is greedy (`re.DOTALL`) and matches the first occurrence of
each tag pair. Tag names become file paths verbatim, so the model must use
exact relative paths. Intermediate directories are created automatically.
