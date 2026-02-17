import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"

export const ExportAgentEnvPlugin: Plugin = async ({ client }) => {
  return {
    tool: {
      codescribe_export_env: tool({
        description:
          "Set OPENCODE_* env vars for a model/provider in process.env and emit shell-compatible exports",

        args: {
          model: tool.schema.string().optional()
            .describe("Model ID (agent frontmatter model:, or pass explicitly in TUI)"),
          provider: tool.schema.string().optional()
            .describe("Provider name (agent frontmatter provider:, or pass explicitly in TUI)")
        },

        async execute({ model, provider }, ctx) {
          // Resolve model/provider (args override, fallback to agent context)
          const resolvedModel = model ?? (ctx as any)?.model
          const resolvedProvider = provider ?? (ctx as any)?.provider

          if (!resolvedModel || !resolvedProvider) {
            return [
              "# ERROR: model/provider not available",
              "# Pass --model and --provider explicitly, or run inside an agent",
            ].join("\n")
          }

          // Load OpenCode config and extract providers
          const cfg = await client.config.get()
          const providers = cfg?.data?.provider ?? {}
          const providerNames = Object.keys(providers)

          // Validate provider exists
          if (!providers[resolvedProvider]) {
            return [
              `# ERROR: Provider '${resolvedProvider}' not found`,
              `# Available providers: ${providerNames.join(",") || "(none)"}`,
            ].join("\n")
          }

          const baseURL = providers[resolvedProvider]?.options?.baseURL
          const availableModels = Object.keys(cfg.data?.provider?.[resolvedProvider]?.models ?? {})

          // Validate model exists for this provider
          if (!availableModels.includes(resolvedModel)) {
            return [
              `# ERROR: Model '${resolvedModel}' not found for provider '${resolvedProvider}'`,
              `# Available models: ${availableModels.join(", ") || "(none)"}`,
            ].join("\n")
          }

          // Set environment variables for the current Node session
          process.env.OPENCODE_CODESCRIBE_MODEL = resolvedModel
          process.env.OPENCODE_CODESCRIBE_PROVIDER = resolvedProvider
          if (baseURL) {
            process.env.OPENCODE_CODESCRIBE_BASEURL = baseURL
          } else {
            delete process.env.OPENCODE_CODESCRIBE_BASEURL
          }

          // Emit shell-compatible exports (string output for TUI/subprocess)
          return [
            "# Environment variables set for current OpenCode session",
            `export OPENCODE_CODESCRIBE_MODEL=${process.env.OPENCODE_CODESCRIBE_MODEL}`,
            `export OPENCODE_CODESCRIBE_PROVIDER=${process.env.OPENCODE_CODESCRIBE_PROVIDER}`,
            baseURL ? `export OPENCODE_CODESCRIBE_BASEURL=${process.env.OPENCODE_CODESCRIBE_BASEURL}` : "# OPENCODE_BASEURL not set",
          ].join("\n")
        },
      }),
    },
  }
}
