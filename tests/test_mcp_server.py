"""Tests for cccm.mcp_server — MCP memory server tools."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cccm.core.memory import ensure_dirs, load_index, save_index
from cccm.core.snapshot import create_snapshot


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    ensure_dirs(tmp_path)
    return tmp_path


class TestMemorySearch:
    @pytest.mark.asyncio
    async def test_no_results(self, project_root: Path):
        from cccm.mcp_server import memory_search

        with patch("cccm.mcp_server._get_root", return_value=project_root):
            result = await memory_search("xyzzy_nonexistent", top_k=5)
        assert "No matching" in result

    @pytest.mark.asyncio
    async def test_finds_match(self, project_root: Path):
        from cccm.mcp_server import memory_search

        (project_root / ".cccm" / "memory" / "decisions.md").write_text(
            "# Decisions\n\n## Caching\nChose Redis for caching because it supports TTL.\n"
        )

        with patch("cccm.mcp_server._get_root", return_value=project_root):
            result = await memory_search("Redis caching TTL", top_k=5)
        assert "Redis" in result
        assert "score" in result


class TestMemoryWrite:
    @pytest.mark.asyncio
    async def test_write_decision(self, project_root: Path):
        from cccm.mcp_server import memory_write

        with patch("cccm.mcp_server._get_root", return_value=project_root):
            result = await memory_write("decisions", "Use gRPC for service communication")
        assert "Appended" in result

        content = (project_root / ".cccm" / "memory" / "decisions.md").read_text()
        assert "gRPC" in content

    @pytest.mark.asyncio
    async def test_invalid_doc_type(self, project_root: Path):
        from cccm.mcp_server import memory_write

        with patch("cccm.mcp_server._get_root", return_value=project_root):
            result = await memory_write("invalid_type", "content")
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_write_all_types(self, project_root: Path):
        from cccm.mcp_server import memory_write

        for doc_type in ("decisions", "constraints", "interfaces", "glossary"):
            with patch("cccm.mcp_server._get_root", return_value=project_root):
                result = await memory_write(doc_type, f"Test content for {doc_type}")
            assert "Appended" in result


class TestMemoryLatest:
    @pytest.mark.asyncio
    async def test_no_snapshot(self, project_root: Path):
        from cccm.mcp_server import memory_latest

        with patch("cccm.mcp_server._get_root", return_value=project_root):
            result = await memory_latest()
        assert "No snapshots" in result

    @pytest.mark.asyncio
    async def test_returns_snapshot(self, project_root: Path):
        from cccm.mcp_server import memory_latest

        create_snapshot(project_root)

        with patch("cccm.mcp_server._get_root", return_value=project_root):
            result = await memory_latest()
        assert "Continuity Packet" in result


class TestMemoryStatus:
    @pytest.mark.asyncio
    async def test_returns_status(self, project_root: Path):
        from cccm.mcp_server import memory_status

        with patch("cccm.mcp_server._get_root", return_value=project_root):
            result = await memory_status()

        status = json.loads(result)
        assert "project_root" in status
        assert "last_snapshot" in status
        assert "tracked_files" in status
