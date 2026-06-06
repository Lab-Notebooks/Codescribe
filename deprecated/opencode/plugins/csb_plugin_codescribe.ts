import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"
import { spawnSync } from "node:child_process"

export const EnvModelPlugin: Plugin = async ({ client }) => {
  return {
    tool: {
      csb_tool_env_model: tool({
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
            `# Models (${availableModels.length}):`,
            ...availableModels.map((m, i) => `${i + 1}. ${m}`),
          ].join("\n")
        },
      }),
    },
  }
}

export const ProviderModelPlugin: Plugin = async ({ client }) => {
  return {
    tool: {
      csb_tool_env_provider: tool({
        description:
          "Select a provider and return the chosen provider ID.",

        args: {},

        async execute({}, ctx) {
          // 1. Load OpenCode config
          const cfg = await client.config.get()
          const providers = cfg?.data?.provider ?? {}
          const providerNames = Object.keys(providers)

          if (providerNames.length === 0) {
            throw new Error("No providers configured")
          }

          // Return structured list for agent consumption
          return [
            `# Providers (${providerNames.length}):`,
            ...providerNames.map((m, i) => `${i + 1}. ${m}`),
          ].join("\n")
        },
      }),
    },
  }
}

/**
 * CodeScribe CLI Tool
 *
 * Sets OPENCODE_CODESCRIBE_* env vars (if model/provider available),
 * then runs the code-scribe CLI for Fortran-to-C++ translation workflows.
 *
 * Commands:
 *   - index <directory>: Index Fortran files, create scribe.yaml
 *   - draft <file>: Generate draft .scribe file with C++ annotations
 *   - translate <file> -p <prompt.toml>: Translate Fortran to C++ (always uses -m oaic-env)
 *   - inspect <files> -q "<query>": Query/analyze source files (always uses -m oaic-env)
 *   - update <files> -p <prompt.toml> -q "<query>" [-r <ref>...]: Update existing files (always uses -m oaic-env)
 *   - generate <prompt> [-r <ref>...]: Generate new code (always uses -m oaic-env)
 *   - format <files>: Format TOML prompt files
 *
 * Command-specific rules:
 *   - translate: requires -p <prompt.toml>, NO -r allowed, Fortran files only
 *   - update: requires at least one of -p <prompt.toml> or -q "<query>", optional -r <ref> (repeatable)
 *   - generate: prompt is positional (TOML path or string), optional -r <ref> (repeatable)
 *   - draft: single Fortran file only
 *   - inspect: requires -q "<query>"
 *   - index: single directory argument
 *   - format: TOML file(s)
 */
