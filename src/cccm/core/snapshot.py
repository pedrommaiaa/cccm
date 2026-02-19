"""Snapshot engine — builds and manages Continuity Packets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cccm.core.memory import (
    append_event,
    ensure_dirs,
    load_config,
    load_index,
    save_index,
    summarize_memory,
    utc_timestamp,
)


def build_snapshot_text(
    root: Path,
    index: dict[str, Any],
    hook_input: dict[str, Any] | None = None,
) -> str:
    """Build a continuity packet as a markdown string."""
    hook_input = hook_input or {}

    mem_summary = summarize_memory(root, max_chars=12000)
    recent_files = index.get("recent_files", [])[:20]
    files_block = "\n".join(f"- {p}" for p in recent_files) if recent_files else "- (none tracked yet)"

    session_id = hook_input.get("session_id", "manual")
    cwd = hook_input.get("cwd", str(root))
    transcript = hook_input.get("transcript_path", "")

    lines = [
        "# CCCM Continuity Packet",
        "",
        f"- Timestamp (UTC): {utc_timestamp()}",
        f"- Session: {session_id}",
        f"- CWD: {cwd}",
    ]
    if transcript:
        lines.append(f"- Transcript: {transcript}")

    lines += [
        "",
        "## What to preserve through compaction",
        "- Current objective and next steps (from user prompt)",
        "- Decisions + constraints in .cccm/memory/*",
        "- Interfaces/APIs noted in interfaces.md",
        "- Recent files touched (below)",
        "",
        "## Recent files touched",
        files_block,
        "",
        "## Project memory (authoritative)",
        mem_summary if mem_summary else "_(memory docs empty — populate .cccm/memory/*.md)_",
    ]

    return "\n".join(lines)


def save_snapshot(root: Path, content: str) -> Path:
    """Write snapshot to .cccm/snapshots/ and update index. Returns snapshot path."""
    paths = ensure_dirs(root)
    config = load_config(root)
    index = load_index(root)

    max_chars = config.get("snapshot", {}).get("max_snapshot_chars", 25000)
    trimmed = content[:max_chars]

    snap_name = f"{utc_timestamp()}_continuity.md"
    snap_path = paths["snaps"] / snap_name
    snap_path.write_text(trimmed, encoding="utf-8")

    # Update index
    rel_path = str(snap_path.relative_to(root))
    index["last_snapshot"] = rel_path
    append_event(index, "snapshot", {"path": rel_path})
    save_index(root, index)

    # Prune old snapshots
    max_snapshots = config.get("snapshot", {}).get("max_snapshots", 50)
    _prune_snapshots(paths["snaps"], max_snapshots)

    return snap_path


def create_snapshot(
    root: Path,
    hook_input: dict[str, Any] | None = None,
) -> tuple[str, Path]:
    """Build and save a snapshot. Returns (text, path)."""
    index = load_index(root)
    text = build_snapshot_text(root, index, hook_input)
    path = save_snapshot(root, text)
    return text, path


def _prune_snapshots(snaps_dir: Path, max_keep: int) -> None:
    """Remove oldest snapshots if exceeding max_keep."""
    files = sorted(snaps_dir.glob("*_continuity.md"))
    if len(files) <= max_keep:
        return
    for old in files[: len(files) - max_keep]:
        try:
            old.unlink()
        except OSError:
            pass
