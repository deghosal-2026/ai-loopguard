"""B5: Redaction throughput benchmark — Redactor.redact() on 50 secrets.

Target: <10ms (10,000,000 ns) for context with 50 secrets across 20 attempts.
Baseline: redact() on context with 0 secrets (empty patterns, no builtins).
Verifies built-in + user regex patterns don't create a bottleneck.
"""

import pytest

from ai_loopguard.context import EscalationContext, Redactor
from tests.perf.benchmark_runner import BenchmarkRunner


@pytest.mark.perf
def test_redaction_throughput(
    escalation_context_50_secrets: EscalationContext,
    escalation_context_0_secrets: EscalationContext,
    benchmark_env: str,
    git_sha: str,
) -> None:
    """Measure Redactor.redact() throughput with 50 secrets."""
    patterns = ["secret-\\w+"]  # one user pattern: tests user + builtin pattern interaction

    runner = BenchmarkRunner(
        name="redaction_throughput",
        target_ns=10_000_000,
        iterations=500,  # fast op (<10ms): need enough samples for stable median
    )
    result = runner.run(
        fn=lambda: Redactor.redact(
            escalation_context_50_secrets,
            patterns=patterns,
            # exercises built-in AWS/GitHub/OpenAI patterns — most CPU-intensive path
            use_builtin=True,
        ),
        baseline_fn=lambda: Redactor.redact(
            escalation_context_0_secrets,
            patterns=[],  # no regexes: measures pure function call overhead with no matching
            use_builtin=False,  # no builtins: baseline isolates call overhead from regex work
        ),
    )

    print(
        f"Redaction throughput: {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"(target: {result.target_ns / 1_000_000:.3f}ms, "
        f"regression: {result.regression_pct:+.1f}%)"
    )

    runner.save_to_history(result, benchmark_env, git_sha)

    assert result.target_met, (
        f"Redaction throughput {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"exceeds target {result.target_ns / 1_000_000:.3f}ms"
    )
    assert (
        result.regression_pct <= BenchmarkRunner.REGRESSION_THRESHOLD_PCT
    ), (
        f"Regression {result.regression_pct:+.1f}% "
        f"exceeds threshold {BenchmarkRunner.REGRESSION_THRESHOLD_PCT}%"
    )
