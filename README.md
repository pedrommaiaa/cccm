# CCCM — Claude Code Context Manager

Persistent memory and context management for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions.

CCCM prevents context window blowout in long, multi-agent Claude Code sessions by automatically snapshotting state before compaction, re-injecting continuity after compaction, tracking file changes, enforcing subagent brevity, and persisting durable project memory.

**Zero changes to Claude Code itself.** Everything works through native integration points: hooks, CLAUDE.md, and MCP servers.

## The Problem

In multi-agent Claude Code sessions, the context window fills with repetitive agent reasoning, tool outputs, file diffs, and duplicate architectural discussion. When compaction triggers, the summary often drops precision details — exact function signatures, why a decision was made, what was already tried. This causes rework and degraded performance.

## How CCCM Solves It

| Hook | Fires When | What It Does |
|------|-----------|-------------|
| `SessionStart` | Session begins, resumes, or post-compact | Injects protocol rules; reinjects latest continuity snapshot after compaction |
| `PreCompact` | Before context compaction | Creates a snapshot and tells Claude exactly what to preserve |
| `PostToolUse` | After Write/Edit/Bash | Silently tracks which files were touched |
| `SubagentStart` | Subagent spawned | Per-agent-type brevity rules + memory injection for research agents |
| `UserPromptSubmit` | User sends a prompt | Injects relevant memory when prompt keywords match stored knowledge |
| `Stop` | Claude finishes responding | Auto-captures architectural decisions from responses |

Plus an **MCP memory server** that gives Claude direct access to search, write, and retrieve project memory.

## Quick Start

### Install

```bash
pip install git+https://github.com/pedrommaiaa/cccm.git
```

Or for development:

```bash
git clone https://github.com/pedrommaiaa/cccm.git
cd cccm
pip install -e ".[dev]"
```

### Set up in your project (one command)

```bash
cd /path/to/your-project
cccm doctor --fix
```

That's it. This single command creates everything CCCM needs:

- `.cccm/` directory with memory docs, config, and snapshots folder
- `.claude/settings.json` with all 6 hook registrations
- `.claude/settings.local.json` with the MCP memory server
- `CLAUDE.md` with compaction instructions (appends to existing file if present)

```
CCCM Doctor --fix — /path/to/your-project

Fixed:
  + Created .cccm/ directory structure (memory, snapshots, config, index)
  + Wrote .claude/settings.json with all 6 hooks
  + Wrote .claude/settings.local.json with cccm-memory MCP server
  + Created CLAUDE.md with CCCM context management sections

All checks passed. CCCM is ready in /path/to/your-project
```

Run `cccm doctor` (without `--fix`) anytime to check health without changing anything.

## Usage

### Automatic (zero effort)

Once hooks are installed, CCCM works silently in the background. Start Claude Code normally — CCCM handles the rest:

- Snapshots are created before compaction
- Continuity is re-injected after compaction
- File changes are tracked
- Subagents get brevity rules
- Decisions are auto-captured
- Relevant memory is injected when your prompts match stored knowledge

### CLI Commands

```bash
cccm doctor --fix      # Set up CCCM in any project (one command)
cccm doctor            # Health check (diagnose only)
cccm snapshot          # Force a continuity snapshot
cccm snapshot --show   # Snapshot + print content
cccm status            # Show tracked files, events, last snapshot
cccm memory            # Print all memory docs
cccm init              # Initialize .cccm/ directory only
```

### MCP Tools (used by Claude directly)

When the MCP server is running, Claude has these tools available:

| Tool | Purpose |
|------|---------|
| `memory_search(query, top_k)` | Keyword search across memory docs and snapshots |
| `memory_write(doc_type, content)` | Persist knowledge to a memory doc |
| `memory_latest()` | Get the latest continuity snapshot |
| `memory_status()` | Check system status |

## Populating Memory

The real power of CCCM comes from seeding your memory docs. These survive compaction and get injected into research agents automatically.

### `.cccm/memory/decisions.md`

Record architectural decisions with rationale:

```markdown
## Database
Chose PostgreSQL because we need JSONB columns and complex joins.

## Auth
Using JWT with refresh tokens. No sessions — must be stateless for horizontal scaling.
```

### `.cccm/memory/constraints.md`

Hard rules and boundaries:

```markdown
- Must support Python 3.10+
- No external dependencies in core module
- All API responses under 200ms p95
```

### `.cccm/memory/interfaces.md`

Key contracts and APIs:

```markdown
## User API
- POST /users — create user (email, name)
- GET /users/:id — returns {id, email, name, created_at}
```

### `.cccm/memory/glossary.md`

Domain-specific terminology for your project.

## Per-Agent Budgets

CCCM applies different rules based on agent type:

| Agent Type | Output Limit | Gets Memory? | Style |
|-----------|-------------|-------------|-------|
| `Bash` | 3 lines | No | Extremely concise |
| `Explore` | 15 lines | Yes | Thorough but structured |
| `Plan` | 15 lines | Yes | Include tradeoffs |
| Other | 8 lines | No | Default structured output |

Override in `.cccm/config.json`:

```json
{
  "agent_budgets": {
    "Bash": {
      "max_output_lines": 5,
      "inject_memory": false
    }
  }
}
```

## Configuration

### `.cccm/config.json`

```json
{
  "snapshot": {
    "max_chars_injected": 6000,
    "max_snapshot_chars": 25000,
    "max_snapshots": 50
  },
  "tracking": {
    "track_decisions": true,
    "track_tools": ["Write", "Edit", "MultiEdit", "Bash"]
  },
  "prompt_inject": {
    "max_chars": 2000
  },
  "agent_budgets": {}
}
```

### `.claude/settings.json`

Hook registrations for Claude Code. See the included file for the full configuration.

### `.claude/settings.local.json`

MCP server configuration (git-ignored by default):

```json
{
  "mcpServers": {
    "cccm-memory": {
      "command": "python3",
      "args": ["-m", "cccm.mcp_server"],
      "env": {
        "PYTHONPATH": "./src",
        "CCCM_PROJECT_ROOT": "."
      }
    }
  }
}
```

## Project Structure

```
src/cccm/
├── __init__.py
├── cli.py                 # CLI entry point
├── mcp_server.py          # MCP memory server (FastMCP)
├── core/
│   ├── memory.py          # Memory store, index, config
│   ├── snapshot.py        # Continuity packet engine
│   ├── search.py          # Keyword-based memory search
│   └── decisions.py       # Auto-decision capture
└── hooks/
    └── runner.py          # Hook event dispatcher (6 events)

.cccm/                     # Project-local memory (created per-project)
├── config.json
├── index.json
├── memory/
│   ├── decisions.md
│   ├── constraints.md
│   ├── interfaces.md
│   └── glossary.md
└── snapshots/

tests/                     # 99 tests
├── test_memory.py
├── test_snapshot.py
├── test_hooks.py
├── test_v1_hooks.py
├── test_search.py
├── test_decisions.py
├── test_mcp_server.py
└── test_cli.py
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src/ tests/
```

## Requirements

- Python 3.10+
- Claude Code CLI
- MCP Python SDK (`mcp>=1.0`) — installed automatically

## License

MIT
