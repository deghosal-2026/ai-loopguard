"""Integration tests for @guard.protect sync decorator.

Covers per WBS S5:
- Function succeeds first try → returns output, no escalation
- Function fails 1× then succeeds → returns output, no escalation
- Function fails 3× same error → escalation called, returns escalated output
- Function fails with different errors 3× → no escalation (not repeated)
- Custom trigger fires after 1 step → escalation called
- Guard with test_failure trigger: records test results, fails 3× → escalation
- Guard with schema_invalid trigger: records invalid schema 3× → escalation
- on_escalate="interrupt" with callback → "y" escalates, "n" returns last
- Fail-open: no escalation model, no crash
"""

import pytest

from ai_loopguard.config import TriggerConfig
from ai_loopguard.guard import Guard

# ── Mock escalation model ────────────────────────────────────────────────

class _MockModel:
    """Mock LangChain model for integration testing."""

    def __init__(
        self,
        response: str = "escalated-output",
        model_name: str = "mock-gpt4",
        should_fail: bool = False,
    ) -> None:
        self._response = response
        self._model_name = model_name
        self._should_fail = should_fail
        self._invoke_args: list[str] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def invoke(self, prompt: str) -> object:
        self._invoke_args.append(prompt)
        if self._should_fail:
            raise RuntimeError("model unavailable")
        return _MockResponse(self._response)


class _MockResponse:
    """Mock AIMessage with .content attribute."""

    def __init__(self, content: str) -> None:
        self.content = content


# ── Helpers ──────────────────────────────────────────────────────────────

def _guard(
    model: _MockModel | None = None,
    **kwargs: object,
) -> Guard:
    """Create a Guard with the given mock model and config overrides."""
    cfg: dict[str, object] = {"escalation_model": model}
    cfg.update(kwargs)
    return Guard(**cfg)  # type: ignore[arg-type]


# ── Success path tests ───────────────────────────────────────────────────

class TestSuccessPath:
    """Tests where the guarded function succeeds."""

    def test_first_try_success_returns_output(self) -> None:
        """Function succeeds on first call → returns output immediately."""
        guard = _guard()

        @guard.protect
        def step() -> str:
            return "success"

        # Success path: the function returns normally, guard records the step
        # and passes the output through unchanged.  No trigger can fire because
        # there are no error conditions (no exception, no test failure, etc.).
        assert step() == "success"

    def test_first_try_success_no_escalation(self) -> None:
        """Successful function does NOT trigger escalation."""
        model = _MockModel()
        guard = _guard(model=model)

        @guard.protect
        def step() -> str:
            return "ok"

        assert step() == "ok"
        assert len(model._invoke_args) == 0

    def test_fail_then_succeed(self) -> None:
        """Fail once → returns None. Succeed next → returns output."""
        guard = _guard()
        call_count: list[int] = [0]

        @guard.protect
        def step() -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("transient error")
            return "recovered"

        # First call raises, no trigger → returns None (fail-open)
        assert step() is None
        # Second call succeeds
        assert step() == "recovered"
        assert call_count[0] == 2

    def test_fail_once_no_escalation(self) -> None:
        """Single failure does NOT trigger escalation (threshold 3)."""
        model = _MockModel()
        guard = _guard(model=model)
        call_count: list[int] = [0]

        @guard.protect
        def step() -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("one-off")
            return "fine"

        # First call fails → no trigger
        assert step() is None
        # Second call succeeds
        assert step() == "fine"
        assert len(model._invoke_args) == 0


# ── Escalation path tests ────────────────────────────────────────────────

class TestEscalationPath:
    """Tests where a trigger fires and escalation occurs."""

    def test_same_error_three_times_escalates(self) -> None:
        """3 consecutive identical errors → escalation model called."""
        model = _MockModel(response="fixed by gpt4")
        guard = _guard(model=model)

        @guard.protect
        def step() -> str:
            raise ValueError("repeated failure")

        # First two calls return None (no trigger yet)
        assert step() is None
        assert step() is None
        # Third call triggers escalation → escalates.
        # Sync @guard.protect scenarios:
        # - success: output returned unchanged, no model call
        # - 3 fails (same error): trigger fires, model called, escalated output returned
        # - 1 fail then success: fail returns None, success returns output, no model call
        result = step()
        assert result == "fixed by gpt4"
        assert len(model._invoke_args) == 1
        assert "You are an escalation model" in model._invoke_args[0]

    def test_different_errors_no_escalation(self) -> None:
        """Unique error per call → no 3 consecutive, no escalation."""
        model = _MockModel()
        guard = _guard(model=model)
        call_count: list[int] = [0]

        @guard.protect
        def step() -> str:
            i = call_count[0]
            call_count[0] += 1
            raise RuntimeError(f"unique-error-{i}")

        # All 10 unique errors → no trigger → all return None (#50)
        for _ in range(10):
            assert step() is None
        assert len(model._invoke_args) == 0

    def test_custom_trigger_fires(self) -> None:
        """Custom callback trigger fires after condition is met."""
        model = _MockModel(response="custom escalated")
        guard = _guard(
            model=model,
            triggers={
                "custom": TriggerConfig(
                    enabled=True,
                    custom_callback=lambda s: len(s.steps) >= 1 and (  # type: ignore[arg-type]
                        s.steps[-1].error_message is not None
                        and "custom-fail" in str(s.steps[-1].error_message)
                    ),
                ),
            },
        )

        @guard.protect
        def step() -> str:
            raise ValueError("custom-fail detected")

        result = step()
        assert result == "custom escalated"
        assert len(model._invoke_args) == 1

    def test_test_failure_trigger(self) -> None:
        """test_failure trigger fires after 3 consecutive test failures."""
        model = _MockModel(response="fixed tests")
        guard = _guard(model=model)

        @guard.protect
        def step() -> str:
            guard.record_test_results({"test_parser": False})
            return "output"

        # First 2 calls: succeed, record test failure, no trigger yet
        assert step() == "output"
        assert step() == "output"
        # 3rd call: trigger fires → escalation
        assert step() == "fixed tests"
        assert len(model._invoke_args) == 1

    def test_schema_invalid_trigger(self) -> None:
        """schema_invalid trigger fires after 3 consecutive schema failures."""
        model = _MockModel(response="valid json")
        guard = _guard(model=model)

        @guard.protect
        def step() -> str:
            guard.record_schema_valid(valid=False)
            return "bad json"

        assert step() == "bad json"
        assert step() == "bad json"
        assert step() == "valid json"
        assert len(model._invoke_args) == 1


