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
- `fortran_files` (concrete list, relative to `root_dir`, for translate only)
- `root_dir` (absolute path, for translate only)

### Step 2: Use Validated Root Directory (translate only)
For `translate` scenario:
- Use `root_dir` from the validated payload (do not compute it; it was provided by the user and validated).

### Step 3: Emit Executor Command Bundle
The router assembles the full bundle wrapper (`Env:`, `FileList:`, etc.). This skill emits the `Commands:` section content.

For `translate`:
```
Commands:
1) codescribe(command="index", args=["."])
2) codescribe(command="draft", args=["@FileList"])
3) codescribe(command="translate", args=["@FileList", "-p", "<prompt_toml>"])
```
- `"."` in index args means "current directory" (executor runs with `cwd=root_dir`).
- `@FileList` is a macro placeholder; the router populates `FileList:` with concrete paths.
- `<prompt_toml>` is the path from the validated payload (absolute or relative).
- The `draft` command does NOT support `-p <prompt_toml>`.

For `generate`:
```
Commands:
1) codescribe(command="generate", args=["<prompt_toml_or_string>", "-r", "<ref1>", "-r", "<ref2>", ...])
```
Omit `-r` flags if no refs provided.

# Constraints
- Input MUST be a validated payload with `ok:true`.
- Translate bundles MUST follow the exact command order: `index` -> `draft` -> `translate`.
- Generate bundles MUST have exactly one `generate` command.
- All file paths in the bundle are concrete (no globs).
