"""Unit tests for the loopguard CLI (analyze command).

Tests JSONL loading, event parsing, filtering, and summary output
using Click's CliRunner.  Typer was replaced with Click due to a
positional-argument bug in Typer 0.25.1 on Python 3.14.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from ai_loopguard.cli import EventLog, analyze, load_jsonl

runner = CliRunner()


# ── Sample log data ────────────────────────────────────────────────────────

_SAMPLE_EVENTS: list[dict[str, Any]] = [
    {
        "timestamp": 1000.0,
        "trigger_type": "repeated_error",
        "trigger_detail": "ValueError 3 consecutive",
        "retry_count": 3,
        "workhorse_model": "qwen2.5",
        "escalation_model": "gpt-4-turbo",
        "escalation_category": "failover",
        "context_tokens": 500,
        "escalation_tokens": 200,
        "escalation_cost_usd": 0.01,
        "total_task_cost_usd": 0.05,
        "total_task_tokens": 700,
        "success": True,
        "sanitized": True,
        "redacted_fields": [],
    },
    {
        "timestamp": 2000.0,
        "trigger_type": "test_failure",
        "trigger_detail": "tests failed 3 consecutive",
        "retry_count": 3,
        "workhorse_model": "claude-3",
        "escalation_model": "gpt-4",
        "escalation_category": "routing",
        "context_tokens": 300,
        "escalation_tokens": 150,
        "escalation_cost_usd": 0.005,
        "total_task_cost_usd": 0.02,
        "total_task_tokens": 500,
        "success": True,
        "sanitized": False,
        "redacted_fields": ["api_key"],
    },
]


def _write_log(path: Path, events: list[dict[str, Any]]) -> None:
    """Write events as JSONL to a file."""
    with path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


# ── load_jsonl ─────────────────────────────────────────────────────────────


class TestLoadJSONL:
    """Tests for the load_jsonl function."""

    def test_loads_jsonl_file(self) -> None:
        """Load JSONL file returns parsed events."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = Path(f.name)
            _write_log(path, _SAMPLE_EVENTS)

        try:
            events = load_jsonl(str(path))
            assert len(events) == 2
        finally:
            path.unlink()

    def test_skips_malformed_lines(self) -> None:
        """Malformed JSONL lines are skipped with warning."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = Path(f.name)
            f.write(json.dumps(_SAMPLE_EVENTS[0]) + "\n")
            f.write("not valid json\n")
            f.write(json.dumps(_SAMPLE_EVENTS[1]) + "\n")
            f.flush()
        # Malformed line between two valid lines — both valid lines are parsed
        try:
            events = load_jsonl(str(path))
            assert len(events) == 2
        finally:
            path.unlink()

    def test_empty_file_returns_empty_list(self) -> None:
        """Empty log file returns empty list."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = Path(f.name)
        # Edge case: zero-byte file must not crash
        try:
            events = load_jsonl(str(path))
            assert events == []
        finally:
            path.unlink()

    def test_skips_blank_lines(self) -> None:
        """Blank lines in the file are silently skipped."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = Path(f.name)
            f.write(json.dumps(_SAMPLE_EVENTS[0]) + "\n")
            f.write("\n")
            f.write("   \n")
            f.write(json.dumps(_SAMPLE_EVENTS[1]) + "\n")
            f.flush()
        # Blank lines and whitespace-only lines should be ignored
        try:
            events = load_jsonl(str(path))
            assert len(events) == 2
        finally:
            path.unlink()


# ── EventLog ───────────────────────────────────────────────────────────────


class TestEventLog:
    """Tests for the EventLog class."""

    def test_total_escalations(self) -> None:
        """Total escalation count matches input."""
        log = EventLog(_SAMPLE_EVENTS)
        assert log.total_escalations == 2

    def test_empty_log(self) -> None:
        """Empty log has zero escalations and zero cost."""
        log = EventLog([])
        # Edge case: empty event list must not cause division/stat errors
        assert log.total_escalations == 0
        assert log.total_cost == 0.0

    def test_total_cost(self) -> None:
        """Total cost sums all events."""
        log = EventLog(_SAMPLE_EVENTS)
        # 0.05 (event 0) + 0.02 (event 1) = 0.07
        assert log.total_cost == 0.07

    def test_trigger_breakdown(self) -> None:
        """Trigger breakdown counts events by type."""
        log = EventLog(_SAMPLE_EVENTS)
        breakdown = log.trigger_breakdown
        assert breakdown["repeated_error"] == 1
        assert breakdown["test_failure"] == 1

    def test_cost_by_trigger(self) -> None:
        """Cost grouped by trigger type is correct."""
        log = EventLog(_SAMPLE_EVENTS)
        costs = log.cost_by_trigger
        assert costs["repeated_error"] == 0.05
        assert costs["test_failure"] == 0.02

    def test_filter_trigger(self) -> None:
        """Filter by trigger type narrows results."""
        log = EventLog(_SAMPLE_EVENTS)
        log.filter_trigger("repeated_error")
        # After filtering, only 1 event remains
        assert log.total_escalations == 1
        assert log.total_cost == 0.05

    def test_filter_trigger_no_match(self) -> None:
        """Filter by non-existent trigger leaves zero events."""
        log = EventLog(_SAMPLE_EVENTS)
        log.filter_trigger("nonexistent")
        # No matching events → total is 0
        assert log.total_escalations == 0

    def test_filter_since(self) -> None:
        """Filter by date narrows results."""
        log = EventLog(_SAMPLE_EVENTS)
        since = datetime.fromtimestamp(1500, tz=timezone.utc)
        log.filter_since(since)
        # Only event at timestamp 2000 survives (1500 < 2000)
        assert log.total_escalations == 1
        assert log.events[0].trigger_type == "test_failure"

    def test_filter_since_before_all(self) -> None:
        """Filter with early date keeps all events."""
        log = EventLog(_SAMPLE_EVENTS)
        since = datetime.fromtimestamp(500, tz=timezone.utc)
        log.filter_since(since)
        # Both events have timestamps > 500
        assert log.total_escalations == 2

    def test_filter_since_after_all(self) -> None:
        """Filter with future date removes all events."""
        log = EventLog(_SAMPLE_EVENTS)
        since = datetime.fromtimestamp(99999, tz=timezone.utc)
        log.filter_since(since)
        # No events have timestamp > 99999
        assert log.total_escalations == 0

    def test_filter_model_substring_match(self) -> None:
        """Filter by model matches on substring."""
        log = EventLog(_SAMPLE_EVENTS)
        log.filter_model("gpt-4")
        # Both have "gpt-4" in their escalation_model name
        assert log.total_escalations == 2

    def test_filter_model_case_insensitive(self) -> None:
        """Model filter is case-insensitive."""
        log = EventLog(_SAMPLE_EVENTS)
        log.filter_model("GPT-4")
        # Case-insensitive substring match
        assert log.total_escalations == 2

    def test_filter_model_no_match(self) -> None:
        """Filter by non-existent model leaves zero events."""
        log = EventLog(_SAMPLE_EVENTS)
        log.filter_model("nonexistent")
        assert log.total_escalations == 0

    def test_skips_non_escalation_events(self) -> None:
        """Non-EscalationEvent lines (e.g. CappedEvent) are skipped."""
        capped: dict[str, Any] = {
            "timestamp": 1500.0,
            "trigger_type": "repeated_error",
            "trigger_detail": "cap hit",
            "retry_count": 3,
            "message": "Escalation cap reached",
        }
        fail_open: dict[str, Any] = {
            "timestamp": 1600.0,
            "trigger_type": "schema_invalid",
            "error_message": "Model failed",
            "fail_open_mode": "raise_original",
        }
        log = EventLog([_SAMPLE_EVENTS[0], capped, fail_open])
        # Only EscalationEvent-type dicts count; CappedEvent/FailOpenEvent are ignored
        assert log.total_escalations == 1

    def test_combined_filters(self) -> None:
        """Multiple filters combine (AND logic)."""
        log = EventLog(_SAMPLE_EVENTS)
        log.filter_trigger("repeated_error")
        log.filter_model("turbo")
        # Only gpt-4-turbo with repeated_error matches both filters
        assert log.total_escalations == 1

    def test_events_property_returns_copy(self) -> None:
        """Events property returns a copy, not the internal list."""
        log = EventLog(_SAMPLE_EVENTS)
        evts = log.events
        assert len(evts) == 2
        evts.clear()
        # Defensive copy: mutating returned list must not affect log internals
        assert log.total_escalations == 2


# ── CLI analyze command ────────────────────────────────────────────────────


class TestCLIAnalyze:
    """Tests for the ``loopguard analyze`` CLI command."""

    def _write_log(self, path: str, events: list[dict[str, Any]]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    def test_analyze_shows_summary(self) -> None:
        """Running analyze with a valid log shows summary."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
            self._write_log(path, _SAMPLE_EVENTS)

        try:
            result = runner.invoke(analyze, [path])
            # Happy path: valid log → exit 0 + summary stats visible
            assert result.exit_code == 0
            assert "Total escalations" in result.output
            assert "2" in result.output
            assert "repeated_error" in result.output
            assert "test_failure" in result.output
        finally:
            Path(path).unlink()

    def test_analyze_empty_log(self) -> None:
        """Empty log prints 'No escalations found'."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
        # Edge case: empty file should not crash CLI
        try:
            result = runner.invoke(analyze, [path])
            assert result.exit_code == 0
            assert "No escalations found" in result.output
        finally:
            Path(path).unlink()

    def test_analyze_trigger_filter(self) -> None:
        """--trigger filters to matching events."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
            self._write_log(path, _SAMPLE_EVENTS)

        try:
            result = runner.invoke(analyze, [path, "--trigger", "test_failure"])
            assert result.exit_code == 0
            assert "1" in result.output
        finally:
            Path(path).unlink()

    def test_analyze_model_filter(self) -> None:
        """--model filters to matching events."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
            self._write_log(path, _SAMPLE_EVENTS)

        try:
            result = runner.invoke(analyze, [path, "--model", "turbo"])
            assert result.exit_code == 0
            assert "1" in result.output
        finally:
            Path(path).unlink()

    def test_analyze_since_filter(self) -> None:
        """--since filters by date."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
            self._write_log(path, _SAMPLE_EVENTS)

        try:
            result = runner.invoke(analyze, [path, "--since", "1970-01-01"])
            assert result.exit_code == 0
            assert "2" in result.output
        finally:
            Path(path).unlink()

    def test_analyze_since_filter_excludes_old(self) -> None:
        """--since with a future date shows no events."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
            self._write_log(path, _SAMPLE_EVENTS)

        try:
            result = runner.invoke(analyze, [path, "--since", "2030-01-01"])
            assert result.exit_code == 0
            assert "No escalations found" in result.output
        finally:
            Path(path).unlink()

    def test_analyze_invalid_date_returns_error(self) -> None:
        """Invalid --since date prints error and exits with code 1."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
            self._write_log(path, _SAMPLE_EVENTS)

        try:
            result = runner.invoke(analyze, [path, "--since", "not-a-date"])
            # User error → exit code 1 with descriptive message
            assert result.exit_code == 1
            assert "invalid date format" in result.output.lower()
        finally:
            Path(path).unlink()

    def test_analyze_nonexistent_file(self) -> None:
        """Nonexistent log file exits with error."""
        result = runner.invoke(analyze, ["/nonexistent/path.jsonl"])
        # File not found → non-zero exit code
        assert result.exit_code != 0

    def test_analyze_no_summary_flag(self) -> None:
        """--no-summary suppresses summary output."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
            self._write_log(path, _SAMPLE_EVENTS)

        try:
            result = runner.invoke(analyze, [path, "--no-summary"])
            assert result.exit_code == 0
            assert "Total escalations" not in result.output
        finally:
            Path(path).unlink()

    def test_analyze_malformed_lines_skipped(self) -> None:
        """Malformed JSONL lines are skipped, valid ones processed."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
            f.write(json.dumps(_SAMPLE_EVENTS[0]) + "\n")
            f.write("not valid json\n")
            f.write(json.dumps(_SAMPLE_EVENTS[1]) + "\n")
            f.flush()

        try:
            result = runner.invoke(analyze, [path])
            # 2 valid events despite 1 malformed line
            assert result.exit_code == 0
            assert "2" in result.output
        finally:
            Path(path).unlink()

    def test_analyze_combined_filters(self) -> None:
        """Multiple filters combine correctly."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name
            self._write_log(path, _SAMPLE_EVENTS)

        try:
            result = runner.invoke(
                analyze,
                [path, "--trigger", "repeated_error", "--model", "turbo"],
            )
            # --trigger AND --model must both match (AND logic)
            assert result.exit_code == 0
            assert "1" in result.output
        finally:
            Path(path).unlink()
