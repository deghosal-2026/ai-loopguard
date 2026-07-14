"""Tests for GuardConfig and TriggerConfig Pydantic models.

Covers:
- Defaults: verify all default values match SPEC §2.1
- Custom values: verify user-provided overrides work
- Validation: verify Pydantic rejects out-of-range values
- Boundaries: verify exact boundary values are accepted
- Fixtures: verify conftest fixtures return expected configs
- Custom triggers: verify overriding the default triggers dict works

All validation errors come from Pydantic at construction time — we test
that invalid values raise ValidationError before any Guard logic runs.
"""

import pytest
from pydantic import ValidationError

from ai_loopguard.config import GuardConfig, TriggerConfig

# ── TriggerConfig tests ───────────────────────────────────────────────


class TestTriggerConfig:
    """Tests for TriggerConfig Pydantic model validation."""

    def test_defaults(self) -> None:
        """Default TriggerConfig: enabled=True, max_retries=3, no callback."""
        config = TriggerConfig()
        assert config.enabled is True
        assert config.max_retries == 3
        assert config.custom_callback is None

    def test_custom_values(self) -> None:
        """Custom max_retries and enabled override the factory defaults."""
        config = TriggerConfig(max_retries=5, enabled=False)
        assert config.max_retries == 5
        assert config.enabled is False

    def test_invalid_max_retries_below_min(self) -> None:
        """max_retries=0 should raise ValidationError — Pydantic Field(ge=1)."""
        with pytest.raises(ValidationError):
            # Pydantic Field(ge=1) rejects 0 before any Guard logic runs
            TriggerConfig(max_retries=0)

    def test_invalid_max_retries_above_max(self) -> None:
        """max_retries=21 should raise ValidationError — Pydantic Field(le=20)."""
        with pytest.raises(ValidationError):
            # Pydantic Field(le=20) rejects 21 as out of range
            TriggerConfig(max_retries=21)

    def test_boundary_values(self) -> None:
        """Boundary values 1 (min) and 20 (max) should be accepted."""
        # Minimum — the lowest valid threshold
        # Tests the inclusive lower bound of Field(ge=1)
        min_config = TriggerConfig(max_retries=1)
        assert min_config.max_retries == 1

        # Maximum — the highest valid threshold
        # Tests the inclusive upper bound of Field(le=20)
        max_config = TriggerConfig(max_retries=20)
        assert max_config.max_retries == 20

    def test_custom_callback_set(self) -> None:
        """A custom callback should be stored and remain callable."""
        def my_callback() -> bool:
            return True

        config = TriggerConfig(custom_callback=my_callback)
        assert config.custom_callback is not None
        # Verify we can actually call it
        assert config.custom_callback() is True


# ── GuardConfig tests ─────────────────────────────────────────────────


