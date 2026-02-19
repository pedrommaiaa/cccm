"""Tests for cccm.core.snapshot."""

from pathlib import Path

import pytest

from cccm.core.memory import ensure_dirs, load_index
from cccm.core.snapshot import build_snapshot_text, create_snapshot, save_snapshot


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    ensure_dirs(tmp_path)
    return tmp_path


class TestBuildSnapshotText:
    def test_basic_output(self, project_root: Path):
        index = load_index(project_root)
        text = build_snapshot_text(project_root, index)

        assert "# CCCM Continuity Packet" in text
        assert "Timestamp (UTC):" in text
        assert "Recent files touched" in text
        assert "Project memory" in text

    def test_includes_recent_files(self, project_root: Path):
        index = load_index(project_root)
        index["recent_files"] = ["src/main.py", "tests/test_main.py"]

        text = build_snapshot_text(project_root, index)
        assert "src/main.py" in text
        assert "tests/test_main.py" in text

    def test_includes_memory(self, project_root: Path):
        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\n- Use PostgreSQL\n"
        )
        index = load_index(project_root)
        text = build_snapshot_text(project_root, index)
        assert "PostgreSQL" in text

    def test_includes_hook_metadata(self, project_root: Path):
        index = load_index(project_root)
        hook_input = {
            "session_id": "abc123",
            "cwd": "/tmp/test",
            "transcript_path": "/tmp/transcript.json",
        }
        text = build_snapshot_text(project_root, index, hook_input)
        assert "abc123" in text
        assert "/tmp/transcript.json" in text


class TestCreateSnapshot:
    def test_creates_file(self, project_root: Path):
        text, path = create_snapshot(project_root)

        assert path.exists()
        assert path.suffix == ".md"
        assert "_continuity" in path.name
        assert "CCCM Continuity Packet" in text

    def test_updates_index(self, project_root: Path):
        _, path = create_snapshot(project_root)

        index = load_index(project_root)
        assert index["last_snapshot"] is not None
        assert "continuity" in index["last_snapshot"]

    def test_multiple_snapshots(self, project_root: Path):
        _, path1 = create_snapshot(project_root)
        _, path2 = create_snapshot(project_root)

        assert path1 != path2
        assert path1.exists()
        assert path2.exists()


class TestSaveSnapshot:
    def test_respects_max_chars(self, project_root: Path):
        # Override config to small max
        import json
        cfg_path = project_root / ".cccm" / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["snapshot"] = {"max_snapshot_chars": 100, "max_snapshots": 50}
        cfg_path.write_text(json.dumps(cfg))

        long_content = "x" * 500
        path = save_snapshot(project_root, long_content)

        saved = path.read_text()
        assert len(saved) <= 100

    def test_prunes_old_snapshots(self, project_root: Path):
        import json
        cfg_path = project_root / ".cccm" / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["snapshot"] = {"max_snapshot_chars": 25000, "max_snapshots": 3}
        cfg_path.write_text(json.dumps(cfg))

        for _ in range(5):
            create_snapshot(project_root)

        snaps = list((project_root / ".cccm" / "snapshots").glob("*_continuity.md"))
        assert len(snaps) <= 3
