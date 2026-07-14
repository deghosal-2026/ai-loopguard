"""B6: Sanitization throughput benchmark — Sanitizer.sanitize() on 20×2KB.

Target: <5ms (5,000,000 ns) for context with 20 failed attempts of ~2KB each.
Baseline: sanitize() on context with 1 minimal attempt.
Verifies delimiter wrapping is O(n), not accidentally quadratic.
"""

import pytest

from ai_loopguard.context import EscalationContext, Sanitizer
from tests.perf.benchmark_runner import BenchmarkRunner


@pytest.mark.perf
def test_sanitization_throughput(
    escalation_context_20_2kb: EscalationContext,
    escalation_context_1_attempt: EscalationContext,
    benchmark_env: str,
    git_sha: str,
) -> None:
    """Measure Sanitizer.sanitize() throughput with 20×2KB context."""
    runner = BenchmarkRunner(
        name="sanitization_throughput",
        target_ns=5_000_000,
        iterations=500,  # fast op (<5ms): need enough samples for stable median
    )
    result = runner.run(
        # 20 attempts × ~2KB: realistic worst-case context size for sanitization
        # verifies O(n) behavior — delimiter wrapping concatenation should be linear, not quadratic
        fn=lambda: Sanitizer.sanitize(escalation_context_20_2kb),
        # 1 minimal attempt: measures delimiter wrapping overhead on minimal data
        baseline_fn=lambda: Sanitizer.sanitize(escalation_context_1_attempt),
    )

    print(
        f"Sanitization throughput: {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"(target: {result.target_ns / 1_000_000:.3f}ms, "
        f"regression: {result.regression_pct:+.1f}%)"
    )

    runner.save_to_history(result, benchmark_env, git_sha)

    assert result.target_met, (
        f"Sanitization throughput {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"exceeds target {result.target_ns / 1_000_000:.3f}ms"
    )
    assert (
        result.regression_pct <= BenchmarkRunner.REGRESSION_THRESHOLD_PCT
    ), (
        f"Regression {result.regression_pct:+.1f}% "
        f"exceeds threshold {BenchmarkRunner.REGRESSION_THRESHOLD_PCT}%"
    )
