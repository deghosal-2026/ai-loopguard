"""BenchmarkRunner utility for consistent performance measurement.

Provides nanosecond-precision timing, baseline subtraction, median/p99
calculation, and regression detection (>25% vs last known good).
Results are persisted to benchmarks/baseline.json and benchmarks/history.jsonl.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
BASELINE_PATH = REPO_ROOT / "benchmarks" / "baseline.json"
HISTORY_PATH = REPO_ROOT / "benchmarks" / "history.jsonl"


@dataclass
class BenchmarkResult:
    """Outcome of a single benchmark run with all timing metrics."""

    name: str
    iterations: int
    median_ns: int
    p99_ns: int
    baseline_ns: int
    adjusted_median_ns: int
    target_ns: int
    target_met: bool
    regression_pct: float


@dataclass
class BenchmarkRunner:
    """Runs a callable N times, measures with nanosecond precision.

    Subtracts a baseline, reports median + p99, and flags regressions >25%.
    """

    name: str
    target_ns: int
    iterations: int = 1000
    warmup: int = 10

    REGRESSION_THRESHOLD_PCT: float = 25.0  # catches real regressions, tolerates runner variance

    def run(self, fn: Callable[[], Any], baseline_fn: Callable[[], Any]) -> BenchmarkResult:
        """Time fn and baseline_fn, return a BenchmarkResult with regression info."""
        self._warmup(baseline_fn)
        baseline_ns = self._median(self._time_n(baseline_fn))

        self._warmup(fn)
        times = self._time_n(fn)
        median_ns = self._median(times)  # primary metric: robust to GC/scheduling outliers
        p99_ns = self._p99(times)  # recorded for visibility; not gating (informational only)
        # Subtract baseline to isolate the operation from fixed overhead (loop, timer, dispatch).
        # Clamp >=0: baseline can exceed the measured median in noisy environments.
        adjusted = max(median_ns - baseline_ns, 0)

        last_good = self._load_last_good()
        regression = 0.0
        if last_good is not None:
            regression = ((adjusted - last_good) / last_good) * 100.0

        return BenchmarkResult(
            name=self.name,
            iterations=self.iterations,
            median_ns=median_ns,
            p99_ns=p99_ns,
            baseline_ns=baseline_ns,
            adjusted_median_ns=adjusted,
            target_ns=self.target_ns,
            target_met=adjusted < self.target_ns,
            regression_pct=round(regression, 1),
        )

    def _warmup(self, fn: Callable[[], Any]) -> None:
        for _ in range(self.warmup):  # not recorded: discard first-call cache/JIT effects
            fn()

    def _time_n(self, fn: Callable[[], Any]) -> list[int]:
        times: list[int] = []
        for _ in range(self.iterations):
            start = time.perf_counter_ns()  # ns precision + monotonic; time.time() is wall-clock
            fn()
            times.append(time.perf_counter_ns() - start)
        return times

    @staticmethod
    def _median(times: list[int]) -> int:
        s = sorted(times)
        return s[len(s) // 2]

    @staticmethod
    def _p99(times: list[int]) -> int:
        s = sorted(times)
        idx = min(int(len(s) * 0.99), len(s) - 1)
        return s[idx]

    def _load_last_good(self) -> int | None:
        """Load the last known good adjusted_median_ns from baseline.json."""
        if not BASELINE_PATH.exists():
            return None
        data: dict[str, Any] = json.loads(BASELINE_PATH.read_text())
        entry = data.get(self.name)
        if entry is None:
            return None
        value: int = entry["adjusted_median_ns"]
        return value

    def save_to_history(
        self, result: BenchmarkResult, environment: str, git_sha: str
    ) -> None:
        """Append result to history.jsonl and update baseline.json."""
        record = asdict(result)
        record["environment"] = environment
        record["git_sha"] = git_sha
        record["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_PATH.open("a") as f:  # append-only: concurrent-safe, no read-modify-write
            f.write(json.dumps(record) + "\n")

        # Read-then-write: last successful run wins; baseline updates after each pass.
        data: dict[str, Any] = {}
        if BASELINE_PATH.exists():
            data = json.loads(BASELINE_PATH.read_text())
        data[self.name] = {
            "adjusted_median_ns": result.adjusted_median_ns,
            "target_ns": result.target_ns,
            "environment": environment,
            "git_sha": git_sha,
            "recorded_at": record["timestamp"],
        }
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(data, indent=2) + "\n")
