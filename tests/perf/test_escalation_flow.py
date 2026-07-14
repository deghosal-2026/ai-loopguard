"""B4: Escalation full flow benchmark — trigger to return end-to-end.

Target: <50ms (50,000,000 ns) for full escalation pipeline.
Baseline: MockModel.invoke() directly (isolates model call overhead).
Measures: trigger → package → sanitize → redact → model invoke → log → return.
"""

import pytest

from ai_loopguard._internal.state import GuardState, TriggerResult
from ai_loopguard.config import GuardConfig
from ai_loopguard.escalation import EscalationManager
from tests.perf.benchmark_runner import BenchmarkRunner
from tests.perf.conftest import _MockModel  # shared mock: instant return, no API calls


@pytest.mark.perf
def test_escalation_full_flow(
    pre_populated_guard_state_3_fails: GuardState,
    benchmark_env: str,
    git_sha: str,
) -> None:
    """Measure end-to-end escalation flow overhead."""
    model = _MockModel()
    config = GuardConfig(
        escalation_model=model,
        sanitize_context=True,  # exercises the Sanitizer code path in the full pipeline
        redact_patterns=["sk-\\d+"],  # exercises the Redactor code path with one user pattern
    )
    manager = EscalationManager(
        config=config,
        state=pre_populated_guard_state_3_fails,
    )
    trigger_result = TriggerResult(
        trigger_name="repeated_error",
        detail="3 consecutive errors",
        retry_count=3,
    )

    runner = BenchmarkRunner(
        name="escalation_full_flow",
        target_ns=50_000_000,
        iterations=500,  # medium op (<50ms): 500 balances stability and runtime
    )
    result = runner.run(
        fn=lambda: manager.escalate(trigger_result),
        # isolates guard overhead from raw model call time
        baseline_fn=lambda: model.invoke("test"),
    )

    print(
        f"Escalation full flow: {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"(target: {result.target_ns / 1_000_000:.3f}ms, "
        f"regression: {result.regression_pct:+.1f}%)"
    )

    runner.save_to_history(result, benchmark_env, git_sha)

    assert result.target_met, (
        f"Escalation full flow {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"exceeds target {result.target_ns / 1_000_000:.3f}ms"
    )
    assert (
        result.regression_pct <= BenchmarkRunner.REGRESSION_THRESHOLD_PCT
    ), (
        f"Regression {result.regression_pct:+.1f}% "
        f"exceeds threshold {BenchmarkRunner.REGRESSION_THRESHOLD_PCT}%"
    )
