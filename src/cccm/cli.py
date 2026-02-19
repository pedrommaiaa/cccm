"""CLI entry point for CCCM."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from cccm.core.memory import (
    ensure_dirs,
    load_config,
    load_index,
    save_json,
    summarize_memory,
)
from cccm.core.snapshot import create_snapshot


def find_project_root() -> Path:
    """Walk up from cwd to find a directory containing .cccm/ or .claude/."""
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".cccm").is_dir() or (parent / ".claude").is_dir():
            return parent
    return cwd


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _run_full_init(root: Path) -> int:
    """Shared init logic: create dirs, hooks, MCP config, CLAUDE.md, verify."""
    root = root.resolve()
    print(f"Initializing CCCM in {root}\n")
    fixed: list[str] = []

    _fix_cccm_dirs(root, fixed)
    _fix_hooks(root, fixed)
    _fix_mcp(root, fixed)
    _fix_claude_md(root, fixed)

    print("Setup:")
    for item in fixed:
        print(f"  + {item}")

    # Verify
    ok, issues = _run_checks(root)
    if issues:
        print("\nRemaining issues:")
        for item in issues:
            print(f"  ! {item}")
        return 1

    print(f"\nAll checks passed. CCCM is ready in {root}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize CCCM in the current project."""
    root = Path(args.root).resolve()
    return _run_full_init(root)


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Create a manual snapshot."""
    root = find_project_root()
    ensure_dirs(root)
    text, path = create_snapshot(root)
    print(f"Snapshot saved: {path}")
    if args.show:
        print("---")
        print(text)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show current CCCM status."""
    root = find_project_root()
    index = load_index(root)

    last = index.get("last_snapshot", "(none)")
    recent = index.get("recent_files", [])[:10]
    events = index.get("events", [])[-5:]

    print(f"Project root:    {root}")
    print(f"Last snapshot:   {last}")
    print(f"Tracked files:   {len(index.get('recent_files', []))}")
    print(f"Events logged:   {len(index.get('events', []))}")

    if recent:
        print("\nRecent files:")
        for f in recent:
            print(f"  {f}")

    if events:
        print("\nRecent events:")
        for e in events:
            print(f"  [{e.get('ts', '?')}] {e.get('kind', '?')}: {json.dumps(e.get('payload', {}))}")

    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    """Show current memory summary."""
    root = find_project_root()
    summary = summarize_memory(root)
    if summary:
        print(summary)
    else:
        print("Memory docs are empty. Populate .cccm/memory/*.md to get started.")
    return 0


def _get_python_cmd() -> str:
    """Return the python command to use in hooks."""
    exe = sys.executable
    # If running from a venv/pipx, use the full path so hooks find cccm
    if exe and Path(exe).exists():
        return exe
    return "python3"


def _build_hooks_config() -> dict:
    """Build the .claude/settings.json hooks config."""
    py = _get_python_cmd()
    return {
        "hooks": {
            "SessionStart": [{
                "matcher": "",
                "hooks": [{
                    "type": "command",
                    "command": f'{py} -m cccm.hooks.runner session_start',
                    "timeout": 10,
                }],
            }],
            "PreCompact": [{
                "matcher": "",
                "hooks": [{
                    "type": "command",
                    "command": f'{py} -m cccm.hooks.runner pre_compact',
                    "timeout": 10,
                }],
            }],
            "PostToolUse": [{
                "matcher": "Write|Edit|MultiEdit|Bash",
                "hooks": [{
                    "type": "command",
                    "command": f'{py} -m cccm.hooks.runner post_tool_use',
                    "timeout": 5,
                }],
            }],
            "SubagentStart": [{
                "matcher": "",
                "hooks": [{
                    "type": "command",
                    "command": f'{py} -m cccm.hooks.runner subagent_start',
                    "timeout": 5,
                }],
            }],
            "UserPromptSubmit": [{
                "hooks": [{
                    "type": "command",
                    "command": f'{py} -m cccm.hooks.runner user_prompt_submit',
                    "timeout": 5,
                }],
            }],
            "Stop": [{
                "hooks": [{
                    "type": "command",
                    "command": f'{py} -m cccm.hooks.runner stop',
                    "timeout": 5,
                    "async": True,
                }],
            }],
        },
    }


def _build_mcp_config() -> dict:
    """Build the .claude/settings.local.json MCP server config."""
    py = _get_python_cmd()
    return {
        "mcpServers": {
            "cccm-memory": {
                "command": py,
                "args": ["-m", "cccm.mcp_server"],
            },
        },
    }


CLAUDE_MD_CCCM_SECTION = """\

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
"""


def _fix_cccm_dirs(root: Path, fixed: list[str]) -> None:
    """Create .cccm/ structure."""
    ensure_dirs(root)
    fixed.append("Created .cccm/ directory structure (memory, snapshots, config, index)")


def _fix_hooks(root: Path, fixed: list[str]) -> None:
    """Create or merge hooks into .claude/settings.json."""
    claude_dir = root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings_path = claude_dir / "settings.json"

    desired = _build_hooks_config()

    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    else:
        existing = {}

    # Merge: preserve non-hook keys, overwrite hooks
    existing["hooks"] = desired["hooks"]
    save_json(settings_path, existing)
    fixed.append("Wrote .claude/settings.json with all 6 hooks")


