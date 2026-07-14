"""Shared fixtures for performance benchmark tests.

Provides pre-populated GuardState instances, EscalationContext objects
with secrets/large payloads, and a mock model so benchmark test files
don't repeat setup boilerplate.
"""

from __future__ import annotations

import platform
from typing import Any

import pytest

from ai_loopguard._internal.state import GuardState, StepRecord
from ai_loopguard.context import EscalationContext


class _MockResponse:
    """Mock LLM response with .content attribute."""

    def __init__(self, content: str = "safe-output") -> None:
        self.content = content


# Duplicated from tests/e2e/conftest.py on purpose: perf tests must not depend on e2e infra.
class _MockModel:
    """Mock escalation model for benchmark tests — instant return, no API."""

    def __init__(self, response: str = "safe-output") -> None:
        self._response = response
        self._model_name_val = "mock-perf-model"

    @property  # EscalationManager expects a .model_name attribute; this satisfies that interface
    def model_name(self) -> str:
        return self._model_name_val

    def invoke(self, prompt: str) -> _MockResponse:
        return _MockResponse(self._response)

    async def ainvoke(self, prompt: str) -> _MockResponse:
        return _MockResponse(self._response)


@pytest.fixture
def git_sha() -> str:
    """Return the current git short SHA, or 'unknown' if not in a repo."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        sha: str | None = result.stdout.strip()
        return sha if sha else "unknown"
    except Exception:
        return "unknown"


@pytest.fixture
def mock_model() -> _MockModel:
    """Return a MockModel instance for escalation benchmarks."""
    return _MockModel()


def _build_step(
    step_num: int,
    error: Exception | None = None,
    test_results: dict[str, bool] | None = None,
    schema_valid: bool | None = None,
    output_size: int = 100,
) -> StepRecord:
    """Build a single StepRecord with sensible defaults for benchmarks."""
    return StepRecord(
        step_num=step_num,
        output="x" * output_size,
        error=error,
        error_type=type(error).__qualname__ if error else None,
        error_message=str(error) if error else None,
        test_results=test_results,
        schema_valid=schema_valid,
        tokens_used=50,
        cost_usd=0.001,
        timestamp=1000.0 + step_num,
    )


@pytest.fixture
def empty_state() -> GuardState:
    """Return an empty GuardState (0 steps) for baseline measurements."""
    return GuardState(max_history_steps=100)


@pytest.fixture
def one_step_state() -> GuardState:
    """Return a GuardState with 1 step for baseline measurements."""
    state = GuardState(max_history_steps=100)
    state.add_step(_build_step(1))
    return state


@pytest.fixture
def one_hundred_step_state() -> GuardState:
    """Return a GuardState with 100 mixed steps for detection benchmarks."""
    state = GuardState(max_history_steps=100)
    # Mix error/test_results/schema_valid across steps so all 3 trigger code paths are exercised.
    for i in range(100):
        state.add_step(
            _build_step(
                step_num=i + 1,
                error=ValueError(f"error-{i}") if i % 3 == 0 else None,
                test_results={"test_parser": i % 2 == 0} if i % 2 == 0 else None,
                schema_valid=bool(i % 5),
            )
        )
    return state


@pytest.fixture
def twenty_step_packaging_state() -> GuardState:
    """Return a GuardState with 20 steps of ~2KB output for packaging benchmarks."""
    state = GuardState(max_history_steps=100)
    for i in range(20):
        state.add_step(
            _build_step(
                step_num=i + 1,
                output_size=2000,
                # errors only on steps 17-19 (i >= 17): triggers compression on the last 3 steps
                error=ValueError(f"fail-{i}") if i >= 17 else None,
                test_results={"test_a": True, "test_b": False, "test_c": True},
                schema_valid=True,
            )
        )
    return state


@pytest.fixture
def pre_populated_guard_state_3_fails() -> GuardState:
    """Return a GuardState with 3 failing steps for escalation flow benchmarks."""
    state = GuardState(max_history_steps=100)
    for i in range(3):
        state.add_step(
            _build_step(
                step_num=i + 1,
                error=ValueError("connection error"),
                schema_valid=False,
            )
        )
    return state


def _build_failed_attempt(secrets: list[str]) -> dict[str, Any]:
    """Build a failed_attempt dict with embedded secrets for redaction benchmarks."""
    d: dict[str, Any] = {
        "output": "normal output " * 50,
        "error_message": "something went wrong",
        "_summary": "Step failed after 3 retries",
    }
    for s in secrets:
        d["output"] += f" {s}"
    return d


# Helper avoids repeating the same trigger dict literal across every EscalationContext fixture.
def _trigger_dict(
    name: str = "repeated_error",
    detail: str = "3 consecutive errors",
    retries: int = 3,
) -> dict[str, str | int]:
    """Build a trigger dict for EscalationContext."""
    return {"trigger_name": name, "detail": detail, "retry_count": retries}


@pytest.fixture
def escalation_context_50_secrets() -> EscalationContext:
    """Return an EscalationContext with ~50 secrets across 20 failed attempts."""
    secrets_pool = [
        "sk-proj-A" + "x" * 48,
        "AKIA" + "y" * 16,
        "ghp_" + "z" * 36,
        "secret-" + "w" * 20,
    ]
    attempts = []
    for idx in range(20):
        num = (idx % 4) + 1  # cycle 1-4 secrets per attempt: varies regex match count
        attempts.append(_build_failed_attempt(secrets_pool[:num]))
    return EscalationContext(
        trigger=_trigger_dict(),
        task_description="Process user request",
        failed_attempts=attempts,
        last_error="connection error",
    )


@pytest.fixture
def escalation_context_0_secrets() -> EscalationContext:
    """Return an EscalationContext with no secrets for baseline measurement."""
    return EscalationContext(
        trigger=_trigger_dict(),
        task_description="Process user request",
        failed_attempts=[
            {"output": "no secrets here", "error_message": "fail", "_summary": "nope"}
        ],
        last_error="fail",
    )


@pytest.fixture
def escalation_context_20_2kb() -> EscalationContext:
    """Return an EscalationContext with 20 failed attempts of ~2KB each."""
    big_output = "x" * 2000
    big_error = "y" * 2000
    big_summary = "z" * 500
    attempts = []
    for _ in range(20):
        attempts.append(
            {
                "output": big_output,
                "error_message": big_error,
                "_summary": big_summary,
            }
        )
    return EscalationContext(
        trigger=_trigger_dict("test_failure", "test_parser failed 3 times"),
        task_description="Process user request",
        failed_attempts=attempts,
        last_error="test_parser failed",
    )


@pytest.fixture
def escalation_context_1_attempt() -> EscalationContext:
    """Return an EscalationContext with 1 minimal attempt for baseline."""
    return EscalationContext(
        trigger=_trigger_dict("test_failure", "test_parser failed 3 times"),
        task_description="Process user request",
        failed_attempts=[
            {"output": "small", "error_message": "fail", "_summary": "short"}
        ],
        last_error="fail",
    )


@pytest.fixture
def environment_info() -> dict[str, str]:
    """Return platform/environment info for the findings document."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
    }
