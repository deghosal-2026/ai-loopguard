# Performance Test Plan — S12

> **Status:** Draft — 2026-07-11
> **SPEC ref:** §11 (Performance NFRs), §12.5 (BenchmarkRunner)
> **PRD ref:** §9.2 (Non-functional requirements)
> **WBS ref:** S12 (Performance Tests)

## 1. Goals

1. **Verify** that loopguard's overhead is negligible relative to model latency.
2. **Detect regressions** — if a code change makes detection 25%+ slower, CI fails.
3. **Record findings** — persist results to `docs/performance-benchmarks.md` and `benchmarks/history.jsonl` for trend analysis.
4. **Demonstrate** — produce a reproducible benchmark suite that runs locally and in CI.

## 2. Environments

Benchmarks run in two environments. Results are recorded separately because hardware variance makes cross-environment comparison meaningless.

| Environment | Hardware | Python | How to run |
|---|---|---|---|
| **Local** | macOS (record CPU, RAM, Python version in findings) | 3.14 | `pytest -m perf --benchmark-env=local` |
| **CI** | ubuntu-latest GitHub Actions runner | 3.10, 3.11, 3.12 | `pytest -m perf` in CI workflow |

Each run records:
- OS / kernel version
- CPU model and core count
- RAM total
- Python version
- Date and git SHA

## 3. Benchmarks

Seven benchmarks total — 3 SPEC-mandated + 4 additional.

### 3.1 SPEC-mandated benchmarks

#### B1: Detection overhead

| | |
|---|---|
| **ID** | `detection_overhead` |
| **What** | `FailureDetector.check()` on a 100-step `GuardState` with all 3 triggers enabled |
| **Target** | <1ms (1,000,000 ns) — gating |
| **SPEC aspirational** | <0.5ms (SPEC §11.1) |
| **Iterations** | 1,000 |
| **Baseline** | `check()` on empty `GuardState()` (0 steps) — isolates method-call overhead |
| **Setup** | 100 `StepRecord`s with mixed: errors (ValueError), test_results (3 tests pass/fail), schema_valid (alternating True/False) |
| **Assert** | `result.target_met` — pass if under target. Fail if >25% regression vs. baseline. |

#### B2: Context packaging

| | |
|---|---|
| **ID** | `context_packaging` |
| **What** | `ContextPackager.package()` on 20-step history with compression enabled |
| **Target** | <100ms (100,000,000 ns) — gating |
| **SPEC aspirational** | <50ms (SPEC §11.2) |
| **Iterations** | 100 |
| **Baseline** | `package()` on 1-step history (no compression) |
| **Setup** | 20 `StepRecord`s, each with ~2KB output/error_message, compression=True, max_context_tokens=4000 |
| **Assert** | `result.target_met` — pass if under target. Fail if >25% regression vs. baseline. |

#### B3: Import time

| | |
|---|---|
| **ID** | `import_time` |
| **What** | Cold `import ai_loopguard` time (core only, no extras) |
| **Target** | <200ms (200,000,000 ns) |
| **Iterations** | 10 runs, median only |
| **Baseline** | `import sys` (sub-millisecond floor) |
| **Method** | Subprocess: `python -X importtime -c "import ai_loopguard" 2>&1` — parse self-time for the `ai_loopguard` package. Delete `__pycache__` before each run for cold import. |
| **Assert** | `result.target_met`. Fail if >25% regression vs. baseline. |

### 3.2 Additional benchmarks

#### B4: Escalation full flow

| | |
|---|---|
| **ID** | `escalation_full_flow` |
| **What** | End-to-end: trigger fires → package → sanitize → redact → mock model `invoke()` → extract content → log event → return |
| **Target** | <50ms (50,000,000 ns) |
| **Iterations** | 500 |
| **Baseline** | Direct `mock_model.invoke("test")` call (isolates model call from guard overhead) |
| **Setup** | Pre-populated `GuardState` with 3 failing steps. `EscalationManager` with `MockModel`, `sanitize_context=True`, `redact_patterns=["sk-\\d+"]`. `TriggerResult` pre-constructed. |
| **Assert** | `result.target_met`. Fail if >25% regression vs. baseline. |
| **Rationale** | Measures total guard overhead per escalation — the real-world cost users pay when a trigger fires. |

