import { tool } from "@opencode-ai/plugin"
import { readdirSync, statSync, existsSync, lstatSync } from "node:fs"
import { resolve, relative } from "node:path"

/**
 * Simple glob pattern matcher supporting only * wildcard.
 * Matches filename against pattern where * matches zero or more characters.
 */
function matchGlob(pattern: string, filename: string): boolean {
  // Escape regex special chars except *, then convert * to .*
  const regexStr = pattern
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')  // escape special regex chars
    .replace(/\*/g, '.*')                   // convert * to .*
  const regex = new RegExp(`^${regexStr}$`, 'i')  // case-insensitive for cross-platform
  return regex.test(filename)
}

/**
 * Validate that a path is within the root directory (no escape)
 */
function isWithinRoot(targetPath: string, root: string): boolean {
  const resolved = resolve(root, targetPath)
  const rel = relative(root, resolved)
  // If relative path starts with "..", it's outside root
  // An empty rel means it's the root itself (valid)
  return rel === "" || (!rel.startsWith("..") && !rel.startsWith("/"))
}

export default tool({
  name: "codescribe.shell",
  description: `Minimal filesystem operations: pwd, ls, path_info, glob.

Commands:
  - pwd: Returns the current working directory (repository root)
  - ls: Lists entries in a directory (non-recursive)
  - path_info: Check if a path exists and its type (file/dir/symlink)
  - glob: Match files in a directory using * wildcard patterns (single-directory only, no recursion)

This tool does NOT execute shell commands. It uses Node.js filesystem APIs only.
Glob is restricted to single-directory matching (no ** or path separators in pattern).`,

  args: {
    command: tool.schema.enum([
      "pwd",
      "ls",
      "path_info",
      "glob"
    ]).describe("The command to run"),
    path: tool.schema.string().optional().describe("Path for ls or path_info (default: '.' for ls)"),
    pattern: tool.schema.string().optional().describe("Glob pattern for glob command (e.g. '*.F90', 'Grid*.f90'). Only * wildcard supported."),
    cwd: tool.schema.string().optional().describe("Directory to search in for glob command (default: '.')"),
    max_matches: tool.schema.number().optional().describe("Maximum matches to return for glob (default: 2000)")
  },

  async execute({ command, path, pattern, cwd, max_matches }) {
    const root = process.cwd()

    if (command === "pwd") {
      return JSON.stringify({ cwd: root }, null, 2)
    }

    if (command === "glob") {
      if (!pattern) {
        return JSON.stringify({ error: "pattern parameter is required for glob command" }, null, 2)
      }

      // Reject patterns with path separators (no subdirectory traversal)
      if (pattern.includes("/") || pattern.includes("\\")) {
        return JSON.stringify({
          error: "Pattern cannot contain path separators. Use cwd to specify the directory.",
          pattern
        }, null, 2)
      }

      // Reject recursive patterns
      if (pattern.includes("**")) {
        return JSON.stringify({
          error: "Recursive patterns (**) are not supported. Only single-directory matching allowed.",
          pattern
        }, null, 2)
      }

      const targetDir = cwd || "."
      const resolvedDir = resolve(root, targetDir)
      const maxResults = max_matches || 2000

      if (!isWithinRoot(targetDir, root)) {
        return JSON.stringify({
          error: "Directory is outside repository root",
          cwd: targetDir
        }, null, 2)
      }

      if (!existsSync(resolvedDir)) {
        return JSON.stringify({
          error: "Directory does not exist",
          cwd: targetDir
        }, null, 2)
      }

      try {
        const stats = statSync(resolvedDir)
        if (!stats.isDirectory()) {
          return JSON.stringify({
            error: "Path is not a directory",
            cwd: targetDir
          }, null, 2)
        }

        const entries = readdirSync(resolvedDir, { withFileTypes: true })
        const matches: string[] = []
        let truncated = false

        for (const entry of entries) {
          if (matches.length >= maxResults) {
            truncated = true
            break
          }

          const fullPath = resolve(resolvedDir, entry.name)

          // Only match files (not directories or symlinks)
          try {
            const lstats = lstatSync(fullPath)
            if (!lstats.isFile()) continue
          } catch {
            continue
          }

          if (matchGlob(pattern, entry.name)) {
            // Return path relative to repo root for consistency
            const relativePath = targetDir === "." ? entry.name : `${targetDir}/${entry.name}`
            matches.push(relativePath)
          }
        }

        // Sort matches alphabetically
        matches.sort((a, b) => a.localeCompare(b))

        return JSON.stringify({
          cwd: targetDir,
          pattern,
          matches,
          count: matches.length,
          truncated
        }, null, 2)
      } catch (err) {
        return JSON.stringify({
          error: `Failed to glob directory: ${err}`,
          cwd: targetDir,
          pattern
        }, null, 2)
      }
    }

    if (command === "path_info") {
      if (!path) {
        return JSON.stringify({ error: "path parameter is required for path_info command" }, null, 2)
      }

      const resolvedPath = resolve(root, path)

      if (!isWithinRoot(path, root)) {
        return JSON.stringify({
          path,
          exists: false,
          kind: null,
          error: "Path is outside repository root"
        }, null, 2)
      }

      if (!existsSync(resolvedPath)) {
        return JSON.stringify({ path, exists: false, kind: null }, null, 2)
      }

      try {
        const lstats = lstatSync(resolvedPath)
        let kind: "file" | "dir" | "symlink" | "other" = "other"
        if (lstats.isSymbolicLink()) kind = "symlink"
        else if (lstats.isFile()) kind = "file"
        else if (lstats.isDirectory()) kind = "dir"

        return JSON.stringify({ path, exists: true, kind }, null, 2)
      } catch {
        return JSON.stringify({ path, exists: false, kind: null }, null, 2)
      }
    }

    if (command === "ls") {
      const targetPath = path || "."
      const resolvedPath = resolve(root, targetPath)

      if (!isWithinRoot(targetPath, root)) {
        return JSON.stringify({
          error: "Path is outside repository root",
          path: targetPath
        }, null, 2)
      }

      if (!existsSync(resolvedPath)) {
        return JSON.stringify({
          error: "Path does not exist",
          path: targetPath
        }, null, 2)
      }

      try {
        const stats = statSync(resolvedPath)
        if (!stats.isDirectory()) {
          return JSON.stringify({
            error: "Path is not a directory",
            path: targetPath
          }, null, 2)
        }

        const entries = readdirSync(resolvedPath, { withFileTypes: true })
        const items: Array<{ name: string; kind: "file" | "dir" | "symlink" | "other" }> = []

        for (const entry of entries) {
          const fullPath = resolve(resolvedPath, entry.name)
          let kind: "file" | "dir" | "symlink" | "other" = "other"

          try {
            const lstats = lstatSync(fullPath)
            if (lstats.isSymbolicLink()) kind = "symlink"
            else if (lstats.isFile()) kind = "file"
            else if (lstats.isDirectory()) kind = "dir"
          } catch {
            kind = "other"
          }

          items.push({ name: entry.name, kind })
        }

        // Sort entries: directories first, then files, alphabetically within each group
        items.sort((a, b) => {
          if (a.kind === "dir" && b.kind !== "dir") return -1
          if (a.kind !== "dir" && b.kind === "dir") return 1
          return a.name.localeCompare(b.name)
        })

        return JSON.stringify({
          path: targetPath,
          entries: items,
          count: items.length
        }, null, 2)
      } catch (err) {
        return JSON.stringify({
          error: `Failed to list directory: ${err}`,
          path: targetPath
        }, null, 2)
      }
    }

    return JSON.stringify({ error: `Unknown command: ${command}` }, null, 2)
  }
})
