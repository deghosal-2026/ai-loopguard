"""E2E: repeated_error trigger — workhorse raises ValueError 3× → escalation.

Verifies:
- 3 consecutive identical errors fire the trigger
- Escalation model is called once
- Escalated output is returned on the 3rd call
- GuardState records 3 steps and 1 escalation
"""

from tests.e2e.conftest import MockModel, make_guard


class TestRepeatedErrorE2E:
    """Full end-to-end flow for repeated_error trigger."""

    def test_three_same_errors_escalates(self) -> None:
        """3× ValueError → trigger fires → escalated output returned."""
        model = MockModel(response="fixed by escalation")
        guard = make_guard(model=model)

        @guard.protect
        def step() -> str:
            raise ValueError("repeated failure")

        # First two calls: function raises ValueError, guard records failed
        # steps and returns None (fail-open when no trigger fires).
        assert step() is None
        assert step() is None
        # Third call: 3 consecutive identical errors → repeated_error fires
        # → escalation model returns "fixed by escalation".
        # The 3-same-errors scenario tests the repeated_error trigger which
        # looks for 3 consecutive steps with identical (error_type, error_message).
        # Different message text or exception type would NOT fire this trigger.
        result = step()
        assert result == "fixed by escalation"
        # Model called exactly once (on the 3rd step, not on steps 1-2).
        assert len(model._invoke_args) == 1
        # Verifying GuardState step count ensures the guard tracks all calls
        # even when some are "invisible" (return None).  Step count must be 3,
        # not 1 — important because the escalation path could short-circuit.
        assert len(guard.state.steps) == 3
        assert guard.state.escalation_count == 1

    def test_different_errors_no_escalation(self) -> None:
        """Unique errors each call → no trigger fires."""
        model = MockModel()
        guard = make_guard(model=model)
        call_count: list[int] = [0]

        @guard.protect
        def step() -> str:
            # Each call raises a unique error by embedding the call index.
            # No 3 consecutive errors have identical type + message, so
            # repeated_error never fires — even after 10 calls.
            # This tests the negative case: the trigger should NOT fire
            # when errors differ, proving it doesn't match on type alone.
            i = call_count[0]
            call_count[0] += 1
            raise RuntimeError(f"unique-error-{i}")

        for _ in range(10):
            assert step() is None
        assert len(model._invoke_args) == 0
        assert guard.state.escalation_count == 0

    def test_two_errors_then_success_no_escalation(self) -> None:
        """2 errors then success → no trigger (needs 3 consecutive)."""
        model = MockModel()
        guard = make_guard(model=model)
        call_count: list[int] = [0]

        @guard.protect
        def step() -> str:
            i = call_count[0]
            call_count[0] += 1
            if i < 2:
                raise ValueError("transient")
            return "recovered"

        # 2 errors not enough (default max_retries=3), and step 2 succeeds
        # which breaks the chain — the trigger looks at the last 3 steps
        # and step 2 is a success.
        # Edge case: transient failure (recovered before threshold) should
        # NOT escalate.  This distinguishes transient from persistent failure.
        assert step() is None
        assert step() is None
        assert step() == "recovered"
        assert len(model._invoke_args) == 0
        assert guard.state.escalation_count == 0

    def test_escalation_prompt_contains_context(self) -> None:
        """The prompt sent to the escalation model includes failure context."""
        model = MockModel(response="fixed")
        guard = make_guard(model=model)

        @guard.protect
        def step() -> str:
            raise ValueError("my specific error")

        step()
        step()
        step()
        prompt = model._invoke_args[0]
        assert "repeated_error" in prompt
        assert "my specific error" in prompt
        assert "ValueError" in prompt
