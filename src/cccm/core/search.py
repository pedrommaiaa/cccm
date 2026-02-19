"""Keyword-based search across memory docs and snapshots.

Optimized for speed: uses str containment checks instead of full tokenization
for scoring, and caches query tokens across calls.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cccm.core.memory import MEMORY_FILES, safe_read_text

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> set[str]:
    """Extract lowercase word tokens from text."""
    return set(_TOKEN_RE.findall(text.lower()))


def _fast_score(query_tokens: set[str], content_lower: str) -> int:
    """Fast scoring: check token presence via `in` on pre-lowered content."""
    return sum(1 for t in query_tokens if t in content_lower)


def search_memory(
    root: Path,
    query: str,
    top_k: int = 5,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search memory docs and snapshots by keyword matching.

    Returns a list of {source, content, score} dicts, sorted by relevance.
    """
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    results: list[dict[str, Any]] = []

    # Search memory docs
    mem_dir = root / ".cccm" / "memory"
    for name in MEMORY_FILES:
        if tags and not _matches_tags(name, tags):
            continue
        path = mem_dir / name
        content = safe_read_text(path, limit=50_000).strip()
        if not content:
            continue
        score = _fast_score(query_tokens, content.lower())
        if score > 0:
            results.append({"source": f"memory/{name}", "content": content, "score": score})

    # Search snapshots (latest 3 — fewer for speed)
    snaps_dir = root / ".cccm" / "snapshots"
    if snaps_dir.is_dir():
        snap_files = sorted(snaps_dir.glob("*_continuity.md"), reverse=True)[:3]
        for snap in snap_files:
            content = safe_read_text(snap, limit=50_000).strip()
            if not content:
                continue
            score = _fast_score(query_tokens, content.lower())
            if score > 0:
                results.append({
                    "source": f"snapshots/{snap.name}",
                    "content": content,
                    "score": score,
                })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def find_relevant_memory(
    root: Path,
    prompt: str,
    max_chars: int = 2000,
) -> str:
    """Find memory content relevant to a user prompt. Returns a compact string."""
    results = search_memory(root, prompt, top_k=3)
    if not results:
        return ""

    threshold = 2  # At least 2 keyword matches
    relevant = [r for r in results if r["score"] >= threshold]
    if not relevant:
        return ""

    query_tokens = tokenize(prompt)
    parts: list[str] = []
    chars = 0
    for r in relevant:
        snippet = _extract_snippet(r["content"], query_tokens, max_snippet=600)
        entry = f"[{r['source']}]\n{snippet}"
        if chars + len(entry) > max_chars:
            break
        parts.append(entry)
        chars += len(entry)

    return "\n\n".join(parts)


def _matches_tags(filename: str, tags: list[str]) -> bool:
    """Check if a memory file name matches any of the given tags."""
    name_lower = filename.lower().replace(".md", "")
    return any(tag.lower() in name_lower for tag in tags)


def _extract_snippet(content: str, query_tokens: set[str], max_snippet: int = 600) -> str:
    """Extract the most relevant portion of content around matching keywords."""
    lines = content.split("\n")
    best_score = 0
    best_idx = 0

    for i, line in enumerate(lines):
        line_lower = line.lower()
        score = sum(1 for t in query_tokens if t in line_lower)
        if score > best_score:
            best_score = score
            best_idx = i

    if best_score == 0:
        return content[:max_snippet]

    start = max(0, best_idx - 3)
    end = min(len(lines), best_idx + 8)
    snippet = "\n".join(lines[start:end])
    return snippet[:max_snippet]
