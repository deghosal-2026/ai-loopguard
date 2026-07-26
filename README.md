# ai-loopguard

[![CI](https://github.com/deghosal-2026/ai-loopguard/actions/workflows/ci.yml/badge.svg)](https://github.com/deghosal-2026/ai-loopguard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/ai-loopguard)](https://pypi.org/project/ai-loopguard/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000)](https://github.com/astral-sh/ruff)
[![Type checked](https://img.shields.io/badge/mypy-strict-blue)](https://github.com/python/mypy)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13799/badge)](https://www.bestpractices.dev/projects/13799)

> Circuit breaker and escalation for LLM agent loops. Drop-in. Framework-agnostic.

## What it does

AI agents get stuck in loops. They change code, tests fail, they change something else, a different test fails, they revert. Tokens burn. Nothing improves.

ai-loopguard detects stuck patterns and escalates to a stronger model before the costs spiral.

## Quick start

```bash
pip install ai-loopguard
```

```python
from ai_loopguard import Guard

guard = Guard(
    escalation_model=gpt4_model,  # any model with .invoke(prompt)
    workhorse_model_name="qwen2.5-coder",
    triggers={
        "test_failure": {"max_retries": 3},
        "repeated_error": {"max_retries": 3},
        "schema_invalid": {"max_retries": 3},
    },
)

@guard.protect
def agent_step(state):
    output = cheap_model.generate(state)
    guard.record_test_results(run_tests(output))
    return output
```

If `agent_step` fails 3 times, ai-loopguard:
1. Packages the context (what was tried, what failed)
2. Escalates to the escalation model
3. Asks it to "break the loop"
4. Logs the escalation event with cost impact

Call `guard.reset()` between independent tasks to clear trigger history.

## Framework integrations

```bash
pip install ai-loopguard[langgraph]   # LangGraph callback handler
pip install ai-loopguard[crewai]      # CrewAI step wrapper
pip install ai-loopguard[all]         # All integrations (dev/evaluation)
```

### LangGraph

```python
from ai_loopguard import Guard
from ai_loopguard.integrations.langgraph import LangGraphHandler

guard = Guard(escalation_model=gpt4_model, workhorse_model_name="qwen")
handler = LangGraphHandler(guard)

# Use in a LangGraph node function
def my_node(state):
    output = model.generate(state)
    return handler.on_step_end(state["step"], state, output)
```

### CrewAI

```python
from ai_loopguard import Guard
from ai_loopguard.integrations.crewai import CrewAIWrapper

guard = Guard(escalation_model=gpt4_model, workhorse_model_name="qwen")
wrapper = CrewAIWrapper(guard)
crew = wrapper.wrap(crew)
result = crew.kickoff()
```

## Triggers

| Trigger | What it detects |
| --- | --- |
| `test_failure` | Tests pass then fail then pass on the same test |
| `repeated_error` | Same exception or error message N times in a row |
| `schema_invalid` | Output fails schema validation N times |
| `custom` | Your callback returns True |

## Metrics

ai-loopguard tracks the metrics that actually matter:

| Metric | What it tells you |
| --- | --- |
| Escalation rate | Are you paying for a cheap attempt + expensive call on every task? |
| Cost per completed task | Real cost including retries, failed loops, and escalations |
| Routing vs failover | Intentional escalation vs availability failure — logged separately |

If 80% of tasks escalate, you haven't built a router. You've built a system that pays for a cheap attempt before every expensive call.

## CLI

```bash
# Analyze escalation logs
loopguard analyze logs.jsonl --summary

# Filter by trigger type
loopguard analyze logs.jsonl --trigger repeated_error

# Filter by date
loopguard analyze logs.jsonl --since 2026-07-01
```

## Why not just use a cheaper model?

Cheaper models are the right default — until they get stuck. The cost isn't the per-call price. It's the per-completed-task price. A $0.001 call that loops 10 times costs more than a $0.05 call that solves it once. ai-loopguard tracks the real number.

## How is this different from LangGraph or CrewAI?

Those are frameworks — they define how you build agents. ai-loopguard is a library — it wraps whatever you've already built. LangGraph doesn't detect stuck loops. CrewAI doesn't escalate. ai-loopguard does both, and it drops into either.

## How is this different from cost trackers?

Cost trackers tell you what happened after the fact. ai-loopguard stops the bleeding in real time. It's the difference between a dashboard and a circuit breaker.

## License

MIT

## Resources

- **Issues:** [github.com/deghosal-2026/ai-loopguard/issues](https://github.com/deghosal-2026/ai-loopguard/issues) — bug reports and feature requests
- **Security:** [SECURITY.md](SECURITY.md) — report vulnerabilities privately
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md) — coding standards and PR process