#### B5: Redaction throughput

| | |
|---|---|
| **ID** | `redaction_throughput` |
| **What** | `Redactor.redact()` on context with 50 secrets across 20 failed attempts |
| **Target** | <10ms (10,000,000 ns) |
| **Iterations** | 500 |
| **Baseline** | `Redactor.redact()` on context with 0 secrets (empty patterns list) |
| **Setup** | `EscalationContext` with 20 failed_attempt dicts, each containing 2-3 secrets (OpenAI keys, AWS keys, GitHub tokens, custom patterns). `use_builtin=True` + 1 user pattern. |
| **Assert** | `result.target_met`. Fail if >25% regression vs. baseline. |
| **Rationale** | Regex matching is the most CPU-intensive part of the pipeline. Ensures built-in + user patterns don't create a bottleneck. |

#### B6: Sanitization throughput

| | |
|---|---|
| **ID** | `sanitization_throughput` |
| **What** | `Sanitizer.sanitize()` on context with 20 failed attempts of 2KB each |
| **Target** | <5ms (5,000,000 ns) |
| **Iterations** | 500 |
| **Baseline** | `Sanitizer.sanitize()` on context with 1 failed attempt (minimal wrapping) |
| **Setup** | `EscalationContext` with 20 failed_attempt dicts, each with 2KB output, 2KB error_message, and a 500-char _summary. All string fields get delimited. |
| **Assert** | `result.target_met`. Fail if >25% regression vs. baseline. |
| **Rationale** | String concatenation for delimiters should be O(n) — verifies no accidental quadratic behavior on large contexts. |

#### B7: Memory footprint

| | |
|---|---|
| **ID** | `memory_footprint` |
| **What** | RSS memory after 1,000 guarded steps with `max_history_steps=100` |
| **Target** | <50MB delta (50,000,000 bytes) above baseline |
| **Iterations** | 1 run (memory is not averaged) |
| **Baseline** | RSS memory of a fresh Python process with ai_loopguard imported but no steps recorded |
| **Method** | `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss` (macOS: bytes, Linux: KB). Measure before and after 1,000 `add_step()` calls. |
| **Assert** | `result.target_met`. Fail if >25% regression vs. baseline. |
| **Rationale** | Verifies T3 mitigation — `max_history_steps` bounds memory. Without it, an infinite agent loop would consume unbounded RAM. |

## 4. Methodology

### 4.1 Timing

- **Nanosecond precision** via `time.perf_counter_ns()` — not `time.time()` (wall-clock, low resolution) or `timeit` (too heavyweight for our needs).
- **Median** is the primary metric (robust to outliers from GC pauses, OS scheduling).
- **P99** is recorded for informational purposes — not gating.
- **Baseline subtraction**: each benchmark subtracts the baseline median from the target median to isolate the operation being measured from fixed overhead.

### 4.2 Iteration counts

| Benchmark | Iterations | Rationale |
|---|---|---|
| Detection overhead | 1,000 | Fast operation (<1ms), need enough samples for stable median |
| Context packaging | 100 | Slower operation (<100ms), 100 is enough for stable median |
| Import time | 10 | Subprocess spawning is expensive; 10 is enough for median |
| Escalation flow | 500 | Medium operation (<50ms), 500 balances stability and runtime |
| Redaction | 500 | Fast operation (<10ms), need enough samples |
| Sanitization | 500 | Fast operation (<5ms), need enough samples |
| Memory | 1 | Memory is not averaged — single measurement after 1,000 steps |

### 4.3 Warmup