export const CodescribePlugin: Plugin = async ({ client }) => {
  return {
    tool: {
      csb_tool_codescribe: tool({
        description: `Run CodeScribe CLI commands for Fortran-to-C++ translation.

Optionally sets OPENCODE_CODESCRIBE_* env vars (model/provider/baseURL) before running the CLI.

Commands:
  - index <directory>: Index Fortran project, creates scribe.yaml
  - draft <file>: Generate draft .scribe file (single Fortran file)
  - translate <file> -p <prompt.toml>: Translate Fortran to C++ (Fortran files only, no -r; always uses -m oaic-env)
  - inspect <files> -q "<query>": Analyze source files (always uses -m oaic-env)
  - update <files> [-p <prompt.toml>] [-q "<query>"] [-r <ref>...]: Modify existing files (requires -p and/or -q; always uses -m oaic-env)
  - generate <prompt> [-r <ref>...]: Generate new code (prompt is TOML path or string; always uses -m oaic-env)
  - format <files>: Format TOML prompt files

Note: The -m/--model CLI option is always set to "oaic-env" for commands that require it. Any user-provided -m/--model is ignored.

Example: codescribe translate src/Solver.F90 -p prompts/code_translation.toml`,

        args: {
          command: tool.schema.enum([
            "index",
            "inspect",
            "draft",
            "generate",
            "translate",
            "format",
            "update"
          ]).describe("The CodeScribe command to run"),
          args: tool.schema.array(tool.schema.string()).default([]).describe("Arguments to pass to the command (files, flags, etc.)"),
          cwd: tool.schema.string().optional().describe("Working directory (defaults to current directory)"),
          model: tool.schema.string().optional().describe("Model ID (from agent frontmatter or passed explicitly)"),
          provider: tool.schema.string().optional().describe("Provider name (from agent frontmatter or passed explicitly)")
        },

        async execute({ command, args, cwd, model, provider }, ctx) {
          const output: string[] = []

          // Commands that require explicit provider + model args
          const requiresProviderModel = new Set(["inspect", "generate", "update", "translate"])
          const needsEnv = requiresProviderModel.has(command)

          // Enforced CLI model for commands that need it
          const FORCED_CLI_MODEL = "oaic-env"

          // Helper to strip any user-supplied -m/--model from args
          function stripModelArgs(argv: string[]): string[] {
            const out: string[] = []
            for (let i = 0; i < argv.length; i++) {
              const a = argv[i]

              // --model=<value>
              if (a.startsWith("--model=")) {
                continue
              }

              // --model <value>
              if (a === "--model") {
                // skip the value if present
                if (i + 1 < argv.length) i++
                continue
              }

              // -m <value>
              if (a === "-m") {
                // skip the value if present
                if (i + 1 < argv.length) i++
                continue
              }

              out.push(a)
            }
            return out
          }

          // Use only explicit args (no ctx/frontmatter fallback)
          const resolvedModel = model
          const resolvedProvider = provider

          let envSet = false
          let baseURL: string | undefined

          if (needsEnv) {
            // Hard-check: both provider and model are required
            if (!resolvedProvider || !resolvedModel) {
              const missing: string[] = []
              if (!resolvedProvider) missing.push("provider")
              if (!resolvedModel) missing.push("model")
              return [
                `## CodeScribe ${command}`,
                ``,
                `**Status:** Failed (missing required args)`,
                ``,
                `### Error`,
                `The \`${command}\` command requires both \`provider\` and \`model\` to be specified.`,
                `Missing: ${missing.join(", ")}`,
                ``,
                `Pass them explicitly when calling this tool.`,
              ].join("\n")
            }

            // Load OpenCode config and extract providers
            const cfg = await client.config.get()
            const providers = cfg?.data?.provider ?? {}
            const providerNames = Object.keys(providers)

            // Validate provider exists
            if (!providers[resolvedProvider]) {
              return [
                `## CodeScribe ${command}`,
                ``,
                `**Status:** Failed (config error)`,
                ``,
                `### Error`,
                `Provider \'${resolvedProvider}\' not found.`,
                `Available providers: ${providerNames.join(", ") || "(none)"}`,
              ].join("\n")
            }

            baseURL = providers[resolvedProvider]?.options?.baseURL
            const availableModels = Object.keys(cfg.data?.provider?.[resolvedProvider]?.models ?? {})

            // Validate model exists for this provider
            if (!availableModels.includes(resolvedModel)) {
              return [
                `## CodeScribe ${command}`,
                ``,
                `**Status:** Failed (config error)`,
                ``,
                `### Error`,
                `Model \'${resolvedModel}\' not found for provider \'${resolvedProvider}\'.`,
                `Available models: ${availableModels.join(", ") || "(none)"}`,
              ].join("\n")
            }

            // Set environment variables for the current Node session
            process.env.OPENAI_COMP_MODEL = resolvedModel
            process.env.OPENAI_COMP_PROVIDER = resolvedProvider
            if (baseURL) {
              process.env.OPENAI_COMP_BASEURL = baseURL
            } else {
              delete process.env.OPENAI_COMP_BASEURL
            }
            envSet = true
          }

          // Run the CLI
          const startTime = Date.now()

          // Normalize args: strip any user-provided -m/--model and enforce -m oaic-env
          const requiresCliModel = requiresProviderModel.has(command)
          const normalizedArgs = requiresCliModel ? stripModelArgs(args) : args
          const cliArgs = requiresCliModel
            ? [command, ...normalizedArgs, "-m", FORCED_CLI_MODEL]
            : [command, ...normalizedArgs]

          const proc = spawnSync(
            "code-scribe",
            cliArgs,
            {
              cwd,
              encoding: "utf-8",
              timeout: 300000, // 5 minute timeout for long translations
              maxBuffer: 10 * 1024 * 1024, // 10MB buffer for large outputs
              env: { ...process.env } // Ensure child inherits updated env vars
            }
          )

          const duration = ((Date.now() - startTime) / 1000).toFixed(2)
          const success = proc.status === 0

          // Build structured output
          output.push(
            `## CodeScribe ${command}`,
            ``,
            `**Status:** ${success ? "Success" : "Failed"}`,
            `**Exit Code:** ${proc.status}`,
            `**Duration:** ${duration}s`,
            ``
          )

          // Env info
          if (envSet) {
            const envLine = baseURL
              ? `**Env:** model=\`${resolvedModel}\` provider=\`${resolvedProvider}\` baseURL=\`${baseURL}\``
              : `**Env:** model=\`${resolvedModel}\` provider=\`${resolvedProvider}\``
            output.push(envLine, ``)
          } else if (!needsEnv) {
            output.push(`**Env:** not required for this command`, ``)
          }

          if (proc.stdout?.trim()) {
            output.push(`### Output`, `\`\`\``, proc.stdout.trim(), `\`\`\``, ``)
          }

          if (proc.stderr?.trim()) {
            output.push(`### ${success ? "Warnings" : "Errors"}`, `\`\`\``, proc.stderr.trim(), `\`\`\``, ``)
          }

          // For translate command, list generated files
          if (command === "translate" && success) {
            output.push(
              `### Generated Files`,
              `The following files should have been created:`,
              `- \`<name>.cpp\` - C++ source`,
              `- \`<name>.hpp\` - C++ header`,
              `- \`<name>_fi.F90\` - Fortran interface`,
              ``
            )
          }

          return output.join("\n")
        },
      }),
    },
  }
}
