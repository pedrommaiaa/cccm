# CCCM — Claude Code Context Manager

This project builds a context management companion for Claude Code that prevents
context window blowout in multi-agent sessions.

## Compact Instructions

When compacting context, you MUST preserve:
- The user's current objective and any constraints they stated
- The latest CCCM Continuity Packet (from `.cccm/snapshots/`)
- All decisions and rationale from `.cccm/memory/decisions.md`
- All constraints from `.cccm/memory/constraints.md`
- All interface contracts from `.cccm/memory/interfaces.md`
- The list of recently touched files and pending next actions

Keep the compacted summary actionable and specific — include file paths, function
signatures, and concrete TODOs. Never reduce to vague summaries.

## Context Management Protocol

You are operating with CCCM external memory.

Rules:
1. Keep outputs high-signal. No verbose reasoning chains.
2. Subagents MUST return structured output only:
   - `RESULT:` — what was done or decided
   - `WHY:` — rationale (max 8 lines)
   - `REFS:` — files, commands, or links
3. Project memory lives in `.cccm/memory/*.md` — treat as authoritative.
4. When context is tight, rely on the Continuity Packet over re-reading files.
5. When asked to summarize, follow the Continuity Packet schema below.

## Continuity Packet Schema

```
GOAL: (1-3 lines — current objective)
CURRENT STATE: (what exists now, key progress)
DECISIONS: (bulleted, with rationale)
CONSTRAINTS: (performance, libraries, style rules)
FILES CHANGED: (paths + what changed)
OPEN ISSUES: (known problems + hypotheses)
NEXT ACTIONS: (ordered checklist)
```

Hard cap: 800 tokens equivalent.

## MCP Memory Tools

CCCM exposes 4 MCP tools via the `cccm-memory` server:
- `memory_search(query, top_k)` — keyword search across memory docs and snapshots
- `memory_write(doc_type, content)` — append to a memory doc (decisions/constraints/interfaces/glossary)
- `memory_latest()` — get the latest continuity snapshot
- `memory_status()` — show system status (tracked files, events, last snapshot)

Use these tools when you need to persist or retrieve project knowledge.

## Project Structure

- `src/cccm/` — main Python package
  - `core/` — snapshot engine, memory store, search, decision capture
  - `hooks/` — Claude Code hook handlers (6 events)
  - `cli.py` — CLI entry point
  - `mcp_server.py` — MCP memory server (FastMCP)
- `.cccm/` — project-local memory and snapshots
  - `memory/` — persistent knowledge (decisions, constraints, interfaces, glossary)
  - `snapshots/` — continuity packets (auto-generated)
  - `config.json` — CCCM configuration
  - `index.json` — runtime index (recent files, events)
- `.claude/settings.json` — hook registrations (6 hooks)
- `.claude/settings.local.json` — MCP server config
- `tests/` — pytest test suite (99 tests)

## Hook Events

| Hook | Purpose |
|------|---------|
| SessionStart | Inject memory after compaction/resume |
| PreCompact | Snapshot + preservation guidance |
| PostToolUse | Track file changes silently |
| SubagentStart | Per-agent-type brevity rules + memory injection |
| UserPromptSubmit | Inject relevant memory when prompt matches |
| Stop | Auto-capture decisions from assistant responses |

## Tech Stack

- Python 3.10+
- MCP SDK (mcp) for the memory server
- Hatchling for packaging
- pytest + ruff for dev tooling
