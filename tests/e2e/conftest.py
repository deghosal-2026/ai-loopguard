"""Shared fixtures for E2E tests.

Provides mock models, guard helpers, and tmp_path log dirs so
individual test files don't repeat boilerplate.
"""

from pathlib import Path

import pytest

from ai_loopguard.guard import Guard


class MockResponse:
    """Mock AIMessage with .content attribute.

    Only mocks .content — the escalation pipeline accesses nothing else
    from the LangChain AIMessage, so additional_kwargs, response_metadata,
    etc. are not needed.
    """

    def __init__(self, content: str) -> None:
        """Store the content payload for .content attribute access."""
        # The escalation pipeline reads response.content — no other fields
        # (tokens, finish_reason, etc.) are accessed.
        self.content = content


class MockModel:
    """Mock escalation model for E2E testing.

    Tracks sync (invoke) and async (ainvoke) calls.
    Can be configured to succeed or raise.
    """

    def __init__(
        self,
        response: str = "escalated-output",
        model_name: str = "mock-gpt4",
        should_fail: bool = False,
    ) -> None:
        """Configure the mock with a fixed response, model name, and failure flag."""
        # Configurable response lets each test set a distinct expected output,
        # while should_fail=True lets tests simulate model-crash scenarios.
        self._response = response
        self._model_name = model_name
        self._should_fail = should_fail
        # Capture every prompt sent to the model.  Tests inspect these
        # to verify the escalation prompt contains expected context
        # (trigger type, error messages, redacted content).  Separate
        # lists for sync/async so tests can verify each path independently.
        self._invoke_args: list[str] = []
        self._ainvoke_args: list[str] = []

    @property
    def model_name(self) -> str:
        """Return the mock model name string."""
        return self._model_name

    def invoke(self, prompt: str) -> MockResponse:
        """Record the prompt string and return the configured response."""
        self._invoke_args.append(prompt)
        if self._should_fail:
            msg = "model unavailable"
            raise RuntimeError(msg)
        return MockResponse(self._response)

    async def ainvoke(self, prompt: str) -> MockResponse:
        """Async variant of invoke — record prompt, return response."""
        self._ainvoke_args.append(prompt)
        if self._should_fail:
            msg = "model unavailable (async)"
            raise RuntimeError(msg)
        return MockResponse(self._response)


def make_guard(
    model: MockModel | None = None,
    **kwargs: object,
) -> Guard:
    """Create a Guard with the given mock model and config overrides.

    Uses **kwargs to let tests override any GuardConfig field
    (max_escalations_per_run, on_guard_error, redact_patterns, etc.)
    without manually building the full config dict each time.
    """
    cfg: dict[str, object] = {}
    if model is not None:
        cfg["escalation_model"] = model
    # **kwargs handles on_escalate="interrupt", redact_patterns=[...],
    # max_escalations_per_run=2, etc. — any GuardConfig field.
    cfg.update(kwargs)
    return Guard(**cfg)  # type: ignore[arg-type]


@pytest.fixture
def mock_model() -> MockModel:
    """Return a basic MockModel that always succeeds."""
    return MockModel(response="escalated-output")


@pytest.fixture
def failing_model() -> MockModel:
    """Return a MockModel that raises on invoke."""
    return MockModel(should_fail=True)


@pytest.fixture
def guard(mock_model: MockModel) -> Guard:
    """Return a Guard with a working escalation model.

    Each test gets a fresh Guard with a fresh MockModel — critical for
    test isolation: the mock's _invoke_args must be empty and the Guard's
    state must be fresh at test start.
    """
    return make_guard(model=mock_model)


@pytest.fixture
def log_dir(tmp_path: Path) -> str:
    """Return a tmp_path string for file-based logging."""
    d = tmp_path / "logs"
    d.mkdir()
    return str(d)


# Why tests/e2e/conftest.py exists separately from tests/conftest.py:
# E2E tests use MockModel/MockResponse exclusively (no real LLM calls).
# tests/conftest.py (if it existed) would provide fixtures for unit tests
# (mock patches, real SDK stubs).  Keeping them separate avoids importing
# optional dependencies (langgraph, crewai) needed by unit-test fixtures
# and keeps e2e test bootstrapping self-contained.
