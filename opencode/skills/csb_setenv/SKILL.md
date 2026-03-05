---
name: csb_setenv
description: Resolve model and provider for codescribe bundles.

---

# What I do
Help the user select LLM model and provider that can be passed to `csb_tool_codescribe` tool.

# How I do it
### Step 1: Resolve Provider
Use the `question` tool to ask a custom question: "Which provider to use?", with the output of 
`csb_tool_env_provider({})` tool as the choices. Make this interactive and let user select.

### Step 2: Fetch Available Models
Use the `question` tool to ask a custom question: "Which model to use?", with the output of
`csb_tool_env_model({ "provider": "<selectedProvider>" })` tool as the choices. Show all 
available choices. Make this interactive and let user select.

Report the provider and model to the agent.
