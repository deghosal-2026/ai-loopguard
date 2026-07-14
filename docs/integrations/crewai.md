# CrewAI integration

`CrewAIWrapper` connects loopguard's detection and escalation pipeline into a
[CrewAI](https://github.com/crewAIInc/crewAI) crew. Call `wrap(crew)` to
instrument every agent in the crew; each agent is then monitored
independently with its own step history, so different triggers can fire for
different agents simultaneously.

## Prerequisites

```bash
pip install ai-loopguard[crewai]
```

This installs `crewai>=0.50.0,<0.60.0` in addition to `ai-loopguard`.

## The wrapper

```python
class CrewAIWrapper:
    def __init__(self, guard: Guard) -> None: ...
```

`CrewAIWrapper.__init__` takes a single, already-configured `Guard` instance.
The guard's `GuardConfig` controls trigger thresholds, the escalation model,
and the `on_escalate` mode. The wrapper itself holds a per-agent state map
(`agent role -> GuardState`); the guard's shared state is not used for
step history, so multiple agents don't bleed into one another.

```python
from ai_loopguard import Guard
from ai_loopguard.integrations.crewai import CrewAIWrapper

guard = Guard(escalation_model=gpt4, workhorse_model_name="qwen")
wrapper = CrewAIWrapper(guard)
```

## wrap()

```python
def wrap(self, crew: Any) -> Any
```

Iterates over `crew.agents` and replaces each agent's `execute_task` method
with a wrapped version that records each step, checks triggers, and escalates
if needed. The crew is mutated **in place** (CrewAI convention); the same
crew instance is returned for fluent chaining:

```python
crew = wrapper.wrap(crew)
result = crew.kickoff()
# or:
result = wrapper.wrap(crew).kickoff()
```

The wrapped step:

1. Lazily creates a `GuardState` for this agent on first call (states for
   agents that never execute are never allocated).
2. Calls the original `execute_task`, catching **all** exceptions — the
   `repeated_error` trigger needs to see any failure type, not just a
   narrow allowlist.
3. Consumes pending metadata from `guard.record_test_results()` /
   `guard.record_schema_valid()` and transfers it to the per-agent
   `StepRecord` (clearing the guard's pending fields so they don't leak to
   the next agent's step).
4. Records the step on the **per-agent** state, not the guard's shared state.
5. Runs all enabled triggers against the per-agent state. The detector is
   shared (it holds only config), but it evaluates only this agent's history.
6. If a trigger fires, temporarily swaps the `EscalationManager`'s state
   reference to the per-agent state for context packaging / cap / fail-open,
   then restores it in a `finally` block. Escalation proceeds normally;
   the escalation model's output replaces the step's output.
7. If no trigger fires, re-raises the original error if there was one, else
   returns the successful output.

## Per-agent state tracking

Each agent is keyed by its `role` string (unique within a crew). This is the
mechanism for independent agent monitoring: without per-agent isolation, steps
from different agents would accumulate in a single history and triggers would
fire incorrectly (e.g., a `repeated_error` trigger would see agent A's
failure, then agent B's different failure, and fire on a false pattern).

A single shared `Guard` + per-agent states is transparent to the user — you
configure one `Guard` and the wrapper handles isolation. (You could also use a
separate `Guard` per agent; the wrapper is less boilerplate.)

## Full working example

```python
from langchain_openai import ChatOpenAI

from crewai import Agent, Crew, Task

from ai_loopguard import Guard
from ai_loopguard.integrations.crewai import CrewAIWrapper

workhorse = ChatOpenAI(model="qwen2.5-coder", temperature=0)
gpt4 = ChatOpenAI(model="gpt-4o", temperature=0)

guard = Guard(
    escalation_model=gpt4,
    workhorse_model_name="qwen2.5-coder",
    on_escalate="auto",
    max_escalations_per_run=2,
)
wrapper = CrewAIWrapper(guard)

researcher = Agent(
    role="Researcher",
    goal="Find sources for the topic",
    backstory="A meticulous research analyst.",
    llm=workhorse,
)
writer = Agent(
    role="Writer",
    goal="Draft the article from the research",
    backstory="A concise technical writer.",
    llm=workhorse,
)

research_task = Task(
    description="Find 3 authoritative sources on {topic}.",
    expected_output="A list of 3 sources with URLs.",
    agent=researcher,
)
write_task = Task(
    description="Write a 500-word article using the research.",
    expected_output="A 500-word markdown article.",
    agent=writer,
)

crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task])
crew = wrapper.wrap(crew)

result = crew.kickoff(inputs={"topic": "vector databases"})
```

Each agent gets its own step history. If the Researcher loops on a retrieval
error three times, the `repeated_error` trigger fires for the Researcher
only and the escalation output replaces that agent's step — the Writer's
history is untouched.

Call `guard.reset()` before `kickoff()`-ing an unrelated crew so the
per-agent states don't carry history across runs.

## Experimental status

CrewAI ships frequent breaking changes — method signatures, the
`execute_task` contract, and the agent identification scheme have all
shifted between minor versions. The wrapper targets `crewai>=0.50.0,<0.60.0`
and pins to that range in `pyproject.toml`, but the integration API may
evolve as CrewAI does. Treat it as experimental: pin your CrewAI version
and re-test on upgrade.

## Thread safety

The state-swapping in `_wrap_agent_step` (temporarily replacing
`EscalationManager._state` with the per-agent state, then restoring it) is
**not** thread-safe for concurrent agent execution. CrewAI v0.50+ runs agents
sequentially by default, so this is fine for the supported version range.

If you run agents concurrently (or use a future CrewAI version that
parallelizes by default), do **not** share a single `CrewAIWrapper`. Instead,
create one `Guard` per agent and wrap each agent's `execute_task` with its own
guard — the shared-state swap is avoided entirely.
