"""Tests for EscalationManager and InterruptHandler.

Covers per WBS S4:
- Trigger fires → escalation model called → output returned
- Escalation cap hit → returns last output, logs capped event
- Escalation model raises → fail-open (raise_original / return_last_output /
  return_sentinel)
- on_escalate="interrupt" → pauses, user says "y" → escalates
- on_escalate="interrupt" → pauses, user says "n" → returns last output
- Custom prompt used when provided
- Default prompt used when not provided
- Context pipeline: package → sanitize → redact applied
"""

from unittest.mock import Mock, PropertyMock

import pytest

from ai_loopguard._internal.state import GuardState, StepRecord, TriggerResult
from ai_loopguard.config import GuardConfig
from ai_loopguard.escalation import EscalationManager, InterruptHandler
from ai_loopguard.exceptions import EscalationError

# ── Mock escalation model ────────────────────────────────────────────────

class _MockModel:
    """Mock LangChain BaseChatModel for testing.

    Tracks calls, supports sync (invoke) and async (ainvoke), and
    can be configured to succeed or raise.
    """

    def __init__(
        self,
        response: str = "escalated output",
        should_fail: bool = False,
        model_name: str = "mock-gpt4",
    ) -> None:
        self._response = response
        self._should_fail = should_fail
        self._model_name = model_name
        self._invoke_args: list[str] = []
        self._ainvoke_args: list[str] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def invoke(self, prompt: str) -> object:
        self._invoke_args.append(prompt)
        if self._should_fail:
            raise RuntimeError("model unavailable")
        return _MockResponse(self._response)

    async def ainvoke(self, prompt: str) -> object:
        self._ainvoke_args.append(prompt)
        if self._should_fail:
            raise RuntimeError("model unavailable (async)")
        return _MockResponse(self._response)


class _MockResponse:
    """Mock LangChain AIMessage for testing _extract_content."""

    def __init__(self, content: str) -> None:
        self.content = content


# ── helpers ──────────────────────────────────────────────────────────────

def _state(
    *step_specs: tuple[str | None, str | None, str | None],
) -> GuardState:
    """Build a GuardState from (output, error_type, error_message) tuples.

    Each tuple: (output, error_type, error_message).  error_type=None
    means a successful step.
    """
    state = GuardState(max_history_steps=100)
    for i, (output, error_type, error_msg) in enumerate(step_specs):
        error: Exception | None = None
        if error_type:
            error = ValueError(error_msg or "fail")
        state.add_step(StepRecord(
            step_num=i,
            output=output,
            error=error,
            error_type=error_type,
            error_message=error_msg,
            timestamp=i,
        ))
    return state


def _trigger(name: str = "repeated_error") -> TriggerResult:
    return TriggerResult(
        trigger_name=name,
        detail=f"{name} trigger fired",
        retry_count=3,
    )


def _config(
    model: _MockModel | None = None,
    on_escalate: str = "auto",
    escalation_prompt: str | None = None,
    max_escalations_per_run: int = 1,
    on_guard_error: str = "raise_original",
    sanitize_context: bool = True,
    redact_patterns: list[str] | None = None,
    redact_fields: list[str] | None = None,
) -> GuardConfig:
    return GuardConfig(
        escalation_model=model or _MockModel(),
        on_escalate=on_escalate,  # type: ignore[arg-type]
        escalation_prompt=escalation_prompt,
        max_escalations_per_run=max_escalations_per_run,
        on_guard_error=on_guard_error,  # type: ignore[arg-type]
        sanitize_context=sanitize_context,
        redact_patterns=redact_patterns or [],
        redact_fields=redact_fields or [],
    )


# ── Basic escalation flow ────────────────────────────────────────────────

