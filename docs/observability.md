# Metrics & Observability Guide

> **Import:** `from ai_loopguard import Guard, GuardConfig`
> **Logging types:** `from ai_loopguard.logging import EscalationLogger, EscalationEvent, CappedEvent, FailOpenEvent, EventHook`
> **Cost tracking:** `from ai_loopguard.cost import CostTracker`
> **OTel:** `from ai_loopguard.integrations.otel import OTelEventHook` (requires `pip install ai-loopguard[otel]`)
> **CLI:** `loopguard analyze logs.jsonl --summary`
> **Target release:** v0.1.0

loopguard emits structured JSONL logs and dispatches pluggable event hooks for every escalation, capped escalation, and fail-open event. This guide covers the event schemas, the logger, the `EventHook` protocol, the OpenTelemetry integration, the `CostTracker`, and the CLI analyzer.

---

## Escalation events

### EscalationEvent

The primary log record, emitted for every escalation. Defined in `ai_loopguard/logging.py` as a Pydantic `BaseModel`.

| Field | Type | Description |
|---|---|---|
| `timestamp` | `float` | Unix timestamp of the escalation |
| `trigger_type` | `str` | Which trigger fired: `repeated_error`, `test_failure`, `schema_invalid`, or `custom` |
| `trigger_detail` | `str` | Human-readable detail (e.g. `"ValueError: rate limited, 3 consecutive"`) |
| `retry_count` | `int` | How many retries occurred before escalation (0 for `custom` triggers, 4 for oscillation) |
| `workhorse_model` | `str` | Name of the model that got stuck |
| `escalation_model` | `str` | Name of the model escalated to |
| `escalation_category` | `Literal["routing", "failover"]` | `routing` = intentional escalation from a failure pattern; `failover` = availability failure (FR-3.3) |
| `context_tokens` | `int` | Tokens in the packaged context sent to the escalation model |
| `escalation_tokens` | `int` | Tokens consumed by the escalation model call |
| `escalation_cost_usd` | `float` | Cost of the escalation model call |
| `total_task_cost_usd` | `float` | Total cost including retries + escalation |
| `total_task_tokens` | `int` | Total tokens including retries + escalation |
| `success` | `bool` | Whether the escalation produced a valid result |
| `sanitized` | `bool` | Whether context was sanitized (T1 prompt-injection mitigation applied) |
| `redacted_fields` | `list[str]` | Field names that were redacted (T2) |

### CappedEvent

Emitted when the escalation cap (`max_escalations_per_run`) is reached. The escalation model is **not** called — the last known output is returned instead.

| Field | Type | Description |
|---|---|---|
| `timestamp` | `float` | Unix timestamp when the cap was hit |
| `trigger_type` | `str` | Which trigger tried to fire |
| `trigger_detail` | `str` | Human-readable detail |
| `retry_count` | `int` | Retry count at the time of capping |
| `message` | `str` | Default: `"Escalation cap reached"` |

### FailOpenEvent

Emitted when loopguard itself fails — the escalation model call raised an exception, so loopguard falls back to the configured `on_guard_error` strategy.

| Field | Type | Description |
|---|---|---|
| `timestamp` | `float` | Unix timestamp of the failure |
| `trigger_type` | `str` | Which trigger caused the escalation attempt |
| `error_message` | `str` | The exception message from the failed call |
| `fail_open_mode` | `str` | Which strategy was used: `raise_original`, `return_last_output`, or `return_sentinel` |

---

## EscalationLogger

