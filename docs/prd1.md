Below is a PRD for a **“Claude Code Context Manager”** that solves your exact issue: **multi-agent conversations blow up the context**, and Claude Code compaction (when it happens) can drop critical details. This PRD is designed to integrate with Claude Code via **Hooks + (optional) MCP memory server**, which are both native integration points in the Claude Code ecosystem. ([Claude Code][1])

---

## PRD: Claude Code Context Manager (CCCM)

### 1) Summary

Build a lightweight companion system for Claude Code that:

1. **Prevents context bloat** in long, multi-agent sessions
2. **Makes compaction safe** by creating high-fidelity summaries at the right times
3. **Persists durable “project memory”** (decisions, APIs, file changes, constraints) outside the chat
4. **Re-injects only relevant memory** back into Claude Code so agents stay sharp

Claude Code already has **context compaction (beta)** and recommends using **CLAUDE.md** for persistent rules, but the default behavior is not sufficient for multi-agent workflows. ([Anthropic][2])

---

## 2) Problem Statement

In multi-agent sessions, Claude Code’s context window fills with:

* repetitive agent planning + reasoning
* tool outputs
* file diffs
* duplicate architectural discussion

When compaction triggers, the summary may miss “precision” details (exact function signatures, why a decision was made, what was already tried). Users report this causes rework and degraded performance. ([GitHub][3])

---

## 3) Goals & Non-Goals

### Goals

* **G1:** Keep active context lean and high-signal during multi-agent operation.
* **G2:** Before compaction happens, generate a **structured “Continuity Packet”** that preserves: decisions, constraints, progress, and next actions.
* **G3:** Persist memory across sessions in a repo-local folder (`.cccm/`).
* **G4:** Integrate with Claude Code with minimal friction:

  * Install once
  * Works automatically per-project
  * Doesn’t require changing how you prompt day-to-day
* **G5:** Support team-of-agents: orchestrator + subagents, without duplicating context.

### Non-Goals

* N1: Replace Claude Code’s built-in compaction.
* N2: Act as a full task tracker (Jira replacement).
* N3: Store secrets; it must respect repo ignore + allow redaction.

---

## 4) Users & Use Cases

### Primary user

Power user running “team of agents” / orchestrated workflows inside Claude Code.

### Core user stories

* **US1:** As a user, I want an automatic snapshot of “what matters so far” before compaction so I never lose critical decisions.
* **US2:** As a user, I want agents to stop polluting context with long reasoning logs; I want only results + references.
* **US3:** As a user, I want persistent project memory (decisions, conventions, commands) injected when relevant.
* **US4:** As a user, I want easy integration with Claude Code via hooks and CLAUDE.md conventions. ([Claude Code][1])

---

## 5) Solution Overview

CCCM has **two integration modes**:

### Mode A (MVP): Hooks-only (fastest, simplest)

* Uses Claude Code **hooks** to:

  * monitor context utilization (via `/context` usage patterns and/or internal hook metadata)
  * trigger a structured summary at thresholds
  * write memory files into `.cccm/`

### Mode B (Full): Hooks + MCP Memory Server (best long-term)

* Same as Mode A, plus:

  * A local MCP server exposes a `memory.search` and `memory.write` tool to Claude Code
  * Claude can retrieve only relevant memory chunks during execution
  * Claude Code supports MCP servers and can be enabled via project settings (commonly via `.claude/settings.local.json`). ([Medium][4])

---

## 6) Key Concepts / Artifacts

### 6.1 Continuity Packet (the “gold” summary)

A structured, deterministic summary generated:

* **before compaction**
* **before agent handoffs**
* **before large refactors**
* **on user command**

Format (Markdown + small JSON header):

* Project goal (1–3 lines)
* Current state (what exists now)
* Key decisions (bulleted, with rationale)
* Constraints (performance, libraries, style rules)
* File change index (paths + what changed)
* Open problems (known issues + hypotheses)
* Next actions (ordered checklist)

This mirrors what people already do manually for compaction survival, but automated. ([Reddit][5])

### 6.2 Memory Store

Repo-local folder:

```
.cccm/
  memory/
    decisions.md
    constraints.md
    glossary.md
    interfaces.md
  snapshots/
    2026-02-19T13-40-xx_continuity.md
  index.json
```

