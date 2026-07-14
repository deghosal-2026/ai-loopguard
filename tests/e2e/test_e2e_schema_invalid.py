"""E2E: schema_invalid trigger — malformed JSON 3× → escalation.

Verifies:
- record_schema_valid() accumulates across steps
- 3 consecutive schema_valid=False fire the trigger
- Escalated output replaces the bad JSON
"""

from tests.e2e.conftest import MockModel, make_guard


class TestSchemaInvalidE2E:
    """Full end-to-end flow for schema_invalid trigger."""

    def test_three_schema_failures_escalates(self) -> None:
        """3× schema_valid=False → trigger fires → escalated output."""
        model = MockModel(response='{"fixed": true}')
        guard = make_guard(model=model)

        @guard.protect
        def step() -> str:
            guard.record_schema_valid(valid=False)
            return "{bad json}"

        assert step() == "{bad json}"
        assert step() == "{bad json}"
        # The function returns "{bad json}" (malformed JSON), and
        # record_schema_valid(valid=False) tells the guard the output is
        # schema-invalid.  The guard checks the schema_valid flag, NOT
        # the actual output string — the test deliberately returns a
        # non-JSON string but the trigger fires based on the metadata flag.
        result = step()
        assert result == '{"fixed": true}'
        assert len(model._invoke_args) == 1
        assert guard.state.escalation_count == 1

    def test_schema_valid_does_not_trigger(self) -> None:
        """Valid schema never triggers schema_invalid."""
        model = MockModel()
        guard = make_guard(model=model)

        @guard.protect
        def step() -> str:
            guard.record_schema_valid(valid=True)
            return '{"valid": true}'

        for _ in range(5):
            assert step() == '{"valid": true}'
        assert len(model._invoke_args) == 0

    def test_mixed_schema_no_trigger(self) -> None:
        """Schema alternating valid/invalid doesn't trigger (needs consecutive)."""
        model = MockModel()
        guard = make_guard(model=model)

        @guard.protect
        def step() -> str:
            n = len(guard.state.steps)
            guard.record_schema_valid(valid=(n % 2 == 0))
            return f"step {n}"

        # Alternating valid=True, valid=False across 6 steps — the schema_invalid
        # trigger requires 3 consecutive False values.  Mixed results should NOT
        # fire.  This is the same pattern as the consecutive-failure path: the
        # trigger uses a sliding window and requires all 3 to be False.
        for _ in range(6):
            step()
        assert len(model._invoke_args) == 0
