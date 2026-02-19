"""Memory store — manages .cccm/ directory, index, config, and memory docs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MEMORY_FILES = ("decisions.md", "constraints.md", "interfaces.md", "glossary.md")

DEFAULT_CONFIG = {
    "version": "0.2.0",
    "snapshot": {
        "max_chars_injected": 6000,
        "max_snapshot_chars": 25000,
        "max_snapshots": 50,
    },
    "tracking": {
        "track_tools": ["Write", "Edit", "MultiEdit", "Bash"],
        "track_decisions": True,
    },
    "prompt_inject": {
        "max_chars": 2000,
    },
    "agent_budgets": {},
}

DEFAULT_INDEX = {
    "version": 1,
    "last_snapshot": None,
    "recent_files": [],
    "events": [],
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")


def ensure_dirs(root: Path) -> dict[str, Path]:
    """Create .cccm/ structure if missing. Returns paths dict."""
    base = root / ".cccm"
    mem = base / "memory"
    snaps = base / "snapshots"

    base.mkdir(exist_ok=True)
    mem.mkdir(exist_ok=True)
    snaps.mkdir(exist_ok=True)

    for name in MEMORY_FILES:
        p = mem / name
        if not p.exists():
            title = name.replace(".md", "").title()
            p.write_text(f"# {title}\n\n", encoding="utf-8")

    cfg_path = base / "config.json"
    if not cfg_path.exists():
        save_json(cfg_path, DEFAULT_CONFIG)

    idx_path = base / "index.json"
    if not idx_path.exists():
        save_json(idx_path, DEFAULT_INDEX)

    return {
        "base": base,
        "mem": mem,
        "snaps": snaps,
        "cfg": cfg_path,
        "idx": idx_path,
    }


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_config(root: Path) -> dict[str, Any]:
    cfg = load_json(root / ".cccm" / "config.json")
    # Merge with defaults for any missing keys
    merged = {**DEFAULT_CONFIG}
    for section in ("snapshot", "tracking", "prompt_inject", "agent_budgets"):
        default_val = DEFAULT_CONFIG.get(section, {})
        cfg_val = cfg.get(section, {})
        if isinstance(default_val, dict) and isinstance(cfg_val, dict):
            merged[section] = {**default_val, **cfg_val}
        elif cfg_val:
            merged[section] = cfg_val
    return merged


def load_index(root: Path) -> dict[str, Any]:
    idx = load_json(root / ".cccm" / "index.json")
    if not idx:
        idx = dict(DEFAULT_INDEX)
    return idx


def save_index(root: Path, index: dict[str, Any]) -> None:
    save_json(root / ".cccm" / "index.json", index)


def append_event(index: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
    events = index.setdefault("events", [])
    events.append({"ts": utc_timestamp(), "kind": kind, "payload": payload})
    # Keep bounded
    max_events = 200
    if len(events) > max_events:
        index["events"] = events[-max_events:]


def add_recent_file(index: dict[str, Any], file_path: str) -> None:
    recent = index.setdefault("recent_files", [])
    if file_path in recent:
        recent.remove(file_path)
    recent.insert(0, file_path)
    index["recent_files"] = recent[:50]


def safe_read_text(path: Path, limit: int = 200_000) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
        return data[:limit]
    except (FileNotFoundError, PermissionError):
        return ""


def summarize_memory(root: Path, max_chars: int = 8000) -> str:
    """Read all memory docs and combine into a summary string."""
    mem_dir = root / ".cccm" / "memory"
    parts: list[str] = []

    for name in MEMORY_FILES:
        txt = safe_read_text(mem_dir / name, limit=max_chars).strip()
        if txt and txt != f"# {name.replace('.md', '').title()}":
            parts.append(txt)

    combined = "\n\n---\n\n".join(parts)
    return combined[:max_chars]


def get_latest_snapshot_text(root: Path, max_chars: int = 12000) -> str:
    """Read the latest snapshot file content."""
    index = load_index(root)
    last = index.get("last_snapshot")
    if not last:
        return ""
    snap_path = root / last
    return safe_read_text(snap_path, limit=max_chars)
