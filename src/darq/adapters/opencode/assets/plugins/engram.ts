/**
 * Engram — OpenCode plugin adapter
 *
 * Thin layer that connects OpenCode's event system to the Engram Go binary.
 * The Go binary runs as a local HTTP server and handles all persistence.
 *
 * Flow:
 *   OpenCode events → this plugin → HTTP calls → engram serve → SQLite
 *
 * Session resilience:
 *   Uses `ensureSession()` before any DB write. This means sessions are
 *   created on-demand — even if the plugin was loaded after the session
 *   started (restart, reconnect, etc.). The session ID comes from OpenCode's
 *   hooks (input.sessionID) rather than relying on a session.created event.
 *
 * No protocol text: this plugin never touches the system prompt. What an agent
 * must do with memory (who writes, when to save) lives in the shared engram
 * block installed with the instructions, which every session reads, sub-agents
 * included. That block also says a launched agent's `## Key Learnings` items
 * are saved automatically — this plugin's passive capture of `task` output.
 */

import type { Plugin } from "@opencode-ai/plugin"

// ─── Configuration ───────────────────────────────────────────────────────────

const ENGRAM_PORT = parseInt(process.env.ENGRAM_PORT ?? "7437")
const ENGRAM_URL = `http://127.0.0.1:${ENGRAM_PORT}`
const ENGRAM_BIN = process.env.ENGRAM_BIN ?? Bun.which("engram") ?? "engram"

// Engram's own MCP tools — don't count these as "tool calls" for session stats.
// OpenCode 1.x reports an MCP tool as `<server key>_<tool>`, so the real ids
// are `engram_mem_*` (9338 `engram_mem_save` rows, 0 `mem_save`, in a live
// install's DB). The bare names are kept for a different server key; see
// `isEngramTool`, which also strips a leading `engram_`.
const ENGRAM_TOOLS = new Set([
  "mem_search",
  "mem_save",
  "mem_update",
  "mem_delete",
  "mem_suggest_topic_key",
  "mem_save_prompt",
  "mem_session_summary",
  "mem_context",
  "mem_stats",
  "mem_timeline",
  "mem_get_observation",
  "mem_session_start",
  "mem_session_end",
])

function isEngramTool(tool: string): boolean {
  const id = tool.toLowerCase()
  return ENGRAM_TOOLS.has(id) || ENGRAM_TOOLS.has(id.replace(/^engram_/, ""))
}

// ─── HTTP Client ─────────────────────────────────────────────────────────────

async function engramFetch(
  path: string,
  opts: { method?: string; body?: any } = {}
): Promise<any> {
  try {
    const res = await fetch(`${ENGRAM_URL}${path}`, {
      method: opts.method ?? "GET",
      headers: opts.body ? { "Content-Type": "application/json" } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      // The engram server is local: never route prompts through a proxy named
      // in HTTP_PROXY/ALL_PROXY (Bun's per-request opt-out).
      proxy: false,
    } as RequestInit)
    return await res.json()
  } catch {
    // Engram server not running — silently fail
    return null
  }
}

