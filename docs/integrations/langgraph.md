# LangGraph integration

`LangGraphHandler` connects loopguard's detection and escalation pipeline into
a [LangGraph](https://github.com/langchain-ai/langgraph) graph. Call
`on_step_end()` from inside any node function that should be guarded, and
loopguard will record each step, evaluate triggers, and escalate to a stronger
model when an agent node is stuck on the same failure.

## Prerequisites

```bash
pip install ai-loopguard[langgraph]
```

This installs `langgraph>=0.2.0,<0.3.0` in addition to `ai-loopguard`. The
LangGraph import is deferred (it happens inside the interrupt branch) so the
handler can be constructed even if only the base package is installed — but
`on_step_end()` requires the extra when a trigger fires.

## The handler

```python
class LangGraphHandler:
    def __init__(self, guard: Guard) -> None: ...
```

`LangGraphHandler.__init__` takes a single, already-configured `Guard`
instance. The guard's `GuardConfig` controls trigger thresholds, the
escalation model, and the `on_escalate` mode (`"auto"` or `"interrupt"`). The
handler holds no state of its own — all step history lives on the guard's
shared `GuardState`.

```python
from ai_loopguard import Guard
from ai_loopguard.integrations.langgraph import LangGraphHandler

guard = Guard(escalation_model=gpt4, workhorse_model_name="qwen2.5-coder")
handler = LangGraphHandler(guard)
```

## on_step_end()

```python
def on_step_end(
    self,
    step: int,
    state: dict[str, Any],
    output: Any,
    error: Exception | None = None,
) -> Any
```

Call this at the end of a node function, after the node has produced its
output (or raised). It:

1. Consumes any pending metadata set via `guard.record_test_results()` /
   `guard.record_schema_valid()` and clears it.
2. Records a `StepRecord` on the guard's state (timestamp is `0.0` —
   LangGraph steps don't carry wall-clock time; the guard's prompts order by
   `step_num`).
3. Runs all enabled triggers.
4. If a trigger fires, handles escalation per `on_escalate`.

Returns the original `output` if no trigger fires, or the escalation model's
output if escalation occurs. Pass `error=` to record the step as a failure,
which enables the `repeated_error` trigger.

## Auto mode vs interrupt mode

The guard's `on_escalate` config field controls what happens when a trigger
fires inside `on_step_end()`:

### Auto (default)

```python
guard = Guard(escalation_model=gpt4, on_escalate="auto")
```

Trigger fires → loopguard escalates directly to the configured model → the
escalation output is returned from `on_step_end()` (replacing the node's
original output). No user interaction. This is the lowest-latency path and
the right default for batch/headless runs.

### Interrupt

```python
guard = Guard(escalation_model=gpt4, on_escalate="interrupt")
```

Trigger fires → loopguard calls LangGraph's native
[`interrupt()`](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/)
to pause the graph and prompt the user → if the user confirms (`y`), escalation
proceeds and the graph resumes via `Command(resume=escalated)` → if the user
declines, the original output is returned unchanged.

The handler bypasses `EscalationManager`'s own interrupt check (it would
double-prompt); the LangGraph interrupt is the single source of truth. The
escalation cap is checked **before** entering the interrupt branch, so a
capped trigger never prompts the user.

## How interrupt mode interacts with LangGraph

When `on_escalate="interrupt"` and a trigger fires:

```python
from langgraph.types import Command, interrupt

user_response = interrupt(
    f"Agent stuck ({trigger_name}: {detail}). "
    f"Escalate to {escalation_model_name}? [y/n]: {summary}"
)
if user_response.strip().lower() == "y":
    escalated = mgr._do_escalate(trigger_result)
    return Command(resume=escalated)
return output
```

