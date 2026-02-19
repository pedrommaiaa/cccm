"""CCCM MCP server — exposes memory tools to Claude Code."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Log to stderr only — stdout is reserved for MCP protocol
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cccm-mcp] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

mcp = FastMCP("cccm-memory")


def _get_root() -> Path:
    """Resolve the project root from env or cwd."""
    root = os.environ.get("CCCM_PROJECT_ROOT") or os.getcwd()
    return Path(root).resolve()


@mcp.tool()
async def memory_search(query: str, top_k: int = 5) -> str:
    """Search project memory for relevant information.

    Searches across memory docs (decisions, constraints, interfaces, glossary)
    and recent snapshots using keyword matching.

    Args:
        query: What to search for (keywords, topics, or questions)
        top_k: Maximum number of results to return (default 5)
    """
    from cccm.core.search import search_memory

    root = _get_root()
    results = search_memory(root, query, top_k=top_k)

    if not results:
        return "No matching memory found."

    parts: list[str] = []
    for r in results:
        # Truncate content for readability
        content = r["content"][:800]
        parts.append(f"**[{r['source']}]** (score: {r['score']})\n{content}")

    return "\n\n---\n\n".join(parts)


@mcp.tool()
async def memory_write(doc_type: str, content: str) -> str:
    """Write to a project memory document.

    Appends content to one of the persistent memory documents.
    These documents survive context compaction and are used to maintain
    project continuity.

    Args:
        doc_type: Which memory doc to write to. One of: decisions, constraints, interfaces, glossary
        content: The content to append (markdown format recommended)
    """
    from cccm.core.memory import ensure_dirs, safe_read_text, utc_timestamp

    root = _get_root()
    ensure_dirs(root)

    valid_types = ("decisions", "constraints", "interfaces", "glossary")
    if doc_type not in valid_types:
        return f"Invalid doc_type '{doc_type}'. Must be one of: {', '.join(valid_types)}"

    mem_path = root / ".cccm" / "memory" / f"{doc_type}.md"
    timestamp = utc_timestamp()

    entry = f"\n## {timestamp}\n\n{content.strip()}\n"

    with open(mem_path, "a", encoding="utf-8") as f:
        f.write(entry)

    logger.info(f"Wrote to memory/{doc_type}.md: {len(content)} chars")
    return f"Appended to memory/{doc_type}.md ({len(content)} chars)"


@mcp.tool()
async def memory_latest() -> str:
    """Get the latest continuity snapshot.

    Returns the most recent continuity packet, which contains the project's
    current state, decisions, constraints, recent files, and next actions.
    """
    from cccm.core.memory import get_latest_snapshot_text

    root = _get_root()
    text = get_latest_snapshot_text(root, max_chars=8000)

    if not text:
        return "No snapshots found. Run `cccm snapshot` or wait for automatic snapshot creation."

    return text


@mcp.tool()
async def memory_status() -> str:
    """Show CCCM memory system status.

    Returns current state: last snapshot, tracked files count, recent events.
    """
    import json

    from cccm.core.memory import load_index

    root = _get_root()
    index = load_index(root)

    status = {
        "project_root": str(root),
        "last_snapshot": index.get("last_snapshot", "(none)"),
        "tracked_files": len(index.get("recent_files", [])),
        "events_logged": len(index.get("events", [])),
        "recent_files": index.get("recent_files", [])[:10],
    }
    return json.dumps(status, indent=2)


def main() -> None:
    """Run the CCCM MCP server with stdio transport."""
    logger.info("Starting CCCM MCP memory server")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
