"""Tests for GuardState, StepRecord, and TriggerResult.

Covers:
- StepRecord: defaults, custom fields, multiple output types
- GuardState: empty state, step accumulation, cost tracking
- History bound enforcement (T3 mitigation — prevent memory exhaustion)
- Thread-safe concurrent access with multiple writers
- TriggerResult: construction and to_dict serialisation

Design notes:
- GuardState.total_tokens is cumulative across ALL steps, not just the
  bounded history — truncation only affects the steps list, not totals.
- add_step() acquires _lock per call, so concurrent writes are safe
  but reads of steps/total_tokens outside the lock are not synchronised.
  This is intentional — read consistency is not required, write safety is.
"""

import threading

from ai_loopguard._internal.state import GuardState, StepRecord, TriggerResult

# ── StepRecord tests ─────────────────────────────────────────────────


class TestStepRecord:
    """Tests for StepRecord dataclass — per-step agent output record."""

    def test_defaults(self) -> None:
        """Default StepRecord: optional fields are None, cost fields are 0."""
        record = StepRecord(step_num=0, output="test")
        assert record.step_num == 0
        assert record.output == "test"
        # Error-related fields — None when function doesn't raise
        assert record.error is None
        assert record.error_type is None
        assert record.error_message is None
        # Trigger-related fields — None when not applicable
        assert record.test_results is None
        assert record.schema_valid is None
        # Cost tracking — zero until a model call is recorded
        assert record.tokens_used == 0
        assert record.cost_usd == 0.0
        assert record.timestamp == 0.0

    def test_custom_values(self) -> None:
        """All fields are settable via the constructor keyword arguments."""
        record = StepRecord(
            step_num=1,
            output={"key": "value"},
            error=ValueError("bad"),
            error_type="ValueError",
            error_message="bad",
            test_results={"test_a": True},
            schema_valid=False,
            tokens_used=100,
            cost_usd=0.002,
            timestamp=1234567890.0,
        )
        # Every field is independently settable — verify round-trip
        assert record.step_num == 1
        assert record.error_type == "ValueError"
        assert record.test_results == {"test_a": True}
        assert record.schema_valid is False
        assert record.tokens_used == 100
        assert record.cost_usd == 0.002
        assert record.timestamp == 1234567890.0

    def test_output_can_be_any_type(self) -> None:
        """Output field accepts str, dict, list, None, and int."""
        # Agent outputs vary widely — the field must accept all valid types
        for output in ["str", {"dict": 1}, [1, 2], None, 42]:
            record = StepRecord(step_num=0, output=output)
            # Use identity check (is) to verify exact object preservation
            assert record.output is output


# ── TriggerResult tests ──────────────────────────────────────────────


class TestTriggerResult:
    """Tests for TriggerResult dataclass — result of a trigger firing."""

    def test_create(self) -> None:
        """TriggerResult stores trigger name, detail, and retry count."""
        result = TriggerResult(
            trigger_name="repeated_error",
            detail="ValueError: bad, 3 consecutive",
            retry_count=3,
        )
        assert result.trigger_name == "repeated_error"
        assert result.retry_count == 3

    def test_to_dict(self) -> None:
        """to_dict() serialises to a flat dict for logging/context."""
        result = TriggerResult(
            trigger_name="test_failure",
            detail="test_parser failed 3x",
            retry_count=3,
        )
        d = result.to_dict()
        # Serialisation is used by context packaging and logging
        assert d["trigger_name"] == "test_failure"
        assert d["detail"] == "test_parser failed 3x"
        assert d["retry_count"] == 3

    def test_to_dict_keys(self) -> None:
        """to_dict() returns exactly three keys — no extras, no omissions."""
        result = TriggerResult("custom", "detail", 1)
        d = result.to_dict()
        # Stable key set — consumers depend on these exact keys
        assert set(d.keys()) == {"trigger_name", "detail", "retry_count"}


# ── GuardState tests ─────────────────────────────────────────────────


class TestGuardState:
    """Tests for GuardState — per-execution state with thread-safe locking."""

    def test_empty_state(self) -> None:
        """A new GuardState is empty with zero totals."""
        state = GuardState()
        assert len(state.steps) == 0
        assert state.escalation_count == 0
        assert state.total_tokens == 0
        assert state.total_cost_usd == 0.0

    def test_add_step(self) -> None:
        """add_step() appends a record and increments totals."""
        state = GuardState()
        record = StepRecord(
            step_num=0, output="result", tokens_used=50, cost_usd=0.001
        )
        state.add_step(record)
        # Single step: history has 1 entry, totals match the step's values
        assert len(state.steps) == 1
        assert state.total_tokens == 50
        assert state.total_cost_usd == 0.001

    def test_multiple_steps(self) -> None:
        """Multiple add_step calls accumulate tokens and cost correctly."""
        state = GuardState()
        for i in range(5):
            state.add_step(
                StepRecord(
                    step_num=i,
                    output=f"result_{i}",
                    tokens_used=10,
                    cost_usd=0.0001,
                )
            )
        # 5 steps × 10 tokens = 50 total; ignores history bound (5 < 100)
        assert len(state.steps) == 5
        assert state.total_tokens == 50
        assert state.total_cost_usd == 0.0005

    def test_history_bound_enforced(self) -> None:
        """History truncation keeps only the newest steps (T3 mitigation)."""
        state = GuardState(max_history_steps=3)
        for i in range(10):
            state.add_step(
                StepRecord(
                    step_num=i, output=f"result_{i}", tokens_used=1, cost_usd=0.0
                )
            )
        # Only the last 3 steps survive
        assert len(state.steps) == 3
        # Oldest retained is step 7 (steps 0-6 discarded)
        assert state.steps[0].step_num == 7
        # Newest is step 9
        assert state.steps[-1].step_num == 9

    def test_history_bound_exact(self) -> None:
        """Adding exactly max_history_steps items does NOT truncate."""
        state = GuardState(max_history_steps=5)
        for i in range(5):
            state.add_step(StepRecord(step_num=i, output=i))
        # Truncation only fires when len > max, not len == max
        # (uses >, not >=)
        assert len(state.steps) == 5

    def test_thread_safety(self) -> None:
        """5 threads × 100 concurrent adds should complete without errors."""
        state = GuardState()
        errors: list[Exception] = []

        def add_steps() -> None:
            try:
                for i in range(100):
                    state.add_step(
                        StepRecord(
                            step_num=i,
                            output=f"result_{i}",
                            tokens_used=1,
                            cost_usd=0.0,
                        )
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_steps) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # No thread should have errored
        assert len(errors) == 0
        # History bounded to 100 (default max_history_steps)
        assert len(state.steps) == 100
        # Totals accumulate 500 steps worth of tokens (not truncated)
        # total_tokens is NOT bounded by history truncation — it's cumulative
        assert state.total_tokens == 500

    def test_custom_max_history_steps(self) -> None:
        """Custom max_history_steps should be stored and different from default."""
        state = GuardState(max_history_steps=10)
        assert state.max_history_steps == 10