Each benchmark runs 10 warmup iterations (not recorded) before timing starts. This eliminates:
- First-call JIT / cache effects
- Module-level lazy initialization
- `__pycache__` creation on first import

## 5. Regression Detection

### 5.1 Baseline management

- **First run**: `benchmarks/baseline.json` does not exist. The first run populates it with the measured `adjusted_median_ns` for each benchmark. This becomes the "last known good."
- **Subsequent runs**: load `benchmarks/baseline.json`, compare current `adjusted_median_ns` to stored value.
- **After releases**: manually update `benchmarks/baseline.json` with the release's measurements once confirmed good.

### 5.2 Regression threshold

- **25%** — if `adjusted_median_ns` is >25% slower than the baseline, the test **fails**.
- If the benchmark is under its absolute target but >25% slower than baseline, it still fails (regression detected).
- If the benchmark is over its absolute target but NOT >25% slower than baseline, it passes (existing slowness, not a regression).

### 5.3 Baseline file format

```json
{
  "detection_overhead": {
    "adjusted_median_ns": 450000,
    "target_ns": 1000000,
    "environment": "macos-arm64",
    "git_sha": "eeafccd",
    "recorded_at": "2026-07-11T16:30:00Z"
  },
  "context_packaging": {
    "adjusted_median_ns": 35000000,
    "target_ns": 100000000,
    "environment": "macos-arm64",
    "git_sha": "eeafccd",
    "recorded_at": "2026-07-11T16:30:00Z"
  }
}
```

## 6. Findings Recording

### 6.1 Findings document: `docs/performance-benchmarks.md`

Updated after each benchmark run. Contains:

1. **Environment specs** — CPU, RAM, Python version, OS, date, git SHA
2. **Results table** — one table per environment (local, CI)

| Benchmark | Median (ns) | P99 (ns) | Baseline (ns) | Adjusted (ns) | Target (ns) | Pass? | Regression % |
|---|---|---|---|---|---|---|---|
| detection_overhead | 520,000 | 890,000 | 15,000 | 505,000 | 1,000,000 | ✅ | +2.1% |
| context_packaging | 42,000,000 | 78,000,000 | 1,200,000 | 40,800,000 | 100,000,000 | ✅ | +0.5% |
| import_time | 95,000,000 | — | 200,000 | 94,800,000 | 200,000,000 | ✅ | +1.0% |
| escalation_full_flow | 12,000,000 | 25,000,000 | 50,000 | 11,950,000 | 50,000,000 | ✅ | +0.0% |
| redaction_throughput | 3,200,000 | 7,100,000 | 100,000 | 3,100,000 | 10,000,000 | ✅ | +0.0% |
| sanitization_throughput | 1,800,000 | 3,900,000 | 80,000 | 1,720,000 | 5,000,000 | ✅ | +0.0% |
| memory_footprint | 12,000,000 | — | 45,000,000 | 12,000,000 | 50,000,000 | ✅ | +0.0% |

3. **Analysis** — brief notes on any regressions or anomalies
4. **Methodology** — link back to this plan

### 6.2 Historical trend: `benchmarks/history.jsonl`

Each benchmark run appends one JSON line per benchmark:

```json
{"benchmark":"detection_overhead","median_ns":520000,"p99_ns":890000,"baseline_ns":15000,"adjusted_median_ns":505000,"target_ns":1000000,"target_met":true,"regression_pct":2.1,"environment":"macos-arm64","git_sha":"eeafccd","timestamp":"2026-07-11T16:30:00Z"}
{"benchmark":"context_packaging","median_ns":42000000,"p99_ns":78000000,"baseline_ns":1200000,"adjusted_median_ns":40800000,"target_ns":100000000,"target_met":true,"regression_pct":0.5,"environment":"macos-arm64","git_sha":"eeafccd","timestamp":"2026-07-11T16:30:00Z"}
```