### 6.3 Injection Pack

A compact payload CCCM re-injects into Claude Code (or makes available via MCP):

* the latest Continuity Packet
* the top N relevant memory chunks
* current task definition

---

## 7) Functional Requirements

### FR1: Context monitoring

* Must estimate “context fullness” and trigger actions at thresholds.
* Threshold defaults:

  * **Warn at 55%**
  * **Snapshot at 65%**
  * **Pre-compaction emergency snapshot at 72–77%** (Claude Code compaction commonly triggers around that region per community reports). ([Zenn][6])

### FR2: Automatic snapshot generation

When threshold hit, CCCM asks Claude (or a designated “Memory Manager” agent) to produce a Continuity Packet with strict schema and max size.

### FR3: Agent output compaction (anti-bloat)

CCCM enforces a rule: subagents must output:

* result
* justification (max ~10 lines)
* references (files/commands)
  No long chain-of-thought style logs.

Implementation: hook that rewrites/filters agent messages before they are appended to the main context (or instructs agent templates via CLAUDE.md).

### FR4: Persistent memory writing

* Save continuity snapshots and memory docs
* Maintain `index.json` with:

  * timestamp
  * tags (e.g., “auth”, “db”, “perf”)
  * files touched
  * embeddings optional (Mode B)

### FR5: Memory retrieval (Mode B)

Provide MCP tool endpoints:

* `memory.search(query, top_k, tags?)`
* `memory.write(doc_type, content, tags)`
* `memory.latest_snapshot()`

Claude uses these tools only when needed.

### FR6: Manual commands

User can run:

* `/cccm snapshot`
* `/cccm memory add`
* `/cccm memory search "..."`

(Exact command wiring depends on Claude Code command extensibility; if commands aren’t pluggable, provide a CLI `cccm` binary and document usage.)

---

## 8) Non-Functional Requirements

### NFR1: Easy install

* Single install script:

  * installs hooks under `~/.claude/hooks/` (or project-local equivalent)
  * adds repo `.gitignore` entries for `.cccm/` (except memory docs if desired)
  * creates a starter `CLAUDE.md`

### NFR2: Safe by default

* Never store secrets:

  * redact patterns (AWS keys, tokens, private keys)
  * allow `.cccm/redact.yml` config

### NFR3: Low latency

* Snapshot generation only on threshold, not every message.
* Mode B search should feel instant (cache + lightweight index).

---

## 9) Integration with Claude Code (What “easy” means)

### 9.1 CLAUDE.md bootstrap (required best practice)

Claude Code docs explicitly recommend putting persistent rules in `CLAUDE.md` because early instructions can get lost with compaction. ([Claude Code][1])

CCCM will generate a `CLAUDE.md` section like:

* “You are operating under CCCM memory constraints”
* “Never paste long reasoning; produce compact results”
* “When asked to summarize, follow Continuity Packet schema”
* “When context > X%, prioritize snapshot”

### 9.2 Hooks install (core integration)

Claude Code supports hooks (widely used by the community for memory triggers / context management). CCCM uses hooks to run on:

* message end
* tool completion
* context warning threshold
* before compaction event (if exposed; otherwise approximate via threshold monitoring)

(Community memory hook systems exist, proving the pathway is viable.) ([GitHub][7])

### 9.3 MCP enablement (Mode B)

Claude Code can start project MCP servers when enabled in settings (commonly `.claude/settings.local.json` with flags such as enabling project MCP servers). ([Medium][4])

CCCM will ship an MCP server that boots automatically per project.

---

## 10) System Architecture

### Components

1. **Hook Runner**

* Node or Python
* Runs on Claude Code hook events
* Maintains context fullness estimate
* Triggers snapshots

2. **Memory Engine**

* File-based storage (MVP)
* Optional SQLite/vec store (Mode B)
* Index builder

3. **MCP Server (optional)**

* Provides memory tools to Claude

4. **Prompt Templates**

* Continuity Packet prompt
* Agent response compression prompt
* “Decision capture” prompt

### Data flow (typical)

