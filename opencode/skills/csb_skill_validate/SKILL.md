---
name: csb_skill_validate
description: I validate codescribe tasks and inputs before execution.

---

# What I do
I detect the user's scenario, validate all inputs, expand globs, and return a normalized payload or error.

# How I do it
### Step 1: Detect Scenario
Infer intent from context. Supported scenarios:
- `generate`: create new code from a prompt (no source files)
- `translate`: translate Fortran files to C++

If ambiguous, use the `question` tool to ask: "Is this `generate` or `translate`?"

If the request is unsupported (update, inspect, format, prompt review, etc.), return:
```
ok: false
error_code: UNSUPPORTED_SCENARIO
message: "Only `generate` and `translate` are supported."
```

### Step 2: Validate Inputs
**For `generate`:**
- Require exactly one of:
  - Prompt TOML path: explicit (no globs), ends `.toml`, exists, is a file
  - Raw prompt string: non-empty
- Optional `-r` `ref_files`: each must be explicit (no globs), exist, be a file

**For `translate`:**
- Index directory (`index_dir`): required, must exist, must be a directory.
- Seed prompt TOML: explicit (no globs), ends `.toml`, exists, is a file.
- Fortran targets: globs allowed
- Expand globs to concrete file list (hidden files excluded)
- Expanded list must be non-empty
- Each file must exist, be a file, have extension in:
  `.f .F .f90 .F90 .f95 .F95 .f03 .F03 .f08 .F08 .for .FOR`
- Each Fortran file
- MUST reject `-r` `ref_files` for translate
- Keep relative path for `fortran_files` 
- Keep relative path for `prompt_toml`.

### Step 3: Return Result
**On success:**
```
ok: true
scenario: <generate|translate>
index_dir: <path>             # translate only (relative to current directory)
prompt_toml: <path>           # as-is (relative to current directory)
prompt_string: <string>       # if applicable
ref_files: [<paths>]          # if applicable
fortran_files: [<paths>]      # concrete list for translate (relative to current directory)
```

**On failure:**
```
ok: false
error_code: <code>
message: <description>
missing: [<fields>]
invalid: [<fields>]
```

# Constraints
- One question at a time: ask exactly ONE clarifying question, then wait.
- Never re-ask: if the answer doesn't resolve the issue, explain what went wrong and wait.
- Maximum 2 attempts: after 2 failed resolutions, STOP and summarize what the user needs to provide.
- TOML paths MUST NOT contain glob metacharacters (`* ? [ ] { }`).
