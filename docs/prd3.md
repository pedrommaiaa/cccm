Alright — here’s a **working MVP you can drop into any repo on macOS** that:

* **auto-snapshots** before compaction (`PreCompact`)
* **re-injects continuity** after compaction / resume (`SessionStart` with `source:"compact"` / `"resume"`)
* **tracks file changes** from tool calls (`PostToolUse`)
* **forces subagents to be terse** (`SubagentStart`)
* gives you a simple **`cccm` command** to snapshot / view status anytime

This uses **Claude Code hooks** exactly as documented (hooks run shell commands, get JSON on stdin, can return `additionalContext` / `systemMessage`). ([Claude Code][1])
It also leverages the fact that Claude Code supports **“Compact Instructions” in `CLAUDE.md`** and has `/context` to inspect what’s eating tokens. ([Claude Code][2])

---

## 0) What you’ll create

In your repo:

```
.claude/
  settings.json
  hooks/
    cccm.py
.cccm/
  config.json
  index.json
  memory/
    decisions.md
    constraints.md
    interfaces.md
    glossary.md
  snapshots/
CLAUDE.md   (add a Compact Instructions block)
```

---

## 1) Add hook config: `.claude/settings.json`

Create `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/cccm.py session_start"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/cccm.py pre_compact"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/cccm.py post_tool_use"
          }
        ]
      }
    ],
    "SubagentStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/cccm.py subagent_start"
          }
        ]
      }
    ]
  }
}
```

Why these events:

