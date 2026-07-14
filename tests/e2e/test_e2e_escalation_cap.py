"""E2E: escalation cap — max_escalations_per_run enforcement.

Verifies:
- After cap hit, escalation model is NOT called again
- Last output is returned instead
- Escalation count does not exceed cap
- EscalationManager handles cap correctly end-to-end
"""

from tests.e2e.conftest import MockModel, make_guard


class TestEscalationCapE2E:
    """Full end-to-end flow for escalation cap."""

    def test_escalation_cap_hit_returns_last_output(self) -> None:
        """After 1 escalation, cap hit → returns last output, no model call."""
        model = MockModel(response="first escalation")
        guard = make_guard(model=model, max_escalations_per_run=1)

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        # First 3 calls: trigger fires → escalation
        step()
        step()
        r1 = step()
        assert r1 == "first escalation"
        assert guard.state.escalation_count == 1
        assert len(model._invoke_args) == 1

        # Next 3 calls: trigger fires again but cap hit → no model call.
        # When the cap is hit, the guard returns the last output instead of
        # calling the escalation model.  Since all steps failed, the last
        # output is None.  This prevents infinite escalation loops while
        # keeping the agent loop alive.
        step()
        step()
        r2 = step()
        assert r2 is None  # last output was None (failed step)
        assert guard.state.escalation_count == 1  # not incremented
        assert len(model._invoke_args) == 1  # no additional call

    def test_reset_resets_escalation_count(self) -> None:
        """reset() clears escalation count so cap resets for next task."""
        model = MockModel(response="escalated")
        guard = make_guard(model=model, max_escalations_per_run=1)

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        # First task: 1 escalation (cap hit)
        step()
        step()
        step()
        assert guard.state.escalation_count == 1

        # Reset + second task: fresh escalation allowed.
        # reset() clears the state (steps, escalation_count) so the cap
        # is effectively reset.  Without this, a single-task run that
        # hits the cap would prevent future tasks from escalating at all.
        guard.reset()
        step()
        step()
        r2 = step()
        assert r2 == "escalated"
        assert guard.state.escalation_count == 1

    def test_escalation_cap_multiple_escalations_allowed(self) -> None:
        """max_escalations_per_run=2 allows 2 escalations before cap."""
        model = MockModel(response="fixed")
        guard = make_guard(model=model, max_escalations_per_run=2)

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        # Steps 0-2: all raise ValueError → trigger fires on step 2 →
        # 1st escalation (count=1), returns "fixed".
        step()
        step()
        assert step() == "fixed"
        assert guard.state.escalation_count == 1
        assert len(model._invoke_args) == 1

        # Step 3 still raises ValueError and steps 1,2,3 all have the
        # same error → trigger fires immediately → 2nd escalation (count=2).
        # The escalated output from step 2 does NOT break the chain — step 3
        # is a new step that independently raised the same error.
        # Non-obvious: the escalation output replaces the step output but does
        # NOT reset the error window.  The guard still sees step 3 as having
        # raised ValueError("fail"), same as steps 1-2.
        assert step() == "fixed"
        assert guard.state.escalation_count == 2
        assert len(model._invoke_args) == 2

        # Steps 4-6: cap hit (count=2, max=2) → no more model calls.
        # Each step returns None because all steps failed.
        step()
        step()
        assert step() is None
        assert len(model._invoke_args) == 2
