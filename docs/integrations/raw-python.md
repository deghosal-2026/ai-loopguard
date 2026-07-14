# Raw Python integration

Use `Guard` directly when your agent loop isn't inside a framework like
LangGraph or CrewAI. Decorate your step function with `@guard.protect`
(sync) or `@guard.aprotect` (async), and loopguard records each call as one
step, evaluates triggers, and escalates to a stronger model when the agent
is stuck.

## Prerequisites

```bash
pip install ai-loopguard
```

No extras are required. The CLI is `loopguard`; the PyPI package is
`ai-loopguard`; the import root is `ai_loopguard`.

## Guard

```python
from ai_loopguard import Guard

guard = Guard(
    escalation_model=gpt4,            # LangChain BaseChatModel
    workhorse_model_name="qwen2.5-coder",
    on_escalate="auto",               # or "interrupt"
    interrupt_callback=my_ui_prompt,  # optional: (str) -> "y"/"n"
)
```

All `GuardConfig` fields are accepted as kwargs, plus the optional
`interrupt_callback` callable `(summary: str) -> str` returning `"y"` or
`"n"` (used in interrupt mode, see below). Construction never fails — config
errors surface on the first guarded call, so you can instantiate at import
time.

## @guard.protect (sync)

```python
def protect(self, fn: Callable[..., Any]) -> Callable[..., Any]
```

Wraps any sync Python function. Each call records one step:

1. Calls `fn(*args, **kwargs)`.
2. On success, records the output; on exception, records the failure
   (output `None`) — a failed step can still fire a trigger (e.g., 3
   consecutive errors → `repeated_error`).
3. Checks all enabled triggers against the shared `GuardState`.
4. If a trigger fires and an `escalation_model` is configured, escalates
   and returns the escalation model's output.
5. If a trigger fires but `escalation_model is None` (detection-only mode),
   returns the last step's output and logs the trigger.
6. If no trigger fires, returns the original output.

```python
@guard.protect
def step(state):
    output = workhorse.invoke(state["messages"]).content
    guard.record_test_results(run_tests(output))
    return output
```

The decorator captures the `Guard` instance at decoration time, so every
call of `step` shares the same guard state — this is how cross-step trigger
accumulation works.

## @guard.aprotect (async)

```python
def aprotect(self, fn: Callable[..., Any]) -> Callable[..., Any]
```

Same semantics as `protect()` with `await`. Uses
`escalate_async()` / `ainvoke()` on the escalation model, and the async
interrupt path (`prompt_async`) so `input()` doesn't block the event loop.

```python
@guard.aprotect
async def step(state):
    output = (await workhorse.ainvoke(state["messages"])).content
    guard.record_test_results(run_tests(output))
    return output
```

## guard.record_test_results()

```python
def record_test_results(self, results: dict[str, bool]) -> None
```

Feed per-test pass/fail for the current step. Call this **inside** the
decorated function body, before it returns, so the `test_failure` trigger
sees the results on the current step. The pending value is consumed by the
next step record; it also updates `state.steps[-1]` immediately for backward
compat (so you see results reflected in step history without a one-step lag).

```python
guard.record_test_results({"test_parse": True, "test_eval": False})
```

## guard.record_schema_valid()

```python
def record_schema_valid(self, *, valid: bool) -> None
```

Keyword-only bool. Feeds a schema-validation result for the current step;
the `schema_invalid` trigger fires after `max_retries` consecutive invalid
steps.

```python
guard.record_schema_valid(valid=is_valid_json(output))
```

## guard.reset()

```python
def reset(self) -> None
```

Clears step history, escalation count, and pending metadata, and
invalidates the cached detector / escalation manager so fresh ones are
created on the next guarded call. Call this **between independent agent
tasks** — without it, trigger thresholds accumulate across unrelated tasks
and you get false positives.

```python
for task in tasks:
    guard.reset()
    run_agent(task)
```

## Full sync example with a test runner

