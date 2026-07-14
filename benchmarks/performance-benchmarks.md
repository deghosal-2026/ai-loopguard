# Performance Benchmark Findings — 2026-07-11

> **Plan ref:** [`docs/performance-test-plan.md`](../docs/performance-test-plan.md)
> **SPEC ref:** §11 (Performance NFRs), §12.5 (BenchmarkRunner)
> **Git SHA:** `eeafccd`
> **Run timestamp:** 2026-07-11T17:06Z

## Environment

| | |
|---|---|
| **OS** | macOS Darwin 25.5.0 |
| **CPU** | Apple M5 (arm64) |
| **RAM** | 34 GB |
| **Python** | 3.14.5 |
| **Benchmark env** | `local` |
| **Command** | `pytest tests/perf/ --benchmark-env=local -v` |

## Results

| Benchmark | Median (ns) | P99 (ns) | Baseline (ns) | Adjusted (ns) | Target (ns) | Pass | Regression % | Headroom |
|---|---:|---:|---:|---:|---:|:---:|---:|---:|
| detection_overhead | 3,292 | 4,083 | 541 | 2,751 | 1,000,000 | ✅ | 0.0% | 363× |
| context_packaging | 10,750 | 12,875 | 500 | 10,250 | 100,000,000 | ✅ | 0.0% | 9,756× |
| import_time | 69,864,500 | 72,075,500 | 15,025,583 | 54,838,917 | 200,000,000 | ✅ | 0.0% | 3.6× |
| escalation_full_flow | 2,709 | 5,000 | 84 | 2,625 | 50,000,000 | ✅ | 0.0% | 19,048× |
| redaction_throughput | 867,167 | 912,291 | 334 | 866,833 | 10,000,000 | ✅ | 0.0% | 11.5× |
| sanitization_throughput | 22,375 | 28,250 | 750 | 21,625 | 5,000,000 | ✅ | 0.0% | 231× |
| memory_footprint | 39,904 | 39,904 | 272 | 39,904 | 50,000,000 | ✅ | 0.0% | 1,253× |

**7/7 benchmarks passed. All targets met with significant headroom.**

## Analysis

### SPEC-mandated benchmarks (B1–B3)

- **Detection overhead (B1):** 2.75 µs adjusted — 363× under the 1ms target. The `FailureDetector.check()` method iterates over 3 trigger checks, each O(1) or O(N) with small N. The 100-step history with mixed error/test/schema patterns exercises all trigger code paths. Baseline (empty state) is 541 ns, confirming the method-call overhead is negligible.
- **Context packaging (B2):** 10.25 µs adjusted — 9,756× under the 100ms target. `ContextPackager.package()` serializes 20 steps of ~2KB each with compression enabled. The compression code path (first + last + summary) adds minimal overhead. Baseline (1-step, no compression) is 500 ns.
- **Import time (B3):** 54.8 ms adjusted — 3.6× under the 200ms target. This is the tightest margin. The cold import spawns a subprocess with `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` deleted. The 15ms baseline (`import sys`) accounts for subprocess spawn + interpreter startup. Lazy imports for langgraph/crewai/otel keep the core import lean.

### Additional benchmarks (B4–B7)

- **Escalation full flow (B4):** 2.6 µs adjusted — 19,048× under the 50ms target. The full pipeline (trigger → package → sanitize → redact → mock model invoke → log → return) is dominated by the model call. With a real LLM (1–5s latency), guard overhead is <0.001% of total escalation time.
- **Redaction throughput (B5):** 0.87 ms adjusted — 11.5× under the 10ms target. Regex matching of 50 secrets (OpenAI, AWS, GitHub, custom patterns) across 20 failed attempts. Built-in patterns + 1 user pattern. This is the second-tightest margin — if more built-in patterns are added, re-benchmark.
- **Sanitization throughput (B6):** 21.6 µs adjusted — 231× under the 5ms target. Delimiter wrapping on 20×2KB context. Confirms O(n) behavior — no accidental quadratic string concatenation.
- **Memory footprint (B7):** 39.9 KB adjusted — 1,253× under the 50MB target. `tracemalloc` measures Python-level allocations after 1,000 `add_step()` calls with `max_history_steps=100`. Only 100 steps are retained (the bound works), each with ~2KB data. The 39.9 KB delta confirms `GuardState.steps` is correctly bounded.

### Observations

1. **Import time is the tightest margin** (3.6× headroom). If heavy dependencies are added to `ai_loopguard/__init__.py`, this benchmark will be the first to fail. Current lazy-import strategy for integration modules is working.
2. **Redaction is the second-tightest** (11.5× headroom). Regex compilation/matching scales with pattern count. If built-in pattern list grows significantly, re-benchmark.
3. **All other benchmarks have >200× headroom** — detection, packaging, escalation, sanitization, and memory are not at risk of regression under normal development.
4. **Regression detection baseline established.** All 7 benchmarks recorded `regression_pct: 0.0%` (first run, no prior baseline). Future runs will compare against `benchmarks/baseline.json`.

## Methodology

- **Timing:** `time.perf_counter_ns()` (nanosecond precision, monotonic clock)
- **Primary metric:** Median (robust to GC pauses, OS scheduling outliers)
- **P99:** Recorded for informational purposes, not gating
- **Baseline subtraction:** Each benchmark subtracts a baseline median to isolate the measured operation from fixed overhead
- **Warmup:** 10 unrecorded iterations before timing to eliminate first-call cache effects
- **Regression threshold:** >25% slower than baseline = test failure
- **Memory:** `tracemalloc` (Python-level allocation tracking) instead of `ru_maxrss` (process peak RSS, which doesn't reflect allocation deltas)

See [`docs/performance-test-plan.md`](../docs/performance-test-plan.md) for full methodology, benchmark definitions, and CI integration plan.

## Raw Data

- **Baseline:** [`benchmarks/baseline.json`](baseline.json) — last known good per benchmark
- **History:** [`benchmarks/history.jsonl`](history.jsonl) — append-only log of every run (one JSON line per benchmark per run)
