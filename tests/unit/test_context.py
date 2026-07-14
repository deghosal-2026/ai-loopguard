"""Tests for ContextPackager, Sanitizer, and Redactor.

Covers per WBS S4:
- Packaging: includes trigger, attempts, error
- Compression: 20 steps → first + summary + last. 2 steps → no compression.
  1 step → no compression.
- Token budget: over-budget context is compressed to fit
- Sanitizer: adds delimiters to all agent content
- Sanitizer: preserves system instructions outside delimiters
- Redactor: strips AWS keys, GitHub tokens, OpenAI keys, Anthropic keys
- Redactor: strips named fields from state dict
- Redactor: replaces with [REDACTED]
- Redactor: with use_builtin=False only applies user patterns
"""

from ai_loopguard._internal.state import GuardState, StepRecord, TriggerResult
from ai_loopguard.context import (
    ContextPackager,
    EscalationContext,
    Redactor,
    Sanitizer,
)

# ── helpers ──────────────────────────────────────────────────────────────

def _build_state(steps: list[StepRecord]) -> GuardState:
    """Build a GuardState from a list of StepRecords."""
    state = GuardState(max_history_steps=100)
    for s in steps:
        state.add_step(s)
    return state


def _trigger() -> TriggerResult:
    """Return a standard TriggerResult for test packaging."""
    return TriggerResult(
        trigger_name="repeated_error",
        detail="ValueError: fail, 3 consecutive",
        retry_count=3,
    )


# ── ContextPackager — packaging ─────────────────────────────────────────

class TestContextPackagerPackage:
    """Tests for ContextPackager.package() — basic packaging."""

    def test_package_includes_trigger(self) -> None:
        """Packaged context includes the trigger dict."""
        packager = ContextPackager()
        state = _build_state([
            StepRecord(step_num=0, output="task description",
                       error_type=None, error_message=None),
        ])
        tr = _trigger()
        ctx = packager.package(state, tr)
        # The EscalationContext bundles trigger info for the escalation model
        assert ctx.trigger["trigger_name"] == "repeated_error"
        assert ctx.trigger["detail"] == "ValueError: fail, 3 consecutive"

    def test_package_includes_task_description(self) -> None:
        """First step output becomes task_description."""
        packager = ContextPackager()
        state = _build_state([
            StepRecord(step_num=0, output="build a parser",
                       error_type=None, error_message=None),
        ])
        ctx = packager.package(state, _trigger())
        # task_description is derived from the first step's output
        assert ctx.task_description == "build a parser"

    def test_package_task_description_none_when_empty(self) -> None:
        """task_description is None when GuardState has no steps."""
        packager = ContextPackager()
        state = GuardState(max_history_steps=100)
        ctx = packager.package(state, _trigger())
        # Edge case: no steps at all → task_description is None, not ""
        assert ctx.task_description is None

    def test_package_task_description_none_when_none_output(self) -> None:
        """task_description is None when first step output is None."""
        packager = ContextPackager()
        state = _build_state([
            StepRecord(step_num=0, output=None,
                       error_type="ValueError", error_message="fail"),
        ])
        ctx = packager.package(state, _trigger())
        # If the first step immediately errored with no output, description is None
        assert ctx.task_description is None

    def test_package_includes_failed_attempts(self) -> None:
        """All steps become failed_attempts summaries (compression disabled)."""
        packager = ContextPackager(compress_context=False)
        state = _build_state([
            StepRecord(step_num=0, output="attempt 1",
                       error_type=None, error_message=None),
            StepRecord(step_num=1, output=None,
                       error_type="ValueError", error_message="fail"),
            StepRecord(step_num=2, output="attempt 3",
                       error_type=None, error_message=None),
        ])
        ctx = packager.package(state, _trigger())
        # Every step is included as a dict summarizing output/error
        assert len(ctx.failed_attempts) == 3
        assert ctx.failed_attempts[0]["step"] == 0
        assert ctx.failed_attempts[1]["error"] == "ValueError"

    def test_package_includes_last_error(self) -> None:
        """last_error comes from the most recent step with an error."""
        packager = ContextPackager()
        state = _build_state([
            StepRecord(step_num=0, output=None,
                       error_type="ValueError", error_message="first fail"),
            StepRecord(step_num=1, output=None,
                       error_type="TypeError", error_message="last fail"),
        ])
        ctx = packager.package(state, _trigger())
        # Scans backwards from the tail for the first step with an error
        assert ctx.last_error == "last fail"

    def test_package_last_error_none_when_no_errors(self) -> None:
        """last_error is None when no steps have errors."""
        packager = ContextPackager()
        state = _build_state([
            StepRecord(step_num=0, output="success",
                       error_type=None, error_message=None),
        ])
        ctx = packager.package(state, _trigger())
        # No errors in history → last_error stays None
        assert ctx.last_error is None


