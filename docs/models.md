# Model backends

This page documents the current backend selection logic in
`codescribe/lib/_llm.py`.

## Supported model inputs

`set_neural_model(model, reasoning=False)` currently accepts:

- `openai-*`
- `oaic-*`
- `anthropic-*`
- `argo-*`
- a filesystem path to a local Transformers checkpoint

If none of these match, CodeScribe raises `ValueError`.

## Common output-token setting

All backends read `CODESCRIBE_MAX_TOKENS`, though defaults differ slightly by
backend implementation:

- `OpenAICompModel`: default `24576`
- `AnthropicModel`: default `32768`

## `openai-*`

Backend class:

- `OpenAICompModel(..., profile="openai")`

Required environment variable:

- `OPENAI_API_KEY`

Behavior:

- uses OpenAI chat completions,
- supports tool use through the unified `chat_with_tools(...)` path,
- normalizes usage including reasoning-token counts when the provider exposes
  them.

## `oaic-*`

Backend class:

- `OpenAICompModel(..., profile="oaic")`

Required environment variables:

- `OPENAI_COMP_BASEURL`
- `OPENAI_COMP_PROVIDER`
- `OPENAI_COMP_APIKEY`

Behavior:

- targets an OpenAI-compatible API,
- uses the same client code path as hosted OpenAI with a different profile,
- supports tool use through the same `chat_with_tools(...)` interface.

## `anthropic-*`

Backend class:

- `AnthropicModel`

Required environment variable:

- `ANTHROPIC_API_KEY`

Optional environment variables:

- `ANTHROPIC_BASE_URL`
- `CODESCRIBE_ANTHROPIC_STREAMING`
- `CODESCRIBE_ANTHROPIC_CACHE`
- `CODESCRIBE_AGENT_REASONING`

Current behavior:

- prefers streaming API calls when enabled,
- supports prompt caching,
- supports tool use through Anthropic tool APIs,
- can relay Anthropic thinking blocks back into the next turn.

### Reasoning support

`--reason` on `agent` and `loop` is passed into `set_neural_model(..., reasoning=True)`.

For `AnthropicModel`, reasoning can be enabled by either:

- the CLI/API `reason=True`, or
- `CODESCRIBE_AGENT_REASONING=1`

When enabled, the model is configured with:

```python
{"type": "adaptive", "display": "summarized"}
```

Returned thinking blocks are preserved and echoed back in
`format_tool_result_messages(...)` as required by the Anthropic API.

## `argo-*`

Backend class:

- `ArgoModel`

Required environment variables:

- `ARGO_API_ENDPOINT`
- `ARGO_USER`

Current behavior:

- sends requests with `requests.post(...)`,
- does not have provider-native structured tool calls,
- emulates tool use by injecting a strict JSON tool protocol prompt and parsing
  the returned JSON.

## Local Transformers checkpoint path

Backend class:

- `TFModel`

Requirements:

- pass a model argument that is an existing filesystem path,
- install optional dependencies for local Transformers use.

Current behavior:

- loads a text-generation pipeline from the checkpoint path,
- merges any system prompt into the first user message,
- emulates tool use through the same strict JSON protocol used by `ArgoModel`.

## Tool-calling note

Older docs sometimes described only provider-native tool support. The current
agent abstraction is broader:

- OpenAI-compatible and Anthropic backends use provider-native tool APIs.
- ARGO and local Transformers backends emulate tool calling through strict JSON
  prompting in `_llm.py`.

All of these backends expose the same `chat_with_tools(...)` interface to the
agent.