1. Agents produce output → Hook filters it to “result format”
2. Context rises → Hook triggers snapshot request
3. Snapshot saved to `.cccm/snapshots/...`
4. On next agent invocation, CCCM injects latest snapshot + relevant memory (or tool-based retrieval via MCP)

---

## 11) Prompt Schemas (Deterministic Contracts)

### Continuity Packet schema (must be followed)

* `Goal:`
* `Current State:`
* `Decisions (with rationale):`
* `Constraints:`
* `Files Changed:`
* `Open Issues / Risks:`
* `Next Actions (ordered):`

Hard cap: e.g. 600–900 tokens.

### Agent result schema (subagent output)

* `Result:`
* `Why:`
* `Refs:` (files/commands)
  Hard cap: e.g. 200–300 tokens.

This is the single biggest lever to stop context bloat.

---

## 12) Config & Customization

Repo config: `.cccm/config.yml`

* thresholds
* redact rules
* memory doc types enabled
* snapshot frequency
* tags auto-extraction rules (paths → tags)

User config: `~/.cccm/config.yml`

* global defaults across projects

---

## 13) MVP Scope (2–3 days build)

### MVP includes

* Hook-based threshold monitor
* Continuity Packet generator
* `.cccm/` file store + index
* CLAUDE.md bootstrap block
* Simple CLI `cccm snapshot`, `cccm show latest`

### MVP excludes

* MCP server
* embeddings / semantic search
* advanced UI

---

## 14) V1 Scope (Production)

Adds:

* MCP memory server
* semantic search (sqlite-vec or similar)
* automatic “decision capture” when detecting architecture choices
* per-agent budgeting (orchestrator vs subagents)
* “handoff packet” generation when switching tasks

---

## 15) Acceptance Criteria

* **AC1:** In a 2+ hour multi-agent session, context growth rate drops materially (fewer repeated discussions; subagent outputs compacted).
* **AC2:** When compaction occurs, the next response still “knows”:

  * current progress
  * key decisions
  * exact next steps
* **AC3:** Restarting Claude Code with only the latest snapshot + memory docs is enough to continue effectively.
* **AC4:** Install takes < 2 minutes and does not require modifying Claude Code itself.

---

## 16) Implementation Plan (Concrete)

### Phase 0: Repo scaffold

* `cccm/` (CLI + hooks + templates)
* `install.sh`:

  * copy hooks into Claude hook directory
  * add `CLAUDE.md` block if missing
  * add `.gitignore` entries

### Phase 1: Hook triggers + snapshot

* Hook reads context % (via available metadata; fallback: periodic `/context` parse)
* On threshold: invoke snapshot prompt
* Write `.cccm/snapshots/...` + update `.cccm/index.json`

### Phase 2: Agent output filter

* Hook wraps subagent outputs into the “Agent result schema”
* Optionally rejects overly-long outputs and requests rewrite

### Phase 3 (V1): MCP server

* Implement `memory.search/write/latest_snapshot`
* Enable project MCP servers in `.claude/settings.local.json` (documented)

---


[1]: https://code.claude.com/docs/en/how-claude-code-works?utm_source=chatgpt.com "How Claude Code works - Claude Code Docs"
[2]: https://www.anthropic.com/news/claude-opus-4-6?utm_source=chatgpt.com "Introducing Claude Opus 4.6"
[3]: https://github.com/anthropics/claude-code/issues/14160?utm_source=chatgpt.com "[FEATURE] Allow custom instructions for auto-compact via ..."
[4]: https://medium.com/%40brentwpeterson/adding-memory-to-claude-code-with-mcp-d515072aea8e?utm_source=chatgpt.com "Adding Memory to Claude Code with MCP"
[5]: https://www.reddit.com/r/ClaudeCode/comments/1pwxy0f/how_do_you_handle_autocompact_in_claude_code/?utm_source=chatgpt.com "How do you handle auto-compact in Claude Code?"
[6]: https://zenn.dev/trust_delta/articles/claude-code-context-warning-001?locale=en&utm_source=chatgpt.com "Preventing Automatic Compacting in Claude Code"
[7]: https://github.com/doobidoo/mcp-memory-service/wiki/Memory-Hooks-Complete-Guide?utm_source=chatgpt.com "Memory Hooks & Natural Triggers - Complete Guide"

