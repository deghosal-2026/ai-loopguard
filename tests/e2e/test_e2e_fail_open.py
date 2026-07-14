"""E2E: fail-open — loopguard internal errors don't crash the agent loop.

Verifies:
- on_guard_error="raise_original" re-raises the last original error
- on_guard_error="return_last_output" returns the last success
- on_guard_error="return_sentinel" returns the configured sentinel
- Agent loop survives all fail-open modes
"""

import pytest

from tests.e2e.conftest import MockModel, make_guard


class TestFailOpenE2E:
    """Full end-to-end flow for fail-open behaviour."""

    def test_fail_open_raise_original(self) -> None:
        """on_guard_error="raise_original" re-raises the ValueError.
        
        The 3 fail-open modes:
        1. raise_original — when the escalation model fails, re-raise the
           original error that triggered the escalation.
        2. return_last_output — return the last successful output (or None
           if all steps failed).
        3. return_sentinel — return a user-configured sentinel value.
        """
        model = MockModel(should_fail=True)
        guard = make_guard(
            model=model,
            on_guard_error="raise_original",
        )

        @guard.protect
        def step() -> str:
            raise ValueError("original failure")

        step()
        step()
        # 3rd call: trigger fires (repeated_error), escalation model fails
        # (MockModel.should_fail=True), fail-open kicks in.
        # raise_original re-raises the ValueError, not the RuntimeError
        # from the model failure.
        with pytest.raises(ValueError, match="original failure"):
            step()

    def test_fail_open_return_last_output(self) -> None:
        """on_guard_error="return_last_output" returns last good output."""
        model = MockModel(should_fail=True)
        guard = make_guard(
            model=model,
            on_guard_error="return_last_output",
        )

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        step()
        step()
        # trigger fires, escalation fails → returns last output.
        # Since all steps failed, last output is None.
        result = step()
        assert result is None  # last output was None (failed steps)

    def test_fail_open_return_sentinel(self) -> None:
        """on_guard_error="return_sentinel" returns sentinel value."""
        model = MockModel(should_fail=True)
        sentinel = {"error": "loopguard failed"}
        guard = make_guard(
            model=model,
            on_guard_error="return_sentinel",
            sentinel_value=sentinel,  # type: ignore[arg-type]
        )

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        step()
        step()
        # The sentinel can be any type (dict, str, None, etc.).  The test uses
        # a dict to verify that non-string sentinels work — important for
        # agents that expect structured output (e.g., LangGraph state dict).
        result = step()
        assert result == sentinel

    def test_fail_open_no_model_no_crash(self) -> None:
        """Guard with no escalation model never crashes."""
        guard = make_guard(model=None)

        @guard.protect
        def step() -> str:
            raise ValueError("fail")

        # With no escalation model, the guard cannot escalate — but it must
        # NOT crash.  Every step returns None (fail-open by default).
        # This is the most basic fail-open invariant: the agent loop survives
        # even when loopguard has no way to escalate.
        for _ in range(10):
            result = step()
            assert result is None

    def test_fail_open_async(self) -> None:
        """Async function with fail-open doesn't crash."""
        model = MockModel(should_fail=True)
        guard = make_guard(
            model=model,
            on_guard_error="return_last_output",
        )

        @guard.aprotect
        async def step() -> str:
            raise ValueError("async fail")

        async def run() -> None:
            await step()
            await step()
            r = await step()
            assert r is None

        import asyncio
        # The async fail-open path goes through aprotect -> async escalation
        # -> ainvoke failure -> fail-open.  Must not deadlock or raise.
        asyncio.run(run())