* `PreCompact` fires **right before context compaction** ([Claude Code][1])
* `SessionStart` fires on new session/resume/**after compaction** via `source:"compact"` ([Claude Code][1])
* `PostToolUse` lets us track writes/edits and build a real continuity packet ([Claude Code][1])
* `SubagentStart` injects “be concise” into every spawned agent ([Claude Code][1])

---

## 2) Add the hook runner: `.claude/hooks/cccm.py`

Create `.claude/hooks/cccm.py`:

```python
#!/usr/bin/env python3
import json
import os
import sys
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -------------------------
# Helpers
# -------------------------

def utc_ts_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

def read_stdin_json() -> Dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    return json.loads(raw)

def out_json(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()

def repo_root(cwd: str) -> Path:
    # Claude Code passes cwd in hook input; assume project root is cwd.
    # If user runs claude inside a subdir, we still want that working tree.
    return Path(cwd).resolve()

def ensure_dirs(root: Path) -> Dict[str, Path]:
    base = root / ".cccm"
    mem = base / "memory"
    snaps = base / "snapshots"
    base.mkdir(exist_ok=True)
    mem.mkdir(exist_ok=True)
    snaps.mkdir(exist_ok=True)

    # Seed memory docs if missing
    for name in ["decisions.md", "constraints.md", "interfaces.md", "glossary.md"]:
        p = mem / name
        if not p.exists():
            p.write_text(f"# {name.replace('.md','').title()}\n\n", encoding="utf-8")

    cfg = base / "config.json"
    if not cfg.exists():
        cfg.write_text(json.dumps({
            "snapshot": {
                "max_chars_injected": 6000,
                "max_snapshot_chars": 25000
            },
            "tracking": {
                "track_tools": ["Write", "Edit", "MultiEdit", "ApplyPatch", "Bash"]
            }
        }, indent=2), encoding="utf-8")

    idx = base / "index.json"
    if not idx.exists():
        idx.write_text(json.dumps({
            "version": 1,
            "last_snapshot": None,
            "recent_files": [],
            "events": []
        }, indent=2), encoding="utf-8")

    return {"base": base, "mem": mem, "snaps": snaps, "cfg": cfg, "idx": idx}

def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def append_event(index: Dict[str, Any], kind: str, payload: Dict[str, Any]) -> None:
    index.setdefault("events", [])
    index["events"].append({
        "ts": utc_ts_compact(),
        "kind": kind,
        "payload": payload
    })
    # keep index small
    if len(index["events"]) > 200:
        index["events"] = index["events"][-200:]

def add_recent_file(index: Dict[str, Any], path_str: str) -> None:
    index.setdefault("recent_files", [])
    rf: List[str] = index["recent_files"]
    if path_str in rf:
        rf.remove(path_str)
    rf.insert(0, path_str)
    # cap
    index["recent_files"] = rf[:50]

def safe_read_text(p: Path, limit: int = 200_000) -> str:
    try:
        data = p.read_text(encoding="utf-8", errors="replace")
        return data[:limit]
    except Exception:
        return ""

def summarize_memory(mem_dir: Path, max_chars: int = 8000) -> str:
    parts = []
    for name in ["decisions.md", "constraints.md", "interfaces.md", "glossary.md"]:
        p = mem_dir / name
        txt = safe_read_text(p, limit=max_chars)
        txt = txt.strip()
        if txt:
            parts.append(f"## {name}\n{txt}\n")
    combined = "\n".join(parts).strip()
    return combined[:max_chars]

def build_snapshot(root: Path, paths: Dict[str, Path], index: Dict[str, Any], hook_input: Dict[str, Any]) -> Tuple[str, Path]:
    # Minimal but high-signal snapshot. We do NOT try to re-summarize the whole conversation (that needs LLM).
    # Instead: memory docs + recent file touches + current hook metadata.
    mem_summary = summarize_memory(paths["mem"], max_chars=12000)

    recent_files = index.get("recent_files", [])[:20]
    recent_files_block = "\n".join([f"- {p}" for p in recent_files]) if recent_files else "- (none tracked yet)"

    session_id = hook_input.get("session_id", "")
    transcript_path = hook_input.get("transcript_path", "")
    permission_mode = hook_input.get("permission_mode", "")
    cwd = hook_input.get("cwd", "")

    snapshot = []
    snapshot.append("# CCCM Continuity Packet")
    snapshot.append("")
    snapshot.append(f"- Timestamp (UTC): {utc_ts_compact()}")
    snapshot.append(f"- Session: {session_id}")
    snapshot.append(f"- CWD: {cwd}")
    snapshot.append(f"- Transcript: {transcript_path}")
    snapshot.append(f"- Permission mode: {permission_mode}")
    snapshot.append("")
    snapshot.append("## What to preserve through compaction")
    snapshot.append("- Current objective and next steps (from user prompt)")
    snapshot.append("- Decisions + constraints in .cccm/memory/*")
    snapshot.append("- Interfaces/APIs noted in interfaces.md")
    snapshot.append("- Recent files touched (below)")
    snapshot.append("")
    snapshot.append("## Recent files touched")
    snapshot.append(recent_files_block)
    snapshot.append("")
    snapshot.append("## Project memory (authoritative)")
    snapshot.append(mem_summary if mem_summary else "_(memory docs empty)_")
    snapshot_text = "\n".join(snapshot)

    # Write snapshot file
    snap_name = f"{utc_ts_compact()}_continuity.md"
    snap_path = paths["snaps"] / snap_name
    cfg = load_json(paths["cfg"])
    max_snapshot_chars = int(cfg.get("snapshot", {}).get("max_snapshot_chars", 25000))
    snap_path.write_text(snapshot_text[:max_snapshot_chars], encoding="utf-8")

    index["last_snapshot"] = str(snap_path.relative_to(root))
    append_event(index, "snapshot", {"path": index["last_snapshot"]})
    save_json(paths["idx"], index)

    return snapshot_text, snap_path

def inject_additional_context(event_name: str, text: str) -> Dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text
        }
    }

def inject_system_message(text: str) -> Dict[str, Any]:
    return {"systemMessage": text}

# -------------------------
# Event handlers
# -------------------------

def handle_session_start(root: Path, paths: Dict[str, Path], index: Dict[str, Any], hook_input: Dict[str, Any]) -> None:
    # If starting after compaction/resume, re-inject the latest continuity packet.
    source = hook_input.get("source")  # "startup" | "resume" | "clear" | "compact"
    last_snapshot_rel = index.get("last_snapshot")
    snap_text = ""
    if last_snapshot_rel:
        snap_text = safe_read_text(root / last_snapshot_rel, limit=12000)

    cfg = load_json(paths["cfg"])
    max_inject = int(cfg.get("snapshot", {}).get("max_chars_injected", 6000))
    snap_text = (snap_text or "")[:max_inject]

    # Always remind about the protocol; add snapshot especially after compaction
    protocol = (
        "CCCM active.\n"
        "Rules:\n"
        "1) Keep outputs high-signal.\n"
        "2) Subagents must return: RESULT / WHY / REFS (no verbose reasoning).\n"
        "3) Project memory lives in .cccm/memory/*.md.\n"
        "4) If context is tight, rely on the Continuity Packet.\n"
    )

    if source in ("compact", "resume") and snap_text:
        payload = protocol + "\n---\nLatest Continuity Packet:\n\n" + snap_text
        append_event(index, "session_start_injected", {"source": source})
        save_json(paths["idx"], index)
        out_json(inject_additional_context("SessionStart", payload))
        return

    # For fresh startup: light injection only
    append_event(index, "session_start", {"source": source})
    save_json(paths["idx"], index)
    out_json(inject_additional_context("SessionStart", protocol))

def handle_pre_compact(root: Path, paths: Dict[str, Path], index: Dict[str, Any], hook_input: Dict[str, Any]) -> None:
    # Make a fresh snapshot and tell Claude exactly what to preserve.
    snap_text, snap_path = build_snapshot(root, paths, index, hook_input)

    cfg = load_json(paths["cfg"])
    max_inject = int(cfg.get("snapshot", {}).get("max_chars_injected", 6000))
    inject_text = snap_text[:max_inject]

    guidance = (
        "About to compact context.\n"
        "Compaction MUST preserve:\n"
        "- The user's current objective and any constraints they gave.\n"
        "- Decisions/constraints/interfaces from .cccm/memory/*.md\n"
        "- The Recent files touched list\n"
        "- Any explicit TODO / Next Actions\n"
        "\n"
        "Use the following Continuity Packet as the source of truth:\n\n"
        + inject_text
    )

    out_json(inject_additional_context("PreCompact", guidance))

def handle_post_tool_use(root: Path, paths: Dict[str, Path], index: Dict[str, Any], hook_input: Dict[str, Any]) -> None:
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {}) or {}

    cfg = load_json(paths["cfg"])
    track = set(cfg.get("tracking", {}).get("track_tools", []))

    if tool_name not in track:
        out_json({})  # no-op
        return

    # Try to detect a file path from common tool schemas
    candidate_keys = ["path", "file_path", "filepath", "target", "filename"]
    file_path = None
    for k in candidate_keys:
        if isinstance(tool_input, dict) and k in tool_input and isinstance(tool_input[k], str):
            file_path = tool_input[k]
            break

    # Some tools embed file path differently; try common nested shapes
    if not file_path and isinstance(tool_input, dict):
        for k in ["files", "edits"]:
            v = tool_input.get(k)
            if isinstance(v, list) and v:
                if isinstance(v[0], dict):
                    for kk in candidate_keys:
                        if kk in v[0] and isinstance(v[0][kk], str):
                            file_path = v[0][kk]
                            break
            if file_path:
                break

    if file_path:
        add_recent_file(index, file_path)

    append_event(index, "tool", {"tool_name": tool_name, "file": file_path})
    save_json(paths["idx"], index)

    # Keep this silent (don’t inject context every tool call).
    out_json({})

def handle_subagent_start(root: Path, paths: Dict[str, Path], index: Dict[str, Any], hook_input: Dict[str, Any]) -> None:
    # Inject strict brevity rules into every subagent
    msg = (
        "Subagent protocol:\n"
        "- Output ONLY:\n"
        "  RESULT:\n"
        "  WHY: (max 8 lines)\n"
        "  REFS: (files/commands)\n"
        "- NO verbose reasoning, NO long plans.\n"
        "- If uncertain, propose 2-3 options with tradeoffs, then pick one.\n"
    )
    append_event(index, "subagent_start", {"agent_type": hook_input.get("agent_type")})
    save_json(paths["idx"], index)
    out_json(inject_additional_context("SubagentStart", msg))

# -------------------------
# CLI (manual convenience)
# -------------------------

def cli_snapshot(root: Path) -> None:
    paths = ensure_dirs(root)
    index = load_json(paths["idx"])
    # Fake hook_input for manual snapshots
    hook_input = {"cwd": str(root), "session_id": "manual", "transcript_path": "", "permission_mode": ""}
    snap_text, snap_path = build_snapshot(root, paths, index, hook_input)
    print(f"Wrote snapshot: {snap_path}")

def cli_status(root: Path) -> None:
    paths = ensure_dirs(root)
    index = load_json(paths["idx"])
    print(json.dumps({
        "last_snapshot": index.get("last_snapshot"),
        "recent_files": index.get("recent_files", [])[:10],
        "events_tail": index.get("events", [])[-5:]
    }, indent=2))

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    hook_input = read_stdin_json()

    cwd = hook_input.get("cwd") or os.getcwd()
    root = repo_root(cwd)
    paths = ensure_dirs(root)
    index = load_json(paths["idx"])

    if mode == "session_start":
        handle_session_start(root, paths, index, hook_input)
    elif mode == "pre_compact":
        handle_pre_compact(root, paths, index, hook_input)
    elif mode == "post_tool_use":
        handle_post_tool_use(root, paths, index, hook_input)
    elif mode == "subagent_start":
        handle_subagent_start(root, paths, index, hook_input)
    elif mode == "snapshot":
        cli_snapshot(root)
    elif mode == "status":
        cli_status(root)
    else:
        # Unknown mode — no-op so we never break Claude Code
        out_json({})

if __name__ == "__main__":
    main()
```

Make it executable:

```bash
chmod +x .claude/hooks/cccm.py
```

---

## 3) Add compaction-safe instructions to `CLAUDE.md`

In your repo’s `CLAUDE.md`, add this section (near the top):

```md
## Compact Instructions
When compacting context, preserve:
- The current objective and any user constraints
- The latest CCCM Continuity Packet (from .cccm/snapshots)
- The authoritative memory docs:
  - .cccm/memory/decisions.md
  - .cccm/memory/constraints.md
  - .cccm/memory/interfaces.md
- Recent files touched and next actions
Keep the compacted summary actionable and specific (paths, interfaces, TODOs).
```

Claude Code explicitly supports steering compaction via a “Compact Instructions” section. ([Claude Code][2])

---

## 4) Optional: add a tiny `cccm` command

Create `cccm` at repo root:

```bash
#!/usr/bin/env bash
set -euo pipefail
python3 .claude/hooks/cccm.py "${1:-status}"
```

Then:

```bash
chmod +x ./cccm
```

Usage:

```bash
./cccm status
./cccm snapshot
```

---

## 5) How this solves “Claude Code doesn’t auto-compact well”

* **Before compaction** (`PreCompact`), CCCM writes a continuity file and injects “preserve this” context. ([Claude Code][1])
* **After compaction**, Claude Code triggers `SessionStart` with `source:"compact"`, and CCCM reinjects the latest continuity packet. ([Claude Code][1])
* **Subagents** stop dumping essays into your main context because they get hard formatting rules at `SubagentStart`. ([Claude Code][1])
* You also avoid MCP bloat (tool definitions count against context). If you later add MCP memory search, you’ll want to keep server count minimal. ([Claude Code][2])

---

## 6) Quick test (takes 30 seconds)

1. Start Claude Code CLI in the repo:

```bash
claude
```

2. Run `/context` and watch it grow (Claude Code’s recommended tool). ([Claude Code][2])
3. When it compacts (or you run `/compact`), you should see:

* a new file in `.cccm/snapshots/`
* and after compaction, CCCM should re-inject the latest snapshot

---

## 7) What you should do next (to make it *really* effective)

This MVP is deterministic. The high leverage comes from you putting **real content** into:

* `.cccm/memory/decisions.md` (decisions + rationale)
* `.cccm/memory/interfaces.md` (function signatures, contracts, schema)
* `.cccm/memory/constraints.md` (perf, style, “no X”, “must Y”)

Because those are what CCCM guarantees survive compaction.

If you want, I’ll extend this into **V1** by adding:

* a `UserPromptSubmit` hook that (only when useful) injects the most relevant memory
* a lightweight **MCP memory server** so Claude can `memory.search()` instead of injecting large blobs (and we’ll do it in a way that avoids the common “MCP config not loading” pitfalls people hit). ([Claude Code][3])

[1]: https://code.claude.com/docs/en/hooks "Hooks reference - Claude Code Docs"
[2]: https://code.claude.com/docs/en/how-claude-code-works?utm_source=chatgpt.com "How Claude Code works - Claude Code Docs"
[3]: https://code.claude.com/docs/en/mcp?utm_source=chatgpt.com "Connect Claude Code to tools via MCP"

