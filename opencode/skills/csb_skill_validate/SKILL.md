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
- Optional `-r` refs: each must be explicit (no globs), exist, be a file

**For `translate`:**
- Root directory (`root_dir`): required, must exist, must be a directory
- Seed prompt TOML: explicit (no globs), ends `.toml`, exists, is a file (no constraint on location—may be inside or outside `root_dir`)
- Fortran targets: globs allowed
- Expand globs to concrete file list (hidden files excluded)
- Expanded list must be non-empty
- Each file must exist, be a file, have extension in:
  `.f .F .f90 .F90 .f95 .F95 .f03 .F03 .f08 .F08 .for .FOR`
- Each Fortran file must be under `root_dir`
- MUST reject `-r` refs for translate
- Convert all `fortran_files` to paths relative to `root_dir`
- Convert `prompt_toml` to absolute path.

### Step 3: Return Result
**On success:**
```
ok: true
scenario: <generate|translate>
root_dir: <path>              # translate only (absolute path)
prompt_toml: <path>           # as-is (absolute or relative, no location constraint)
prompt_string: <string>       # if applicable
refs: [<paths>]               # if applicable
fortran_files: [<paths>]      # concrete list for translate (relative to root_dir)
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
- For translate: if any Fortran file is not under `root_dir`, fail with:
  ```
  ok: false
  error_code: FILE_OUTSIDE_ROOT
  message: "<file> is not under root_dir <root_dir>"
  ```
  (This constraint does NOT apply to `prompt_toml`—it may be located anywhere.)