def _fix_mcp(root: Path, fixed: list[str]) -> None:
    """Create or merge MCP config into .claude/settings.local.json."""
    claude_dir = root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    local_path = claude_dir / "settings.local.json"

    desired = _build_mcp_config()

    if local_path.exists():
        try:
            existing = json.loads(local_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    else:
        existing = {}

    servers = existing.setdefault("mcpServers", {})
    servers["cccm-memory"] = desired["mcpServers"]["cccm-memory"]
    save_json(local_path, existing)
    fixed.append("Wrote .claude/settings.local.json with cccm-memory MCP server")


def _fix_claude_md(root: Path, fixed: list[str]) -> None:
    """Create CLAUDE.md or append CCCM sections if missing."""
    claude_md = root / "CLAUDE.md"

    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8", errors="replace")
        if "Compact Instructions" in content:
            return  # Already has the section
        # Append CCCM section
        content = content.rstrip() + "\n" + CLAUDE_MD_CCCM_SECTION
        claude_md.write_text(content, encoding="utf-8")
        fixed.append("Appended CCCM sections to existing CLAUDE.md")
    else:
        header = f"# {root.name}\n"
        claude_md.write_text(header + CLAUDE_MD_CCCM_SECTION, encoding="utf-8")
        fixed.append("Created CLAUDE.md with CCCM context management sections")


def _run_checks(root: Path) -> tuple[list[str], list[str]]:
    """Run all doctor checks. Returns (ok, issues) lists."""
    issues: list[str] = []
    ok: list[str] = []

    # Check .cccm/ exists
    cccm_dir = root / ".cccm"
    if cccm_dir.is_dir():
        ok.append(".cccm/ directory exists")
    else:
        issues.append(".cccm/ directory missing")

    # Check memory files
    mem_dir = root / ".cccm" / "memory"
    if mem_dir.is_dir():
        for name in ("decisions.md", "constraints.md", "interfaces.md", "glossary.md"):
            if (mem_dir / name).exists():
                ok.append(f"  memory/{name}")
            else:
                issues.append(f"  memory/{name} missing")
    else:
        issues.append(".cccm/memory/ directory missing")

    # Check config
    cfg_path = root / ".cccm" / "config.json"
    if cfg_path.exists():
        ok.append("config.json exists")
    else:
        issues.append("config.json missing")

    # Check .claude/settings.json for hooks
    settings_path = root / ".claude" / "settings.json"
    if settings_path.exists():
        ok.append(".claude/settings.json exists")
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            hooks = settings.get("hooks", {})
            for event in ("SessionStart", "PreCompact", "PostToolUse",
                          "SubagentStart", "UserPromptSubmit", "Stop"):
                if event in hooks:
                    ok.append(f"  Hook: {event}")
                else:
                    issues.append(f"  Hook: {event} not registered")
        except (json.JSONDecodeError, OSError):
            issues.append(".claude/settings.json is not valid JSON")
    else:
        issues.append(".claude/settings.json missing — hooks won't fire")

    # Check MCP server config
    local_settings = root / ".claude" / "settings.local.json"
    if local_settings.exists():
        try:
            local_cfg = json.loads(local_settings.read_text(encoding="utf-8"))
            if "cccm-memory" in local_cfg.get("mcpServers", {}):
                ok.append("MCP server: cccm-memory configured")
            else:
                issues.append("MCP server: cccm-memory not in settings.local.json")
        except (json.JSONDecodeError, OSError):
            issues.append(".claude/settings.local.json is not valid JSON")
    else:
        issues.append(".claude/settings.local.json missing — MCP memory server not configured")

    # Check CLAUDE.md
    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8", errors="replace")
        if "Compact Instructions" in content:
            ok.append("CLAUDE.md has Compact Instructions section")
        else:
            issues.append("CLAUDE.md missing 'Compact Instructions' section")
    else:
        issues.append("CLAUDE.md missing — compaction behavior won't be guided")

    return ok, issues


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check CCCM installation health and optionally fix issues."""
    root = find_project_root()
    fix = getattr(args, "fix", False)

    if fix:
        return _run_full_init(root)

    # Diagnose-only mode
    ok, issues = _run_checks(root)

    print(f"CCCM Doctor — {root}\n")
    if ok:
        print("OK:")
        for item in ok:
            print(f"  + {item}")
    if issues:
        print("\nIssues:")
        for item in issues:
            print(f"  ! {item}")
        print("\nRun 'cccm doctor --fix' to auto-fix all issues.")
    else:
        print("\nAll checks passed.")

    return 1 if issues else 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cccm",
        description="Claude Code Context Manager — persistent memory for Claude Code sessions",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Full CCCM setup: dirs, hooks, MCP config, CLAUDE.md")
    p_init.add_argument("--root", default=".", help="Project root directory (default: current directory)")

    # snapshot
    p_snap = sub.add_parser("snapshot", help="Create a manual snapshot")
    p_snap.add_argument("--show", action="store_true", help="Print snapshot content")

    # status
    sub.add_parser("status", help="Show CCCM status")

    # memory
    sub.add_parser("memory", help="Show memory summary")

    # doctor
    p_doc = sub.add_parser("doctor", help="Check CCCM installation health")
    p_doc.add_argument("--fix", action="store_true",
                        help="Auto-fix all issues (create dirs, hooks, MCP config, CLAUDE.md)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "init": cmd_init,
        "snapshot": cmd_snapshot,
        "status": cmd_status,
        "memory": cmd_memory,
        "doctor": cmd_doctor,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
