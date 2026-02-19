"""Tests for cccm.core.search — keyword-based memory search."""

from pathlib import Path

import pytest

from cccm.core.memory import ensure_dirs, load_index, save_index
from cccm.core.search import find_relevant_memory, search_memory, tokenize


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    ensure_dirs(tmp_path)
    return tmp_path


class TestTokenize:
    def test_basic(self):
        assert tokenize("Hello World") == {"hello", "world"}

    def test_with_code(self):
        tokens = tokenize("def my_function(arg1, arg2):")
        assert "my_function" in tokens
        assert "arg1" in tokens

    def test_empty(self):
        assert tokenize("") == set()

    def test_numbers(self):
        tokens = tokenize("Python 3.10 support")
        assert "python" in tokens
        assert "3" in tokens
        assert "10" in tokens


class TestSearchMemory:
    def test_no_match(self, project_root: Path):
        results = search_memory(project_root, "xyzzy_nonexistent_term")
        assert results == []

    def test_matches_memory_doc(self, project_root: Path):
        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\n## Use Redis for caching\nChose Redis because it supports TTL natively.\n"
        )
        results = search_memory(project_root, "Redis caching TTL")
        assert len(results) > 0
        assert results[0]["source"] == "memory/decisions.md"
        assert results[0]["score"] >= 2

    def test_matches_snapshot(self, project_root: Path):
        snap = project_root / ".cccm" / "snapshots" / "2026-01-01T00-00-00-000000Z_continuity.md"
        snap.write_text("# Continuity\n\nWorking on authentication module with JWT tokens.\n")

        results = search_memory(project_root, "authentication JWT")
        assert any("snapshots" in r["source"] for r in results)

    def test_top_k_limit(self, project_root: Path):
        for name in ("decisions.md", "constraints.md", "interfaces.md", "glossary.md"):
            (project_root / ".cccm" / "memory" / name).write_text(
                f"# {name}\n\nThis document mentions Python and testing.\n"
            )
        results = search_memory(project_root, "Python testing", top_k=2)
        assert len(results) <= 2

    def test_empty_query(self, project_root: Path):
        assert search_memory(project_root, "") == []

    def test_tags_filter(self, project_root: Path):
        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\nUse PostgreSQL.\n"
        )
        (project_root / ".cccm" / "memory" / "constraints.md").write_text(
            "# Constraints\n\nMust use PostgreSQL.\n"
        )
        results = search_memory(project_root, "PostgreSQL", tags=["decisions"])
        assert all("decisions" in r["source"] for r in results)


class TestFindRelevantMemory:
    def test_no_relevant(self, project_root: Path):
        result = find_relevant_memory(project_root, "xyz nonexistent term")
        assert result == ""

    def test_finds_relevant(self, project_root: Path):
        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\n## Database choice\nDecided to use PostgreSQL for the user service "
            "because it handles complex queries well and supports JSON columns.\n"
        )
        result = find_relevant_memory(project_root, "database PostgreSQL user service queries")
        assert "PostgreSQL" in result

    def test_respects_max_chars(self, project_root: Path):
        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\n" + "PostgreSQL is great. " * 500
        )
        result = find_relevant_memory(project_root, "PostgreSQL database", max_chars=200)
        assert len(result) <= 200 + 100  # Allow some header overhead

    def test_short_prompt_ignored(self, project_root: Path):
        result = find_relevant_memory(project_root, "hi")
        assert result == ""
