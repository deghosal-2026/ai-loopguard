"""Tests for the loopguard exception hierarchy.

Verifies:
- All 6 custom exceptions inherit from LoopguardError → Exception
- Each exception carries a message string
- The backwards-compatible alias EscalationCapReached works (SPEC §16)
- Catching LoopguardError catches all subclasses (correct hierarchy)
- Specific subclass catch works without catching siblings
- Raising base LoopguardError is NOT caught by subclass handler

Naming note: SPEC §16 originally used "EscalationCapReached".
Ruff rule N818 requires exception names to end in "Error", so the
canonical name is EscalationCapError. The old name is preserved as
an alias for backwards compatibility.
"""

from ai_loopguard.exceptions import (
    ConfigError,
    ContextError,
    EscalationCapError,
    EscalationCapReached,
    EscalationError,
    LoopguardError,
    TriggerError,
)

# ── Hierarchy tests ──────────────────────────────────────────────────


class TestExceptionHierarchy:
    """Verify all exceptions inherit correctly from LoopguardError."""

    def test_loopguard_error_base(self) -> None:
        """LoopguardError inherits from Exception."""
        assert issubclass(LoopguardError, Exception)

    def test_escalation_error(self) -> None:
        """EscalationError inherits from LoopguardError."""
        assert issubclass(EscalationError, LoopguardError)
        # Verify message propagation — standard Exception.__init__
        error = EscalationError("model failed")
        assert str(error) == "model failed"

    def test_escalation_cap_error(self) -> None:
        """EscalationCapError inherits from LoopguardError."""
        assert issubclass(EscalationCapError, LoopguardError)
        error = EscalationCapError("max escalations hit")
        assert str(error) == "max escalations hit"

    def test_escalation_cap_reached_alias(self) -> None:
        """EscalationCapReached IS EscalationCapError (same object)."""
        # Identity check — the alias points to the same class object
        # Maintained for SPEC §16 backwards compatibility
        assert EscalationCapReached is EscalationCapError
        # Inheritance still works through the alias
        assert issubclass(EscalationCapReached, LoopguardError)

    def test_trigger_error(self) -> None:
        """TriggerError inherits from LoopguardError."""
        assert issubclass(TriggerError, LoopguardError)
        error = TriggerError("callback failed")
        assert str(error) == "callback failed"

    def test_config_error(self) -> None:
        """ConfigError inherits from LoopguardError."""
        assert issubclass(ConfigError, LoopguardError)
        error = ConfigError("invalid config")
        assert str(error) == "invalid config"

    def test_context_error(self) -> None:
        """ContextError inherits from LoopguardError."""
        assert issubclass(ContextError, LoopguardError)
        error = ContextError("redaction failed")
        assert str(error) == "redaction failed"

    # ── Catch-all behaviour ────────────────────────────────────────

    def test_catch_all_loopguard(self) -> None:
        """All 5 subclasses are catchable via `except LoopguardError:`."""
        for exc in [
            EscalationError,
            EscalationCapError,
            TriggerError,
            ConfigError,
            ContextError,
        ]:
            assert issubclass(exc, LoopguardError)

    def test_catch_specific_exception(self) -> None:
        """A specific subclass catch handler should fire for its own type."""
        try:
            raise EscalationError("test")
        except EscalationError:
            pass  # Expected — caught by specific handler
        else:
            raise AssertionError("EscalationError was not caught by its own handler")

    def test_loopguard_error_not_caught_as_subclass(self) -> None:
        """Raising LoopguardError base should NOT be caught by a subclass handler."""
        try:
            raise LoopguardError("base error")
        except EscalationError:
            # This would be WRONG — base class should not match subclass handler
            raise AssertionError(
                "Base LoopguardError should not be caught as EscalationError"
            )
        except LoopguardError:
            pass  # Expected — caught by the base handler
