# Model backends

Codescribe selects an LLM backend based on the prefix of the `-m/--model` argument.

## Recommended: OpenAI-compatible endpoints (`oaic-*`)

Use this when you have **any OpenAI-compatible `/v1` API** (self-hosted or managed). This is the most portable backend and is generally the recommended default.

- Model prefix: `oaic-...` (required)
- Example:

```bash
code-scribe translate <files...> -m oaic-llama3.1 -p seed_prompt.toml
```

Environment variables:

- `OPENAI_COMP_BASEURL` (must include `/v1`, e.g. `http://localhost:11434/v1`)
- `OPENAI_COMP_PROVIDER` (a label used for routing/auth policy, e.g. `ollama`, `alcf-inference`)
- `OPENAI_COMP_APIKEY` (required by the current implementation; may be a placeholder for local endpoints)

Tool calling:

- Supports **native tool calling** (so agent/loop can use tools without the text fallback protocol).

## OpenAI hosted (`openai-*`)

- Model prefix: `openai-...`
- Env var: `OPENAI_API_KEY`
- Tool calling: **native tool calling supported**

## Anthropic (`anthropic-*`)

- Model prefix: `anthropic-...`
- Env vars:
  - `ANTHROPIC_API_KEY`
  - `ANTHROPIC_BASE_URL` (optional; override API base URL)
- Tool calling: **native tool calling supported**

## ARGO (`argo-*`)

ARGO is supported primarily for environments where the ARGO endpoint is available.

- Model prefix: `argo-...`
- Env vars: `ARGO_USER`, `ARGO_API_ENDPOINT`
- Tool calling: **no native tool calling**; agent mode uses the **text-protocol fallback**.

## Local Hugging Face / Transformers checkpoint (path)

If `-m` is a filesystem path, Codescribe uses a local Transformers pipeline.

- Model argument: path to a checkpoint directory
- Tool calling: **no native tool calling**; agent mode uses the **text-protocol fallback**.
