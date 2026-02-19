#!/usr/bin/env python3
"""CCCM hook runner — entry point for Claude Code hook events.

Called by Claude Code hooks with event name as argv[1] and JSON on stdin.
Outputs JSON to stdout per the hooks API contract.

Performance-critical: each hook spawns a fresh Python process, so we use lazy
imports to only load modules each handler actually needs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# I/O helpers — no heavy imports needed
# ---------------------------------------------------------------------------

def read_stdin_json() -> dict[str, Any]:
    try:
        raw = sys.stdin.buffer.read()
    except AttributeError:
        raw = sys.stdin.read().encode()
    if not raw or raw.isspace():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _write_stdout(data: str) -> None:
    """Write to stdout using buffer when available (faster), with fallback."""
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        buf.write(data.encode())
        buf.flush()
    else:
        sys.stdout.write(data)
        sys.stdout.flush()


def out_json(obj: dict[str, Any]) -> None:
    _write_stdout(json.dumps(obj, ensure_ascii=False))


def noop() -> None:
    _write_stdout("{}")


# ---------------------------------------------------------------------------
# Response builders (per hooks API)
# ---------------------------------------------------------------------------

def additional_context(event_name: str, text: str) -> dict[str, Any]:
    """Build a hookSpecificOutput with additionalContext."""
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }


# ---------------------------------------------------------------------------
# Event handlers — lazy imports per handler
# ---------------------------------------------------------------------------

def handle_session_start(root: Path, hook_input: dict[str, Any]) -> None:
    """SessionStart — inject memory after compaction/resume, light protocol on fresh start."""
    from cccm.core.memory import (
        append_event, ensure_dirs, get_latest_snapshot_text,
        load_config, load_index, save_index,
    )
    ensure_dirs(root)
    index = load_index(root)
    source = hook_input.get("source", "startup")

    protocol = (
        "CCCM active.\n"
        "Rules:\n"
        "1) Keep outputs high-signal — no verbose reasoning.\n"
        "2) Subagents must return: RESULT / WHY / REFS only.\n"
        "3) Project memory lives in .cccm/memory/*.md — treat as authoritative.\n"
        "4) If context is tight, rely on the Continuity Packet.\n"
    )

    if source in ("compact", "resume"):
        config = load_config(root)
        max_inject = config.get("snapshot", {}).get("max_chars_injected", 6000)
        snap_text = get_latest_snapshot_text(root, max_chars=max_inject)

        if snap_text:
            payload = protocol + "\n---\nLatest Continuity Packet:\n\n" + snap_text
            append_event(index, "session_start_injected", {"source": source})
            save_index(root, index)
            out_json(additional_context("SessionStart", payload))
            return

    # Fresh startup — light injection
    append_event(index, "session_start", {"source": source})
    save_index(root, index)
    out_json(additional_context("SessionStart", protocol))


def handle_pre_compact(root: Path, hook_input: dict[str, Any]) -> None:
    """PreCompact — snapshot current state and inject preservation guidance."""
    from cccm.core.memory import ensure_dirs, load_config
    from cccm.core.snapshot import create_snapshot

    ensure_dirs(root)
    snap_text, snap_path = create_snapshot(root, hook_input)

    config = load_config(root)
    max_inject = config.get("snapshot", {}).get("max_chars_injected", 6000)
    inject_text = snap_text[:max_inject]

    guidance = (
        "About to compact context.\n"
        "Compaction MUST preserve:\n"
        "- The user's current objective and any constraints they gave\n"
        "- Decisions/constraints/interfaces from .cccm/memory/*.md\n"
        "- The recent files touched list\n"
        "- Any explicit TODO / Next Actions\n"
        "\n"
        "Use the following Continuity Packet as source of truth:\n\n"
        + inject_text
    )

    out_json(additional_context("PreCompact", guidance))


# Default tracked tools — avoids loading config.json on every tool call
_DEFAULT_TRACKED_TOOLS = frozenset(("Write", "Edit", "MultiEdit", "Bash"))

FILE_PATH_KEYS = ("file_path", "path", "filepath", "target", "filename")


def handle_post_tool_use(root: Path, hook_input: dict[str, Any]) -> None:
    """PostToolUse — track file changes. Optimized: hottest path, fires every tool call."""
    tool_name = hook_input.get("tool_name", "")

    # Fast reject — no config load needed for the common case
    if tool_name not in _DEFAULT_TRACKED_TOOLS:
        noop()
        return

    tool_input = hook_input.get("tool_input") or {}
    file_path = _extract_file_path(tool_input)
    if not file_path:
        noop()
        return

    # Only now do we need the heavy imports
    from cccm.core.memory import add_recent_file, append_event, load_index, save_index

    index = load_index(root)
    add_recent_file(index, file_path)
    append_event(index, "tool", {"tool_name": tool_name, "file": file_path})
    save_index(root, index)
    noop()


def handle_subagent_start(root: Path, hook_input: dict[str, Any]) -> None:
    """SubagentStart — inject per-agent-type rules and relevant memory."""
    from cccm.core.memory import (
        append_event, ensure_dirs, load_config, load_index,
        save_index, summarize_memory,
    )
    ensure_dirs(root)
    index = load_index(root)
    config = load_config(root)

    agent_type = hook_input.get("agent_type", "unknown")
    budgets = config.get("agent_budgets", {})

    msg = _build_agent_instructions(agent_type, budgets, root)

    append_event(index, "subagent_start", {"agent_type": agent_type})
    save_index(root, index)
    out_json(additional_context("SubagentStart", msg))


def handle_user_prompt_submit(root: Path, hook_input: dict[str, Any]) -> None:
    """UserPromptSubmit — inject relevant memory when prompt matches stored knowledge."""
    prompt = hook_input.get("prompt", "")

    # Fast reject before any imports
    if not prompt or len(prompt) < 10:
        noop()
        return

    from cccm.core.memory import (
        append_event, ensure_dirs, load_config, load_index, save_index,
    )
    from cccm.core.search import find_relevant_memory

    ensure_dirs(root)
    config = load_config(root)
    max_inject = config.get("prompt_inject", {}).get("max_chars", 2000)

    relevant = find_relevant_memory(root, prompt, max_chars=max_inject)
    if not relevant:
        noop()
        return

    injection = (
        "Relevant project memory (from CCCM):\n"
        "---\n"
        + relevant
        + "\n---"
    )

    index = load_index(root)
    append_event(index, "prompt_memory_injected", {"prompt_len": len(prompt)})
    save_index(root, index)
    out_json(additional_context("UserPromptSubmit", injection))


def handle_stop(root: Path, hook_input: dict[str, Any]) -> None:
    """Stop — auto-capture decisions from assistant's last message."""
    if hook_input.get("stop_hook_active"):
        noop()
        return

    last_message = hook_input.get("last_assistant_message", "")
    if not last_message or len(last_message) < 80:
        noop()
        return

    from cccm.core.decisions import append_decision, detect_decision, extract_decision_summary
    from cccm.core.memory import (
        append_event, ensure_dirs, load_config, load_index, save_index,
    )

    ensure_dirs(root)
    config = load_config(root)

    if not config.get("tracking", {}).get("track_decisions", True):
        noop()
        return

    if detect_decision(last_message):
        summary = extract_decision_summary(last_message)
        written = append_decision(root, summary)
        if written:
            index = load_index(root)
            append_event(index, "decision_captured", {"chars": len(summary)})
            save_index(root, index)

    noop()


