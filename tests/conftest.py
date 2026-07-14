"""Shared fixtures for loopguard tests.

These fixtures provide default config objects so individual test modules
don't need to construct them repeatedly. Import them via::

    from tests.conftest import mock_guard_config

Each fixture is intentionally lightweight — they return plain Pydantic
models with defaults, no setup/teardown needed.

Registering fixtures here means they are auto-discovered by pytest and
available to any test via function arguments (dependency injection).
"""

from typing import Any

import pytest

from ai_loopguard.config import GuardConfig, TriggerConfig


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register --benchmark-env CLI option (used by perf tests)."""
    parser.addoption(
        "--benchmark-env",
        action="store",
        default="local",
        choices=["local", "ci"],
        help="Benchmark environment: local (macOS) or ci (GitHub Actions)",
    )


@pytest.fixture
def benchmark_env(request: Any) -> str:
    """Return the benchmark environment string (local or ci)."""
    value: object = request.config.getoption("--benchmark-env")
    return str(value)

# ── GuardConfig fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_guard_config() -> GuardConfig:
    """Return a default GuardConfig with all three triggers at max_retries=3.

    Useful for tests that need a valid GuardConfig but don't care about
    specific field values — just that the config object exists and has
    sensible defaults.
    """
    return GuardConfig()
# ^ Factory-default fields: on_escalate="auto", max_escalations_per_run=1,
#   max_history_steps=100, all triggers enabled at max_retries=3


# ── TriggerConfig fixtures ────────────────────────────────────────────


@pytest.fixture
def mock_trigger_config() -> TriggerConfig:
    """Return a TriggerConfig with max_retries=3 and enabled=True (defaults).

    This is the "happy path" fixture — a standard, enabled trigger with
    the factory-default retry threshold.
    """
    return TriggerConfig(max_retries=3)
# ^ Used by tests that need any valid trigger without caring about specifics


@pytest.fixture
def mock_trigger_config_disabled() -> TriggerConfig:
    """Return a disabled TriggerConfig for testing enabled=False behaviour.

    When a trigger is disabled, FailureDetector.check() should skip it
    entirely — it should never fire regardless of state.
    """
    # enabled=False + max_retries=5 ensures retries alone don't fire when disabled
    return TriggerConfig(enabled=False, max_retries=5)


@pytest.fixture
def mock_trigger_config_custom_retries() -> TriggerConfig:
    """Return a TriggerConfig with max_retries=5 for boundary testing.

    Useful for verifying that trigger thresholds are actually configurable
    and not hardcoded to the default value of 3.
    """
    # Non-default max_retries=5 — tests using this fixture should assert
    # that exactly 5 (not 3) consecutive failures are required to fire
    return TriggerConfig(max_retries=5)
