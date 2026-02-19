"""Tests for V1 hook handlers — UserPromptSubmit, Stop, enhanced SubagentStart."""

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from cccm.core.memory import ensure_dirs, load_index
from cccm.hooks.runner import (
    handle_stop,
    handle_subagent_start,
    handle_user_prompt_submit,
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


class TestUserPromptSubmit:
    def test_no_injection_on_short_prompt(self, project_root: Path):
        result = capture_stdout(handle_user_prompt_submit, project_root, {"prompt": "hi"})
        assert result == {}

    def test_no_injection_when_no_match(self, project_root: Path):
        result = capture_stdout(handle_user_prompt_submit, project_root, {
            "prompt": "Tell me about xyzzy_nonexistent_thing_12345"
        })
        assert result == {}

    def test_injects_when_memory_matches(self, project_root: Path):
        # Populate memory with content
        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\n## Database\nDecided to use PostgreSQL for the user service "
            "because it handles complex queries and JSON columns well.\n"
        )

        result = capture_stdout(handle_user_prompt_submit, project_root, {
            "prompt": "Let's work on the PostgreSQL database schema for the user service"
        })

        if "hookSpecificOutput" in result:
            ctx = result["hookSpecificOutput"]["additionalContext"]
            assert "PostgreSQL" in ctx
            assert "project memory" in ctx.lower() or "CCCM" in ctx

    def test_empty_prompt(self, project_root: Path):
        result = capture_stdout(handle_user_prompt_submit, project_root, {"prompt": ""})
        assert result == {}


class TestStop:
    def test_noop_when_stop_hook_active(self, project_root: Path):
        result = capture_stdout(handle_stop, project_root, {
            "stop_hook_active": True,
            "last_assistant_message": "We decided to use Redis because it's fast.",
        })
        assert result == {}

    def test_captures_decision(self, project_root: Path):
        message = (
            "After reviewing the options, we decided to use PostgreSQL for the "
            "user service because it handles complex queries well and supports "
            "JSON columns natively."
        )
        capture_stdout(handle_stop, project_root, {
            "stop_hook_active": False,
            "last_assistant_message": message,
        })

        # Check if decision was captured
        content = (project_root / ".cccm" / "memory" / "decisions.md").read_text()
        assert "PostgreSQL" in content

    def test_no_capture_on_nondecision(self, project_root: Path):
        message = "Here is the implementation of the function. It computes the sum of two numbers."
        capture_stdout(handle_stop, project_root, {
            "stop_hook_active": False,
            "last_assistant_message": message,
        })

        content = (project_root / ".cccm" / "memory" / "decisions.md").read_text()
        # Should still be the default header only
        assert "sum of two" not in content

    def test_no_capture_when_disabled(self, project_root: Path):
        import json as json_mod

        # Disable decision tracking in config
        cfg_path = project_root / ".cccm" / "config.json"
        cfg = json_mod.loads(cfg_path.read_text())
        cfg["tracking"] = {"track_decisions": False}
        cfg_path.write_text(json_mod.dumps(cfg))

        message = "We decided to use Redis because it's the fastest option available."
        capture_stdout(handle_stop, project_root, {
            "stop_hook_active": False,
            "last_assistant_message": message,
        })

        content = (project_root / ".cccm" / "memory" / "decisions.md").read_text()
        assert "Redis" not in content

    def test_logs_event_on_capture(self, project_root: Path):
        message = (
            "We chose to implement caching with Redis because it provides "
            "native TTL support and pub/sub capabilities."
        )
        capture_stdout(handle_stop, project_root, {
            "stop_hook_active": False,
            "last_assistant_message": message,
        })

        index = load_index(project_root)
        events = index.get("events", [])
        assert any(e["kind"] == "decision_captured" for e in events)


class TestEnhancedSubagentStart:
    def test_bash_agent_strict(self, project_root: Path):
        result = capture_stdout(handle_subagent_start, project_root, {
            "agent_type": "Bash",
        })

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "max 3 lines" in ctx
        assert "concise" in ctx.lower()

    def test_explore_agent_gets_memory(self, project_root: Path):
        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\n## Architecture\nUsing microservices with gRPC.\n"
        )

        result = capture_stdout(handle_subagent_start, project_root, {
            "agent_type": "Explore",
        })

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "thorough" in ctx.lower()
        assert "gRPC" in ctx

    def test_plan_agent_gets_memory(self, project_root: Path):
        (project_root / ".cccm" / "memory" / "constraints.md").write_text(
            "# Constraints\n\n- Must use Python 3.10+\n"
        )

        result = capture_stdout(handle_subagent_start, project_root, {
            "agent_type": "Plan",
        })

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "tradeoffs" in ctx.lower()
        assert "Python 3.10" in ctx

    def test_unknown_agent_gets_default(self, project_root: Path):
        result = capture_stdout(handle_subagent_start, project_root, {
            "agent_type": "CustomAgent",
        })

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "RESULT" in ctx
        assert "WHY" in ctx

    def test_logs_agent_type(self, project_root: Path):
        capture_stdout(handle_subagent_start, project_root, {
            "agent_type": "Explore",
        })

        index = load_index(project_root)
        events = index.get("events", [])
        subagent_events = [e for e in events if e["kind"] == "subagent_start"]
        assert len(subagent_events) > 0
        assert subagent_events[-1]["payload"]["agent_type"] == "Explore"
