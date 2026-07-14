# Release Notes — ai-loopguard v0.1.0

> **Date:** 2026-07-11
> **PyPI:** `pip install ai-loopguard`
> **Import:** `from ai_loopguard import Guard`
> **CLI:** `loopguard analyze logs.jsonl --summary`

## Overview

ai-loopguard is a circuit breaker and escalation library for LLM agent loops. It detects when an agent is stuck in a loop (repeated errors, test failures, schema violations) and escalates to a stronger model before costs spiral. It drops into LangGraph, CrewAI, or raw Python with zero refactoring.

## Changelog

### S1–S4: Core foundation

- **Pydantic configuration** — `GuardConfig` with per-trigger `TriggerConfig`, validated constraints, sensible defaults
- **GuardState** — thread-safe step history with `max_history_steps` bound, `StepRecord` dataclass
- **FailureDetector** — 4 triggers: `repeated_error`, `test_failure`, `schema_invalid`, `custom` callback
- **Context packaging** — `ContextPackager` with compression (first + last + summary), `Sanitizer` (delimiter wrapping), `Redactor` (built-in OpenAI/AWS/GitHub patterns + user patterns + field stripping)
- **EscalationManager** — full pipeline: trigger → package → sanitize → redact → model invoke → log → return

### S5–S6: Guard decorator + integrations

- **@guard.protect** — sync and async decorators, shared state across calls, `reset()` between tasks
- **Fail-open modes** — `raise_original`, `return_last_output`, `return_sentinel`
- **Interrupt mode** — user callback `(summary: str) -> "y" | "n"` pauses before escalation
- **LangGraph integration** — `LangGraphHandler` with `on_step_end()`, native `interrupt()` support
- **CrewAI integration** — `CrewAIWrapper` with per-agent state, `wrap(crew)` instrumentation
- **OTel integration** — `OTelEventHook` with GenAI semantic conventions, span attributes per event type

### S7–S9: Testing + CLI

- **Unit tests** — 11 test files covering all components (detectors, escalation, context, config, state, logging, cost, exceptions, prompts, CLI, history)
- **Integration tests** — 5 files (sync guard, async guard, langgraph, crewai, otel)
- **CostTracker** — cost per completed task, escalation rate, routing vs failover separation
- **CLI** — `loopguard analyze` with `--summary`, `--trigger`, `--since`, `--model` filters

### S10–S11: Polish + E2E

- **CLI** — Click-based (Typer 0.25.1 has positional arg bug on Python 3.14), JSONL parsing, malformed line skipping
- **E2E tests** — 11 test files, 38 tests covering: repeated error, test failure, schema invalid, interrupt mode, escalation cap, fail-open, redaction, sanitization, langgraph full flow, crewai full flow, otel full flow

### S12: Performance benchmarks

7 benchmarks, all passing with significant headroom:

| Benchmark | Adjusted median | Target | Headroom |
|---|---:|---:|---:|
| Detection overhead | 2.75 µs | 1 ms | 363× |
| Context packaging | 10.25 µs | 100 ms | 9,756× |
| Import time | 54.8 ms | 200 ms | 3.6× |
| Escalation full flow | 2.6 µs | 50 ms | 19,048× |
| Redaction throughput | 0.87 ms | 10 ms | 11.5× |
| Sanitization throughput | 21.6 µs | 5 ms | 231× |
| Memory footprint | 39.9 KB | 50 MB | 1,253× |

See `benchmarks/performance-benchmarks.md` for full results and analysis.

## Key metrics

- **436 tests** passing, 1 skipped
- **97.31%** test coverage
- **0** ruff errors, **0** mypy errors
- **3** framework integrations (LangGraph, CrewAI, OTel)
- **4** trigger types (repeated_error, test_failure, schema_invalid, custom)
- **3** fail-open modes
- **7** performance benchmarks with regression detection

## Known limitations (v0.1.0)

- **Basic triggers only** — no hallucination_cycle detection (planned for v0.2.0)
- **Single-loop scenarios** — no multi-agent coordination or cross-loop escalation
- **Python 3.10–3.14** — not tested on 3.15+
- **LangGraph interrupt mode** — requires LangGraph >= 0.2.0 with native `interrupt()` support
- **CrewAI integration** — marked experimental due to frequent CrewAI breaking changes
- **No prompt injection detector** — delimiter-based sanitization raises the bar but is not foolproof
- **No web UI** — CLI only for log analysis

## Future roadmap

- **v0.2.0:** Hallucination cycle detection, prompt injection detector extra, multi-agent coordination
- **v0.3.0:** Custom trigger SDK, escalation policy engine, cost budget enforcement
- **Post-launch:** Web dashboard, LangSmith integration, eval harness integration

## Acknowledgments

Built by Debashish Ghosal. Uses LangChain Core, Pydantic, and Click. Integrates with LangGraph, CrewAI, and OpenTelemetry.

## Links

- **Repository:** https://github.com/deghosal-2026/ai-loopguard
- **Issues:** https://github.com/deghosal-2026/ai-loopguard/issues
- **Changelog:** https://github.com/deghosal-2026/ai-loopguard/releases
- **Performance plan:** `docs/performance-test-plan.md`
- **Performance findings:** `benchmarks/performance-benchmarks.md`
