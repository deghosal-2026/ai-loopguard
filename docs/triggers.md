# Trigger Reference

> **Import:** `from ai_loopguard import Guard, GuardConfig, TriggerConfig`
> **Target release:** v0.1.0

loopguard's `FailureDetector` monitors the step history of a guarded call and fires a trigger when an agent is stuck in a loop. Four trigger types are supported in v0.1.0; `hallucination_cycle` is planned for v0.2.0.

## How triggers are evaluated

Triggers are evaluated in a fixed order on every step (SPEC §3.3):

1. `custom` — user-defined, highest priority
2. `repeated_error` — string comparison, cheapest
3. `test_failure` — dict comparison
4. `schema_invalid` — boolean flag check

The **first trigger to fire wins** — only one escalation is produced per evaluation cycle. Trigger order is hardcoded in `ai_loopguard/detectors.py` (`_TRIGGER_ORDER`), not derived from dict insertion order, so reordering your `triggers` config does not change evaluation priority.

Disabled triggers (`enabled=False`) are skipped entirely. Unknown trigger names are silently skipped — to add custom detection logic, use the `custom` trigger with a `custom_callback`, never a new trigger name.

---

## Comparison table

| Trigger | What it detects | Config key | Data input method | Default threshold |
|---|---|---|---|---|
| `test_failure` | Same test fails N consecutive times, or pass→fail→pass→fail oscillation over a fixed 4-step window | `max_retries` | `guard.record_test_results({"test_name": bool})` | 3 |
| `repeated_error` | Same `error_type` + `error_message` across N consecutive total steps | `max_retries` | Auto-recorded from exceptions raised inside `@guard.protect` | 3 |
| `schema_invalid` | `schema_valid` flag is `False` for N consecutive steps that have schema data | `max_retries` | `guard.record_schema_valid(valid=bool)` | 3 |
| `custom` | User callback returns `True` | `custom_callback` | Any data the callback reads from `GuardState` | Fires instantly (no threshold) |
| `hallucination_cycle` | _Planned for v0.2.0 — not yet implemented_ | — | — | — |

---

## test_failure

**What it detects:** A test that keeps failing or oscillates between pass and fail. Two detection modes run on every step that has test results:

1. **Consecutive failure** — the same test name is `False` in the last `max_retries` steps that recorded test results. A test must appear in *every* one of those steps to be a candidate.
2. **Oscillation** — the same test alternates pass/fail over a **fixed 4-step window** (independent of `max_retries`). Detects both `pass→fail→pass→fail` and `fail→pass→fail→pass` patterns.

Steps without `test_results` (i.e. `None`) are **skipped, not counted as failures** — they neither advance the consecutive-fail chain nor break it. This means intermittent steps where you didn't run tests won't reset your counter.

**Configuration:**

```python
from ai_loopguard import Guard, GuardConfig, TriggerConfig

config = GuardConfig(
    escalation_model=escalation_model,
    triggers={
        "test_failure": TriggerConfig(enabled=True, max_retries=3),
    },
)
guard = Guard(config=config)
```

**How to feed data:** Call `guard.record_test_results()` inside your guarded function with a dict mapping test name → pass/fail boolean. The results are attached to the current step immediately (no one-step lag):

```python
from ai_loopguard import Guard, GuardConfig

guard = Guard(escalation_model=escalation_model)

@guard.protect
def generate_code(prompt: str) -> str:
    output = run_agent(prompt)
    guard.record_test_results(run_tests(output))  # {"test_parse": True, "test_lint": False}
    return output
```

**Example:** With `max_retries=3`, if `test_lint` is `False` in three consecutive steps that recorded test results, the trigger fires with detail `test 'test_lint' failed 3 consecutive times`. If the same test oscillates `pass→fail→pass→fail` over any 4-step window, the trigger fires with `retry_count=4` (the window length) regardless of `max_retries`.

---

## repeated_error

**What it detects:** The same exception type *and* message repeated across `max_retries` **consecutive total steps**. Unlike `test_failure` and `schema_invalid`, this trigger inspects the last `max_retries` *total* steps — a success step (no error) in that window **breaks the chain**. This enforces strict consecutiveness per SPEC §3.1's "appears max_retries consecutive times."

Comparison is a tuple of `(error_type, error_message)` — e.g. `("ValueError", "invalid literal for int()")`. Two `ValueError`s with different messages do not match.

**Configuration:**

```python
from ai_loopguard import Guard, GuardConfig, TriggerConfig

config = GuardConfig(
    escalation_model=escalation_model,
    triggers={
        "repeated_error": TriggerConfig(enabled=True, max_retries=3),
    },
)
guard = Guard(config=config)
```

**How to feed data:** No manual call needed. Error metadata (`error_type`, `error_message`) is auto-recorded by `@guard.protect` when the guarded function raises an exception — `error_type` is `type(exc).__name__` and `error_message` is `str(exc)`.

**Example:**

