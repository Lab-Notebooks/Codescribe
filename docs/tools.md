# Tools (`codescribe/lib/_tools.py`)

This document describes the agent tool implementations used by Codescribe.
The agent loop lives in `codescribe/lib/_agent.py`; the concrete tool
implementations live in `codescribe/lib/_tools.py`.

## Overview

Tools are small, schema-described functions the model can invoke:

- `read`: read file contents (optionally with line offsets/limits)
- `glob`: list files via glob patterns
- `bash`: run shell commands (bounded allowlist mode supported)
- `edit`: exact text replacement edits
- `write`: write (create/overwrite) a whole file

Tools share a common base class: `AgentTool`.

## `AgentTool`

`AgentTool` carries:

- `name`
- `description`
- `parameters` (JSON-schema-like object used for tool calling)
- `enabled`

It also provides:

- `to_openai_tool()`: converts the tool to an OpenAI-style function schema.
- `describe_for_prompt()`: text description + schema for fallback/text protocol prompting.

## Path bounding: `_resolve_within_root()`

When a tool is created with a `root`, file paths are resolved under that root.
Any attempt to escape (e.g. `../..` traversal) is rejected.

This is the core safety primitive for bounded mode.

## `ReadTool` (`read`)

Reads a text file with optional slicing:

- `offset`: 1-indexed starting line
- `limit`: max number of lines
- `with_line_numbers`: defaults to `1` (prefixes lines as `0001: ...`)

Bounded behavior:

- if constructed with `root=...`, reads are restricted to the working tree.

## `GlobTool` (`glob`)

Lists files matching a glob pattern (supports `**`).

Key args:

- `pattern` (required)
- `root` (optional): sub-root for the search
- `include_dirs` (0/1)
- `limit` (default 2000)

In bounded mode, results are kept within the configured root and returned
relative to the chosen search base.

## `BashTool` (`bash`)

Executes shell commands and returns a normalized text block:

- `exit_code: N`
- `STDOUT:`
- `STDERR:`

Bounded behavior (when `bounded=True`):

- rejects common shell metacharacters (pipes, redirects, `$`, etc.)
- allows only a command allowlist (defaults include `ls`, `find`, `grep`, `git`, ...)
- the allowlist can be extended by loop/task metadata (see `docs/loop.md`)

Note: current implementation still uses `shell=True` even in bounded mode;
boundedness is enforced by pre-validation.

## `EditTool` (`edit`)

Performs **exact** text replacements.

Arguments:

- `path`
- `edits`: list of `{oldText, newText}`

Rules:

- each `oldText` must match **exactly once** in the original file

The tool writes the updated file and returns a JSON report with before/after
snippets to make it easier for an agent to verify changes.

## `WriteTool` (`write`)

Creates or overwrites a file with full content.

Arguments:

- `path`
- `content`

In bounded mode, the write path must stay within the tool root.

## Toolset constructors

- `make_tools(root, bash_allow=None)`: bounded default toolset used by loop mode
  (`read`, `glob`, bounded `bash`, `edit`, `write`).
- `make_readonly_tools(root, bash_allow=None)`: bounded read-only set
  (`read`, `glob`, bounded `bash`).

`DEFAULT_TOOLS` is a convenience list built from `make_tools(Path.cwd())`.
