Good. On macOS with the **Claude Code CLI**, we can integrate extremely cleanly using **project hooks + CLAUDE.md + optional MCP server**. Below is the **macOS-specific PRD + exact file layout + install flow** optimized for your multi-agent Jarvis-style workflows.

This is designed to feel native to Claude Code — no hacks, no patching Claude itself.

---

# PRD: Claude Code Context Manager (CCCM) — macOS CLI Edition

## 1. Objective

Create a local companion system that integrates with Claude Code CLI on macOS to:

* prevent context explosion
* preserve continuity across compaction
* support multi-agent orchestration
* persist durable project memory
* automatically inject relevant state into Claude sessions

Zero changes to Claude Code itself.

Everything lives in your project folder and user config.

---

# 2. Integration Points (macOS Claude Code CLI)

Claude Code CLI supports 3 native integration mechanisms:

1. **CLAUDE.md**
2. **Hooks**
3. **MCP servers**

We use all three.

Priority order:

```
MVP:
CLAUDE.md
Hooks

Production:
CLAUDE.md
Hooks
MCP server
```

---

# 3. Final File Layout

Per project:

```
your-project/
├─ CLAUDE.md
├─ .claude/
│  ├─ hooks/
│  │  ├─ post_message.py
│  │  ├─ pre_compact.py
│  │  ├─ session_start.py
│  │  └─ agent_output_filter.py
│  │
│  └─ settings.local.json
│
├─ .cccm/
│  ├─ config.yml
│  ├─ index.json
│  │
│  ├─ memory/
│  │  ├─ decisions.md
│  │  ├─ constraints.md
│  │  ├─ interfaces.md
│  │  └─ glossary.md
│  │
│  └─ snapshots/
│     └─ 2026-02-19T14-32-01.md
│
└─ cccm/
   ├─ cli.py
   ├─ memory_manager.py
   ├─ snapshot.py
   ├─ injector.py
   ├─ context_monitor.py
   └─ schemas.py
```

User-level global install:

```
~/.cccm/
├─ bin/cccm
├─ config.yml
└─ templates/
```

---

# 4. Core System Components

## Component 1: Context Monitor

Detect when compaction risk is approaching.

Triggers snapshot at thresholds.

Threshold defaults:

```
warning: 55%
snapshot: 65%
critical snapshot: 75%
```

Claude Code CLI exposes context info via `/context`.

Hook reads it and parses usage.

---

## Component 2: Snapshot Engine

Creates Continuity Packet.

Saved to:

```
.cccm/snapshots/
```

Snapshot schema:

```
GOAL
CURRENT STATE
DECISIONS
CONSTRAINTS
FILES MODIFIED
OPEN PROBLEMS
NEXT ACTIONS
```

Max size: 800 tokens equivalent.

---

## Component 3: Memory Manager

Persistent knowledge storage.

Stores:

```
architectural decisions
API contracts
data structures
constraints
completed work
```

Files:

```
.cccm/memory/*.md
```

---

## Component 4: Injector

Injects relevant memory back into Claude context when:

* session starts
* new task begins
* after compaction

Injection sources:

```
latest snapshot
memory files
CLAUDE.md
```

Injection target:

Claude Code system context.

---

## Component 5: Agent Output Filter

Prevents subagents from polluting context.

Transforms output from:

BAD:

```
Thinking step 1...
Considering option A...
Evaluating architecture...
```

TO:

GOOD:

```
RESULT:
Selected Redis caching layer

WHY:
Improves performance by 4x

FILES:
cache_manager.py
```

Reduces context growth by 60–80%.

---

# 5. Hook System (macOS Claude Code CLI)

Hooks live here:

```
.claude/hooks/
```

## Hook 1: post_message.py

Runs after each Claude response.

Responsibilities:

* check context usage
* trigger snapshot if threshold exceeded
* update memory index

---

## Hook 2: session_start.py

Runs when Claude CLI starts.

Responsibilities:

* load latest snapshot
* inject memory context

---

## Hook 3: pre_compact.py

Runs before compaction (if detectable).

Responsibilities:

* force snapshot
* preserve continuity

---

## Hook 4: agent_output_filter.py

Runs on subagent output.

Responsibilities:

* compress output
* remove verbose reasoning

---

# 6. CLAUDE.md Integration

CLAUDE.md acts as persistent root instructions.

CCCM appends this block automatically:

```
# Context Management Protocol

You are operating with external memory.

Rules:

1. Never output verbose reasoning.
2. Always produce structured results.
3. Use concise summaries.
4. Assume long-term memory exists externally.
5. When asked to summarize, follow Continuity Packet schema.

Continuity Packet Schema:

GOAL:
CURRENT STATE:
DECISIONS:
CONSTRAINTS:
FILES:
OPEN ISSUES:
NEXT ACTIONS:
```

Claude Code always loads CLAUDE.md first.

This survives compaction.

---

# 7. CLI Tool (cccm)

Global binary:

```
~/.cccm/bin/cccm
```

Commands:

```
cccm snapshot
cccm memory add
cccm memory list
cccm inject
cccm status
cccm doctor
```

---

# 8. MCP Server Integration (Phase 2)

Optional but extremely powerful.

Add to:

```
.claude/settings.local.json
```

Example:

```
{
  "mcpServers": {
    "cccm-memory": {
      "command": "cccm",
      "args": ["mcp"]
    }
  }
}
```

This exposes tools to Claude:

```
memory.search
memory.write
memory.latest
```

Claude retrieves only relevant memory.

Massively improves agent performance.

---

# 9. Installation Flow (macOS)

User runs:

```
curl -sSL https://cccm.sh/install | bash
```

Installer does:

```
mkdir ~/.cccm
install CLI
add to PATH
create templates
```

Then inside project:

```
cccm init
```

This creates:

```
.cccm/
.claude/hooks/
CLAUDE.md additions
settings.local.json
```

Ready immediately.

---

# 10. Runtime Lifecycle

Normal operation:

```
User starts Claude Code CLI
↓
session_start hook injects memory
↓
User runs agents
↓
post_message hook monitors context
↓
snapshot created when needed
↓
compaction happens safely
↓
session continues normally
```

User never has to think about context limits again.

---

# 11. Performance Targets

Context growth reduction:

```
Baseline: 100%
With CCCM: 30–40%
```

Session stability improvement:

```
2–3x longer stable runtime
```

Agent reliability improvement:

```
major reduction in repetition and regression
```

---

# 12. MVP Implementation Time

You (or I) can implement MVP in:

```
4–6 hours
```

Production version:

```
1–2 days
```

---

# 13. Why this works extremely well with YOUR setup

Your system has:

* orchestrator agent
* worker agents
* long sessions
* infrastructure generation

This architecture prevents:

* agent drift
* repeated planning loops
* context collapse
* compaction damage

This is exactly what production agent systems use.

---

