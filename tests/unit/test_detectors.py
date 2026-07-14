"""Tests for FailureDetector — all four trigger implementations.

Covers:
- repeated_error: FR-1.1 — same error N consecutive steps
- test_failure: FR-1.2 — same test fails N consecutive or oscillates
- schema_invalid: FR-1.3 — flag is False for N consecutive steps
- custom: FR-1.5 — user callback returns True
- Threshold boundaries, empty history, single step
- Evaluation order per SPEC §3.3
- Disabled triggers
- Guard helper methods (record_test_results, record_schema_valid)
- Consecutiveness enforcement (success breaks error chain, etc.)
"""

import pytest

from ai_loopguard._internal.state import GuardState, StepRecord
from ai_loopguard.config import GuardConfig, TriggerConfig
from ai_loopguard.detectors import FailureDetector
from ai_loopguard.exceptions import TriggerError
from ai_loopguard.guard import Guard


def _build_state(steps: list[StepRecord]) -> GuardState:
    """Build a GuardState from a list of StepRecords."""
    state = GuardState(max_history_steps=100)
    for s in steps:
        state.add_step(s)
    return state


# ── repeated_error trigger (FR-1.1) ────────────────────────────────────


class TestRepeatedError:
    """Tests for the repeated_error trigger (FR-1.1)."""

    def test_three_consecutive_same_error_fires(self) -> None:
        """3 consecutive identical errors → trigger fires."""
        detector = FailureDetector.from_defaults(repeated_error_max_retries=3)
        # Core pattern: same error_type AND same error_message across N steps
        steps = [
            StepRecord(step_num=i, output=None, error=ValueError("fail"),
                       error_type="ValueError", error_message="fail")
            for i in range(3)
        ]
        state = _build_state(steps)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "repeated_error"
        assert "ValueError" in result.detail
        assert "3 consecutive" in result.detail

    def test_two_consecutive_no_fire(self) -> None:
        """2 consecutive same errors → no fire when max_retries=3."""
        detector = FailureDetector.from_defaults(repeated_error_max_retries=3)
        # Boundary: N-1 steps should NOT trigger — tests the > threshold, not >=
        steps = [
            StepRecord(step_num=i, output=None, error=ValueError("fail"),
                       error_type="ValueError", error_message="fail")
            for i in range(2)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_different_errors_no_fire(self) -> None:
        """Different error types or messages → no fire."""
        detector = FailureDetector.from_defaults(repeated_error_max_retries=3)
        # Both error_type AND error_message must match — different types don't trigger
        steps = [
            StepRecord(step_num=0, output=None, error=ValueError("a"),
                       error_type="ValueError", error_message="a"),
            StepRecord(step_num=1, output=None, error=TypeError("b"),
                       error_type="TypeError", error_message="b"),
            StepRecord(step_num=2, output=None, error=ValueError("c"),
                       error_type="ValueError", error_message="c"),
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_different_message_same_type_no_fire(self) -> None:
        """Same error type but different messages → no fire."""
        detector = FailureDetector.from_defaults(repeated_error_max_retries=3)
        # Same error_type ("ValueError") but unique messages — message must also match
        steps = [
            StepRecord(step_num=i, output=None, error=ValueError(f"msg_{i}"),
                       error_type="ValueError", error_message=f"msg_{i}")
            for i in range(3)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_mixed_success_and_error(self) -> None:
        """A single success + 2 errors → no fire (success breaks chain + insuff)."""
        detector = FailureDetector.from_defaults(repeated_error_max_retries=3)
        # Two issues: success at step 0 means no error to count, and only 2 errors < 3
        steps = [
            StepRecord(step_num=0, output="ok"),
            StepRecord(step_num=1, output=None, error=ValueError("fail"),
                       error_type="ValueError", error_message="fail"),
            StepRecord(step_num=2, output=None, error=ValueError("fail"),
                       error_type="ValueError", error_message="fail"),
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_success_breaks_error_chain(self) -> None:
        """A success step between errors breaks the consecutive chain (S3-BUG-001)."""
        detector = FailureDetector.from_defaults(repeated_error_max_retries=3)
        # Regression: must only count CONSECUTIVE errors from the tail; a success
        # anywhere earlier means the chain is broken even if count >= threshold
        steps = [
            StepRecord(step_num=0, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x"),
            StepRecord(step_num=1, output="ok"),  # success breaks consecutiveness
            StepRecord(step_num=2, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x"),
            StepRecord(step_num=3, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x"),
        ]
        state = _build_state(steps)
        # Last 3 steps = [success(1), error(2), error(3)]
        # Step 1 has no error → breaks chain → no fire
        assert detector.check(state) is None

    def test_threshold_boundary(self) -> None:
        """Exactly N fires, N-1 doesn't, N+1 still fires once."""
        detector = FailureDetector.from_defaults(repeated_error_max_retries=3)

        # N-1 = 2 → no fire
        # Boundary: confirms the trigger uses strict >, not >=
        state_2 = _build_state([
            StepRecord(step_num=i, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x")
            for i in range(2)
        ])
        assert detector.check(state_2) is None

        # N = 3 → fires
        # Exactly at threshold — the minimum to trigger
        state_3 = _build_state([
            StepRecord(step_num=i, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x")
            for i in range(3)
        ])
        assert detector.check(state_3) is not None

        # N+1 = 4 → still fires once
        # Verifies the trigger doesn't double-fire on over-threshold
        state_4 = _build_state([
            StepRecord(step_num=i, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x")
            for i in range(4)
        ])
        result = detector.check(state_4)
        assert result is not None
        assert result.trigger_name == "repeated_error"

    def test_custom_max_retries(self) -> None:
        """Configurable retry threshold (max_retries=5) works."""
        detector = FailureDetector.from_defaults(repeated_error_max_retries=5)
        # 4 errors but threshold is 5 — proves threshold is NOT hardcoded
        steps = [
            StepRecord(step_num=i, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x")
            for i in range(4)
        ]
        state = _build_state(steps)
        # 4 < 5 → no fire
        assert detector.check(state) is None

        # 5th error now meets the custom threshold
        steps.append(
            StepRecord(step_num=4, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x"),
        )
        state = _build_state(steps)
        assert detector.check(state) is not None


# ── test_failure trigger (FR-1.2) ──────────────────────────────────────


class TestTestFailure:
    """Tests for the test_failure trigger (FR-1.2)."""

    def test_same_test_fails_consecutive(self) -> None:
        """Same test fails 3 consecutive times → fires."""
        detector = FailureDetector.from_defaults()
        # The detector must track each test name independently; only "test_a"
        # failing 3x triggers, even if other tests pass
        steps = [
            StepRecord(step_num=i, output="x",
                       test_results={"test_a": False})
            for i in range(3)
        ]
        state = _build_state(steps)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "test_failure"
        assert "test_a" in result.detail

    def test_oscillation_fires(self) -> None:
        """Pass → fail → pass → fail (4 steps) → fires (S3-BUG-004 fixed)."""
        detector = FailureDetector.from_defaults()
        # Oscillation pattern: the same test alternates True/False repeatedly.
        # This is a distinct detection mode from consecutive failures.
        # Minimum window: 4 steps showing the alternation.
        steps = [
            StepRecord(step_num=0, output="x", test_results={"t": True}),
            StepRecord(step_num=1, output="x", test_results={"t": False}),
            StepRecord(step_num=2, output="x", test_results={"t": True}),
            StepRecord(step_num=3, output="x", test_results={"t": False}),
        ]
        state = _build_state(steps)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "test_failure"
        assert "oscillating" in result.detail
        # retry_count should be the oscillation window (4), not max_retries
        assert result.retry_count == 4

    def test_oscillation_fail_pass_fail_pass(self) -> None:
        """Fail → pass → fail → pass (alternating, starts with False)."""
        detector = FailureDetector.from_defaults()
        # Same oscillation pattern but starting with False instead of True —
        # the detector must handle both entry points symmetrically
        steps = [
            StepRecord(step_num=0, output="x", test_results={"t": False}),
            StepRecord(step_num=1, output="x", test_results={"t": True}),
            StepRecord(step_num=2, output="x", test_results={"t": False}),
            StepRecord(step_num=3, output="x", test_results={"t": True}),
        ]
        state = _build_state(steps)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "test_failure"
        assert "fail -> pass -> fail -> pass" in result.detail

    def test_different_tests_fail_no_fire(self) -> None:
        """Different tests fail → no fire (not the same test failing)."""
        detector = FailureDetector.from_defaults()
        # test_a fails at step 0 and 2, test_b fails at step 1 — no single test
        # has 3 consecutive failures, but checker must NOT aggregate across tests
        steps = [
            StepRecord(step_num=0, output="x",
                       test_results={"test_a": False, "test_b": True}),
            StepRecord(step_num=1, output="x",
                       test_results={"test_a": True, "test_b": False}),
            StepRecord(step_num=2, output="x",
                       test_results={"test_a": False, "test_b": True}),
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_two_consecutive_fails_no_fire(self) -> None:
        """2 consecutive test failures → no fire when max_retries=3."""
        detector = FailureDetector.from_defaults()
        # Boundary: N-1 = 2 same-test failures → should NOT trigger
        steps = [
            StepRecord(step_num=i, output="x",
                       test_results={"t": False})
            for i in range(2)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_successful_tests_no_fire(self) -> None:
        """All tests pass → no fire."""
        detector = FailureDetector.from_defaults()
        # All True results — no failure pattern at all
        steps = [
            StepRecord(step_num=i, output="x",
                       test_results={"t": True})
            for i in range(3)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_missing_test_results_no_fire(self) -> None:
        """No test_results at all → no fire."""
        detector = FailureDetector.from_defaults()
        # test_results=None on all steps — detector must handle gracefully
        steps = [
            StepRecord(step_num=i, output="x")
            for i in range(3)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_custom_retry_threshold(self) -> None:
        """Configurable retry threshold for test_failure."""
        detector = FailureDetector.from_defaults(test_failure_max_retries=5)
        # 4 < 5 — verifies the threshold is configurable, not hardcoded to 3
        steps = [
            StepRecord(step_num=i, output="x",
                       test_results={"t": False})
            for i in range(4)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

        # 5 = threshold — now fires
        steps.append(
            StepRecord(step_num=4, output="x",
                       test_results={"t": False}),
        )
        state = _build_state(steps)
        assert detector.check(state) is not None

    def test_consecutive_checked_before_oscillation(self) -> None:
        """Consecutive mode is dispatched before oscillation mode in _check_test_failure."""
        detector = FailureDetector.from_defaults()
        # 4 steps: first 3 have "t"=False → consecutive fires on last 3
        # Priority matters because 4 straight Falses could ALSO match oscillation
        # if we checked oscillation first. Consecutive must win.
        steps = [
            StepRecord(step_num=0, output="x", test_results={"t": False}),
            StepRecord(step_num=1, output="x", test_results={"t": False}),
            StepRecord(step_num=2, output="x", test_results={"t": False}),
            StepRecord(step_num=3, output="x", test_results={"t": False}),
        ]
        state = _build_state(steps)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "test_failure"
        # Consecutive mode fires, not oscillation
        assert "consecutive times" in result.detail
        assert "oscillating" not in result.detail


# ── schema_invalid trigger (FR-1.3) ────────────────────────────────────


class TestSchemaInvalid:
    """Tests for the schema_invalid trigger (FR-1.3)."""

    def test_schema_invalid_three_consecutive_fires(self) -> None:
        """schema_valid=False for 3 consecutive steps → fires."""
        detector = FailureDetector.from_defaults()
        # Unlike repeated_error, schema_invalid only checks the boolean flag
        # — no error type/message matching needed
        steps = [
            StepRecord(step_num=i, output="x", schema_valid=False)
            for i in range(3)
        ]
        state = _build_state(steps)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "schema_invalid"

    def test_two_consecutive_no_fire(self) -> None:
        """schema_valid=False for 2 steps → no fire when max_retries=3."""
        detector = FailureDetector.from_defaults()
        # Boundary: N-1 = 2 False values → NOT enough to trigger
        steps = [
            StepRecord(step_num=i, output="x", schema_valid=False)
            for i in range(2)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_true_then_false(self) -> None:
        """Pattern True → False → False → False → fires (last 3 False)."""
        detector = FailureDetector.from_defaults()
        # Leading True is fine — only the tail matters for consecutiveness
        steps = [
            StepRecord(step_num=0, output="x", schema_valid=True),
            StepRecord(step_num=1, output="x", schema_valid=False),
            StepRecord(step_num=2, output="x", schema_valid=False),
            StepRecord(step_num=3, output="x", schema_valid=False),
        ]
        state = _build_state(steps)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "schema_invalid"

    def test_interleaved_valid_no_fire(self) -> None:
        """False → True → False → False → no fire (True breaks chain)."""
        detector = FailureDetector.from_defaults()
        # Step 1 has schema_valid=True, which resets the consecutive False counter
        steps = [
            StepRecord(step_num=0, output="x", schema_valid=False),
            StepRecord(step_num=1, output="x", schema_valid=True),
            StepRecord(step_num=2, output="x", schema_valid=False),
            StepRecord(step_num=3, output="x", schema_valid=False),
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_none_between_false_still_fires(self) -> None:
        """None between False steps is skipped, chain continues (by design)."""
        detector = FailureDetector.from_defaults()
        # schema_valid=None is treated as "not reported" and skipped,
        # unlike True which actively breaks the chain
        steps = [
            StepRecord(step_num=0, output="x", schema_valid=False),
            StepRecord(step_num=1, output="x"),  # None — skipped
            StepRecord(step_num=2, output="x", schema_valid=False),
            StepRecord(step_num=3, output="x", schema_valid=False),
        ]
        state = _build_state(steps)
        # Steps with schema_valid set: [False(0), False(2), False(3)]
        # All 3 are False → fires
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "schema_invalid"

    def test_missing_schema_valid_no_fire(self) -> None:
        """No schema_valid at all → no fire."""
        detector = FailureDetector.from_defaults()
        # All None — detector must handle absence of schema_valid field
        steps = [
            StepRecord(step_num=i, output="x")
            for i in range(3)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_custom_retry_threshold(self) -> None:
        """Configurable retry threshold for schema_invalid."""
        detector = FailureDetector.from_defaults(schema_invalid_max_retries=5)
        # 4 < 5 — verifies threshold is independently configurable per trigger
        steps = [
            StepRecord(step_num=i, output="x", schema_valid=False)
            for i in range(4)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

        # 5th False meets threshold
        steps.append(
            StepRecord(step_num=4, output="x", schema_valid=False),
        )
        state = _build_state(steps)
        assert detector.check(state) is not None


# ── custom trigger (FR-1.5) ────────────────────────────────────────────


class TestCustomTrigger:
    """Tests for the custom trigger (FR-1.5)."""

    def test_callback_returns_true_fires(self) -> None:
        """Custom callback returns True → fires."""
        def callback(state: GuardState) -> bool:  # noqa: ARG001
            return True

        detector = FailureDetector(
            config={
                "custom": {
                    "enabled": True,
                    "max_retries": 3,
                    "custom_callback": callback,
                },
            },
        )
        state = _build_state([StepRecord(step_num=0, output="x")])
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "custom"
        # Custom trigger ignores max_retries — fires immediately on callback=True
        assert result.retry_count == 0

    def test_callback_returns_false_no_fire(self) -> None:
        """Custom callback returns False → no fire."""
        def callback(state: GuardState) -> bool:  # noqa: ARG001
            return False

        detector = FailureDetector(
            config={
                "custom": {
                    "enabled": True,
                    "max_retries": 3,
                    "custom_callback": callback,
                },
            },
        )
        state = _build_state([StepRecord(step_num=0, output="x")])
        assert detector.check(state) is None

    def test_callback_raises_trigger_error(self) -> None:
        """Custom callback raises → TriggerError wraps it."""
        def callback(state: GuardState) -> bool:  # noqa: ARG001
            raise ValueError("oops")

        detector = FailureDetector(
            config={
                "custom": {
                    "enabled": True,
                    "max_retries": 3,
                    "custom_callback": callback,
                },
            },
        )
        state = _build_state([StepRecord(step_num=0, output="x")])
        # Exceptions from user callbacks must not propagate raw —
        # they get wrapped in TriggerError for consistent error handling
        with pytest.raises(TriggerError, match="custom trigger callback"):
            detector.check(state)

    def test_no_callback_no_fire(self) -> None:
        """custom_callback is None → no fire."""
        detector = FailureDetector(
            config={
                "custom": {
                    "enabled": True,
                    "max_retries": 3,
                    "custom_callback": None,
                },
            },
        )
        state = _build_state([StepRecord(step_num=0, output="x")])
        # A custom trigger with no callback defined is effectively a no-op
        assert detector.check(state) is None

    def test_disabled_custom_no_fire(self) -> None:
        """Disabled custom trigger → never fires (S3-BUG-015)."""
        def callback(state: GuardState) -> bool:  # noqa: ARG001
            return True

        detector = FailureDetector(
            config={
                "custom": {
                    "enabled": False,
                    "max_retries": 3,
                    "custom_callback": callback,
                },
            },
        )
        state = _build_state([StepRecord(step_num=0, output="x")])
        # enabled=False must prevent firing even if callback returns True
        assert detector.check(state) is None


# ── Edge cases ─────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases: empty history, single step, disabled triggers."""

    def test_empty_history_no_fire(self) -> None:
        """Empty GuardState → no trigger fires."""
        detector = FailureDetector.from_defaults()
        state = GuardState()
        # Edge case: zero steps must not cause index errors or false positives
        assert detector.check(state) is None

    def test_single_step_no_fire(self) -> None:
        """Single step → no trigger fires (except custom which we test separately)."""
        detector = FailureDetector.from_defaults()
        # All three built-in triggers require at least max_retries=3 consecutive
        # indicators — a single step can never satisfy that
        state = _build_state([
            StepRecord(step_num=0, output="x", error=ValueError("e"),
                       error_type="ValueError", error_message="e",
                       test_results={"t": False}, schema_valid=False),
        ])
        assert detector.check(state) is None

    def test_single_step_custom_fires(self) -> None:
        """Single step + custom callback returning True → fires."""
        def callback(state: GuardState) -> bool:  # noqa: ARG001
            return True

        detector = FailureDetector(
            config={
                "custom": {
                    "enabled": True,
                    "max_retries": 3,
                    "custom_callback": callback,
                },
            },
        )
        state = _build_state([StepRecord(step_num=0, output="x")])
        # Custom trigger is the only one that can fire on a single step
        assert detector.check(state) is not None

    def test_disabled_repeated_error_no_fire(self) -> None:
        """Disabled repeated_error trigger → never fires (S3-BUG-001 coverage)."""
        detector = FailureDetector(
            config={
                "repeated_error": {
                    "enabled": False,
                    "max_retries": 1,
                    "custom_callback": None,
                },
            },
        )
        # max_retries=1 would normally fire on a single error, but enabled=False
        # must supersede the threshold check
        steps = [
            StepRecord(step_num=i, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x")
            for i in range(5)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_disabled_test_failure_no_fire(self) -> None:
        """Disabled test_failure trigger → never fires (S3-BUG-013)."""
        detector = FailureDetector(
            config={
                "test_failure": {
                    "enabled": False,
                    "max_retries": 1,
                    "custom_callback": None,
                },
            },
        )
        # Same pattern: enough failures to trigger, but disabled flag blocks it
        steps = [
            StepRecord(step_num=i, output="x",
                       test_results={"t": False})
            for i in range(5)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_disabled_schema_invalid_no_fire(self) -> None:
        """Disabled schema_invalid trigger → never fires (S3-BUG-014)."""
        detector = FailureDetector(
            config={
                "schema_invalid": {
                    "enabled": False,
                    "max_retries": 1,
                    "custom_callback": None,
                },
            },
        )
        # All three built-in triggers must respect enabled=False individually
        steps = [
            StepRecord(step_num=i, output="x", schema_valid=False)
            for i in range(5)
        ]
        state = _build_state(steps)
        assert detector.check(state) is None

    def test_evaluation_order_custom_first(self) -> None:
        """Evaluation order: custom fires before repeated_error (SPEC §3.3)."""
        def callback(state: GuardState) -> bool:  # noqa: ARG001
            return True

        detector = FailureDetector(
            config={
                "custom": {
                    "enabled": True,
                    "max_retries": 3,
                    "custom_callback": callback,
                },
                "repeated_error": {
                    "enabled": True,
                    "max_retries": 1,
                    "custom_callback": None,
                },
            },
        )
        # If repeated_error were checked first, it would fire (max_retries=1).
        # This test verifies custom is evaluated first per SPEC §3.3.
        steps = [
            StepRecord(step_num=i, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x")
            for i in range(1)
        ]
        state = _build_state(steps)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "custom"

    def test_evaluation_order_repeated_before_test(self) -> None:
        """Evaluation order: repeated_error fires before test_failure (S3-BUG-020)."""
        detector = FailureDetector(
            config={
                "repeated_error": {
                    "enabled": True,
                    "max_retries": 3,
                    "custom_callback": None,
                },
                "test_failure": {
                    "enabled": True,
                    "max_retries": 3,
                    "custom_callback": None,
                },
            },
        )
        # Both triggers would fire here — repeated_error must win the tie
        steps = [
            StepRecord(step_num=i, output=None, error=ValueError("x"),
                       error_type="ValueError", error_message="x",
                       test_results={"t": False})
            for i in range(3)
        ]
        state = _build_state(steps)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "repeated_error"

    def test_no_triggers_configured(self) -> None:
        """No trigger configs → check returns None."""
        detector = FailureDetector(config={})
        state = _build_state([StepRecord(step_num=0, output="x")])
        # Edge case: empty config dict should not cause KeyError
        assert detector.check(state) is None

    def test_unknown_trigger_name_skipped(self) -> None:
        """A trigger name not in TRIGGER_ORDER is silently skipped."""
        detector = FailureDetector(
            config={
                # "my_custom" is not in TRIGGER_ORDER
                # Unknown triggers must be skipped, not raise KeyError
                "my_custom": {
                    "enabled": True,
                    "max_retries": 1,
                    "custom_callback": None,
                },
                "repeated_error": {
                    "enabled": True,
                    "max_retries": 1,
                    "custom_callback": None,
                },
            },
        )
        step = StepRecord(step_num=0, output=None, error=ValueError("x"),
                          error_type="ValueError", error_message="x")
        state = _build_state([step])
        # repeated_error fires (max_retries=1, 1 error step)
        result = detector.check(state)
        assert result is not None
        assert result.trigger_name == "repeated_error"


# ── from_defaults helper ───────────────────────────────────────────────


class TestFromDefaults:
    """Tests for the FailureDetector.from_defaults() convenience method."""

    def test_defaults_all_triggers_enabled(self) -> None:
        """from_defaults() creates a detector with all 3 built-in triggers."""
        detector = FailureDetector.from_defaults()
        # from_defaults is a convenience constructor — all triggers enabled at 3
        assert "repeated_error" in detector.trigger_configs
        assert "test_failure" in detector.trigger_configs
        assert "schema_invalid" in detector.trigger_configs
        assert detector.trigger_configs["repeated_error"].enabled

    def test_defaults_custom_retries(self) -> None:
        """from_defaults() accepts per-trigger overrides."""
        detector = FailureDetector.from_defaults(
            repeated_error_max_retries=5,
            test_failure_max_retries=7,
            schema_invalid_max_retries=2,
        )
        # Each trigger's threshold is independently configurable via kwargs
        assert detector.trigger_configs["repeated_error"].max_retries == 5
        assert detector.trigger_configs["test_failure"].max_retries == 7
        assert detector.trigger_configs["schema_invalid"].max_retries == 2


# ── Detector construction ──────────────────────────────────────────────


class TestDetectorConstruction:
    """Tests for FailureDetector constructor variants (S3-BUG-019)."""

    def test_constructor_with_triggerconfig_objects(self) -> None:
        """Constructor accepts TriggerConfig objects directly."""
        detector = FailureDetector(
            config={
                "repeated_error": TriggerConfig(max_retries=7),
                "test_failure": TriggerConfig(max_retries=5),
            },
        )
        # Using typed TriggerConfig objects instead of raw dicts
        assert detector.trigger_configs["repeated_error"].max_retries == 7
        assert detector.trigger_configs["test_failure"].max_retries == 5

    def test_constructor_with_mixed_configs(self) -> None:
        """Constructor accepts a mix of TriggerConfig objects and dicts."""
        detector = FailureDetector(
            config={
                "repeated_error": TriggerConfig(max_retries=7),
                "test_failure": {"enabled": True, "max_retries": 5},
                "schema_invalid": TriggerConfig(max_retries=2),
            },
        )
        # Mixed-style config ensures internal normalization handles both types
        assert detector.trigger_configs["repeated_error"].max_retries == 7
        assert detector.trigger_configs["test_failure"].max_retries == 5
        assert detector.trigger_configs["schema_invalid"].max_retries == 2

    def test_trigger_configs_returns_copy(self) -> None:
        """trigger_configs returns a copy — mutations don't affect internals."""
        detector = FailureDetector.from_defaults()
        configs = detector.trigger_configs
        # Defensive copy: user mutating the returned dict must not poison internals
        configs["new_key"] = TriggerConfig()  # type: ignore[dict-item]
        assert "new_key" not in detector.trigger_configs


# ── Guard helper methods ───────────────────────────────────────────────


class TestGuardHelpers:
    """Tests for Guard.__init__, properties, record_test_results, record_schema_valid."""

    def test_init_creates_config(self) -> None:
        """Guard.__init__ passes kwargs to GuardConfig (S3-BUG-012)."""
        guard = Guard(max_history_steps=100)
        assert guard.config.max_history_steps == 100
        assert guard.state is not None

    def test_config_property(self) -> None:
        """Guard.config returns the GuardConfig (S3-BUG-011)."""
        guard = Guard(max_history_steps=77)
        assert isinstance(guard.config, GuardConfig)
        assert guard.config.max_history_steps == 77

    def test_state_property_returns_guardstate(self) -> None:
        """Guard.state returns a GuardState (initialised in __init__ for S5)."""
        guard = Guard()
        assert guard.state is not None
        assert isinstance(guard.state, GuardState)

    def test_record_test_results_sets_pending_only(self) -> None:
        """record_test_results stores in _pending_test_results (S5: no direct step write)."""
        guard = Guard()
        results = {"test_parser": False, "test_lint": True}
        guard.record_test_results(results)
        # Test results are buffered in _pending, not written directly to state
        assert guard._pending_test_results == results  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    def test_record_schema_valid_sets_pending(self) -> None:
        """record_schema_valid stores in _pending_schema_valid (S3-BUG-010)."""
        guard = Guard()
        guard.record_schema_valid(valid=False)
        # Schema validity is also buffered, to be merged on the next step write
        assert guard._pending_schema_valid is False  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    def test_record_schema_valid_keyword_only(self) -> None:
        """record_schema_valid requires keyword argument (FBT001 fix)."""
        guard = Guard()
        guard.record_schema_valid(valid=True)
        # Keyword-only argument prevents accidental positional mis-use
        assert guard._pending_schema_valid is True  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    def test_pending_fields_initial_none(self) -> None:
        """_pending_test_results and _pending_schema_valid start as None."""
        guard = Guard()
        # Verify initial state is None, not empty dict or False
        assert guard._pending_test_results is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        assert guard._pending_schema_valid is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
