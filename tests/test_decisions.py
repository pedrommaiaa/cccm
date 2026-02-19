"""Tests for cccm.core.decisions — auto-decision capture."""

from pathlib import Path

import pytest

from cccm.core.decisions import append_decision, detect_decision, extract_decision_summary
from cccm.core.memory import ensure_dirs, safe_read_text


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    ensure_dirs(tmp_path)
    return tmp_path


class TestDetectDecision:
    def test_explicit_decision(self):
        assert detect_decision(
            "After evaluating both options, we decided to use PostgreSQL "
            "for the user service because it handles complex queries well."
        )

    def test_chose_pattern(self):
        assert detect_decision(
            "We chose Redis over Memcached for caching because Redis supports "
            "data structures like sorted sets which we need for leaderboards."
        )

    def test_going_with(self):
        assert detect_decision(
            "Going with JWT tokens instead of session cookies because our "
            "architecture is stateless and we need to scale horizontally."
        )

    def test_architecture_because(self):
        assert detect_decision(
            "The architecture design decision is to use microservices because "
            "we need independent deployment and scaling per team."
        )

    def test_short_message_not_detected(self):
        assert not detect_decision("Use Redis.")

    def test_no_decision_keywords(self):
        assert not detect_decision(
            "Here is the implementation of the function. It takes two arguments "
            "and returns the sum. Let me know if you need changes."
        )

    def test_instead_of_pattern(self):
        assert detect_decision(
            "We will use TypeScript instead of JavaScript for the frontend "
            "because the type safety catches bugs at compile time due to our large codebase."
        )


class TestExtractDecisionSummary:
    def test_extracts_decision_lines(self):
        message = (
            "Let me analyze the options.\n"
            "Looking at the requirements...\n"
            "We decided to use PostgreSQL because it handles JSON well.\n"
            "This means we need to update the schema.\n"
            "Here's the implementation plan.\n"
        )
        summary = extract_decision_summary(message)
        assert "PostgreSQL" in summary
        assert "decided" in summary

    def test_respects_max_chars(self):
        message = "We decided to " + "x" * 1000 + " because reasons."
        summary = extract_decision_summary(message, max_chars=100)
        assert len(summary) <= 100

    def test_fallback_to_beginning(self):
        message = "No decision keywords here. Just a long message about stuff. " * 10
        summary = extract_decision_summary(message, max_chars=200)
        assert len(summary) <= 200


class TestAppendDecision:
    def test_appends_to_file(self, project_root: Path):
        written = append_decision(project_root, "Use Redis for caching")
        assert written is True

        content = safe_read_text(project_root / ".cccm" / "memory" / "decisions.md")
        assert "Use Redis for caching" in content
        assert "Auto-captured" in content

    def test_avoids_duplicates(self, project_root: Path):
        append_decision(project_root, "Use Redis for caching")
        written = append_decision(project_root, "Use Redis for caching")
        assert written is False

    def test_multiple_decisions(self, project_root: Path):
        append_decision(project_root, "Use Redis for caching")
        append_decision(project_root, "Use PostgreSQL for persistence")

        content = safe_read_text(project_root / ".cccm" / "memory" / "decisions.md")
        assert "Redis" in content
        assert "PostgreSQL" in content
