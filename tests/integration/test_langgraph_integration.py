"""Integration tests for LangGraphHandler.

Tests that the handler correctly monitors steps, detects triggers,
and escalates when a stuck pattern is found. These tests exercise
the handler's full flow: step recording -> trigger detection ->
context packaging -> model invocation -> output return.

LangGraph graph compilation is not tested here (SDK version
compatibility varies). Instead, we call ``on_step_end()`` directly
to verify the handler's internal logic.
"""

from unittest.mock import patch

from ai_loopguard.detectors import FailureDetector
from ai_loopguard.escalation import EscalationManager
from ai_loopguard.guard import Guard
from ai_loopguard.integrations.langgraph import LangGraphHandler
from ai_loopguard.logging import EscalationLogger

# ── Mock model ─────────────────────────────────────────────────────────────
# LangGraph mock graph setup: we don't use a real compiled LangGraph graph.
# Instead, tests call handler.on_step_end() directly with node_index, state,
# output, and optional error.  This avoids depending on the langgraph SDK
# and graph compilation, which varies across versions.
# The handler monitors each step: it records the result in GuardState,
# checks triggers, and if a trigger fires, initiates escalation.

class _MockModel:
    """Mock LangChain BaseChatModel for testing."""

    def __init__(
        self, response: str = "escalated via langgraph",
    ) -> None:
        self._response = response
        self._invoke_args: list[str] = []
        self._model_name = "mock-gpt4"

    @property
    def model_name(self) -> str:
        return self._model_name

    def invoke(self, prompt: str) -> object:
        self._invoke_args.append(prompt)
        return _MockResponse(self._response)

    async def ainvoke(self, prompt: str) -> object:
        self._invoke_args.append(prompt)
        return _MockResponse(self._response)


class _MockResponse:
    def __init__(self, content: str) -> None:
        self.content = content


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_guard(
    model: _MockModel | None = None,
    on_escalate: str = "auto",
    max_retries: int = 3,
    max_escalations: int = 1,
) -> Guard:
    """Create a Guard instance with test-friendly config."""
    model = model or _MockModel()
    guard = Guard(
        escalation_model=model,
        workhorse_model_name="test-workhorse",
        on_escalate=on_escalate,
        max_escalations_per_run=max_escalations,
    )
    for t in guard.config.triggers.values():
        t.max_retries = max_retries
    guard._detector = FailureDetector(guard.config.triggers)
    guard._escalation_mgr = EscalationManager(
        config=guard.config,
        state=guard.state,
        logger=EscalationLogger(),
    )
    return guard


# ── Step monitoring ────────────────────────────────────────────────────────

class TestStepMonitoring:
    """Tests that on_step_end records steps and checks triggers."""

    def test_records_step_in_state(self) -> None:
        """Step is recorded in GuardState after on_step_end."""
        guard = _make_guard()
        handler = LangGraphHandler(guard)
        handler.on_step_end(0, {"step": 0}, "output-0")
        assert len(guard.state.steps) == 1
        assert guard.state.steps[0].output == "output-0"

    def test_record_error_step(self) -> None:
        """Error passed to on_step_end is recorded in the step."""
        guard = _make_guard()
        handler = LangGraphHandler(guard)
        handler.on_step_end(
            0, {"step": 0}, None,
            error=ValueError("fail"),
        )
        assert guard.state.steps[0].error_type == "ValueError"
        assert guard.state.steps[0].error_message == "fail"

    def test_multiple_steps_accumulate(self) -> None:
        """Multiple calls accumulate steps in state."""
        guard = _make_guard(max_retries=5)
        handler = LangGraphHandler(guard)
        for i in range(3):
            handler.on_step_end(i, {"step": i}, f"output-{i}")
        assert len(guard.state.steps) == 3

    def test_passes_through_output_without_trigger(self) -> None:
        """Without trigger conditions, output is returned unchanged."""
        guard = _make_guard()
        handler = LangGraphHandler(guard)
        result = handler.on_step_end(0, {"step": 0}, "normal output")
        assert result == "normal output"