class TestGuardConfig:
    """Tests for GuardConfig Pydantic model validation."""

    # ── defaults ──────────────────────────────────────────────────

    def test_defaults(self) -> None:
        """Default GuardConfig: all SPEC §2.1 defaults are correct."""
        config = GuardConfig()
        # Every field must match the spec-defined factory defaults
        assert config.on_escalate == "auto"
        assert config.max_escalations_per_run == 1
        assert config.max_context_tokens == 4000
        assert config.compress_context is True
        assert config.sanitize_context is True
        assert config.on_guard_error == "raise_original"
        assert config.max_history_steps == 100
        assert config.log_dir is None
        assert config.sentinel_value is None

    def test_default_triggers(self) -> None:
        """Default GuardConfig includes all three built-in triggers at max_retries=3."""
        config = GuardConfig()
        assert "repeated_error" in config.triggers
        assert "test_failure" in config.triggers
        assert "schema_invalid" in config.triggers
        # All three triggers should share the same default max_retries
        for trigger in config.triggers.values():
            assert trigger.max_retries == 3
            assert trigger.enabled is True

    def test_redact_fields_default_empty(self) -> None:
        """redact_fields and redact_patterns default to empty lists."""
        config = GuardConfig()
        # Empty lists means no field stripping or pattern redaction by default
        assert config.redact_fields == []
        assert config.redact_patterns == []

    # ── custom values ──────────────────────────────────────────────

    def test_custom_values(self) -> None:
        """All configurable fields accept and retain custom values."""
        config = GuardConfig(
            on_escalate="interrupt",
            max_escalations_per_run=3,
            max_context_tokens=8000,
            compress_context=False,
            sanitize_context=False,
            on_guard_error="return_last_output",
            max_history_steps=50,
            log_dir="/tmp/loopguard",
        )
        # Every field can be overridden from its default
        assert config.on_escalate == "interrupt"
        assert config.max_escalations_per_run == 3
        assert config.max_context_tokens == 8000
        assert config.compress_context is False
        assert config.sanitize_context is False
        assert config.on_guard_error == "return_last_output"
        assert config.max_history_steps == 50
        assert config.log_dir == "/tmp/loopguard"

    def test_sentinel_value_custom(self) -> None:
        """sentinel_value accepts arbitrary Python objects."""
        config = GuardConfig(sentinel_value="FALLBACK")
        # sentinel_value is Any type — can be string, dict, None, etc.
        assert config.sentinel_value == "FALLBACK"

    def test_custom_triggers_override(self) -> None:
        """Custom triggers dict replaces defaults entirely — not a merge."""
        custom = {"repeated_error": TriggerConfig(max_retries=5)}
        config = GuardConfig(triggers=custom)
        assert "repeated_error" in config.triggers
        # Other triggers should NOT be present when overridden
        # This is a full replacement, not dict.update()
        assert "test_failure" not in config.triggers
        assert config.triggers["repeated_error"].max_retries == 5

    # ── invalid values ────────────────────────────────────────────

    def test_invalid_on_escalate(self) -> None:
        """Invalid on_escalate value raises Pydantic ValidationError."""
        with pytest.raises(ValidationError):
            # on_escalate is a Literal["auto", "interrupt"] — "invalid" doesn't match
            GuardConfig(on_escalate="invalid")  # type: ignore[arg-type]

    def test_invalid_max_escalations(self) -> None:
        """max_escalations_per_run outside [1, 10] is rejected."""
        with pytest.raises(ValidationError):
            # Below minimum (Field(ge=1))
            GuardConfig(max_escalations_per_run=0)
        with pytest.raises(ValidationError):
            # Above maximum (Field(le=10))
            GuardConfig(max_escalations_per_run=11)

    def test_invalid_max_context_tokens(self) -> None:
        """max_context_tokens outside [500, 32000] is rejected."""
        with pytest.raises(ValidationError):
            # Below min token budget
            GuardConfig(max_context_tokens=499)
        with pytest.raises(ValidationError):
            # Above max token budget
            GuardConfig(max_context_tokens=32001)

    def test_invalid_on_guard_error(self) -> None:
        """Invalid on_guard_error value raises Pydantic ValidationError."""
        with pytest.raises(ValidationError):
            # on_guard_error is a Literal — "nonexistent" is not a valid option
            GuardConfig(on_guard_error="nonexistent")  # type: ignore[arg-type]

    def test_invalid_max_history_steps(self) -> None:
        """max_history_steps outside [10, 1000] is rejected."""
        with pytest.raises(ValidationError):
            # Below minimum history window
            GuardConfig(max_history_steps=9)
        with pytest.raises(ValidationError):
            # Above maximum history window
            GuardConfig(max_history_steps=1001)

    # ── boundary values ───────────────────────────────────────────

    def test_boundary_max_escalations(self) -> None:
        """Boundary max_escalations_per_run: 1 (min) and 10 (max) accepted."""
        assert GuardConfig(max_escalations_per_run=1).max_escalations_per_run == 1
        assert GuardConfig(max_escalations_per_run=10).max_escalations_per_run == 10

    def test_boundary_max_context_tokens(self) -> None:
        """Boundary max_context_tokens: 500 (min) and 32000 (max) accepted."""
        assert GuardConfig(max_context_tokens=500).max_context_tokens == 500
        assert GuardConfig(max_context_tokens=32000).max_context_tokens == 32000

    def test_boundary_max_history_steps(self) -> None:
        """Boundary max_history_steps: 10 (min) and 1000 (max) accepted."""
        assert GuardConfig(max_history_steps=10).max_history_steps == 10
        assert GuardConfig(max_history_steps=1000).max_history_steps == 1000


# ── Conftest fixture integration tests ──────────────────────────────


class TestConftestFixtures:
    """Verify that conftest.py fixtures return correct configurations.

    Separate from TestGuardConfig because these depend on fixture
    injection by pytest, not direct construction.
    """

    def test_mock_guard_config(
        self, mock_guard_config: GuardConfig
    ) -> None:
        """mock_guard_config fixture returns a valid default config."""
        assert mock_guard_config.on_escalate == "auto"
        assert mock_guard_config.max_escalations_per_run == 1

    def test_mock_trigger_config(
        self, mock_trigger_config: TriggerConfig
    ) -> None:
        """mock_trigger_config fixture returns max_retries=3, enabled=True."""
        assert mock_trigger_config.max_retries == 3
        assert mock_trigger_config.enabled is True

    def test_mock_trigger_config_disabled(
        self, mock_trigger_config_disabled: TriggerConfig
    ) -> None:
        """Disabled fixture returns enabled=False, max_retries=5."""
        assert mock_trigger_config_disabled.enabled is False
        assert mock_trigger_config_disabled.max_retries == 5

    def test_mock_trigger_config_custom_retries(
        self, mock_trigger_config_custom_retries: TriggerConfig
    ) -> None:
        """custom_retries fixture returns max_retries=5."""
        assert mock_trigger_config_custom_retries.max_retries == 5
