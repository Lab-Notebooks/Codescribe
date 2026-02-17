import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"

export const EnvModelPlugin: Plugin = async ({ client }) => {
  return {
    tool: {
      codescribe_env_model: tool({
        description:
          "List available models for a given provider. Returns model IDs that can be passed to codescribe_export_env.",

        args: {
          provider: tool.schema.string().optional()
            .describe("Provider name (from agent frontmatter or passed explicitly)")
        },

        async execute({ provider }, ctx) {
          // Resolve provider from arg or agent context
          const resolvedProvider = provider ?? (ctx as any)?.provider

          if (!resolvedProvider) {
            return [
              "# ERROR: provider not specified",
              "# Pass --provider explicitly, or set provider: in agent frontmatter",
            ].join("\n")
          }

          // Load OpenCode config
          const cfg = await client.config.get()
          const providers = cfg?.data?.provider ?? {}
          const providerNames = Object.keys(providers)

          // Validate provider exists
          if (!providers[resolvedProvider]) {
            return [
              `# ERROR: Provider '${resolvedProvider}' not found`,
              `# Available providers: ${providerNames.join(", ") || "(none)"}`,
            ].join("\n")
          }

          // Get models for this provider
          const availableModels = Object.keys(cfg.data?.provider?.[resolvedProvider]?.models ?? {})

          if (availableModels.length === 0) {
            return [
              `# Provider: ${resolvedProvider}`,
              "# No models configured for this provider",
            ].join("\n")
          }

          // Return structured list for agent consumption
          return [
            `# Provider: ${resolvedProvider}`,
            `# Models (${availableModels.length}):`,
            ...availableModels.map((m, i) => `${i + 1}. ${m}`),
          ].join("\n")
        },
      }),
    },
  }
}