# ── Auto escalation ────────────────────────────────────────────────────────

class TestAutoEscalation:
    """Tests that auto escalation fires when trigger conditions are met."""

    def test_repeated_error_escalates(self) -> None:
        """Repeated error trigger fires escalation."""
        guard = _make_guard(max_retries=3)
        handler = LangGraphHandler(guard)
        for i in range(3):
            # Handler monitoring: on_step_end is called after each graph node.
            # The handler checks if an error was passed — if so, it records a
            # failed step.  After 3 identical errors, the repeated_error trigger
            # fires and the escalation model is invoked.
            handler.on_step_end(
                i, {"step": i}, None,
                error=ValueError("fail"),
            )
        model = guard.config.escalation_model
        assert len(model._invoke_args) >= 1

    def test_schema_invalid_escalates(self) -> None:
        """Schema invalid trigger fires escalation via pending metadata."""
        guard = _make_guard(max_retries=3)
        handler = LangGraphHandler(guard)
        for i in range(3):
            guard.record_schema_valid(valid=False)
            handler.on_step_end(i, {"step": i}, "bad json")
        model = guard.config.escalation_model
        assert len(model._invoke_args) >= 1

    def test_escalation_returns_correct_output(self) -> None:
        """Escalation output is returned on the step that triggers it."""
        guard = _make_guard(
            model=_MockModel(response="fixed by escalation"),
            max_retries=2,
            max_escalations=3,
        )
        handler = LangGraphHandler(guard)
        # Step 0: first error
        handler.on_step_end(
            0, {"step": 0}, None,
            error=ValueError("fail"),
        )
        # Step 1: second error — trigger fires, returns escalated output
        result = handler.on_step_end(
            1, {"step": 1}, None,
            error=ValueError("fail"),
        )
        assert result == "fixed by escalation"


# ── Interrupt mode ─────────────────────────────────────────────────────────

class TestInterruptMode:
    """Tests for interrupt mode behaviour."""

    def test_interrupt_yes_escalates(self) -> None:
        """When interrupt fires, user says 'y' -> escalation."""
        guard = _make_guard(
            on_escalate="interrupt",
            max_retries=2,
            max_escalations=3,
        )
        handler = LangGraphHandler(guard)
        with patch("langgraph.types.interrupt", return_value="y"):
            handler.on_step_end(
                0, {"step": 0}, None,
                error=ValueError("fail"),
            )
            handler.on_step_end(
                1, {"step": 1}, None,
                error=ValueError("fail"),
            )
            model = guard.config.escalation_model
            assert len(model._invoke_args) >= 1

    def test_interrupt_declined_returns_output(self) -> None:
        """When user declines interrupt, original output is returned."""
        guard = _make_guard(
            on_escalate="interrupt",
            max_retries=2,
            max_escalations=3,
        )
        handler = LangGraphHandler(guard)
        with patch("langgraph.types.interrupt", return_value="n"):
            handler.on_step_end(
                0, {"step": 0}, None,
                error=ValueError("fail"),
            )
            result = handler.on_step_end(
                1, {"step": 1}, "declined output",
                error=ValueError("fail"),
            )
            model = guard.config.escalation_model
            assert result == "declined output"
            assert len(model._invoke_args) == 0


# ── Threshold boundary ─────────────────────────────────────────────────────

class TestThresholdBoundary:
    """Tests that triggers fire only after threshold is met."""

    def test_no_escalation_below_threshold(self) -> None:
        """Trigger does NOT fire before max_retries is reached."""
        guard = _make_guard(max_retries=5)
        handler = LangGraphHandler(guard)
        for i in range(3):
            handler.on_step_end(
                i, {"step": i}, None,
                error=ValueError("fail"),
            )
        output = handler.on_step_end(3, {"step": 3}, "normal")
        assert output == "normal"
