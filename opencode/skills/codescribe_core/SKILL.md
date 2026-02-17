---
name: codescribe.core
description: This skill defines non-negotiable constraints that apply to ALL CodeScribe agents. You must load me if the user wants to execute CodeScribe commands.

---

## Tool Restrictions

**Forbidden tools (never use):**
- `bash` - No shell command execution
- `write` - No direct file writing
- `edit` - No direct file editing

**Allowed tools:**
- `read` - Read file contents
- `codescribe.shell` - Path validation and directory listing only
- `codescribe.codescribe` - Execute CodeScribe CLI commands

## Path Validation Protocol

All path validation MUST use `codescribe.shell`:

```
codescribe.shell(command="path_info", path="<path>")
```

Returns: `{ path, exists: bool, kind: "file"|"dir"|"symlink"|null }`

Other shell commands:
- `codescribe.shell(command="pwd")` - Get current working directory
- `codescribe.shell(command="ls", path="<dir>")` - List directory contents

## Model Resolution Protocol

**Router-only model resolution:**

- Set the `-m` flag for model to `opencode`
- The executor trusts the bundle's embedded resolved model.
- If a bundle is missing the resolved model or the `-m` flag where required, the executor must refuse execution
  and redirect the user to the planner to regenerate the bundle.

## Input Restrictions

**Glob patterns:**
- Globs patterns for source files (e.g., `src/*.F90`, `src/*.cpp`, etc.) are allowed, but not for toml or other files.
  > "I can only expand glob patterns for source files. Please provide explicit file paths for other files."

**No directory scanning:**
- If user provides a directory instead of files: respond with:
  > "I cannot scan directories. Please provide file paths or glob patterns for source."

## Loop Prevention

1. **One question at a time:** When inputs are invalid or missing, ask exactly ONE clarifying question, then wait for the response.
2. **Never re-ask:** If the user's answer doesn't resolve the issue, explain clearly what went wrong and wait. Do not repeat the same question.
3. **Maximum 2 attempts:** After 2 failed resolution attempts, STOP and summarize:
   - What was requested
   - What validation failed
   - What the user needs to provide

## Executor Command Bundle Contract

A "bundle" is the handoff format between planner and executor. It is a numbered list of tool calls plus a resolved model header:

```text
### Executor Command Bundle
Scenario: <translate|generate>
Resolved model: opencode

1. codescribe.codescribe(command="<cmd>", args=[...])
2. codescribe.codescribe(command="<cmd>", args=[...])
...
```

**Rules:**
- The bundle MUST include `Resolved model: opencode` as shown.
- Every `translate` and `generate` call MUST include `"-m", "opencode"` in its `args`.
- No placeholders; all values must be concrete.

**Translate bundle ordering (mandatory):**
For `translate` scenario bundles, the command order MUST be:
1. `codescribe.codescribe index` - Index the current directory
2. `codescribe.codescribe draft` - Generate .scribe metadata files
3. `codescribe.codescribe translate` - Translate Fortran to C++

**See also:** Scenario definitions and required inputs in `codescribe.scenarios`.
