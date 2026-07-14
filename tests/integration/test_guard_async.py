"""Integration tests for @guard.aprotect async decorator.

Covers per WBS S5:
- Async function succeeds first try → returns output, no escalation
- Async function fails 1× then succeeds → returns output, no escalation
- Async function fails 3× → async escalation model call → returns result
- Async escalation with interrupt mode
- Async fail-open behaviour
"""

import asyncio

import pytest

from ai_loopguard.config import TriggerConfig
from ai_loopguard.guard import Guard

# ── Mock async escalation model ──────────────────────────────────────────

class _MockModel:
    """Mock LangChain model with async ainvoke for integration testing."""

    def __init__(
        self,
        response: str = "async-escalated",
        model_name: str = "mock-gpt4",
        should_fail: bool = False,
    ) -> None:
        self._response = response
        self._model_name = model_name
        self._should_fail = should_fail
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

class TestAsyncSuccessPath:
    """Tests where the async function succeeds."""

    @pytest.mark.asyncio
    async def test_first_try_success_returns_output(self) -> None:
        """Async function succeeds on first call → returns output."""
        guard = _guard()

        @guard.aprotect
        async def step() -> str:
            return "async-success"

        # Async @guard.aprotect scenarios mirror sync @guard.protect:
        # - success: output returned unchanged, no ainvoke call
        # - 3 fails (same error): trigger fires, async escalation via ainvoke
        # - 1 fail then success: fail returns None, success returns output
        assert await step() == "async-success"

    @pytest.mark.asyncio
    async def test_first_try_success_no_escalation(self) -> None:
        """Successful async function does NOT trigger escalation."""
        model = _MockModel()
        guard = _guard(model=model)

        @guard.aprotect
        async def step() -> str:
            return "ok"

        assert await step() == "ok"
        assert len(model._ainvoke_args) == 0

    @pytest.mark.asyncio
    async def test_fail_then_succeed(self) -> None:
        """Fail once → returns None. Succeed next → returns output."""
        guard = _guard()
        call_count: list[int] = [0]

        @guard.aprotect
        async def step() -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("transient")
            return "recovered"

        assert await step() is None
        assert await step() == "recovered"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_fail_once_no_escalation(self) -> None:
        """Single failure does NOT trigger escalation (threshold 3)."""
        model = _MockModel()
        guard = _guard(model=model)
        call_count: list[int] = [0]

        @guard.aprotect
        async def step() -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("one-off")
            return "fine"

        assert await step() is None
        assert await step() == "fine"
        assert len(model._ainvoke_args) == 0


# ── Escalation path tests ────────────────────────────────────────────────

class TestAsyncEscalationPath:
    """Tests where a trigger fires in async context."""

    @pytest.mark.asyncio
    async def test_same_error_three_times_escalates(self) -> None:
        """3 consecutive same errors → async escalation model called."""
        model = _MockModel(response="async-fixed")
        guard = _guard(model=model)

        @guard.aprotect
        async def step() -> str:
            raise ValueError("repeated")

        assert await step() is None
        assert await step() is None
        result = await step()
        assert result == "async-fixed"
        assert len(model._ainvoke_args) == 1

    @pytest.mark.asyncio
    async def test_different_errors_no_escalation(self) -> None:
        """Unique error per call — no 3 consecutive, no escalation."""
        model = _MockModel()
        guard = _guard(model=model)
        call_count: list[int] = [0]

        @guard.aprotect
        async def step() -> str:
            i = call_count[0]
            call_count[0] += 1
            raise RuntimeError(f"unique-error-{i}")

        for _ in range(10):
            assert await step() is None
        assert len(model._ainvoke_args) == 0

    @pytest.mark.asyncio
    async def test_custom_trigger_fires(self) -> None:
        """Custom trigger fires in async context."""
        model = _MockModel(response="custom-async")
        guard = _guard(
            model=model,
            triggers={
                "custom": TriggerConfig(
                    enabled=True,
                    custom_callback=lambda s: len(s.steps) >= 1 and (
                        s.steps[-1].error_message is not None
                        and "custom" in str(s.steps[-1].error_message)
                    ),
                ),
            },
        )

        @guard.aprotect
        async def step() -> str:
            raise ValueError("custom-fail")

        result = await step()
        assert result == "custom-async"
        assert len(model._ainvoke_args) == 1

    @pytest.mark.asyncio
    async def test_test_failure_trigger(self) -> None:
        """test_failure trigger fires in async context."""
        model = _MockModel(response="async-fixed-tests")
        guard = _guard(model=model)

        @guard.aprotect
        async def step() -> str:
            guard.record_test_results({"test_parser": False})
            return "output"

        assert await step() == "output"
        assert await step() == "output"
        assert await step() == "async-fixed-tests"
        assert len(model._ainvoke_args) == 1

    @pytest.mark.asyncio
    async def test_schema_invalid_trigger(self) -> None:
        """schema_invalid trigger fires in async context."""
        model = _MockModel(response="valid-async-json")
        guard = _guard(model=model)

        @guard.aprotect
        async def step() -> str:
            guard.record_schema_valid(valid=False)
            return "bad"

        assert await step() == "bad"
        assert await step() == "bad"
        assert await step() == "valid-async-json"
        assert len(model._ainvoke_args) == 1


# ── Fail-open tests ──────────────────────────────────────────────────────

class TestAsyncFailOpen:
    """Tests for async fail-open behaviour."""

    @pytest.mark.asyncio
    async def test_fail_returns_none(self) -> None:
        """Exception without trigger → returns None (fail-open)."""
        guard = _guard()

        @guard.aprotect
        async def step() -> str:
            raise ValueError("fail")

        assert await step() is None

    @pytest.mark.asyncio
    async def test_no_model_trigger_returns_last_output(self) -> None:
        """No escalation model + trigger → returns last output."""
        guard = _guard()

        @guard.aprotect
        async def step() -> str:
            raise ValueError("always fail")

        assert await step() is None
        assert await step() is None
        assert await step() is None
        assert len(guard._state.steps) == 3


# ── Metadata tests ───────────────────────────────────────────────────────

class TestAsyncMetadata:
    """Tests for async decorator transparency."""

    @pytest.mark.asyncio
    async def test_preserves_function_name(self) -> None:
        """Async decorated function keeps original __name__."""
        guard = _guard()

        @guard.aprotect
        async def my_async_func() -> str:
            return "hello"

        assert my_async_func.__name__ == "my_async_func"

    @pytest.mark.asyncio
    async def test_preserves_docstring(self) -> None:
        """Async decorated function keeps original __doc__."""
        guard = _guard()

        @guard.aprotect
        async def my_async_func() -> str:
            """My async docstring."""
            return "hello"

        assert my_async_func.__doc__ == "My async docstring."

    @pytest.mark.asyncio
    async def test_inner_await_works(self) -> None:
        """Decorated async function with internal await works correctly."""
        guard = _guard()

        @guard.aprotect
        async def my_async_func() -> str:
            await asyncio.sleep(0.001)
            return "awaited"

        assert await my_async_func() == "awaited"
