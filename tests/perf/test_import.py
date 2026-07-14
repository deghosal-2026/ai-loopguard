"""B3: Import time benchmark — cold import of ai_loopguard package.

Target: <200ms (200,000,000 ns) for `import ai_loopguard`.
Baseline: subprocess wall-clock for `import sys` (sub-millisecond floor).
Method: subprocess with PYTHONDONTWRITEBYTECODE=1, __pycache__ deleted
before each run for cold import.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.perf.benchmark_runner import BenchmarkResult, BenchmarkRunner

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _cold_subprocess_ns(code: str) -> int:
    """Run a cold subprocess and return wall-clock time in nanoseconds."""
    # subprocess is required because Python caches imports in sys.modules,
    # so a cold import can't be measured in-process
    pycache_dirs = list(REPO_ROOT.rglob("__pycache__"))
    for d in pycache_dirs:
        try:
            # delete .pyc caches so the import compiles from source
            # rather than loading precompiled bytecode
            shutil.rmtree(d)
        except OSError:
            pass

    # prevent the subprocess from writing fresh __pycache__ during the run,
    # which would warm the cache for later iterations
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    start = time.perf_counter()
    subprocess.run(
        # sys.executable is portable; macOS ships only python3, not python
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(REPO_ROOT),
    )
    # wall-clock measured externally since perf_counter_ns
    # can't be run inside the child process
    return int((time.perf_counter() - start) * 1_000_000_000)


@pytest.mark.perf
def test_import_time(benchmark_env: str, git_sha: str) -> None:
    """Measure cold import time of loopguard via subprocess wall-clock."""
    runner = BenchmarkRunner(
        name="import_time",
        target_ns=200_000_000,
        # subprocess spawning is expensive (~15ms each); 10 samples is enough
        # for a stable median without making the suite too slow
        iterations=10,
    )

    times: list[int] = []
    baseline_times: list[int] = []
    for _ in range(runner.iterations):
        times.append(_cold_subprocess_ns("import ai_loopguard"))
        # sys is a built-in module (sub-millisecond), so the baseline
        # isolates pure subprocess-spawn overhead
        baseline_times.append(_cold_subprocess_ns("import sys"))

    median_ns = runner._median(times)
    p99_ns = runner._p99(times)
    baseline_ns = runner._median(baseline_times)
    # subprocess timing variance can make the baseline exceed the target;
    # clamp at 0 to avoid a negative adjusted value
    adjusted = max(median_ns - baseline_ns, 0)

    last_good = runner._load_last_good()
    regression = 0.0
    if last_good is not None:
        regression = ((adjusted - last_good) / last_good) * 100.0

    # BenchmarkResult is built by hand because subprocess timing can't use
    # runner.run() (which calls perf_counter_ns inside the process); we
    # measure wall-clock externally instead
    result = BenchmarkResult(
        name="import_time",
        iterations=runner.iterations,
        median_ns=median_ns,
        p99_ns=p99_ns,
        baseline_ns=baseline_ns,
        adjusted_median_ns=adjusted,
        target_ns=runner.target_ns,
        target_met=adjusted < runner.target_ns,
        regression_pct=round(regression, 1),
    )

    print(
        f"Import time: {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"(target: {result.target_ns / 1_000_000:.3f}ms, "
        f"regression: {result.regression_pct:+.1f}%)"
    )

    runner.save_to_history(result, benchmark_env, git_sha)

    assert result.target_met, (
        f"Import time {result.adjusted_median_ns / 1_000_000:.3f}ms "
        f"exceeds target {result.target_ns / 1_000_000:.3f}ms"
    )
    assert (
        result.regression_pct <= BenchmarkRunner.REGRESSION_THRESHOLD_PCT
    ), (
        f"Regression {result.regression_pct:+.1f}% "
        f"exceeds threshold {BenchmarkRunner.REGRESSION_THRESHOLD_PCT}%"
    )