async function isEngramRunning(): Promise<boolean> {
  try {
    const res = await fetch(`${ENGRAM_URL}/health`, {
      signal: AbortSignal.timeout(500),
      proxy: false,
    } as RequestInit)
    return res.ok
  } catch {
    return false
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function extractProjectName(directory: string): string {
  // Try git remote origin URL
  try {
    const result = Bun.spawnSync(["git", "-C", directory, "remote", "get-url", "origin"])
    if (result.exitCode === 0) {
      const url = result.stdout?.toString().trim()
      if (url) {
        const name = url.replace(/\.git$/, "").split(/[/:]/).pop()
        if (name) return name
      }
    }
  } catch {}

  // Fallback: git root directory name (works in worktrees)
  try {
    const result = Bun.spawnSync(["git", "-C", directory, "rev-parse", "--show-toplevel"])
    if (result.exitCode === 0) {
      const root = result.stdout?.toString().trim()
      if (root) return root.split("/").pop() ?? "unknown"
    }
  } catch {}

  // Final fallback: cwd basename
  return directory.split("/").pop() ?? "unknown"
}

function truncate(str: string, max: number): string {
  if (!str) return ""
  return str.length > max ? str.slice(0, max) + "..." : str
}

/**
 * Strip <private>...</private> tags before sending to engram.
 * Double safety: the Go binary also strips, but we strip here too
 * so sensitive data never even hits the wire.
 */
function stripPrivateTags(str: string): string {
  if (!str) return ""
  // Linear scan equal to /<private>[\s\S]*?<\/private>/gi: the regex rescans to
  // the end of the text for every unclosed open tag (quadratic).
  const open = /<private>/gi
  const close = /<\/private>/gi
  let out = ""
  let pos = 0
  while (true) {
    open.lastIndex = pos
    const start = open.exec(str)
    if (!start) break
    close.lastIndex = start.index + start[0].length
    const end = close.exec(str)
    if (!end) break
    out += str.slice(pos, start.index) + "[REDACTED]"
    pos = end.index + end[0].length
  }
  return (out + str.slice(pos)).trim()
}

/**
 * The detection pass of the secret transport skips text above its byte cap
 * (256 KiB, catalog `max_detect_bytes`), so redaction would fail open. This
 * plugin never sends such text: a prompt is cut to the cap first (only its
 * first 2000 characters are kept anyway), a passive capture is not sent.
 */
const DETECT_CAP_BYTES = 262144

function cutToDetectCap(str: string): string {
  if (Buffer.byteLength(str, "utf8") <= DETECT_CAP_BYTES) return str
  const buf = Buffer.from(str, "utf8")
  // Cut on a character boundary: a cut inside a multibyte character decodes to
  // U+FFFD (3 bytes), which would push the result above the cap again and make
  // the detection pass skip it. Step back while the byte at the cut is a
  // continuation byte, so the cut falls before the character it would split.
  let end = DETECT_CAP_BYTES
  while (end > 0 && (buf[end] & 0xc0) === 0x80) end--
  return buf.subarray(0, end).toString("utf8")
}

/**
 * Credential transport (7.3.0): before any POST to `/prompts` or
 * `/observations/passive`, call the secret-transport plugin's process-wide
 * redaction function, if it is present, in addition to `stripPrivateTags`
 * above. The two plugins' load order is not guaranteed (see
 * `arquitectura.md`'s 7.3.0 section), so this never assumes the global is
 * there: when it is, it replaces every credential value this process has
 * already registered (and detects anything new by the same catalog); when
 * it is not (the capability is not installed, or this plugin loaded first
 * and the other has not run yet for this value), this is a no-op and
 * `stripPrivateTags` remains the only defense, exactly as it was before.
 */
function redactCredentials(str: string): string {
  if (!str) return str
  const transport = (globalThis as any).__CREDENTIAL_TRANSPORT_V1__
  if (transport && typeof transport.redact === "function") {
    try {
      return transport.redact(str)
    } catch {
      return str
    }
  }
  return str
}

// ─── Plugin Export ───────────────────────────────────────────────────────────

export const Engram: Plugin = async (ctx) => {
  const oldProject = ctx.directory.split("/").pop() ?? "unknown"
  const project = extractProjectName(ctx.directory)

  // Track which sessions we've already ensured exist in engram
  const knownSessions = new Set<string>()

  // Track sub-agent session IDs so we can suppress their tool-hook registrations.
  // Sub-agents (Task() calls) have a parentID or a title ending in " subagent)".
  // We must not register them as top-level Engram sessions — they cause session
  // inflation (e.g. 170 sessions for 1 real conversation, issue #116).
  const subAgentSessions = new Set<string>()

  /**
   * Ensure a session exists in engram. Idempotent — calls POST /sessions
   * which uses INSERT OR IGNORE. Safe to call multiple times.
   *
   * Silently skips sub-agent sessions (tracked in `subAgentSessions`).
   */
  async function ensureSession(sessionId: string): Promise<void> {
    if (!sessionId || knownSessions.has(sessionId)) return
    // Do not register sub-agent sessions in Engram (issue #116).
    if (subAgentSessions.has(sessionId)) return
    knownSessions.add(sessionId)
    await engramFetch("/sessions", {
      method: "POST",
      body: {
        id: sessionId,
        project,
        directory: ctx.directory,
      },
    })
  }

  // Try to start engram server if not running
  const running = await isEngramRunning()
  if (!running) {
    try {
      Bun.spawn([ENGRAM_BIN, "serve"], {
        stdout: "ignore",
        stderr: "ignore",
        stdin: "ignore",
      })
      await new Promise((r) => setTimeout(r, 500))
    } catch {
      // Binary not found or can't start — plugin will silently no-op
    }
  }

  // Migrate project name if it changed (one-time, idempotent)
  // Must run AFTER server startup to ensure the endpoint is available
  if (oldProject !== project) {
    await engramFetch("/projects/migrate", {
      method: "POST",
      body: { old_project: oldProject, new_project: project },
    })
  }

  // Auto-import: if .engram/manifest.json exists in the project repo,
  // run `engram sync --import` to load any new chunks into the local DB.
  // This is how git-synced memories get loaded when cloning a repo or
  // pulling changes. Each chunk is imported only once (tracked by ID).
  try {
    const manifestFile = `${ctx.directory}/.engram/manifest.json`
    const file = Bun.file(manifestFile)
    if (await file.exists()) {
      Bun.spawn([ENGRAM_BIN, "sync", "--import"], {
        cwd: ctx.directory,
        stdout: "ignore",
        stderr: "ignore",
        stdin: "ignore",
      })
    }
  } catch {
    // Manifest doesn't exist or binary not found — silently skip
  }

  return {
    // ─── Event Listeners ───────────────────────────────────────────

    event: async ({ event }) => {
      // --- Session Created ---
      if (event.type === "session.created") {
        // Bug fix (#116): session data is nested under event.properties.info,
        // not event.properties directly.
        const info = (event.properties as any)?.info
        const sessionId = info?.id
        const parentID = info?.parentID
        const title: string = info?.title ?? ""

        // Sub-agent sessions (created via Task()) must NOT be registered as
        // top-level Engram sessions. They cause massive session inflation
        // (e.g. 170 sessions for 1 real conversation).
        //
        // Detection heuristics:
        //   - parentID is set on all Task() sub-agent sessions
        //   - title ends with " subagent)" as a secondary signal
        const isSubAgent = !!parentID || title.endsWith(" subagent)")

        if (sessionId && !isSubAgent) {
          await ensureSession(sessionId)
        } else if (sessionId && isSubAgent) {
          // Remember this as a sub-agent session so tool-hook calls
          // to ensureSession() are also suppressed for it.
          subAgentSessions.add(sessionId)
        }
      }

      // --- Session Deleted ---
      if (event.type === "session.deleted") {
        // Same properties.info path as session.created.
        const info = (event.properties as any)?.info
        const sessionId = info?.id
        if (sessionId) {
          knownSessions.delete(sessionId)
          subAgentSessions.delete(sessionId)
        }
      }

    },

    // ─── User Prompt Capture ──────────────────────────────────────
    // chat.message is called once per user message, before the LLM sees it.
    // input.sessionID is always reliable here (no knownSessions workaround).
    // output.message is typed as UserMessage (role:"user" already guaranteed).
    // output.parts contains TextPart[] with the actual message text.

    "chat.message": async (input, output) => {
      // Skip sub-agent sessions — they inflate session counts (issue #116)
      if (subAgentSessions.has(input.sessionID)) return

      const sessionId = input.sessionID

      // Extract text from parts (type:"text")
      const content = output.parts
        .filter((p) => p.type === "text")
        .map((p) => (p as any).text ?? "")
        .join("\n")
        .trim()

      // Also fallback to summary if parts yield nothing
      const fallback = !content && output.message.summary
        ? `${output.message.summary.title ?? ""}\n${output.message.summary.body ?? ""}`.trim()
        : ""

      const finalContent = content || fallback

      // Only capture non-trivial prompts (>10 chars)
      if (finalContent.length > 10) {
        await ensureSession(sessionId)
        await engramFetch("/prompts", {
          method: "POST",
          body: {
            session_id: sessionId,
            content: truncate(stripPrivateTags(redactCredentials(cutToDetectCap(finalContent))), 2000),
            project,
          },
        })
      }
    },

    // ─── Tool Execution Hook ─────────────────────────────────────
    // Count tool calls per session (for session end stats).
    // Also ensures the session exists — handles plugin reload / reconnect.
    // Passive capture: when a Task tool completes, POST its output to
    // the passive capture endpoint so the server extracts learnings.

    "tool.execute.after": async (input, output) => {
      if (isEngramTool(input.tool)) return

      // input.sessionID comes from OpenCode — always available
      const sessionId = input.sessionID
      if (sessionId) {
        await ensureSession(sessionId)
      }

      // Passive capture: extract learnings from a sub-agent's output.
      //
      // The tool id is checked case-insensitively, and against every id a
      // sub-agent has been observed or reported to carry. OpenCode records
      // this tool as lowercase `task` (5171/5171 rows in a live install's
      // DB), not the capitalized `Task` this check was copied from — that
      // name came from Claude Code's own tool naming and never fired here.
      // `subagent` is an unverified, reported future rename; kept so this
      // does not go dark again if OpenCode renames the tool.
      //
      // We send `output.output` — the tool's own text, not a JSON dump of
      // the hook's output object. Engram's extractor (`ExtractLearnings` in
      // engram v1.20.0) matches headings and list items at real line
      // starts (`(?m)^#{2,3}\s+...`); `JSON.stringify` escapes newlines to
      // `\n`, so a `## Key Learnings` heading would never match a line
      // start and nothing would ever be captured.
      //
      // The extractor itself is the gate: it stores nothing unless the
      // text has a `## Key Learnings` section — engram's heading pattern is
      // anchored to two or three `#` (`^#{2,3}`), never one — which a
      // sub-agent writes only when its own brief asked for one — this hook
      // makes no decision about what to save, it only ships the text.
      const subAgentToolIds = new Set(["task", "subagent"])
      // Do not post the passive capture when the session that ran this
      // sub-agent tool is itself a sub-agent session. A sub-agent never
      // launches its own sub-agents with a `## Key Learnings` request —
      // that criterion belongs to the agent talking with the person — so
      // whatever a sub-sub-agent found reaches memory through the
      // intermediate agent's own `## Key Learnings` section, captured when
      // the intermediate agent's tool call completes under the root
      // session. Posting here too used to just hand engram a session id it
      // does not recognise (a sub-agent session is never registered with
      // engram), which engram rejected and `engramFetch` silently swallowed.
      if (
        subAgentToolIds.has(input.tool.toLowerCase()) &&
        output &&
        sessionId &&
        !subAgentSessions.has(sessionId)
      ) {
        const text = output.output ?? ""
        if (text.length > 50 && Buffer.byteLength(text, "utf8") <= DETECT_CAP_BYTES) {
          await engramFetch("/observations/passive", {
            method: "POST",
            body: {
              session_id: sessionId,
              content: stripPrivateTags(redactCredentials(text)),
              project,
              source: "task-complete",
            },
          })
        }
      }
    },

    // ─── Compaction Hook: Persist memory + inject context ──────────
    // Compaction is triggered by the system (not the agent) when context
    // gets too long. The old agent "dies" and a new one starts with the
    // compacted summary. This is our chance to:
    // 1. Auto-save a session checkpoint (the agent can't do this itself)
    // 2. Inject context from previous sessions into the compaction prompt
    // 3. Tell the compressor to remind the new agent to save memories

    "experimental.session.compacting": async (input, output) => {
      // Subagent sessions do not write memory; the "FIRST ACTION REQUIRED"
      // nudge below is for the root session only. Returning early here keeps
      // a subagent from being told to call mem_session_summary on
      // compaction, which its brief never asked for.
      if (input.sessionID && subAgentSessions.has(input.sessionID)) return

      if (input.sessionID) {
        await ensureSession(input.sessionID)
      }

      // Inject context from previous sessions
      const data = await engramFetch(
        `/context?project=${encodeURIComponent(project)}`
      )
      if (data?.context) {
        output.context.push(data.context)
      }

      // Tell the compressor to instruct the new agent to persist the
      // compacted summary to Engram. The new agent reads the compacted
      // summary and this instruction, then saves it as a session summary.
      output.context.push(
        `CRITICAL INSTRUCTION FOR COMPACTED SUMMARY:\n` +
        `The agent has access to Engram persistent memory via MCP tools.\n` +
        `You MUST include the following instruction at the TOP of the compacted summary:\n\n` +
        `"FIRST ACTION REQUIRED: Call mem_session_summary with the content of this compacted summary. ` +
        `Use project: '${project}'. This preserves what was accomplished before compaction. Do this BEFORE any other work."\n\n` +
        `This is NOT optional. Without this, everything done before compaction is lost from memory.`
      )
    },
  }
}
