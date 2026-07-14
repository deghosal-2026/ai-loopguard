"""Tests for default escalation prompt templates.

Covers:
- DEFAULT_ESCALATION_PROMPT exists and is a non-empty string
- All 6 template placeholders are present (missing one = KeyError at runtime)
- The prompt contains structural section headers (What happened, etc.)
- The prompt can be .format()'ed with all placeholders without error

The prompt is a template consumed by EscalationManager._build_prompt().
Template variables are filled via str.format(**kwargs). Missing a
placeholder would cause a KeyError at runtime, so we verify all expected
keys are present in the template string.
"""

from ai_loopguard._internal.prompts import DEFAULT_ESCALATION_PROMPT


class TestDefaultPrompt:
    """Tests for the DEFAULT_ESCALATION_PROMPT template (SPEC §4.4)."""

    def test_prompt_exists(self) -> None:
        """DEFAULT_ESCALATION_PROMPT is a non-empty str."""
        assert isinstance(DEFAULT_ESCALATION_PROMPT, str)
        assert len(DEFAULT_ESCALATION_PROMPT) > 0

    def test_prompt_has_placeholders(self) -> None:
        """All 6 template placeholders are present in the prompt string."""
        # If any of these is missing, str.format() will raise KeyError at runtime
        for placeholder in [
            "{trigger_type}",
            "{trigger_detail}",
            "{retry_count}",
            "{workhorse_model}",
            "{failed_attempts}",
            "{last_error}",
        ]:
            assert placeholder in DEFAULT_ESCALATION_PROMPT

    def test_prompt_has_sections(self) -> None:
        """The prompt contains structural section headers (SPEC §4.4 format)."""
        assert "What happened" in DEFAULT_ESCALATION_PROMPT
        assert "What was tried" in DEFAULT_ESCALATION_PROMPT
        assert "Last error" in DEFAULT_ESCALATION_PROMPT
        assert "Your task" in DEFAULT_ESCALATION_PROMPT

    def test_prompt_can_be_formatted(self) -> None:
        """The prompt can be .format()'ed with all placeholders (no KeyError)."""
        formatted = DEFAULT_ESCALATION_PROMPT.format(
            trigger_type="repeated_error",
            trigger_detail="ValueError 3x",
            retry_count=3,
            workhorse_model="qwen",
            failed_attempts="attempt1, attempt2, attempt3",
            last_error="ValueError: bad value",
        )
        # The formatted output should contain the substituted values
        # Verifies all placeholders resolve without KeyError
        assert "repeated_error" in formatted
        assert "ValueError 3x" in formatted
        assert "ValueError: bad value" in formatted
