import { tool } from "@opencode-ai/plugin"

/**
 * CodeScribe Model Resolver
 * 
 * Maps the agent's model ID to the corresponding CodeScribe CLI `-m` model name.
 * 
 * Rule:
 *   - If model_id contains "argo" -> codescribe_model = "argo-gpt4o"
 *   - Otherwise -> error (no fallback)
 */
export default tool({
  name: "codescribe.model",
  description: `Resolve the CodeScribe CLI model name from the agent's model ID.

Call this before any codescribe.codescribe command to get the correct -m flag value.

Args:
  - model_id: The agent's model ID string (from the agent's frontmatter model: field)

Returns JSON with:
  - ok: true/false
  - codescribe_model: The -m flag value (only if ok=true)
  - error_code: MODEL_ID_MISSING or MODEL_ID_NOT_ARGO (only if ok=false)
  - message: Human-readable explanation`,

  args: {
    model_id: tool.schema.string().optional().describe("The agent's model ID (e.g., 'argo_proxy/argo:gpt-5.2')")
  },

  async execute({ model_id }) {
    // Check if model_id is missing or empty
    if (!model_id || model_id.trim() === "") {
      return JSON.stringify({
        ok: false,
        error_code: "MODEL_ID_MISSING",
        model_id: null,
        codescribe_model: null,
        message: "No model_id provided. Pass the agent's model: field value from the frontmatter."
      }, null, 2)
    }

    const trimmedId = model_id.trim()

    // Check if model_id contains "argo"
    if (trimmedId.toLowerCase().includes("argo")) {
      return JSON.stringify({
        ok: true,
        model_id: trimmedId,
        codescribe_model: "argo-gpt4o",
        rule: "includes('argo') => argo-gpt4o"
      }, null, 2)
    }

    // No match, return error (no fallback)
    return JSON.stringify({
      ok: false,
      error_code: "MODEL_ID_NOT_ARGO",
      model_id: trimmedId,
      codescribe_model: null,
      message: `Model ID '${trimmedId}' does not contain 'argo'. Cannot determine CodeScribe model. Switch to an Argo model or update the mapping rules.`
    }, null, 2)
  }
})
