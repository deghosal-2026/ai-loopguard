"""B2: Context packaging benchmark — ContextPackager.package() on 20-step history.

Target: <100ms (100,000,000 ns) for 20-step history with ~2KB avg output.
Baseline: package() on 1-step history (no compression).
"""

import pytest

from ai_loopguard._internal.state import GuardState, TriggerResult
from ai_loopguard.context import ContextPackager
from tests.perf.benchmark_runner import BenchmarkRunner


@pytest.mark.perf
def test_context_packaging(
    twenty_step_packaging_state: GuardState,
    one_step_state: GuardState,
    benchmark_env: str,
    git_sha: str,
) -> None:
    """Measure ContextPackager.package() time on 20-step history."""
    # compress_context exercises the compression code path (worst case for packaging time);
    # max_context_tokens=4000 forces compression since 20×2KB steps = 40KB >> 4000 tokens
    packager = ContextPackager(max_context_tokens=4000, compress_context=True)
    # pre-constructed so its creation cost is excluded from the measured package() call
    trigger_result = TriggerResult(
        trigger_name="repeated_error",
        detail="3 consecutive errors",
        retry_count=3,
    )

    runner = BenchmarkRunner(
        name="context_packaging",
        target_ns=100_000_000,
        # package() is <100ms per call; 100 samples is enough for a stable median
        # without making the suite too slow
        iterations=100,
    )
    result = runner.run(
        fn=lambda: packager.package(twenty_step_packaging_state, trigger_result),
        baseline_fn=lambda: packager.package(one_step_state, trigger_result),
    )

    print(
        f"Context packaging: {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"(target: {result.target_ns / 1_000_000:.3f}ms, "
        f"regression: {result.regression_pct:+.1f}%)"
    )

    runner.save_to_history(result, benchmark_env, git_sha)

    assert result.target_met, (
        f"Context packaging {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"exceeds target {result.target_ns / 1_000_000:.3f}ms"
    )
    assert (
        result.regression_pct <= BenchmarkRunner.REGRESSION_THRESHOLD_PCT
    ), (
        f"Regression {result.regression_pct:+.1f}% "
        f"exceeds threshold {BenchmarkRunner.REGRESSION_THRESHOLD_PCT}%"
    )