# ---------------------------------------------------------------------------
# Per-agent budgeting
# ---------------------------------------------------------------------------

DEFAULT_AGENT_BUDGETS = {
    "Bash": {
        "max_output_lines": 10,
        "inject_memory": False,
        "instructions": (
            "Subagent protocol (CCCM):\n"
            "- Output ONLY structured results:\n"
            "  RESULT: (what was done/decided)\n"
            "  WHY: (max 3 lines)\n"
            "  REFS: (files/commands)\n"
            "- NO verbose reasoning. Be extremely concise.\n"
        ),
    },
    "Explore": {
        "max_output_lines": 30,
        "inject_memory": True,
        "instructions": (
            "Subagent protocol (CCCM):\n"
            "- Output structured results:\n"
            "  RESULT: (findings)\n"
            "  WHY: (max 15 lines of analysis)\n"
            "  REFS: (files/commands)\n"
            "- Be thorough but structured. No filler.\n"
        ),
    },
    "Plan": {
        "max_output_lines": 30,
        "inject_memory": True,
        "instructions": (
            "Subagent protocol (CCCM):\n"
            "- Output structured results:\n"
            "  RESULT: (plan or recommendation)\n"
            "  WHY: (max 15 lines of rationale)\n"
            "  REFS: (files/commands)\n"
            "- Include tradeoffs when relevant.\n"
        ),
    },
    "_default": {
        "max_output_lines": 15,
        "inject_memory": False,
        "instructions": (
            "Subagent protocol (CCCM):\n"
            "- Output ONLY structured results:\n"
            "  RESULT: (what was done/decided)\n"
            "  WHY: (max 8 lines)\n"
            "  REFS: (files/commands)\n"
            "- NO verbose reasoning, NO long plans, NO restating the problem.\n"
            "- If uncertain, propose 2-3 options with tradeoffs, then pick one.\n"
        ),
    },
}


def _build_agent_instructions(agent_type: str, config_budgets: dict, root: Path) -> str:
    """Build per-agent instructions based on type and config."""
    from cccm.core.memory import summarize_memory

    budgets = {**DEFAULT_AGENT_BUDGETS}
    for key, val in config_budgets.items():
        if key in budgets and isinstance(val, dict):
            budgets[key] = {**budgets[key], **val}
        else:
            budgets[key] = val

    budget = budgets.get(agent_type, budgets["_default"])
    msg = budget.get("instructions", budgets["_default"]["instructions"])

    if budget.get("inject_memory"):
        mem_summary = summarize_memory(root, max_chars=1500)
        if mem_summary:
            msg += "\n---\nProject memory (for reference):\n" + mem_summary[:1500] + "\n"

    return msg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_file_path(tool_input: dict[str, Any]) -> str | None:
    """Try to extract a file path from various tool input shapes."""
    if not isinstance(tool_input, dict):
        return None

    for key in FILE_PATH_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            return val

    for list_key in ("files", "edits"):
        items = tool_input.get(list_key)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            for key in FILE_PATH_KEYS:
                val = items[0].get(key)
                if isinstance(val, str) and val:
                    return val

    return None


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

HANDLERS = {
    "session_start": handle_session_start,
    "pre_compact": handle_pre_compact,
    "post_tool_use": handle_post_tool_use,
    "subagent_start": handle_subagent_start,
    "user_prompt_submit": handle_user_prompt_submit,
    "stop": handle_stop,
}


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    hook_input = read_stdin_json()

    cwd = hook_input.get("cwd") or os.getcwd()
    root = Path(cwd).resolve()

    handler = HANDLERS.get(event)
    if handler:
        try:
            handler(root, hook_input)
        except Exception as e:
            print(f"cccm: {event} error: {e}", file=sys.stderr)
            noop()
    else:
        noop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
