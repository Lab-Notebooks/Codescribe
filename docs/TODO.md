# TODO

This document tracks *open* work items. It intentionally avoids duplicating
implementation details that are easy to drift; prefer pointing to code and the
agent internals doc.

See also: `docs/agent.md`.

## Agent efficiency

### Context compaction

- Add deterministic rolling context compaction in `codescribe/lib/_agent.py`.
- Preserve system prompt and recent turns while summarizing older history.
- Add configurable thresholds, e.g. `compact_context`, `compact_threshold_tokens`, and `compact_keep_last_messages`.
- Apply compaction in both text-protocol and native-tool execution loops.
- Ensure summaries are local/deterministic rather than model-generated on the first pass.

### Tool output management

Already implemented:

- Tool outputs are truncated before reinsertion into the model context.
  (See `_truncate_for_model()` in `codescribe/lib/_agent.py`.)

Still open / possible improvements:

- Tool-specific compact summaries for `read` and `bash`.
- Optional paging/chunking for large file and command outputs.
- Optionally store full tool outputs outside prompt context and feed only summaries back.

## Native tool execution and backend robustness

- Add smoke tests for native tool execution:
  - `OpenAIModel`
  - `OpenAICompModel`
  - `AnthropicModel`
- Verify fallback behavior remains correct for backends without native tool calling:
  - `ArgoModel`
  - `TFModel`
- Harden response normalization for OpenAI-compatible providers with partial/inconsistent tool-calling support.

Already documented:

- The native-tools vs text-protocol split is described in `docs/agent.md`.

## Bounded tool policy

- Consider tightening bounded `bash` validation rules (allowlist and argument checks).
- Consider disabling commands with high variance if not needed.
- Investigate deterministic sandboxing options for bounded mode.
- Evaluate whether bounded mode should prefer structured tools over raw shell access.

## Observability

Already implemented:

- Usage accounting when providers return token counts, plus heuristic estimates in
  fallback mode (see `docs/agent.md`).

Still open / possible improvements:

- Optional “trace” mode emitted by the runtime (brief plan + tool calls + short
  result summaries), without forcing verbose Thought/Action/Observation formatting.
- Model-native tool-path metrics / debug logging improvements (beyond the current
  diagnostics sinks).
- History compaction informed by tool/result structure rather than raw message count.
- Consider a dual-layer memory model: compact working context + external full transcript.
