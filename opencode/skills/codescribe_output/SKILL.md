---
name: codescribe.output
description: This skill defines standard output templates for consistent agent responses.

---

## Planner Output Format

After completing planning, provide:

```markdown
## Planning Summary

**Scenario:** `generate` | `translate`

### Validated Inputs

| Input | Path | Status |
|-------|------|--------|
| Seed Prompt | `prompts/code_translation.toml` | Valid (file exists) |
| Target File | `src/Solver.F90` | Valid (file exists) |
| Reference | `src/Utils.hpp` | Valid (file exists) |

### Executor Command Bundle

*(Bundle must conform to `codescribe_core` Executor Command Bundle Contract.)*

1. `codescribe.model(model_id="<model-id>")`
2. `codescribe.codescribe(command="index", args=["src"])`
3. `codescribe.codescribe(command="draft", args=["src/Solver.F90"])`
4. `codescribe.codescribe(command="translate", args=["src/Solver.F90", "-p", "prompts/code_translation.toml", "-m", "<resolved-model>"])`

---

Planning complete. Please switch to the `codescribe.executor` agent to execute this bundle.
```

## Executor Output Format

After executing commands, provide:

```markdown
## Execution Summary

### Commands Executed

| # | Command | Status | Duration |
|---|---------|--------|----------|
| 1 | `codescribe.model` | Success | - |
| 2 | `index src` | Success | 0.1s |
| 3 | `draft src/Solver.F90` | Success | 0.2s |
| 4 | `translate src/Solver.F90` | Success | 12.3s |

### Generated Files

- `src/Solver.cpp` - C++ source
- `src/Solver.hpp` - C++ header  
- `src/Solver_fi.F90` - Fortran interface

### Review Checklist

- [ ] Array bounds mapped correctly
- [ ] intent(in) vs intent(inout) respected
- [ ] iso_c_binding interfaces correct
- [ ] Wrapper naming consistent

### Next Steps

1. Review generated files
2. Run `make` to build
3. If errors occur, adjust prompt TOML and re-run, or use default Plan/Build agents for manual fixes
```

## Error Output Format

When an error occurs:

```markdown
## Error Report

**Command:** `translate src/Solver.F90 -p prompts/code_translation.toml -m argo-gpt4o`

**Exit Code:** 1

**Error:**
<error message from stderr>

### Diagnosis

<Brief explanation of what likely went wrong>

### Recommended Fix

Adjust your prompt TOML and re-run the translation, or switch to the default **Plan** and **Build** agents for manual edits.
```

## Validation Failure Format

When path validation fails:

```markdown
## Validation Failed

| Path | Expected | Actual |
|------|----------|--------|
| `src/Missing.F90` | file | does not exist |
| `prompts/` | file | directory |

**Action Required:**
Please provide valid file paths. I cannot proceed with missing or invalid inputs.
```