class TestBasicEscalation:
    """Happy path: trigger fires, escalation model returns output."""

    def test_escalate_returns_model_output(self) -> None:
        """Escalation model output is returned from escalate()."""
        model = _MockModel(response="fixed result")
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        # Happy path: trigger fires → model is called → output surfaces to caller
        result = mgr.escalate(_trigger())
        assert result == "fixed result"

    def test_escalate_increments_count(self) -> None:
        """escalation_count increments after successful escalation."""
        model = _MockModel()
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        # Counter starts at 0, post-escalation must be 1
        assert state.escalation_count == 0
        mgr.escalate(_trigger())
        assert state.escalation_count == 1

    def test_escalate_calls_model_with_prompt(self) -> None:
        """The model.invoke() receives a formatted prompt string."""
        model = _MockModel()
        state = _state((None, "ValueError", "test error"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        mgr.escalate(_trigger())
        # One call, not multiple — escalation invokes model exactly once
        assert len(model._invoke_args) == 1
        prompt = model._invoke_args[0]
        # Default prompt template is used when no custom prompt provided
        assert "You are an escalation model" in prompt

    @pytest.mark.asyncio
    async def test_escalate_async_returns_output(self) -> None:
        """escalate_async returns the model output."""
        model = _MockModel(response="async fixed")
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        # Async path mirrors sync but uses ainvoke() instead of invoke()
        result = await mgr.escalate_async(_trigger())
        assert result == "async fixed"

    @pytest.mark.asyncio
    async def test_escalate_async_calls_ainvoke(self) -> None:
        """escalate_async uses the model's ainvoke() method."""
        model = _MockModel()
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        await mgr.escalate_async(_trigger())
        # Verifies the async method dispatches to the correct coroutine
        assert len(model._ainvoke_args) == 1


# ── Escalation cap (T6 / OQ-4) ───────────────────────────────────────────

class TestEscalationCap:
    """Tests for max_escalations_per_run enforcement."""

    def test_cap_returns_last_output(self) -> None:
        """When cap is hit, last step's output is returned."""
        model = _MockModel()
        state = _state(
            (None, "ValueError", "fail1"),
            ("last good output", None, None),  # last known good
        )
        state.escalation_count = 1  # cap already reached (default=1)
        mgr = EscalationManager(config=_config(model=model), state=state)
        # Fallback: return the most recent successful output instead of model call
        result = mgr.escalate(_trigger())
        assert result == "last good output"

    def test_cap_returns_none_when_no_steps(self) -> None:
        """Cap with empty state returns None."""
        model = _MockModel()
        state = GuardState(max_history_steps=100)
        state.escalation_count = 1
        mgr = EscalationManager(config=_config(model=model), state=state)
        # Edge case: capped AND no history → return None, not crash
        result = mgr.escalate(_trigger())
        assert result is None

    def test_cap_does_not_call_model(self) -> None:
        """When capped, the escalation model is NOT called."""
        model = _MockModel()
        state = _state((None, "ValueError", "fail"))
        state.escalation_count = 1
        mgr = EscalationManager(config=_config(model=model), state=state)
        mgr.escalate(_trigger())
        # Model must not be invoked when capped — saves cost
        assert len(model._invoke_args) == 0

    def test_cap_does_not_increment_count(self) -> None:
        """escalation_count stays at cap, doesn't increment further."""
        model = _MockModel()
        state = _state((None, "ValueError", "fail"))
        state.escalation_count = 2
        mgr = EscalationManager(
            config=_config(model=model, max_escalations_per_run=2),
            state=state,
        )
        mgr.escalate(_trigger())
        # Counter freezes at the cap, does not overflow past 2
        assert state.escalation_count == 2


# ── Fail-open (SPEC §4.5, OQ-3) ─────────────────────────────────────────

class TestFailOpen:
    """Tests for fail-open behaviour when escalation model fails."""

    def test_raise_original_re_raises_last_error(self) -> None:
        """on_guard_error="raise_original" re-raises the last ValueError."""
        model = _MockModel(should_fail=True)
        state = _state((None, "ValueError", "original failure"))
        mgr = EscalationManager(
            config=_config(model=model, on_guard_error="raise_original"),
            state=state,
        )
        # Fail-open mode "raise_original" finds the last error in history and re-raises
        with pytest.raises(ValueError, match="original failure"):
            mgr.escalate(_trigger())

    def test_raise_original_raises_escalation_error_when_no_prior(self) -> None:
        """If no prior error, raise_original raises EscalationError."""
        model = _MockModel(should_fail=True)
        state = _state(("ok output", None, None))  # no error
        mgr = EscalationManager(
            config=_config(model=model, on_guard_error="raise_original"),
            state=state,
        )
        # Edge case: no prior error to re-raise → fallback to EscalationError
        with pytest.raises(EscalationError, match="no previous error"):
            mgr.escalate(_trigger())

    def test_return_last_output(self) -> None:
        """on_guard_error="return_last_output" returns last step output."""
        model = _MockModel(should_fail=True)
        state = _state(("last known good", None, None))
        mgr = EscalationManager(
            config=_config(
                model=model, on_guard_error="return_last_output"
            ),
            state=state,
        )
        # Graceful degradation: return the last successful agent output
        result = mgr.escalate(_trigger())
        assert result == "last known good"

    def test_return_sentinel(self) -> None:
        """on_guard_error="return_sentinel" returns configured value."""
        model = _MockModel(should_fail=True)
        sentinel = {"status": "failed"}
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(
            config=_config(
                model=model,
                on_guard_error="return_sentinel",
            ),
            state=state,
        )

        mgr._config.sentinel_value = sentinel
        # Sentinel mode returns a caller-defined marker instead of real output
        result = mgr.escalate(_trigger())
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_async_fail_open_return_last_output(self) -> None:
        """Async escalation: model fails → return_last_output."""
        model = _MockModel(should_fail=True)
        state = _state(("last async output", None, None))
        mgr = EscalationManager(
            config=_config(
                model=model, on_guard_error="return_last_output"
            ),
            state=state,
        )
        # Async path must also handle fail-open correctly
        result = await mgr.escalate_async(_trigger())
        assert result == "last async output"


# ── Interrupt mode (on_escalate="interrupt") ─────────────────────────────

class TestInterruptMode:
    """Tests for on_escalate="interrupt" behaviour."""

    def test_interrupt_yes_escalates(self) -> None:
        """User says 'y' → escalation proceeds."""
        model = _MockModel(response="escalated result")
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(
            config=_config(model=model, on_escalate="interrupt"),
            state=state,
            interrupt_callback=lambda _: "y",
        )
        # Interrupt mode pauses before escalation; "y" means proceed
        result = mgr.escalate(_trigger())
        assert result == "escalated result"

    def test_interrupt_no_returns_last_output(self) -> None:
        """User says 'n' → returns last output, model NOT called."""
        model = _MockModel()
        state = _state(("declined output", None, None))
        mgr = EscalationManager(
            config=_config(model=model, on_escalate="interrupt"),
            state=state,
            interrupt_callback=lambda _: "n",
        )
        # "n" means skip escalation, return the last agent output instead
        result = mgr.escalate(_trigger())
        assert result == "declined output"
        # Model must NOT be called when user declines
        assert len(model._invoke_args) == 0

    def test_interrupt_callback_receives_summary(self) -> None:
        """Interrupt callback receives context summary string."""
        captured: list[str] = []

        def capture(summary: str) -> str:
            captured.append(summary)
            return "y"

        model = _MockModel()
        state = _state((None, "ValueError", "test failure"))
        mgr = EscalationManager(
            config=_config(model=model, on_escalate="interrupt"),
            state=state,
            interrupt_callback=capture,
        )
        mgr.escalate(_trigger())
        # The summary passed to the callback contains trigger + error info
        assert len(captured) == 1
        assert "repeated_error" in captured[0]
        assert "test failure" in captured[0]

    @pytest.mark.asyncio
    async def test_async_interrupt_yes_escalates(self) -> None:
        """Async interrupt with 'y' proceeds."""
        model = _MockModel(response="async escalated")
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(
            config=_config(model=model, on_escalate="interrupt"),
            state=state,
            interrupt_callback=lambda _: "y",
        )
        # Async interrupt also supports y/n decision via the same callback
        result = await mgr.escalate_async(_trigger())
        assert result == "async escalated"


# ── InterruptHandler standalone ──────────────────────────────────────────

class TestInterruptHandler:
    """Tests for InterruptHandler directly (without EscalationManager)."""

    def test_yes_answer_returns_true(self) -> None:
        """'y' response returns True."""
        handler = InterruptHandler(callback=lambda _: "y")
        assert handler.prompt("summary") is True

    def test_no_answer_returns_false(self) -> None:
        """'n' response returns False."""
        handler = InterruptHandler(callback=lambda _: "n")
        assert handler.prompt("summary") is False

    def test_case_insensitive(self) -> None:
        """'Y' (uppercase) response returns True."""
        handler = InterruptHandler(callback=lambda _: "Y")
        # User may type 'Y' instead of 'y' — must be tolerated
        assert handler.prompt("summary") is True

    def test_whitespace_tolerant(self) -> None:
        """Response with surrounding whitespace is trimmed before check."""
        handler = InterruptHandler(callback=lambda _: "  y  ")
        # Input may have accidental whitespace from copy-paste
        assert handler.prompt("summary") is True

    def test_any_other_response_is_false(self) -> None:
        """Non-y/n response (e.g. 'maybe') returns False."""
        handler = InterruptHandler(callback=lambda _: "maybe")
        # Only 'y'/'Y' maps to True; everything else (incl empty) is False
        assert handler.prompt("summary") is False


# ── Custom prompt ────────────────────────────────────────────────────────

class TestCustomPrompt:
    """Tests for configurable escalation prompts (FR-2.5)."""

    def test_custom_prompt_used_when_provided(self) -> None:
        """When escalation_prompt is set, it is used instead of default."""
        custom = "FIX THIS: {trigger_type} — {trigger_detail}"
        model = _MockModel()
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(
            config=_config(model=model, escalation_prompt=custom),
            state=state,
        )
        mgr.escalate(_trigger())
        prompt = model._invoke_args[0]
        # Custom prompt replaces the default template entirely
        assert prompt.startswith("FIX THIS:")
        assert "repeated_error" in prompt

    def test_default_prompt_used_when_not_provided(self) -> None:
        """When no custom prompt, the default template is used."""
        model = _MockModel()
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        mgr.escalate(_trigger())
        prompt = model._invoke_args[0]
        # Default prompt contains specific sentences from the template
        assert "You are an escalation model" in prompt
        assert "break the cycle" in prompt

    def test_prompt_includes_all_placeholders(self) -> None:
        """Default prompt is formatted with all required placeholders."""
        model = _MockModel()
        state = _state((None, "ValueError", "failed hard"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        mgr.escalate(_trigger())
        prompt = model._invoke_args[0]
        # Verify placeholders are resolved (not raw {brace} syntax)
        # Unresolved placeholders would mean str.format() missed a key
        assert "{trigger_type}" not in prompt
        assert "{trigger_detail}" not in prompt
        assert "{retry_count}" not in prompt

    def test_prompt_includes_failed_attempts(self) -> None:
        """Escalation prompt includes formatted failed attempts."""
        model = _MockModel()
        state = _state(
            (None, "ValueError", "error A"),
            (None, "ValueError", "error B"),
            (None, "ValueError", "error C"),
        )
        mgr = EscalationManager(config=_config(model=model), state=state)
        mgr.escalate(_trigger())
        prompt = model._invoke_args[0]
        # The formatted failed attempts section must include actual error messages
        assert "error A" in prompt or "error C" in prompt


# ── Context pipeline ─────────────────────────────────────────────────────

class TestContextPipeline:
    """Tests that context pipeline steps are applied."""

    def test_sanitization_applied_by_default(self) -> None:
        """Context is sanitized when sanitize_context=True (default)."""
        model = _MockModel()
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(
            config=_config(model=model, sanitize_context=True),
            state=state,
        )
        mgr.escalate(_trigger())
        prompt = model._invoke_args[0]
        # Sanitizer adds [AGENT OUTPUT] / [END AGENT OUTPUT] delimiters
        assert "[AGENT OUTPUT" in prompt or "[END AGENT OUTPUT]" in prompt

    def test_sanitization_skipped_when_disabled(self) -> None:
        """Context is NOT sanitized when sanitize_context=False."""
        model = _MockModel()
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(
            config=_config(model=model, sanitize_context=False),
            state=state,
        )
        mgr.escalate(_trigger())
        prompt = model._invoke_args[0]
        # Delimiters must not appear when sanitization is off
        assert "[AGENT OUTPUT" not in prompt

    def test_redaction_applied_when_patterns_set(self) -> None:
        """Secrets are redacted before sending to escalation model."""
        model = _MockModel()
        fake_key = "sk-proj1234567890abcdef1234567890abcdef1234567890abcdef"
        state = _state((None, "ValueError", f"key: {fake_key}"))
        mgr = EscalationManager(
            config=_config(
                model=model,
                redact_patterns=[r"sk-[A-Za-z0-9]{48}"],
                sanitize_context=False,
            ),
            state=state,
        )
        mgr.escalate(_trigger())
        prompt = model._invoke_args[0]
        # API keys must be replaced with [REDACTED] before reaching the model
        assert "[REDACTED]" in prompt

    def test_redaction_skipped_when_no_patterns_or_fields(self) -> None:
        """When no redact_patterns or redact_fields, no redaction runs."""
        model = _MockModel()
        state = _state((None, "ValueError", "clean message"))
        mgr = EscalationManager(
            config=_config(
                model=model,
                redact_patterns=[],
                redact_fields=[],
                sanitize_context=False,
            ),
            state=state,
        )
        mgr.escalate(_trigger())
        prompt = model._invoke_args[0]
        # Without patterns or fields, message passes through unmodified
        assert "clean message" in prompt


# ── Model response extraction ────────────────────────────────────────────

class TestExtractContent:
    """Tests for _extract_content — response unwrapping."""

    def test_extracts_content_from_message(self) -> None:
        """AIMessage.content is extracted."""
        model = _MockModel(response="the answer")
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        # LangChain models return AIMessage objects — must unwrap .content
        result = mgr.escalate(_trigger())
        assert result == "the answer"

    def test_passes_through_plain_strings(self) -> None:
        """Plain string responses (no .content) are returned as-is."""
        model = Mock()
        model.invoke.return_value = "plain result"
        type(model).model_name = PropertyMock(return_value="mock")

        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        # Non-LangChain models may return strings directly — handle gracefully
        result = mgr.escalate(_trigger())
        assert result == "plain result"


# ── Custom trigger type ──────────────────────────────────────────────────

class TestCustomTriggerType:
    """Tests for escalation with non-default trigger types."""

    def test_custom_trigger_name_in_prompt(self) -> None:
        """Custom trigger name appears in the escalation prompt."""
        model = _MockModel()
        state = _state((None, "ValueError", "fail"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        mgr.escalate(_trigger(name="schema_invalid"))
        prompt = model._invoke_args[0]
        # The trigger name is injected into the prompt via {trigger_type}
        assert "schema_invalid" in prompt

    def test_test_failure_trigger(self) -> None:
        """test_failure trigger fires and escalates correctly."""
        model = _MockModel(response="fixed tests")
        state = _state((None, "ValueError", "test_parser failed"))
        mgr = EscalationManager(config=_config(model=model), state=state)
        # All trigger types should flow through escalation identically
        result = mgr.escalate(_trigger(name="test_failure"))
        assert result == "fixed tests"
