---
name: csb_skill_bundle
description: I produce an Executor Command Bundle from validated codescribe inputs.

---

# What I do
I take a validated payload (`ok:true` from `csb_skill_validate`) and emit the exact commands for `csb_tool_codescribe`.

# How I do it
### Step 1: Receive Validated Payload
Input must be a successful validation result containing:
- `scenario`: `generate` or `translate`
- `prompt_toml` or `prompt_string`
- `refs` (optional, for generate only)
- `fortran_files` (concrete list, for translate only)

### Step 2: Compute Root Directory (translate only)
For `translate` scenario:
- Compute `root_dir` as the lowest common ancestor directory of all `fortran_files`.
- If only one file, use its parent directory.

### Step 3: Emit Executor Command Bundle
For `translate`:
```
Scenario: translate
Root dir: <root_dir>

1. (command="index", args=["<root_dir>"])
2. (command="draft", args=["<file1>", "<file2>", ...])
3. (command="translate", args=["<file1>", "<file2>", ..., "-p", "<prompt_toml>"])
```

For `generate`:
```
Scenario: generate

1. (command="generate", args=["<prompt_toml_or_string>", "-r", "<ref1>", "-r", "<ref2>", ...])
```
Omit `-r` flags if no refs provided.

# Constraints
- Input MUST be a validated payload with `ok:true`.
- Translate bundles MUST follow the exact command order: `index` -> `draft` -> `translate`.
- Generate bundles MUST have exactly one `generate` command.
- All file paths in the bundle are concrete (no globs).
