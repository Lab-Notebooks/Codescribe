---
name: codescrib.env
description: Pick a model for a provider, then export env vars for Codescribe tool calling

---

# Codescribe Model Selection Workflow

You help the user select a model for a given provider and then export the environment variables needed by CodeScribe.

## Instructions

### Step 1: Resolve Provider

Check if `provider` is set in the agent frontmatter above. provider is the string before the first
"/" in the model name.

- If **set**: use that provider value.
- If **not set**: ask the user: "Which provider should I use?" and wait for their response.

### Step 2: Fetch Available Models

Call the `codescribe_env_model` tool:

```
codescribe_env_model({ "provider": "<provider>" })
```

Parse the returned list. If there's an error (provider not found, no models), show it to the user and stop.

### Step 3: Present Model Options

Display the models as a numbered list to the user. Ask:

> "Select a model by number or paste the model ID:"

You must list all the models as standard output. No interactive mode.
Wait for user input. Validate their selection matches one of the available models.

### Step 4: Export Environment

Once a valid model is selected, call:

```
codescribe_export_env({ "provider": "<provider>", "model": "<selectedModel>" })
```

### Step 5: Confirm

Print the returned `export ...` lines to the user so they can see the environment is configured.

---

## Example Flow

1. Extract provider from the agent model frontmatter. For example in `model: argo_proxy/argo:gpt4o`
   `argo_proxy` is the provider

2. Agent calls `codescribe_env_model({ "provider": "argo_proxy" })`

3. Tool returns:
   ```
   # Provider: argo_proxy
   # Models (3):
   1. argo:gpt4o
   2. argo:claude-sonnet
   3. argo:llama3
   ...

   ```
4. Agent asks user to pick
5. User says "1"
6. Agent calls `codescribe_export_env({ "provider": "argo_proxy", "model": "argo:gpt4o" })`
7. Agent prints the export statements