# ── Interrupt mode tests (#47) ────────────────────────────────────────────

class TestInterruptMode:
    """Tests for on_escalate="interrupt" with custom callback."""

    def test_interrupt_yes_escalates(self) -> None:
        """Callback returns 'y' → escalation proceeds."""
        model = _MockModel(response="interrupt-escalated")
        guard = _guard(
            model=model,
            on_escalate="interrupt",
            interrupt_callback=lambda _: "y",
        )

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        assert step() is None
        assert step() is None
        assert step() == "interrupt-escalated"
        assert len(model._invoke_args) == 1

    def test_interrupt_no_returns_last_output(self) -> None:
        """Callback returns 'n' → returns last output, no escalation."""
        model = _MockModel()
        guard = _guard(
            model=model,
            on_escalate="interrupt",
            interrupt_callback=lambda _: "n",
        )

        last_output: list[str] = []

        @guard.protect
        def step() -> str:
            last_output.append("attempt")
            raise ValueError("fail")

        assert step() is None
        assert step() is None
        # 3rd call: trigger fires, user says no → returns last output
        assert step() is None
        assert len(model._invoke_args) == 0
        # State has 3 steps
        assert len(guard._state.steps) == 3

    def test_interrupt_callback_receives_summary(self) -> None:
        """Callback receives context summary string with trigger info."""
        captured: list[str] = []

        def capture(summary: str) -> str:
            captured.append(summary)
            return "y"

        model = _MockModel(response="ok")
        guard = _guard(
            model=model,
            on_escalate="interrupt",
            interrupt_callback=capture,
        )

        @guard.protect
        def step() -> str:
            raise ValueError("test failure")

        assert step() is None
        assert step() is None
        assert step() == "ok"
        assert len(captured) == 1
        assert "repeated_error" in captured[0]
        assert "test failure" in captured[0]


# ── Fail-open tests ──────────────────────────────────────────────────────

class TestFailOpen:
    """Tests for fail-open behaviour (PRD §9.3)."""

    def test_fail_returns_none(self) -> None:
        """Exception with no trigger → returns None (fail-open)."""
        guard = _guard()

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        assert step() is None

    def test_no_escalation_model_still_tracks_steps(self) -> None:
        """Without escalation model, guard tracks steps, returns output."""
        guard = _guard()
        call_count: list[int] = [0]

        @guard.protect
        def step() -> str:
            call_count[0] += 1
            if call_count[0] <= 2:
                raise ValueError("fail")
            return "recovered"

        assert step() is None
        assert step() is None
        assert step() == "recovered"
        assert call_count[0] == 3

    def test_no_model_trigger_returns_none(self) -> None:
        """No model + trigger fires → returns last output which is None (failed output)."""
        guard = _guard()

        @guard.protect
        def step() -> str:
            raise ValueError("always fail")

        # 3 same errors → trigger fires, but no model → returns last output
        assert step() is None
        assert step() is None
        assert step() is None
        # State should have 3 steps
        assert len(guard._state.steps) == 3

    def test_escalation_model_fails_raises_original(self) -> None:
        """Escalation model failure → on_guard_error default raises original."""
        model = _MockModel(should_fail=True)
        guard = _guard(model=model, on_guard_error="raise_original")

        @guard.protect
        def step() -> str:
            raise ValueError("original failure")

        step()  # 1
        step()  # 2
        # 3rd call triggers escalation, escalation model fails too,
        # on_guard_error="raise_original" re-raises the original error.
        with pytest.raises(ValueError, match="original failure"):
            step()


# ── Decorator metadata tests ─────────────────────────────────────────────

class TestDecoratorMetadata:
    """Tests for decorator transparency."""

    def test_preserves_function_name(self) -> None:
        """Decorated function keeps its original __name__."""
        guard = _guard()

        @guard.protect
        def my_func() -> str:
            """Docstring."""
            return "hello"

        assert my_func.__name__ == "my_func"

    def test_preserves_docstring(self) -> None:
        """Decorated function keeps its original __doc__."""
        guard = _guard()

        @guard.protect
        def my_func() -> str:
            """My custom docstring."""
            return "hello"

        assert my_func.__doc__ == "My custom docstring."

    def test_guard_with_no_args(self) -> None:
        """Guard() with no arguments works (no escalation model)."""
        guard = Guard()
        assert guard is not None
        assert guard.config is not None

    def test_guard_with_kwargs(self) -> None:
        """Guard(**kwargs) accepts standard configuration."""
        guard = Guard(
            on_escalate="interrupt",
            max_history_steps=100,
            log_dir="/tmp/loopguard",
        )
        assert guard is not None
        assert guard.config.on_escalate == "interrupt"
        assert guard.config.max_history_steps == 100
