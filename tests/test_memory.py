"""Tests for cccm.core.memory."""

import json
from pathlib import Path

import pytest

from cccm.core.memory import (
    DEFAULT_CONFIG,
    DEFAULT_INDEX,
    MEMORY_FILES,
    add_recent_file,
    append_event,
    ensure_dirs,
    get_latest_snapshot_text,
    load_config,
    load_index,
    save_index,
    summarize_memory,
)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return tmp_path


class TestEnsureDirs:
    def test_creates_structure(self, project_root: Path):
        paths = ensure_dirs(project_root)

        assert paths["base"].is_dir()
        assert paths["mem"].is_dir()
        assert paths["snaps"].is_dir()
        assert paths["cfg"].is_file()
        assert paths["idx"].is_file()

    def test_creates_memory_files(self, project_root: Path):
        ensure_dirs(project_root)

        for name in MEMORY_FILES:
            p = project_root / ".cccm" / "memory" / name
            assert p.exists()
            assert p.read_text().startswith("#")

    def test_idempotent(self, project_root: Path):
        ensure_dirs(project_root)
        # Write something to a memory file
        (project_root / ".cccm" / "memory" / "decisions.md").write_text("# Decisions\n\n- Use Redis\n")
        # Re-run — should NOT overwrite
        ensure_dirs(project_root)
        content = (project_root / ".cccm" / "memory" / "decisions.md").read_text()
        assert "Use Redis" in content

    def test_creates_default_config(self, project_root: Path):
        ensure_dirs(project_root)
        cfg = json.loads((project_root / ".cccm" / "config.json").read_text())
        assert "snapshot" in cfg
        assert "tracking" in cfg


class TestIndex:
    def test_load_empty(self, project_root: Path):
        index = load_index(project_root)
        assert index.get("version") == 1 or index == {}

    def test_save_and_load(self, project_root: Path):
        ensure_dirs(project_root)
        index = load_index(project_root)
        index["recent_files"] = ["foo.py"]
        save_index(project_root, index)

        reloaded = load_index(project_root)
        assert reloaded["recent_files"] == ["foo.py"]

    def test_append_event(self, project_root: Path):
        index = {"events": []}
        append_event(index, "test", {"key": "val"})
        assert len(index["events"]) == 1
        assert index["events"][0]["kind"] == "test"
        assert index["events"][0]["payload"] == {"key": "val"}
        assert "ts" in index["events"][0]

    def test_append_event_bounds(self, project_root: Path):
        index = {"events": []}
        for i in range(250):
            append_event(index, "test", {"i": i})
        assert len(index["events"]) == 200

    def test_add_recent_file(self):
        index = {"recent_files": []}
        add_recent_file(index, "a.py")
        add_recent_file(index, "b.py")
        assert index["recent_files"] == ["b.py", "a.py"]

    def test_add_recent_file_deduplicates(self):
        index = {"recent_files": ["b.py", "a.py"]}
        add_recent_file(index, "a.py")
        assert index["recent_files"] == ["a.py", "b.py"]

    def test_add_recent_file_caps_at_50(self):
        index = {"recent_files": [f"{i}.py" for i in range(55)]}
        add_recent_file(index, "new.py")
        assert len(index["recent_files"]) == 50
        assert index["recent_files"][0] == "new.py"


class TestConfig:
    def test_load_default(self, project_root: Path):
        ensure_dirs(project_root)
        cfg = load_config(project_root)
        assert cfg["snapshot"]["max_chars_injected"] == 6000
        assert "Write" in cfg["tracking"]["track_tools"]

    def test_load_custom_merges(self, project_root: Path):
        ensure_dirs(project_root)
        # Override one value
        custom = {"snapshot": {"max_chars_injected": 3000}, "tracking": {}}
        (project_root / ".cccm" / "config.json").write_text(json.dumps(custom))

        cfg = load_config(project_root)
        assert cfg["snapshot"]["max_chars_injected"] == 3000
        # Defaults still present for unset keys
        assert "max_snapshot_chars" in cfg["snapshot"]


class TestSummarizeMemory:
    def test_empty_memory(self, project_root: Path):
        ensure_dirs(project_root)
        result = summarize_memory(project_root)
        assert result == ""

    def test_with_content(self, project_root: Path):
        ensure_dirs(project_root)
        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\n- Use Redis for caching\n"
        )
        result = summarize_memory(project_root)
        assert "Redis" in result

    def test_respects_max_chars(self, project_root: Path):
        ensure_dirs(project_root)
        (project_root / ".cccm" / "memory" / "decisions.md").write_text("x" * 10000)
        result = summarize_memory(project_root, max_chars=100)
        assert len(result) <= 100


class TestLatestSnapshot:
    def test_no_snapshot(self, project_root: Path):
        ensure_dirs(project_root)
        result = get_latest_snapshot_text(project_root)
        assert result == ""

    def test_with_snapshot(self, project_root: Path):
        ensure_dirs(project_root)
        # Write a fake snapshot
        snap = project_root / ".cccm" / "snapshots" / "test.md"
        snap.write_text("# Test snapshot\nContent here.")

        index = load_index(project_root)
        index["last_snapshot"] = ".cccm/snapshots/test.md"
        save_index(project_root, index)

        result = get_latest_snapshot_text(project_root)
        assert "Test snapshot" in result
