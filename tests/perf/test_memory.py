"""B7: Memory footprint benchmark — bounded memory after 1000 guarded steps.

Target: <50MB delta after 1000 add_step() calls with max_history_steps=100.
Baseline: tracemalloc current allocation before any steps are added.
Verifies T3 mitigation — max_history_steps bounds memory usage.
"""

import tracemalloc  # tracks Python-level allocations; ru_maxrss is process peak RSS (no delta)

import pytest

from ai_loopguard._internal.state import GuardState, StepRecord
from tests.perf.benchmark_runner import BenchmarkResult, BenchmarkRunner


def _make_step(i: int) -> StepRecord:
    """Build a ~2KB StepRecord for memory footprint testing."""
    return StepRecord(
        step_num=i + 1,
        output="x" * 2000,  # ~2KB gives retained steps a meaningful memory footprint
        error=ValueError(f"error-{i}") if i % 3 == 0 else None,
        error_type="ValueError" if i % 3 == 0 else None,
        error_message=f"error-{i}" if i % 3 == 0 else None,
        test_results={"test_a": True, "test_b": False, "test_c": True},
        schema_valid=bool(i % 5),
        tokens_used=50,
        cost_usd=0.001,
        timestamp=1000.0 + i,
    )


@pytest.mark.perf
def test_memory_footprint(benchmark_env: str, git_sha: str) -> None:
    """Measure tracemalloc allocation delta after 1000 guarded steps with max_history_steps=100."""
    tracemalloc.start()  # must enable tracing before taking the baseline snapshot

    snapshot_before = tracemalloc.take_snapshot()
    # statistics("filename") groups allocations by source file for stable per-file totals
    baseline_bytes = sum(stat.size for stat in snapshot_before.statistics("filename"))

    state = GuardState(max_history_steps=100)  # bound: only 100 steps retained, not all 1000
    for i in range(1000):
        state.add_step(_make_step(i))

    snapshot_after = tracemalloc.take_snapshot()
    after_bytes = sum(stat.size for stat in snapshot_after.statistics("filename"))
    delta = max(after_bytes - baseline_bytes, 0)

    tracemalloc.stop()  # clean up tracing state

    runner = BenchmarkRunner(
        name="memory_footprint",
        target_ns=50_000_000,  # 50MB = 50,000,000 bytes (field says ns but holds bytes for memory)
        iterations=1,  # runner iterations unused; BenchmarkResult is constructed manually
    )
    last_good = runner._load_last_good()
    regression = 0.0
    if last_good is not None:
        regression = ((delta - last_good) / last_good) * 100.0

    result = BenchmarkResult(
        name="memory_footprint",
        iterations=1000,  # 1000 reflects the actual number of add_step() calls
        median_ns=delta,  # single measurement, not a distribution: median == p99
        p99_ns=delta,  # identical to median (no distribution)
        baseline_ns=baseline_bytes,
        adjusted_median_ns=delta,
        target_ns=50_000_000,
        target_met=delta < 50_000_000,
        regression_pct=round(regression, 1),
    )

    print(
        f"Memory footprint: {delta / 1_000_000:.1f}MB delta "
        f"(target: {result.target_ns / 1_000_000:.1f}MB, "
        f"regression: {result.regression_pct:+.1f}%)"
    )

    runner.save_to_history(result, benchmark_env, git_sha)

    assert result.target_met, (
        f"Memory delta {delta / 1_000_000:.1f}MB "
        f"exceeds target {result.target_ns / 1_000_000:.1f}MB"
    )
    assert (
        result.regression_pct <= BenchmarkRunner.REGRESSION_THRESHOLD_PCT
    ), (
        f"Regression {result.regression_pct:+.1f}% "
        f"exceeds threshold {BenchmarkRunner.REGRESSION_THRESHOLD_PCT}%"
    )