```python
from langchain_openai import ChatOpenAI

from ai_loopguard import Guard

workhorse = ChatOpenAI(model="qwen2.5-coder", temperature=0)
gpt4 = ChatOpenAI(model="gpt-4o", temperature=0)

guard = Guard(
    escalation_model=gpt4,
    workhorse_model_name="qwen2.5-coder",
    on_escalate="auto",
    max_escalations_per_run=2,
)


@guard.protect
def generate(state):
    output = workhorse.invoke(state["messages"]).content
    # Feed test results for the test_failure trigger.
    guard.record_test_results(run_tests(output))
    # Feed schema validation for the schema_invalid trigger.
    guard.record_schema_valid(valid=is_valid_json(output))
    return output


def run_agent(task):
    guard.reset()  # fresh history per task
    state = {"messages": [{"role": "user", "content": task}]}
    for _ in range(10):
        output = generate(state)
        if done(output):
            return output
        state["messages"].append({"role": "assistant", "content": output})
    return None
```

## Full async example

```python
import asyncio

from langchain_openai import ChatOpenAI

from ai_loopguard import Guard

workhorse = ChatOpenAI(model="qwen2.5-coder", temperature=0)
gpt4 = ChatOpenAI(model="gpt-4o", temperature=0)

guard = Guard(
    escalation_model=gpt4,
    workhorse_model_name="qwen2.5-coder",
    on_escalate="auto",
)


@guard.aprotect
async def generate(state):
    output = (await workhorse.ainvoke(state["messages"])).content
    guard.record_test_results(await run_tests_async(output))
    return output


async def run_agent(task):
    guard.reset()
    state = {"messages": [{"role": "user", "content": task}]}
    for _ in range(10):
        output = await generate(state)
        if done(output):
            return output
        state["messages"].append({"role": "assistant", "content": output})
    return None


asyncio.run(run_agent("Refactor utils.py to use dataclasses."))
```

## Interrupt mode with a custom callback

In raw Python (not LangGraph), `on_escalate="interrupt"` pauses execution
and asks the user before spending tokens. By default it prompts via
`input()` on stdin. Pass `interrupt_callback` to route the prompt anywhere —
a TUI, a chat client, a Slack webhook, etc. The callback receives the full
prompt string (trigger name, detail, context summary, the yes/no question)
and must return `"y"` (escalate) or anything else (skip).

```python
def ui_prompt(message: str) -> str:
    # Render `message` in your UI; collect a yes/no click.
    return "y" if user_clicked_yes() else "n"


guard = Guard(
    escalation_model=gpt4,
    workhorse_model_name="qwen2.5-coder",
    on_escalate="interrupt",
    interrupt_callback=ui_prompt,
)
```

For async code (`@guard.aprotect`), the callback may be sync or async. A sync
callback is run in a thread pool so it doesn't block the event loop; an async
callback is awaited directly. Only a `"y"` response (case-insensitive,
whitespace-stripped) proceeds with escalation — anything else (`"n"`, `""`,
Ctrl-C) skips it and the last output is returned.

The escalation cap is checked **before** the interrupt prompt, so a capped
trigger never prompts the user.

## Fail-open modes

`on_guard_error` controls what happens when loopguard itself errors or the
escalation model fails. The agent loop must never crash because of a guard
failure.

```python
guard = Guard(
    escalation_model=gpt4,
    on_guard_error="return_last_output",  # or "raise_original" / "return_sentinel"
    sentinel_value={"error": "escalation_failed"},  # only used by return_sentinel
)
```

| Mode | Behaviour |
| --- | --- |
| `raise_original` (default) | Re-raise the last original agent error. If there is no previous error, raises `EscalationError`. This makes a guard failure look like the agent error never left — useful in development. |
| `return_last_output` | Return the last successful step's output (or `None` if there are no steps). The agent loop continues with stale-but-valid data — useful in production where you'd rather degrade than crash. |
| `return_sentinel` | Return `sentinel_value` (any object, default `None`). The agent loop can branch on the sentinel to retry, log, or surface a structured error. |

A failed escalation is logged as a `FailOpenEvent` (with the fail-open mode
recorded) before the fail-open output is returned, so observability hooks
still see the failure even when the agent loop continues.

## Detection-only mode

If you set `escalation_model=None` (the default), the guard runs detection
and logging only — when a trigger fires it returns the last step's output
instead of escalating. Useful for evaluating trigger accuracy on historical
runs before paying for escalations, or for pure observability via event
hooks.
