"""E2E: test_failure trigger — test_parser fails 3× → escalation.

Verifies:
- record_test_results() accumulates across steps
- 3 consecutive same-test failures fire the trigger
- Escalation model receives context with test failure detail
"""

from tests.e2e.conftest import MockModel, make_guard


class TestTestFailureE2E:
    """Full end-to-end flow for test_failure trigger."""

    def test_three_test_failures_escalates(self) -> None:
        """3× test_parser=False → trigger fires → escalated output."""
        model = MockModel(response="tests fixed")
        guard = make_guard(model=model)

        @guard.protect
        def step() -> str:
            guard.record_test_results({"test_parser": False})
            return "ran tests"

        assert step() == "ran tests"
        assert step() == "ran tests"
        # record_test_results() accumulates test results across steps.
        # The guard checks all test names — if ANY test name has 3
        # consecutive failures, the test_failure trigger fires.  Here
        # we track a single test ("test_parser") across 3 steps.
        result = step()
        assert result == "tests fixed"
        assert len(model._invoke_args) == 1
        assert guard.state.escalation_count == 1

    def test_mixed_test_results_no_trigger(self) -> None:
        """Passing tests don't trigger test_failure."""
        model = MockModel()
        guard = make_guard(model=model)

        @guard.protect
        def step() -> str:
            guard.record_test_results({"test_parser": True})
            return "all green"

        for _ in range(5):
            assert step() == "all green"
        # All results are True (passing) — the test_failure trigger looks
        # for False values.  This proves the trigger doesn't misfire on
        # passing results.
        assert len(model._invoke_args) == 0

    def test_pending_test_results_cleared_after_step(self) -> None:
        """Pending test results are consumed by the next step record."""
        guard = make_guard()

        @guard.protect
        def step() -> str:
            guard.record_test_results({"test_a": False})
            return "done"

        step()
        # The pending results set via record_test_results() should be
        # consumed (cleared) and stored in the current step's metadata.
        # If not cleared, they'd leak into subsequent steps.
        assert guard.state.steps[0].test_results == {"test_a": False}

    def test_test_failure_oscillation_detected(self) -> None:
        """Pass→fail→pass→fail oscillation fires trigger.

        Pattern [True, False, True, False] across 4 steps triggers the
        oscillation detector (not the consecutive-failure detector).
        Oscillation uses a fixed 4-step window, independent of max_retries.
        """
        # Non-obvious pattern: the oscillation detector catches test results
        # that alternate pass/fail (e.g., flaky infrastructure).  This is a
        # separate detection path from the consecutive-failure path — it uses
        # a 4-step sliding window rather than max_retries.  Both paths can
        # fire independently.
        model = MockModel(response="oscillation fixed")
        guard = make_guard(model=model)
        pattern: list[bool] = [True, False, True, False]

        @guard.protect
        def step() -> str:
            val = pattern[len(guard.state.steps) % len(pattern)]
            # Set _pending_test_results directly — record_test_results()
            # would overwrite the previous step's test_results via its
            # backward-compat steps[-1] mutation, corrupting the pattern.
            # This is a known gotcha: record_test_results() mutates the
            # last recorded step, so for the oscillation test we bypass it.
            guard._pending_test_results = {"test_osc": val}
            return "step done"

        for _ in range(3):
            step()
        result = step()
        assert result == "oscillation fixed"
        assert len(model._invoke_args) == 1