This enables:
- Trend charts over time (plot `adjusted_median_ns` per benchmark per date)
- Regression detection without re-running old code
- Comparison between local and CI environments

## 7. File Structure

```
tests/perf/
├── __init__.py
├── benchmark_runner.py       # BenchmarkRunner + BenchmarkResult dataclass
├── conftest.py               # Shared fixtures (populated GuardState, EscalationContext)
├── test_overhead.py          # B1: detection_overhead
├── test_packaging.py         # B2: context_packaging
├── test_import.py            # B3: import_time (subprocess-based)
├── test_escalation_flow.py   # B4: escalation_full_flow
├── test_redaction.py         # B5: redaction_throughput
├── test_sanitization.py      # B6: sanitization_throughput
└── test_memory.py            # B7: memory_footprint

benchmarks/
├── baseline.json             # Last known good — populated from first run
└── history.jsonl             # Append-only log of every run

docs/
├── performance-test-plan.md  # This document
└── performance-benchmarks.md # Findings — updated after each run
```

## 8. CI Integration

### 8.1 pytest markers

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "perf: performance benchmarks (deselect with '-m \"not perf\"')",
]
```

- `pytest -m "not perf"` — default, skips benchmarks (fast CI)
- `pytest -m perf` — runs only benchmarks
- `pytest` — runs everything

### 8.2 CI workflow

A separate CI job (`perf-benchmarks`) runs on every push to `main` and on PRs:

```yaml
perf-benchmarks:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - run: pip install -e ".[dev]"
    - run: pytest -m perf --benchmark-env=ci
    - run: pytest -m perf --benchmark-env=ci --benchmark-update-baseline  # only on main
```

- On PRs: benchmarks run but do NOT update baseline (regression check only).
- On `main`: benchmarks run AND update `benchmarks/baseline.json` if all pass.
- Findings MD is committed by a bot or manually after release.

### 8.3 Gating behavior

| Condition | PR | main |
|---|---|---|
| All benchmarks under target, no regression | ✅ Pass | ✅ Pass + update baseline |
| Benchmark under target but >25% regression | ❌ Fail | ❌ Fail |
| Benchmark over target but no regression | ✅ Pass (existing issue) | ✅ Pass (investigate separately) |
| Benchmark over target AND >25% regression | ❌ Fail | ❌ Fail |

## 9. Acceptance Criteria

- [ ] `BenchmarkRunner` class with `BenchmarkResult` dataclass
- [ ] 7 benchmark test files, all decorated with `@pytest.mark.perf`
- [ ] `benchmarks/baseline.json` populated from first run
- [ ] `benchmarks/history.jsonl` appends one line per benchmark per run
- [ ] `docs/performance-benchmarks.md` with results tables for local + CI
- [ ] Regression detection: >25% = fail, implemented and tested
- [ ] `pytest -m "not perf"` skips all benchmarks
- [ ] `pytest -m perf` runs only benchmarks
- [ ] All 7 benchmarks pass on local macOS
- [ ] All 7 benchmarks pass on CI ubuntu-latest

## 10. Implementation Order

1. `tests/perf/benchmark_runner.py` — shared runner + dataclass
2. `tests/perf/conftest.py` — shared fixtures (populated states, contexts)
3. `tests/perf/test_overhead.py` — B1 (detection)
4. `tests/perf/test_packaging.py` — B2 (packaging)
5. `tests/perf/test_import.py` — B3 (import)
6. `tests/perf/test_escalation_flow.py` — B4 (escalation)
7. `tests/perf/test_redaction.py` — B5 (redaction)
8. `tests/perf/test_sanitization.py` — B6 (sanitization)
9. `tests/perf/test_memory.py` — B7 (memory)
10. `benchmarks/baseline.json` — created on first run
11. Run benchmarks locally → populate baseline → record findings
12. `docs/performance-benchmarks.md` — write findings from local run
13. Update CI workflow to include `perf-benchmarks` job
14. Update WBS S12 checkpoint with results
