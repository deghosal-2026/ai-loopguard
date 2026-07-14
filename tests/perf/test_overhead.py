"""B1: Detection overhead benchmark — FailureDetector.check() on 100-step history.

Target: <1ms (1,000,000 ns) for 100-step GuardState with 3 enabled triggers.
Baseline: check() on empty GuardState (isolates method-call overhead).
"""

import pytest

from ai_loopguard._internal.state import GuardState
from ai_loopguard.detectors import FailureDetector
from tests.perf.benchmark_runner import BenchmarkRunner


@pytest.mark.perf
def test_detection_overhead(
    one_hundred_step_state: GuardState,
    empty_state: GuardState,
    benchmark_env: str,
    git_sha: str,
) -> None:
    """Measure FailureDetector.check() overhead on 100-step history."""
    # from_defaults() ensures all 3 triggers are enabled with standard thresholds;
    # avoids drift if defaults change and keeps the benchmark representative.
    detector = FailureDetector.from_defaults()

    runner = BenchmarkRunner(
        name="detection_overhead",
        target_ns=1_000_000,
        iterations=1000,  # check() is <1ms; 1000 samples give a stable median and reduce jitter
    )
    result = runner.run(
        fn=lambda: detector.check(one_hundred_step_state),
        # empty state short-circuits trigger logic, so the baseline isolates detector
        # traversal overhead from the fixed method-call cost
        baseline_fn=lambda: detector.check(empty_state),
    )

    print(
        f"Detection overhead: {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"(target: {result.target_ns / 1_000_000:.3f}ms, "
        f"regression: {result.regression_pct:+.1f}%)"
    )

    runner.save_to_history(result, benchmark_env, git_sha)

    # fail-fast policy: assert absolute target first, then check for regression vs. last good run
    assert result.target_met, (
        f"Detection overhead {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"exceeds target {result.target_ns / 1_000_000:.3f}ms"
    )
    assert (
        result.regression_pct <= BenchmarkRunner.REGRESSION_THRESHOLD_PCT
    ), (
        f"Regression {result.regression_pct:+.1f}% "
        f"exceeds threshold {BenchmarkRunner.REGRESSION_THRESHOLD_PCT}%"
    )