`EscalationLogger` serialises every event as one JSONL line (via Pydantic's `model_dump_json()`) and dispatches it to all registered `EventHook` implementations. Lines are flushed immediately after each write so logs survive crashes.

**Sink selection** (set via `GuardConfig.log_dir`):

| `log_dir` | Sink |
|---|---|
| `None` (default) | JSONL written to **stdout** |
| `"/path/to/dir"` | JSONL appended to `/path/to/dir/escalations.jsonl` (append mode — does not overwrite across restarts) |

```python
from ai_loopguard import Guard, GuardConfig

guard = Guard(
    escalation_model=escalation_model,
    config=GuardConfig(
        log_dir="logs/",  # writes to logs/escalations.jsonl
    ),
)
```

Each JSONL line is a complete JSON object, making logs greppable and importable by the CLI analyzer (`loopguard analyze`).

---

## EventHook protocol

`EventHook` is a `@runtime_checkable` `Protocol` (structural subtyping — no inheritance required). Implement the three methods to integrate with custom logging, metrics, or monitoring systems. All three event types are dispatched to every registered hook.

```python
from ai_loopguard import Guard
from ai_loopguard.logging import EventHook, EscalationEvent, CappedEvent, FailOpenEvent

class DatadogHook(EventHook):
    def on_escalation(self, event: EscalationEvent) -> None:
        send_metric("loopguard.escalation", tags=[f"trigger:{event.trigger_type}"])

    def on_capped(self, event: CappedEvent) -> None:
        increment_counter("loopguard.capped")

    def on_fail_open(self, event: FailOpenEvent) -> None:
        increment_counter("loopguard.fail_open", tags=[f"mode:{event.fail_open_mode}"])

guard = Guard(escalation_model=escalation_model)
guard.logger.register_hook(DatadogHook())
```

The dispatch model is a simple observer pattern — no async dispatch, no event bus. `guard.logger.hooks` returns a read-only copy of the registered hooks.

---

## OTelEventHook

`OTelEventHook` implements `EventHook` and emits OpenTelemetry spans for every event. Requires the `otel` extra:

```
pip install ai-loopguard[otel]
```

**Registration:**

```python
from ai_loopguard import Guard
from ai_loopguard.integrations.otel import OTelEventHook

guard = Guard(escalation_model=escalation_model)
guard.logger.register_hook(OTelEventHook())
```

The tracer is lazy-created on the first event (so importing the module never requires `opentelemetry`). Pass a custom `TracerProvider` to capture spans in-memory for tests:

```python
OTelEventHook(tracer_provider=my_provider)
```

### Span attributes

Every span sets `gen_ai.system = "loopguard"` (OTel GenAI semantic convention). Additional attributes use the `ai_loopguard.*` prefix:

**Escalation span** — name: `ai_loopguard.escalation`

| Attribute | Source |
|---|---|
| `gen_ai.system` | `"loopguard"` |
| `ai_loopguard.trigger_type` | `event.trigger_type` |
| `ai_loopguard.retry_count` | `event.retry_count` |
| `ai_loopguard.workhorse_model` | `event.workhorse_model` |
| `ai_loopguard.escalation_model` | `event.escalation_model` |
| `ai_loopguard.escalation_category` | `event.escalation_category` (`routing` / `failover`) |
| `ai_loopguard.cost_per_task` | `event.total_task_cost_usd` |

A span event named `escalation` with the full event dict (`event.model_dump()`) is attached for fields not surfaced as attributes (`success`, `sanitized`, `redacted_fields`, etc.).

**Capped span** — name: `ai_loopguard.escalation.capped`

| Attribute | Source |
|---|---|
| `gen_ai.system` | `"loopguard"` |
| `ai_loopguard.trigger_type` | `event.trigger_type` |
| `ai_loopguard.retry_count` | `event.retry_count` |

Plus a `capped` span event with the full payload.

**Fail-open span** — name: `ai_loopguard.fail_open`

| Attribute | Source |
|---|---|
| `gen_ai.system` | `"loopguard"` |
| `ai_loopguard.trigger_type` | `event.trigger_type` |
| `ai_loopguard.fail_open_mode` | `event.fail_open_mode` |
| `ai_loopguard.error_message` | `event.error_message` |

Plus a `fail_open` span event with the full payload.

---

## CLI — `loopguard analyze`

Parses JSONL logs produced by `EscalationLogger` and prints summarised metrics. Only `EscalationEvent` lines are parsed into metrics; `CappedEvent` and `FailOpenEvent` lines are silently skipped.

```
loopguard analyze logs/escalations.jsonl
loopguard analyze logs/escalations.jsonl --summary
loopguard analyze logs/escalations.jsonl --trigger repeated_error
loopguard analyze logs/escalations.jsonl --since 2026-07-01
loopguard analyze logs/escalations.jsonl --model gpt-4
```

### Options

| Option | Default | Description |
|---|---|---|
| `log_file` (positional) | — | Path to the JSONL log file (must exist) |
| `--summary` / `--no-summary` | `--summary` | Print the summary table (on by default; `--no-summary` for scripting) |
| `--trigger <type>` | `None` | Filter to events with the given trigger type (e.g. `repeated_error`) |
| `--since <date>` | `None` | Filter to events on or after this date (`YYYY-MM-DD`, interpreted as UTC) |
| `--model <name>` | `None` | Filter by escalation model name — **case-insensitive substring match** so `--model gpt-4` matches `gpt-4-turbo` |

Filters accumulate with **AND logic** — each filter narrows the result set further. For OR logic, run `analyze` separately per filter.

### Summary output

The default summary prints:

- Total escalations (after filtering)
- Total cost in USD (`Σ total_task_cost_usd`)
- Cost breakdown by trigger type, sorted by count descending:

```
==================================================
loopguard escalation summary
==================================================
Total escalations:       42
Total cost (USD):        $1.2340

Cost breakdown by trigger:
  repeated_error            20  $0.5600
  test_failure              15  $0.4500
  schema_invalid             7  $0.2240
```

Malformed JSONL lines are skipped with a warning to stderr (`Warning: skipping malformed line N`); blank lines are skipped silently. An invalid `--since` date prints an error and exits with code 1.

---

## CostTracker

`CostTracker` aggregates per-completed-task cost, escalation rate, and the routing-vs-failover split (SPEC §6.1 / FR-3.3). It is thread-safe (`threading.Lock`). The key distinction from per-call cost trackers: a task that loops 10 times costs more than one that succeeds first try — the "cheap" per-call price is misleading.

```python
from ai_loopguard.cost import CostTracker

tracker = CostTracker()

# After each agent step (workhorse model retry)
tracker.record_step("task-1", tokens=150, cost_usd=0.003)

# After each escalation (stronger model)
tracker.record_escalation("task-1", tokens=500, cost_usd=0.01, escalation_category="routing")

# Increment the guarded-call counter (once per @guard.protect invocation)
tracker.record_guarded_call()

# Query metrics
cost = tracker.get_cost_per_completed_task("task-1")   # float | None
rate = tracker.get_escalation_rate()                   # 0.0 – 1.0
split = tracker.get_routing_vs_failover()              # {"routing": int, "failover": int}
```

### Methods

| Method | Returns | Description |
|---|---|---|
| `record_step(task_id, tokens, cost_usd)` | `None` | Record a retry step (workhorse model) |
| `record_escalation(task_id, tokens, cost_usd, escalation_category)` | `None` | Record an escalation call; category is `"routing"` (default) or `"failover"` |
| `record_guarded_call()` | `None` | Increment the total guarded-call counter (used for escalation rate) |
| `get_cost_per_completed_task(task_id)` | `float \| None` | Total cost for a task (retries + escalations), or `None` if no data |
| `get_escalation_rate()` | `float` | `total_escalations / total_guarded_calls` (0.0 if no calls) |
| `get_routing_vs_failover()` | `dict[str, int]` | `{"routing": N, "failover": N}` counts across all tasks |
| `clear()` | `None` | Reset all tracked data (useful between benchmark runs) |

**Routing vs failover (FR-3.3):**
- **routing** — intentional escalation triggered by a failure pattern (`repeated_error`, `test_failure`, `schema_invalid`, `custom`)
- **failover** — escalation caused by model unavailability or infrastructure failure

---

## Key metrics to monitor

| Metric | How to compute | Target / guidance |
|---|---|---|
| **Escalation rate** | `CostTracker.get_escalation_rate()` or `total_escalations / total_guarded_calls` | **< 20%** — a high rate means the workhorse model is underpowered for the task or trigger thresholds are too low |
| **Cost per completed task** | `CostTracker.get_cost_per_completed_task(task_id)` | Track the trend; a task that loops 10× costs ~10× the per-call price. Compare against the escalation cost to decide if a stronger workhorse model is cheaper |
| **Trigger distribution** | `loopguard analyze ... --summary` → "Cost breakdown by trigger", or `EventLog.trigger_breakdown` | Which triggers fire most often tells you which failure mode dominates your workload |
| **Routing vs failover** | `CostTracker.get_routing_vs_failover()` | Failover count should be near zero — non-zero failover indicates infrastructure/model-availability problems, not model-capability problems |
| **Capped escalations** | Count `CappedEvent` lines in JSONL, or `OTelEventHook` `ai_loopguard.escalation.capped` spans | Sustained capping means `max_escalations_per_run` is too low for the workload |
| **Fail-open events** | Count `FailOpenEvent` lines, or `ai_loopguard.fail_open` spans | Any non-zero count means the escalation model itself is failing — investigate `error_message` and `fail_open_mode` |
