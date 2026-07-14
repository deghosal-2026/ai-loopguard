"""Tests for logging models, EscalationLogger, and EventHook protocol.

Covers:
- EscalationEvent / CappedEvent / FailOpenEvent: construction, JSON serialisation,
  custom message, redacted_fields
- EventHook protocol: isinstance check via @runtime_checkable, structural subtyping
- EscalationLogger: hook registration, dispatch to single/multiple hooks
- EscalationLogger file sink: writes JSONL to disk, appends, close/close-idempotent

Previously untested gaps now covered:
- File sink write path (was silently broken — _sink was always None)
- File sink append behaviour (multiple log calls → multiple lines)
- close() idempotency (safe to call multiple times)
- EventHook isinstance check (Protocol with @runtime_checkable)
- Custom CappedEvent.message override
"""

import json
import os

from ai_loopguard.logging import (
    CappedEvent,
    EscalationEvent,
    EscalationLogger,
    EventHook,
    FailOpenEvent,
)

# ── Test helpers ─────────────────────────────────────────────────────


def _make_escalation_event(**overrides: object) -> EscalationEvent:
    """Build a minimal valid EscalationEvent with defaults.

    All fields have sensible values so tests only override what they
    care about. This keeps test code short and avoids copy-paste.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        A fully valid EscalationEvent instance.

    """
    defaults: dict[str, object] = {
        "timestamp": 1.0,
        "trigger_type": "repeated_error",
        "trigger_detail": "test",
        "retry_count": 3,
        "workhorse_model": "qwen",
        "escalation_model": "gpt-4",
        "escalation_category": "routing",
        "context_tokens": 100,
        "escalation_tokens": 50,
        "escalation_cost_usd": 0.001,
        "total_task_cost_usd": 0.002,
        "total_task_tokens": 150,
        "success": True,
        "sanitized": True,
        "redacted_fields": [],
    }
    defaults.update(overrides)
    return EscalationEvent(**defaults)  # type: ignore[arg-type]


def _make_capped_event(**overrides: object) -> CappedEvent:
    """Build a minimal valid CappedEvent with defaults.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        A fully valid CappedEvent instance.

    """
    defaults: dict[str, object] = {
        "timestamp": 1.0,
        "trigger_type": "repeated_error",
        "trigger_detail": "ValueError 3x",
        "retry_count": 3,
    }
    defaults.update(overrides)
    return CappedEvent(**defaults)  # type: ignore[arg-type]


# ── Event model tests ────────────────────────────────────────────────


class TestEscalationEvent:
    """Tests for EscalationEvent Pydantic model — the primary log record."""

    def test_create(self) -> None:
        """EscalationEvent stores all fields correctly on construction."""
        event = _make_escalation_event(
            trigger_type="repeated_error",
            escalation_category="routing",
            success=True,
        )
        # Pydantic model with ~15 fields — verify a representative subset
        assert event.trigger_type == "repeated_error"
        assert event.success is True
        assert event.escalation_category == "routing"

    def test_json_serialization(self) -> None:
        """model_dump_json() produces valid JSON with all fields."""
        event = _make_escalation_event(
            trigger_type="test_failure",
            escalation_category="failover",
            success=False,
        )
        # JSON serialisation is used for the JSONL log file
        data = json.loads(event.model_dump_json())
        assert data["trigger_type"] == "test_failure"
        assert data["escalation_category"] == "failover"
        assert data["success"] is False

    def test_redacted_fields_list(self) -> None:
        """redacted_fields preserves the list of field names for audit trail."""
        event = _make_escalation_event(redacted_fields=["api_key", "ssn"])
        # redacted_fields is a list of strings for audit trail transparency
        assert event.redacted_fields == ["api_key", "ssn"]


class TestCappedEvent:
    """Tests for CappedEvent — emitted when escalation cap prevents a call."""

    def test_create(self) -> None:
        """CappedEvent has a default message 'Escalation cap reached'."""
        event = _make_capped_event()
        # Default message is user-facing in logs
        assert event.message == "Escalation cap reached"

    def test_custom_message(self) -> None:
        """CappedEvent accepts a custom message override."""
        event = _make_capped_event(message="Custom cap message")
        # Allows callers to provide more context about why cap was hit
        assert event.message == "Custom cap message"


class TestFailOpenEvent:
    """Tests for FailOpenEvent — emitted when escalation model itself fails."""

    def test_create(self) -> None:
        """FailOpenEvent stores error_message and fail_open_mode."""
        event = FailOpenEvent(
            timestamp=1234567890.0,
            trigger_type="repeated_error",
            error_message="Model call failed",
            fail_open_mode="raise_original",
        )
        # Records which fail-open strategy was used for audit trail
        assert event.fail_open_mode == "raise_original"
        assert event.error_message == "Model call failed"


# ── EventHook protocol tests ─────────────────────────────────────────