```python
from ai_loopguard import Guard, GuardConfig

guard = Guard(escalation_model=escalation_model)

@guard.protect
def call_tool(tool_name: str) -> dict:
    return invoke_tool(tool_name)  # raises ValueError("rate limited") on each retry
```

If `invoke_tool` raises `ValueError("rate limited")` on three consecutive calls, the trigger fires with detail `ValueError: rate limited, 3 consecutive`. A successful call between failures resets the chain.

---

## schema_invalid

**What it detects:** The `schema_valid` flag is `False` for `max_retries` consecutive steps that have schema data. Steps where `schema_valid` is `None` (validation wasn't performed) are **skipped** — they neither count as failures nor break the chain. A step where validation wasn't run should not reset your counter.

**Configuration:**

```python
from ai_loopguard import Guard, GuardConfig, TriggerConfig

config = GuardConfig(
    escalation_model=escalation_model,
    triggers={
        "schema_invalid": TriggerConfig(enabled=True, max_retries=3),
    },
)
guard = Guard(config=config)
```

**How to feed data:** Call `guard.record_schema_valid()` inside your guarded function with a keyword-only `valid` boolean:

```python
from ai_loopguard import Guard, GuardConfig
from pydantic import BaseModel

class OutputSchema(BaseModel):
    answer: str
    citations: list[str]

guard = Guard(escalation_model=escalation_model)

@guard.protect
def answer_question(q: str) -> str:
    output = run_agent(q)
    try:
        OutputSchema.model_validate_json(output)
        guard.record_schema_valid(valid=True)
    except Exception:
        guard.record_schema_valid(valid=False)
    return output
```

**Example:** With `max_retries=3`, if three consecutive schema-validated steps all report `False`, the trigger fires with detail `schema invalid for 3 consecutive steps`. Steps where you didn't call `record_schema_valid` are ignored.

---

## custom

**What it detects:** Anything your callback decides. The callback receives the full `GuardState` and returns `True` to fire the trigger. Custom triggers have **no retry threshold** — they fire instantly the moment the callback returns `True` (`retry_count=0` in the resulting `TriggerResult`).

If the callback raises an exception, loopguard wraps it in a `TriggerError` rather than letting it propagate raw.

**Configuration:** Provide a `custom_callback` on a `TriggerConfig` registered under the `"custom"` key. The callback signature is `Callable[[GuardState], bool]`:

```python
from ai_loopguard import Guard, GuardConfig, TriggerConfig

def timeout_trigger(state) -> bool:
    """Fire if any single step took longer than 60 seconds."""
    if not state.steps:
        return False
    last = state.steps[-1]
    return last.timestamp > 0 and (last.timestamp - state.steps[0].timestamp) > 60.0

config = GuardConfig(
    escalation_model=escalation_model,
    triggers={
        "custom": TriggerConfig(enabled=True, custom_callback=timeout_trigger),
    },
)
guard = Guard(config=config)
```

**Example with a custom timeout trigger:**

```python
from ai_loopguard import Guard, GuardConfig, TriggerConfig
import time

def wall_clock_timeout(state) -> bool:
    if len(state.steps) < 2:
        return False
    elapsed = state.steps[-1].timestamp - state.steps[0].timestamp
    return elapsed > 120.0  # escalate if the whole task exceeds 2 minutes

guard = Guard(
    escalation_model=escalation_model,
    config=GuardConfig(
        triggers={
            "custom": TriggerConfig(custom_callback=wall_clock_timeout),
        },
    ),
)

@guard.protect
def long_running_task(payload: dict) -> dict:
    return expensive_agent_call(payload)
```

A `custom_callback` of `None` silently never fires — useful for toggling a custom trigger off via config without removing the entry.

---

## hallucination_cycle (planned — not implemented)

A `hallucination_cycle` trigger is **planned for v0.2.0** and is **not yet implemented** in v0.1.0. It is listed here for forward reference only. Do not register a `"hallucination_cycle"` entry in `triggers` — it will be silently skipped as an unknown trigger name. If you need hallucination detection today, use the `custom` trigger with a callback that inspects `GuardState`.

---

## Configuring thresholds

All threshold-based triggers use the same `max_retries` field on `TriggerConfig`, constrained to `1 ≤ max_retries ≤ 20` (enforced by Pydantic at construction time). The default `GuardConfig.triggers` enables `repeated_error`, `test_failure`, and `schema_invalid` at `max_retries=3`. To disable a trigger without removing it, set `enabled=False`.

To build a `FailureDetector` standalone (without a full `Guard`) with default thresholds, use `FailureDetector.from_defaults()`:

```python
from ai_loopguard import FailureDetector

detector = FailureDetector.from_defaults(
    repeated_error_max_retries=5,
    test_failure_max_retries=4,
    schema_invalid_max_retries=3,
)
```

Call `guard.reset()` between independent tasks — without it, trigger thresholds accumulate across unrelated tasks and cause false positives.
