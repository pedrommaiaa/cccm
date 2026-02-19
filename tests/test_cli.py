"""Tests for cccm.cli — CLI commands."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cccm.core.memory import ensure_dirs


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    ensure_dirs(tmp_path)
    # Create .claude/settings.json with all V1 hooks
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings = {
        "hooks": {
            "SessionStart": [],
            "PreCompact": [],
            "PostToolUse": [],
            "SubagentStart": [],
            "UserPromptSubmit": [],
            "Stop": [],
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(settings))

    # Create settings.local.json with MCP server
    local_settings = {
        "mcpServers": {
            "cccm-memory": {
                "command": "python3",
                "args": ["-m", "cccm.mcp_server"],
            }
        }
    }
    (claude_dir / "settings.local.json").write_text(json.dumps(local_settings))

    # Create a CLAUDE.md with compact instructions
    (tmp_path / "CLAUDE.md").write_text("# Test\n\n## Compact Instructions\nPreserve everything.\n")

    return tmp_path


class TestInit:
    def test_init_creates_full_setup(self, tmp_path: Path, capsys):
        from cccm.cli import cmd_init
        import argparse

        args = argparse.Namespace(root=str(tmp_path))
        result = cmd_init(args)

        assert result == 0

        # .cccm/ structure
        assert (tmp_path / ".cccm").is_dir()
        assert (tmp_path / ".cccm" / "memory").is_dir()
        assert (tmp_path / ".cccm" / "config.json").is_file()

        # Hooks
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.is_file()
        settings = json.loads(settings_path.read_text())
        for event in ("SessionStart", "PreCompact", "PostToolUse",
                       "SubagentStart", "UserPromptSubmit", "Stop"):
            assert event in settings["hooks"]

        # MCP config
        local_path = tmp_path / ".claude" / "settings.local.json"
        assert local_path.is_file()
        local_cfg = json.loads(local_path.read_text())
        assert "cccm-memory" in local_cfg["mcpServers"]

        # CLAUDE.md
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.is_file()
        assert "Compact Instructions" in claude_md.read_text()

        captured = capsys.readouterr()
        assert "All checks passed" in captured.out


class TestSnapshot:
    def test_snapshot_creates_file(self, project_root: Path):
        from cccm.cli import cmd_snapshot
        import argparse

        with patch("cccm.cli.find_project_root", return_value=project_root):
            args = argparse.Namespace(show=False)
            result = cmd_snapshot(args)

        assert result == 0
        snaps = list((project_root / ".cccm" / "snapshots").glob("*_continuity.md"))
        assert len(snaps) == 1


class TestStatus:
    def test_status_runs(self, project_root: Path, capsys):
        from cccm.cli import cmd_status
        import argparse

        with patch("cccm.cli.find_project_root", return_value=project_root):
            args = argparse.Namespace()
            result = cmd_status(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Project root" in captured.out


class TestDoctor:
    def test_healthy_project(self, project_root: Path, capsys):
        from cccm.cli import cmd_doctor
        import argparse

        with patch("cccm.cli.find_project_root", return_value=project_root):
            args = argparse.Namespace()
            result = cmd_doctor(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "All checks passed" in captured.out

    def test_missing_hooks(self, project_root: Path, capsys):
        from cccm.cli import cmd_doctor
        import argparse

        # Remove settings.json
        (project_root / ".claude" / "settings.json").unlink()

        with patch("cccm.cli.find_project_root", return_value=project_root):
            args = argparse.Namespace()
            result = cmd_doctor(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "settings.json missing" in captured.out

    def test_missing_mcp_server(self, project_root: Path, capsys):
        from cccm.cli import cmd_doctor
        import argparse

        # Remove settings.local.json
        (project_root / ".claude" / "settings.local.json").unlink()

        with patch("cccm.cli.find_project_root", return_value=project_root):
            args = argparse.Namespace()
            result = cmd_doctor(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "MCP" in captured.out or "settings.local.json" in captured.out