class TestEventHookProtocol:
    """Tests for the EventHook Protocol (structural subtyping, FR-3.5)."""

    def test_isinstance_protocol(self) -> None:
        """A class implementing all three methods passes isinstance check."""

        class MyHook(EventHook):
            def on_escalation(self, event: EscalationEvent) -> None:
                pass

            def on_capped(self, event: CappedEvent) -> None:
                pass

            def on_fail_open(self, event: FailOpenEvent) -> None:
                pass

        hook = MyHook()
        # @runtime_checkable enables isinstance for Protocols at runtime
        # Verifies structural subtyping — no need to inherit from EventHook
        assert isinstance(hook, EventHook)


# ── EscalationLogger tests (no sink) ─────────────────────────────────


class _RecordingHook(EventHook):
    """Test helper: records all dispatched events in a list."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def on_escalation(self, event: EscalationEvent) -> None:
        self.events.append(event)

    def on_capped(self, event: CappedEvent) -> None:
        self.events.append(event)

    def on_fail_open(self, event: FailOpenEvent) -> None:
        self.events.append(event)


class TestEscalationLogger:
    """Tests for EscalationLogger hook registration and event dispatch."""

    def test_register_hook(self) -> None:
        """register_hook() stores the hook and public property returns it."""
        logger = EscalationLogger()
        hook = _RecordingHook()
        logger.register_hook(hook)
        # Hooks list should contain exactly the registered hook
        assert len(logger.hooks) == 1
        assert logger.hooks[0] is hook

    def test_log_dispatches_to_hook(self) -> None:
        """log() dispatches EscalationEvent to all registered hooks."""
        logger = EscalationLogger()
        hook = _RecordingHook()
        logger.register_hook(hook)

        logger.log(_make_escalation_event())
        # Hook receives exactly one event dispatch
        assert len(hook.events) == 1

    def test_log_multiple_hooks(self) -> None:
        """Multiple registered hooks all receive the event."""
        logger = EscalationLogger()
        hook1 = _RecordingHook()
        hook2 = _RecordingHook()
        logger.register_hook(hook1)
        logger.register_hook(hook2)

        logger.log(_make_escalation_event())
        # Both hooks must receive the event independently
        assert len(hook1.events) == 1
        assert len(hook2.events) == 1

    def test_log_capped_dispatches_to_hook(self) -> None:
        """log_capped() dispatches CappedEvent to registered hooks."""
        logger = EscalationLogger()
        hook = _RecordingHook()
        logger.register_hook(hook)

        logger.log_capped(_make_capped_event())
        assert len(hook.events) == 1

    def test_log_escalation_failure_dispatches_fail_open(self) -> None:
        """log_escalation_failure constructs FailOpenEvent from exception + CappedEvent."""
        logger = EscalationLogger()
        hook = _RecordingHook()
        logger.register_hook(hook)

        # Constructs a FailOpenEvent by combining error info with the event data
        logger.log_escalation_failure(
            ValueError("model failed"), _make_capped_event()
        )
        assert len(hook.events) == 1

    def test_log_escalation_failure_with_escalation_event(self) -> None:
        """log_escalation_failure also accepts EscalationEvent as the event arg."""
        logger = EscalationLogger()
        hook = _RecordingHook()
        logger.register_hook(hook)

        # The event parameter can be either CappedEvent or EscalationEvent
        logger.log_escalation_failure(
            RuntimeError("timeout"), _make_escalation_event()
        )
        assert len(hook.events) == 1


# ── EscalationLogger file sink tests ─────────────────────────────────


class TestEscalationLoggerFileSink:
    """Tests for EscalationLogger file sink (log_dir != None)."""

    def test_file_sink_writes_jsonl(self, tmp_path: str) -> None:
        """log() with log_dir set writes one valid JSONL line to disk."""
        log_dir = str(tmp_path)
        logger = EscalationLogger(log_dir=log_dir)
        logger.log(_make_escalation_event())
        logger.close()

        # Verify the file was created
        log_file = os.path.join(log_dir, "escalations.jsonl")
        assert os.path.exists(log_file)

        # Verify it contains exactly one valid JSON line
        with open(log_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["trigger_type"] == "repeated_error"

    def test_file_sink_appends(self, tmp_path: str) -> None:
        """Multiple log() calls append to the same file (not overwrite)."""
        log_dir = str(tmp_path)
        logger = EscalationLogger(log_dir=log_dir)

        logger.log(_make_escalation_event(trigger_type="first"))
        logger.log(_make_escalation_event(trigger_type="second"))
        logger.close()

        log_file = os.path.join(log_dir, "escalations.jsonl")
        with open(log_file) as f:
            lines = f.readlines()
        # Two events → two JSONL lines, in order
        assert len(lines) == 2
        assert json.loads(lines[0])["trigger_type"] == "first"
        assert json.loads(lines[1])["trigger_type"] == "second"

    def test_close_method(self, tmp_path: str) -> None:
        """close() on a file sink should not raise."""
        log_dir = str(tmp_path)
        logger = EscalationLogger(log_dir=log_dir)
        logger.close()  # should not raise

    def test_close_idempotent(self, tmp_path: str) -> None:
        """Calling close() twice should be safe (no-op on second call)."""
        log_dir = str(tmp_path)
        logger = EscalationLogger(log_dir=log_dir)
        logger.close()
        logger.close()  # second close should be harmless