# ── ContextPackager — compression ────────────────────────────────────────

class TestContextPackagerCompression:
    """Tests for ContextPackager compression (FR-2.6)."""

    def _step(self, i: int, output: str) -> StepRecord:
        return StepRecord(
            step_num=i, output=output,
            error_type=None, error_message=None,
        )

    def test_no_compression_for_one_step(self) -> None:
        """Single step — no compression applies."""
        packager = ContextPackager(compress_context=True)
        state = _build_state([self._step(0, "only step")])
        ctx = packager.package(state, _trigger())
        # 1 step is below the compression threshold
        assert len(ctx.failed_attempts) == 1

    def test_no_compression_for_two_steps(self) -> None:
        """Two steps — no compression (≤2 steps returned as-is)."""
        packager = ContextPackager(compress_context=True)
        state = _build_state([
            self._step(0, "first"), self._step(1, "second"),
        ])
        ctx = packager.package(state, _trigger())
        # 2 steps is also below the compression threshold (threshold is > 2)
        assert len(ctx.failed_attempts) == 2

    def test_compression_for_three_steps(self) -> None:
        """Three steps — compressed to [first, _summary, last]."""
        packager = ContextPackager(compress_context=True)
        state = _build_state([
            self._step(0, "first"),
            self._step(1, "middle"),
            self._step(2, "last"),
        ])
        ctx = packager.package(state, _trigger())
        # 3+ steps get compressed: first kept, middle summarized, last kept
        assert len(ctx.failed_attempts) == 3
        assert ctx.failed_attempts[0]["step"] == 0
        assert "_summary" in ctx.failed_attempts[1]
        assert ctx.failed_attempts[2]["step"] == 2

    def test_compression_for_twenty_steps(self) -> None:
        """20 steps — compressed to [first, _summary, last]."""
        packager = ContextPackager(compress_context=True)
        steps = [self._step(i, f"step {i}") for i in range(20)]
        state = _build_state(steps)
        ctx = packager.package(state, _trigger())
        # Even 20 steps collapse to just 3 entries
        assert len(ctx.failed_attempts) == 3

    def test_no_compression_when_disabled(self) -> None:
        """compress_context=False returns all steps uncompressed."""
        packager = ContextPackager(compress_context=False)
        steps = [self._step(i, f"step {i}") for i in range(10)]
        state = _build_state(steps)
        ctx = packager.package(state, _trigger())
        # Disabling compression preserves every step individually
        assert len(ctx.failed_attempts) == 10

    def test_compression_drops_middle_when_over_budget(self) -> None:
        """Small budget → middle summary dropped, only first+last."""
        packager = ContextPackager(
            max_context_tokens=50, compress_context=True,
        )
        steps = [self._step(i, "long output text " * 5) for i in range(10)]
        state = _build_state(steps)
        ctx = packager.package(state, _trigger())
        # Token budget too small even for 3 entries → drops to first + last only
        assert len(ctx.failed_attempts) == 2
        assert "_summary" not in ctx.failed_attempts[0]
        assert "_summary" not in ctx.failed_attempts[1]


# ── ContextPackager — summary() ──────────────────────────────────────────

class TestContextPackagerSummary:
    """Tests for ContextPackager.summary() — interrupt-mode display."""

    def test_summary_includes_trigger_name(self) -> None:
        """Summary string includes the trigger name."""
        packager = ContextPackager()
        state = _build_state([
            StepRecord(step_num=0, output="task",
                       error_type=None, error_message=None),
        ])
        ctx = packager.package(state, _trigger())
        s = packager.summary(ctx)
        # Summary is a human-readable string for interrupt-mode display
        assert "repeated_error" in s

    def test_summary_includes_detail(self) -> None:
        """Summary string includes the trigger detail."""
        packager = ContextPackager()
        state = _build_state([
            StepRecord(step_num=0, output="task",
                       error_type=None, error_message=None),
        ])
        ctx = packager.package(state, _trigger())
        s = packager.summary(ctx)
        assert "ValueError" in s

    def test_summary_includes_retries(self) -> None:
        """Summary string includes the retry count."""
        packager = ContextPackager()
        state = _build_state([
            StepRecord(step_num=0, output="task",
                       error_type=None, error_message=None),
        ])
        ctx = packager.package(state, _trigger())
        s = packager.summary(ctx)
        assert "3" in s  # retry count

    def test_summary_includes_last_error(self) -> None:
        """Summary string includes the last error message."""
        packager = ContextPackager()
        state = _build_state([
            StepRecord(step_num=0, output=None,
                       error_type="ValueError", error_message="boom"),
        ])
        ctx = packager.package(state, _trigger())
        s = packager.summary(ctx)
        assert "boom" in s