`Command(resume=...)` tells LangGraph to continue the graph with the
escalation output as the node's return value. The graph's edge condition sees
that output and routes normally from there. To drive this from the outside,
invoke the graph with a [checkpointer](https://langchain-ai.github.io/langgraph/concepts/persistence/)
and respond to the `interrupt` by resuming with `Command(resume=...)`:

```python
config = {"configurable": {"thread_id": "1"}}
result = graph.invoke(initial_state, config=config)
# If the graph paused on an interrupt, resume:
from langgraph.types import Command
result = graph.invoke(Command(resume="y"), config=config)
```

## Full working example

```python
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from typing_extensions import TypedDict

from ai_loopguard import Guard
from ai_loopguard.integrations.langgraph import LangGraphHandler

# Cheap workhorse model that is being guarded.
workhorse = ChatOpenAI(model="qwen2.5-coder", temperature=0)
# Stronger model loopguard escalates to.
gpt4 = ChatOpenAI(model="gpt-4o", temperature=0)

guard = Guard(
    escalation_model=gpt4,
    workhorse_model_name="qwen2.5-coder",
    on_escalate="auto",
    max_escalations_per_run=2,
)
handler = LangGraphHandler(guard)


class State(TypedDict):
    step: int
    messages: list[str]
    output: str


def generate_node(state: State) -> dict:
    step = state["step"]
    try:
        output = workhorse.invoke(state["messages"]).content
    except Exception as exc:  # record the failure for the repeated_error trigger
        return handler.on_step_end(step, state, None, error=exc)
    return handler.on_step_end(step, state, output)


def tests_node(state: State) -> dict:
    output = state["output"]
    results = run_tests(output)  # dict[str, bool]
    guard.record_test_results(results)
    return handler.on_step_end(state["step"] + 1, state, output)


# Build the graph.
builder = StateGraph(State)
builder.add_node("generate", generate_node)
builder.add_node("tests", tests_node)
builder.set_entry_point("generate")
builder.add_edge("generate", "tests")
builder.add_conditional_edges(
    "tests",
    lambda s: "generate" if not all(s.get("output", "")) else "__end__",
)
graph = builder.compile()

result = graph.invoke({"step": 0, "messages": [...], "output": ""})
```

Call `guard.reset()` before invoking the graph for an independent task so
trigger history from a previous run doesn't bleed in.

## Configuration tips

All of these are `GuardConfig` fields, passed as kwargs to `Guard(...)`.

| Field | Default | Notes |
| --- | --- | --- |
| `triggers` | all three built-ins, `max_retries=3` | Dict of `repeated_error`, `test_failure`, `schema_invalid` → `TriggerConfig`. Set `enabled=False` to disable one, or raise/lower `max_retries` (1–20). |
| `max_escalations_per_run` | `1` | Hard cap per guarded run; 1–10. Prevents unbounded cost. |
| `escalation_model` | `None` | Any LangChain `BaseChatModel` (`ChatOpenAI`, `ChatAnthropic`, `ChatOllama`, …). If `None`, the guard runs detection-only and returns the last output on a trigger (observability without escalation). |
| `workhorse_model_name` | `""` | Name of the cheap model being guarded. Surfaced in the escalation prompt and `EscalationEvent` for observability. |
| `on_escalate` | `"auto"` | `"auto"` escalates immediately; `"interrupt"` prompts via LangGraph's `interrupt()`. |
| `max_context_tokens` | `4000` | Token budget for the escalation context packager (500–32000). |
| `sanitize_context` | `True` | Wraps agent-produced content in delimiters to mitigate prompt injection. |
| `redact_patterns` / `redact_fields` | `[]` | Regex patterns / field names stripped from the escalation context before sending to the model. |
| `on_guard_error` | `"raise_original"` | Fail-open behaviour if loopguard itself errors. See the raw-Python guide for the three modes. |

For test-driven agents, feed results **before** calling `on_step_end()` so the
`test_failure` trigger sees them on the current step:

```python
guard.record_test_results({"test_parse": True, "test_eval": False})
return handler.on_step_end(step, state, output)
```
