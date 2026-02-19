"""Tests for cccm.hooks.runner — hook event handlers."""

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from cccm.core.memory import ensure_dirs, load_index, save_index
from cccm.core.snapshot import create_snapshot
from cccm.hooks.runner import (
    _extract_file_path,
    handle_post_tool_use,
    handle_pre_compact,
    handle_session_start,
    handle_subagent_start,
)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    ensure_dirs(tmp_path)
    return tmp_path


def capture_stdout(handler, root: Path, hook_input: dict) -> dict:
    """Run a handler and capture its JSON output."""
    buf = StringIO()
    with patch("sys.stdout", buf):
        handler(root, hook_input)
    raw = buf.getvalue().strip()
    return json.loads(raw) if raw else {}


class TestSessionStart:
    def test_fresh_startup(self, project_root: Path):
        result = capture_stdout(handle_session_start, project_root, {"source": "startup"})

        assert "hookSpecificOutput" in result
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "CCCM active" in ctx

    def test_after_compaction_with_snapshot(self, project_root: Path):
        # Create a snapshot first
        create_snapshot(project_root)

        result = capture_stdout(handle_session_start, project_root, {"source": "compact"})

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "CCCM active" in ctx
        assert "Continuity Packet" in ctx

    def test_after_resume_without_snapshot(self, project_root: Path):
        result = capture_stdout(handle_session_start, project_root, {"source": "resume"})

        # Should still work, just lighter injection
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "CCCM active" in ctx


class TestPreCompact:
    def test_creates_snapshot(self, project_root: Path):
        result = capture_stdout(handle_pre_compact, project_root, {
            "trigger": "auto",
            "cwd": str(project_root),
        })

        assert "hookSpecificOutput" in result
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "compact" in ctx.lower()
        assert "preserve" in ctx.lower()

        # Should have created a snapshot file
        snaps = list((project_root / ".cccm" / "snapshots").glob("*_continuity.md"))
        assert len(snaps) == 1

    def test_includes_memory_in_snapshot(self, project_root: Path):
        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\n- Use gRPC for service communication\n"
        )

        result = capture_stdout(handle_pre_compact, project_root, {
            "trigger": "manual",
            "cwd": str(project_root),
        })

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "gRPC" in ctx


class TestPostToolUse:
    def test_tracks_write(self, project_root: Path):
        result = capture_stdout(handle_post_tool_use, project_root, {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/foo.py", "content": "..."},
        })

        index = load_index(project_root)
        assert "/tmp/foo.py" in index["recent_files"]

    def test_tracks_edit(self, project_root: Path):
        result = capture_stdout(handle_post_tool_use, project_root, {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/bar.py", "old_string": "a", "new_string": "b"},
        })

        index = load_index(project_root)
        assert "/tmp/bar.py" in index["recent_files"]

    def test_ignores_untracked_tool(self, project_root: Path):
        result = capture_stdout(handle_post_tool_use, project_root, {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/baz.py"},
        })

        index = load_index(project_root)
        assert "/tmp/baz.py" not in index.get("recent_files", [])

    def test_silent_output(self, project_root: Path):
        result = capture_stdout(handle_post_tool_use, project_root, {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/foo.py"},
        })
        # Should return empty JSON (no context injection on every tool call)
        assert result == {}


class TestSubagentStart:
    def test_injects_brevity_rules(self, project_root: Path):
        result = capture_stdout(handle_subagent_start, project_root, {
            "agent_type": "Bash",
        })

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "RESULT" in ctx
        assert "WHY" in ctx
        assert "REFS" in ctx
        assert "verbose" in ctx.lower()

    def test_logs_event(self, project_root: Path):
        capture_stdout(handle_subagent_start, project_root, {
            "agent_type": "Explore",
        })

        index = load_index(project_root)
        events = index.get("events", [])
        assert any(e["kind"] == "subagent_start" for e in events)


class TestExtractFilePath:
    def test_file_path_key(self):
        assert _extract_file_path({"file_path": "/a/b.py"}) == "/a/b.py"

    def test_path_key(self):
        assert _extract_file_path({"path": "/a/b.py"}) == "/a/b.py"

    def test_nested_in_edits(self):
        result = _extract_file_path({
            "edits": [{"file_path": "/a/b.py", "old": "x", "new": "y"}]
        })
        assert result == "/a/b.py"

    def test_no_path(self):
        assert _extract_file_path({"command": "ls"}) is None

    def test_empty_dict(self):
        assert _extract_file_path({}) is None

    def test_non_dict(self):
        assert _extract_file_path("string") is None