# ── Sanitizer ────────────────────────────────────────────────────────────

class TestSanitizer:
    """Tests for Sanitizer (T1 / FR-2.8)."""

    def test_sanitize_wraps_task_description(self) -> None:
        """Task description is wrapped in AGENT_CONTENT delimiters."""
        ctx = EscalationContext(
            trigger={"trigger_name": "t", "detail": "d", "retry_count": 1},
            task_description="do something",
            failed_attempts=[],
            last_error=None,
        )
        result = Sanitizer.sanitize(ctx)
        # Delimiters help the escalation model distinguish agent output from instructions
        assert result.task_description is not None
        assert Sanitizer.AGENT_CONTENT_PREFIX in result.task_description
        assert Sanitizer.AGENT_CONTENT_SUFFIX in result.task_description

    def test_sanitize_wraps_last_error(self) -> None:
        """last_error is wrapped in delimiters."""
        ctx = EscalationContext(
            trigger={},
            task_description=None,
            failed_attempts=[],
            last_error="something broke",
        )
        result = Sanitizer.sanitize(ctx)
        # Even single strings like last_error get wrapped
        assert result.last_error is not None
        assert Sanitizer.AGENT_CONTENT_PREFIX in result.last_error
        assert "something broke" in result.last_error

    def test_sanitize_wraps_failed_attempts_string_fields(self) -> None:
        """Output and error_message fields are delimited in failed_attempts."""
        ctx = EscalationContext(
            trigger={},
            task_description=None,
            failed_attempts=[{
                "step": 0,
                "output": "agent produced this",
                "error_message": "agent erred",
            }],
            last_error=None,
        )
        result = Sanitizer.sanitize(ctx)
        fa = result.failed_attempts[0]
        # Each string field in failed_attempt dicts is individually wrapped
        assert Sanitizer.AGENT_CONTENT_PREFIX in str(fa["output"])
        assert Sanitizer.AGENT_CONTENT_PREFIX in str(fa["error_message"])

    def test_sanitize_preserves_trigger(self) -> None:
        """Trigger dict is passed through unchanged."""
        trigger: dict[str, str | int] = {
            "trigger_name": "repeated_error", "detail": "d", "retry_count": 1,
        }
        ctx = EscalationContext(
            trigger=trigger,
            task_description=None,
            failed_attempts=[],
            last_error=None,
        )
        result = Sanitizer.sanitize(ctx)
        # Trigger metadata is system-generated, not agent output — no wrapping
        assert result.trigger == trigger

    def test_sanitize_none_fields_stay_none(self) -> None:
        """None fields remain None after sanitization."""
        ctx = EscalationContext(
            trigger={},
            task_description=None,
            failed_attempts=[],
            last_error=None,
        )
        result = Sanitizer.sanitize(ctx)
        # None fields must not be converted to "None" string by wrapping
        assert result.task_description is None
        assert result.last_error is None


# ── Redactor — built-in patterns ─────────────────────────────────────────

class TestRedactorBuiltinPatterns:
    """Tests for Redactor built-in secret patterns (T2 / FR-2.9)."""

    def _ctx(self, **kwargs: str | None) -> EscalationContext:
        return EscalationContext(
            trigger={},
            task_description=kwargs.get("task"),
            failed_attempts=kwargs.get("attempts", []),  # type: ignore[arg-type]
            last_error=kwargs.get("last_error"),
        )

    def test_redacts_openai_key(self) -> None:
        """OpenAI API key replaced with [REDACTED]."""
        ctx = self._ctx(
            task="use key sk-proj1234567890abcdef1234567890abcdef1234567890abcdef",
        )
        result = Redactor.redact(ctx)
        # Built-in pattern matches OpenAI sk-proj-* keys
        assert result.task_description is not None
        assert Redactor.REDACTED_PLACEHOLDER in result.task_description
        assert "sk-" not in result.task_description

    def test_redacts_aws_access_key(self) -> None:
        """AWS access key (AKIA...) replaced with [REDACTED]."""
        ctx = self._ctx(task="key: AKIAIOSFODNN7EXAMPLE")
        result = Redactor.redact(ctx)
        # Built-in pattern matches AWS AKIA* access keys
        assert result.task_description is not None
        assert Redactor.REDACTED_PLACEHOLDER in result.task_description
        assert "AKIA" not in result.task_description

    def test_redacts_github_token(self) -> None:
        """GitHub token (ghp_...) replaced with [REDACTED]."""
        ctx = self._ctx(task="token=ghp_abcdefghijklmnopqrstuvwxyz1234567890")
        result = Redactor.redact(ctx)
        # Built-in pattern matches GitHub ghp_* personal access tokens
        assert result.task_description is not None
        assert Redactor.REDACTED_PLACEHOLDER in result.task_description

    def test_redacts_anthropic_key(self) -> None:
        """Anthropic API key replaced with [REDACTED]."""
        # Use the pattern: sk-ant- + 95 chars of alphanumeric/hyphen/underscore
        key = "sk-ant-" + ("a" * 95)
        ctx = self._ctx(task=f"key: {key}")
        result = Redactor.redact(ctx)
        # Built-in pattern matches Anthropic sk-ant-* API keys
        assert result.task_description is not None
        assert Redactor.REDACTED_PLACEHOLDER in result.task_description

    def test_redacts_in_last_error(self) -> None:
        """Secrets in last_error are also redacted."""
        ctx = self._ctx(
            last_error="Auth failed with key sk-ant-" + ("a" * 95),
        )
        result = Redactor.redact(ctx)
        # Redaction applies to all text fields, not just task_description
        assert "sk-ant-" not in str(result.last_error)

    def test_redacts_in_failed_attempts(self) -> None:
        """Secrets in failed_attempts output fields are redacted."""
        ctx = _esc_ctx_with_attempts([
            {"step": 0, "output": "token: ghp_abcdefghijklmnopqrstuvwxyz1234567890"},
        ])
        result = Redactor.redact(ctx)
        # Also applies to all string fields inside failed_attempt dicts
        output = str(result.failed_attempts[0].get("output", ""))
        assert Redactor.REDACTED_PLACEHOLDER in output
        assert "ghp_" not in output


