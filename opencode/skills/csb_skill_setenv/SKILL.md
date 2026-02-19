---
name: csb_skill_setenv
description: I resolve model and provider for tools that run agents.

---

# What I do
I help the user select LLM model and provider that can be passed to a tool.

# How I do it
### Step 1: Resolve Provider
Use the `question` tool to ask a custom question: "Which provider to use?", with the output of 
`csb_tool_env_provider({})` tool as the choices.

### Step 2: Fetch Available Models
Use the `question` tool to ask a custom question: "Which model to use?", with the output of
`csb_tool_env_model({ "provider": "<selectedProvider>" })` tool as the choices. Show 20 choices.

I report the provider and model to the agent.
