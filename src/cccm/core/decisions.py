"""Auto-decision capture — detect and record architectural decisions."""

from __future__ import annotations

import re
from pathlib import Path

from cccm.core.memory import ensure_dirs, safe_read_text, utc_timestamp

# Patterns that suggest a decision was made
DECISION_PATTERNS = [
    r"\b(?:decided|choosing|chose|selected|going with|picked|opting for|will use|switched to)\b",
    r"\b(?:architecture|design decision|trade-?off|approach)\b.*\b(?:because|since|due to|for)\b",
    r"\b(?:instead of|rather than|over|prefer(?:red)?)\b.*\b(?:because|since|due to|for)\b",
]

# Minimum message length to consider (short messages are unlikely decisions)
MIN_MESSAGE_LENGTH = 80

# Maximum decisions to keep in the file
MAX_DECISIONS = 100


def detect_decision(message: str) -> bool:
    """Check if a message contains a decision-like statement."""
    if len(message) < MIN_MESSAGE_LENGTH:
        return False

    message_lower = message.lower()

    # Must match at least one decision pattern
    for pattern in DECISION_PATTERNS:
        if re.search(pattern, message_lower):
            return True

    return False


def extract_decision_summary(message: str, max_chars: int = 500) -> str:
    """Extract the most decision-relevant portion of a message."""
    lines = message.strip().split("\n")

    # Look for lines containing decision keywords
    decision_keywords = {
        "decided", "chose", "selected", "going with", "will use",
        "because", "instead of", "trade-off", "approach", "architecture",
    }

    relevant: list[str] = []
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if any(kw in line_lower for kw in decision_keywords):
            # Include this line and some context
            start = max(0, i - 1)
            end = min(len(lines), i + 3)
            relevant.extend(lines[start:end])

    if relevant:
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for line in relevant:
            if line not in seen:
                seen.add(line)
                unique.append(line)
        return "\n".join(unique)[:max_chars]

    # Fallback: return beginning of message
    return message[:max_chars]


def append_decision(root: Path, summary: str) -> bool:
    """Append a decision entry to .cccm/memory/decisions.md. Returns True if written."""
    ensure_dirs(root)
    decisions_path = root / ".cccm" / "memory" / "decisions.md"

    existing = safe_read_text(decisions_path, limit=200_000)

    # Avoid duplicates — check if this summary is already recorded
    if summary.strip()[:100] in existing:
        return False

    timestamp = utc_timestamp()
    entry = f"\n## {timestamp} — Auto-captured\n\n{summary.strip()}\n"

    # Append to file
    with open(decisions_path, "a", encoding="utf-8") as f:
        f.write(entry)

    # Prune if too many entries
    _prune_decisions(decisions_path)

    return True


def _prune_decisions(path: Path) -> None:
    """Keep only the latest MAX_DECISIONS entries."""
    content = safe_read_text(path, limit=500_000)
    # Split on ## headings (each decision starts with ##)
    parts = re.split(r"(?=^## )", content, flags=re.MULTILINE)

    # First part is the header (# Decisions ...)
    header = parts[0] if parts else "# Decisions\n\n"
    entries = parts[1:] if len(parts) > 1 else []

    if len(entries) <= MAX_DECISIONS:
        return

    # Keep only latest entries
    kept = entries[-MAX_DECISIONS:]
    pruned = header + "".join(kept)
    path.write_text(pruned, encoding="utf-8")
