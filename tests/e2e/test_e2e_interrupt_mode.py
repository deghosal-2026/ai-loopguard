"""E2E: interrupt mode — on_escalate="interrupt" with custom callback.

Verifies:
- Callback returning "y" escalates and returns escalated output
- Callback returning "n" skips escalation, returns last output
- Callback receives context summary with trigger info
"""

from tests.e2e.conftest import MockModel, make_guard


class TestInterruptModeE2E:
    """Full end-to-end flow for interrupt mode."""

    def test_interrupt_yes_escalates(self) -> None:
        """Interrupt callback returns 'y' → escalation proceeds."""
        model = MockModel(response="interrupt-fixed")
        guard = make_guard(
            model=model,
            on_escalate="interrupt",
            interrupt_callback=lambda _: "y",
        )

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        step()
        step()
        # The "y" callback scenario: when on_escalate="interrupt", the guard
        # defers to the callback instead of escalating automatically.
        # Callback returning "y" means "yes, escalate" — the model is invoked
        # and the escalated output is returned.
        result = step()
        assert result == "interrupt-fixed"
        assert len(model._invoke_args) == 1

    def test_interrupt_no_skips_escalation(self) -> None:
        """Interrupt callback returns 'n' → no escalation, returns None."""
        model = MockModel()
        guard = make_guard(
            model=model,
            on_escalate="interrupt",
            interrupt_callback=lambda _: "n",
        )

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        step()
        step()
        # The "n" callback scenario: user says "no, don't escalate".
        # The guard skips escalation entirely — model is NOT called,
        # escalation_count stays 0, and None is returned (since the
        # step itself failed).  This is the abort path.
        result = step()
        assert result is None
        assert len(model._invoke_args) == 0
        assert guard.state.escalation_count == 0

    def test_interrupt_callback_receives_summary(self) -> None:
        """Interrupt callback receives context summary with trigger detail."""
        captured: list[str] = []

        def capture(summary: str) -> str:
            captured.append(summary)
            return "y"

        model = MockModel(response="ok")
        guard = make_guard(
            model=model,
            on_escalate="interrupt",
            interrupt_callback=capture,
        )

        @guard.protect
        def step() -> str:
            raise ValueError("test failure")

        step()
        step()
        step()
        # The callback receives a human-readable summary string containing
        # the trigger type ("repeated_error") and context (error message).
        # This allows the callback to make an informed decision without
        # parsing the full guard state.  Summary is a string, not a dict.
        assert len(captured) == 1
        assert "repeated_error" in captured[0]
        assert "test failure" in captured[0]

    def test_interrupt_multiple_tasks(self) -> None:
        """Reset between tasks, interrupt works fresh for each."""
        model = MockModel(response="fixed after interrupt")
        guard = make_guard(
            model=model,
            on_escalate="interrupt",
            interrupt_callback=lambda _: "y",
        )

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        # Task 1
        step()
        step()
        r1 = step()
        assert r1 == "fixed after interrupt"
        assert guard.state.escalation_count == 1

        # Task 2 — reset and run again
        guard.reset()
        step()
        step()
        r2 = step()
        assert r2 == "fixed after interrupt"
        assert guard.state.escalation_count == 1  # reset