# ── Redactor — field stripping ───────────────────────────────────────────

class TestRedactorFieldStripping:
    """Tests for field name stripping in Redactor."""

    def test_strips_named_field_from_attempts(self) -> None:
        """Field named in redact_fields is removed from attempt dicts."""
        ctx = _esc_ctx_with_attempts([
            {"step": 0, "api_key": "secret123", "output": "ok"},
        ])
        result = Redactor.redact(ctx, fields=["api_key"])
        # Named fields are deleted from the dict entirely, not replaced
        assert "api_key" not in result.failed_attempts[0]
        # Non-targeted fields must be preserved
        assert result.failed_attempts[0]["output"] == "ok"

    def test_strips_multiple_fields(self) -> None:
        """Multiple named fields are all removed."""
        ctx = _esc_ctx_with_attempts([
            {"step": 0, "api_key": "a", "credentials": "b", "ssn": "c", "ok": "d"},
        ])
        result = Redactor.redact(ctx, fields=["api_key", "credentials", "ssn"])
        fa = result.failed_attempts[0]
        # All three named field keys must be removed
        assert "api_key" not in fa
        assert "credentials" not in fa
        assert "ssn" not in fa
        # Unlisted field is preserved
        assert fa["ok"] == "d"

    def test_missing_field_no_error(self) -> None:
        """Stripping a field that doesn't exist is a no-op."""
        ctx = _esc_ctx_with_attempts([
            {"step": 0, "output": "ok"},
        ])
        result = Redactor.redact(ctx, fields=["nonexistent"])
        # Attempting to strip a non-existent key must not raise
        assert result.failed_attempts[0]["output"] == "ok"


# ── Redactor — use_builtin=False ─────────────────────────────────────────

class TestRedactorNoBuiltin:
    """Tests for Redactor with use_builtin=False."""

    def test_no_builtin_does_not_redact_openai_key(self) -> None:
        """Without built-in patterns, OpenAI key is NOT redacted."""
        ctx = _esc_ctx(task="key=sk-proj1234567890abcdef1234567890abcdef1234567890abcdef")
        result = Redactor.redact(ctx, use_builtin=False)
        # use_builtin=False disables the built-in pattern set — key passes through
        assert "sk-" in str(result.task_description)

    def test_user_patterns_still_apply_without_builtin(self) -> None:
        """User-defined patterns apply even when built-in is disabled."""
        ctx = _esc_ctx(task="my custom secret is supersafe")
        result = Redactor.redact(ctx, patterns=[r"supersafe"], use_builtin=False)
        # User-supplied regex patterns still operate even without builtins
        assert result.task_description is not None
        assert "supersafe" not in result.task_description


# ── helpers ──────────────────────────────────────────────────────────────

def _esc_ctx(
    task: str | None = None,
    attempts: list[dict[str, object]] | None = None,
    last_error: str | None = None,
) -> EscalationContext:
    return EscalationContext(
        trigger={},
        task_description=task,
        failed_attempts=attempts or [],
        last_error=last_error,
    )


def _esc_ctx_with_attempts(
    attempts: list[dict[str, object]],
) -> EscalationContext:
    return EscalationContext(
        trigger={},
        task_description=None,
        failed_attempts=attempts,
        last_error=None,
    )
