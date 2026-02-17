import { tool } from "@opencode-ai/plugin"
import { spawnSync } from "node:child_process"

/**
 * CodeScribe CLI Tool
 * 
 * Wraps the code-scribe CLI for Fortran-to-C++ translation workflows.
 * 
 * Commands:
 *   - index <directory>: Index Fortran files, create scribe.yaml
 *   - draft <file>: Generate draft .scribe file with C++ annotations
 *   - translate <file> -p <prompt.toml> -m <model>: Translate Fortran to C++
 *   - inspect <files> -q "<query>" -m <model>: Query/analyze source files
 *   - update <files> -p <prompt.toml> -q "<query>" [-r <ref>...] -m <model>: Update existing files
 *   - generate <prompt> [-r <ref>...] -m <model>: Generate new code
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
 * 
 * Models available via Argo:
 *   - argo-gpt4o
 *   - argo-gpt5mini
 */

export default tool({
  name: "codescribe.codescribe",
  description: `Run CodeScribe CLI commands for Fortran-to-C++ translation.

Commands:
  - index <directory>: Index Fortran project, creates scribe.yaml
  - draft <file>: Generate draft .scribe file (single Fortran file)
  - translate <file> -p <prompt.toml> -m <model>: Translate Fortran to C++ (Fortran files only, no -r)
  - inspect <files> -q "<query>" -m <model>: Analyze source files
  - update <files> [-p <prompt.toml>] [-q "<query>"] [-r <ref>...] -m <model>: Modify existing files (requires -p and/or -q)
  - generate <prompt> [-r <ref>...] -m <model>: Generate new code (prompt is TOML path or string)
  - format <files>: Format TOML prompt files

Example: codescribe translate src/Solver.F90 -p prompts/code_translation.toml -m argo-gpt4o`,

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
    cwd: tool.schema.string().optional().describe("Working directory (defaults to current directory)")
  },

  async execute({ command, args, cwd }) {

    const startTime = Date.now()
    
    const proc = spawnSync(
      "code-scribe",
      [command, ...args],
      {
        cwd,
        encoding: "utf-8",
        timeout: 300000, // 5 minute timeout for long translations
        maxBuffer: 10 * 1024 * 1024 // 10MB buffer for large outputs
      }
    )

    const duration = ((Date.now() - startTime) / 1000).toFixed(2)
    const success = proc.status === 0

    // Build structured output
    const output: string[] = [
      `## CodeScribe ${command}`,
      ``,
      `**Status:** ${success ? "Success" : "Failed"}`,
      `**Exit Code:** ${proc.status}`,
      `**Duration:** ${duration}s`,
      ``
    ]

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
  }
})
