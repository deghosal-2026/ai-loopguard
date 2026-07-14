# Field Study Plan — S14

> **Status:** Draft — 2026-07-11
> **PRD ref:** §7.1 (Success criteria), §11.3 (Methodology)
> **SPEC ref:** §12.4 (Field study)
> **WBS ref:** S14 (Field Study)
> **Issues:** —
>
> **Goal:** Validate that loopguard detects stuck loops and escalation resolves them in real-world conditions across 3 external agent repos.

## 1. Success Criteria

| Metric | Target | How to measure |
|---|---|---|
| Escalation success rate | >70% | % of escalations where escalation model produces a successful output |
| Token reduction on stuck tasks | >40% | Total tokens consumed on stuck-loop tasks, guarded vs baseline |
| Median latency | Stays flat or improves | Wall-clock time per completed task, guarded vs baseline |
| Drop-in lines of code | <10 LOC | Lines added to instrument an existing agent with loopguard |

## 2. Repo Selection (OQ-10)

### 2.1 Candidates

| Repo | Agent loop | Test suite | Task types | Stars | Language |
|---|---|---|---|---|---|
| **SWE-agent** | Yes — agent modifies code, runs tests, iterates | Yes (pytest) | Software engineering bug fixes | ~14k | Python |
| **OpenDevin / CodeAct** | Yes — agent plans, codes, tests, repeats | Yes | SWE-bench tasks, coding | ~35k | Python |
| **Aider** | Yes — agent edits code, runs tests, fixes failures | Yes | Code generation, bug fixing | ~25k | Python |
| **LangGraph example repos** | Yes — agent loops via LangGraph nodes | Varies | Multi-step workflows | Various | Python |
| **CrewAI example repos** | Yes — multi-agent crews with tasks | Varies | Role-based automation | Various | Python |

### 2.2 Selection criteria

1. **Active agent loop** — the agent must iterate (code → test → fix → repeat), not single-shot
2. **Test suite** — must have a test runner so `test_failure` trigger can fire
3. **Diverse task types** — coding, data extraction, structured output — to exercise all 3 built-in triggers
4. **Open source** — MIT/Apache license, can fork and publish results
5. **Active maintenance** — not archived, recent commits

### 2.3 Recommended shortlist

| # | Repo | Stars | Rationale |
|---|---|---|---|
| 1 | **SWE-agent** | ~14k | Designed for test-failure cycles. Agent edits code → runs `pytest` → fixes failures → loops. Directly triggers `test_failure` and `repeated_error`. Most relevant to loopguard's core use case. |
| 2 | **Aider** | ~46k | Code generation with automatic test running. Supports multiple models, has a benchmark suite (exercises, swe-bench). Triggers `test_failure` (tests fail after edit) and `schema_invalid` (JSON parsing in structured output mode). |
| 3 | **LangGraph** | ~100k | Most popular agent framework. Demonstrates the `LangGraphHandler` integration. Triggers `repeated_error` (tool keeps failing) and `custom` (manual timeout detection). |

**Fallback:** If any of the above repos are unavailable, replace with a CrewAI multi-agent demo (triggers per-agent escalation).

## 3. Task Selection

### 3.1 15 tasks (5 per repo)

#### SWE-agent (5 tasks)

| # | Task | Expected trigger | Description |
|---|---|---|---|
| SWE-1 | Fix a function with a clear bug | `test_failure` | Agent edits function, runs pytest, one test fails → agent must fix |
| SWE-2 | Fix a function where the initial guess is wrong | `test_failure` → `repeated_error` | First fix attempt fails a different test, agent loops |
| SWE-3 | Add a missing import | `repeated_error` | Agent tries to use undefined function, same ImportError repeatedly |
| SWE-4 | Refactor with schema constraint | `schema_invalid` | Agent must return structured output (JSON) that matches a schema |
| SWE-5 | Fix a flaky test interaction | `test_failure` oscillation | Fixing test A breaks test B, fixing test B breaks test A |

#### Aider (5 tasks)

| # | Task | Expected trigger | Description |
|---|---|---|---|
| AI-1 | Generate code that passes a given test | `test_failure` | Agent writes code, runs test, test fails → fix loop |
| AI-2 | Fix a syntax error introduced by the agent itself | `repeated_error` | Agent generates bad syntax repeatedly |
| AI-3 | Extract structured data from markdown | `schema_invalid` | Agent must output valid JSON with specific fields |
| AI-4 | Multi-file edit with cascading test failures | `test_failure` oscillation | Fix in file A breaks file B's tests |
| AI-5 | Agent falls back to wrong approach repeatedly | `repeated_error` | Same logical error in 3 consecutive attempts |

#### LangGraph ReAct (5 tasks)

| # | Task | Expected trigger | Description |
|---|---|---|---|
| LG-1 | Tool returns error, agent retries same tool | `repeated_error` | A tool (e.g., weather API) returns 500, agent calls it again |
| LG-2 | Tool returns bad schema, agent retries | `schema_invalid` | A tool returns malformed JSON, agent can't parse it |
| LG-3 | Multi-step reasoning with a failing sub-step | `custom` (timeout) | A sub-task exceeds max iterations, guard escalates |
| LG-4 | Agent keeps calling the same failed tool | `repeated_error` → escalation | 3 consecutive tool failures, escalation model suggests alternative |
| LG-5 | Complex task that requires escalation | `test_failure` | Agent must produce code, test it, and escalate when stuck |

### 3.2 Task design principles

- Each task MUST have a **deterministic way to detect success or failure** (test pass/fail, valid JSON, correct output)
- Each task SHOULD exercise at least one of the 3 built-in triggers
- At least 3 tasks per repo SHOULD produce a stuck loop in the baseline (unguarded) run
- Tasks must be **reproducible** — same agent config, same model, same seed

## 4. Setup

### 4.1 Environment

| Component | Value |
|---|---|
| **Workhorse model** | `qwen2.5-coder:7b` (local, OMLX) — fast, cheap, occasionally wrong |
| **Escalation model** | `deepseek-v4-flash` (API) — stronger, slower, resolves stuck loops |
| **Hardware** | Apple M5, 34 GB RAM (same as benchmark environment) |
| **Python** | 3.14.5 |
| **loopguard version** | 0.1.0 |

### 4.2 Installation

```bash
git clone https://github.com/deghosal-2026/ai-loopguard.git
cd ai-loopguard
pip install -e ".[dev]"
```

### 4.3 Agent setup

Each repo needs:
1. Clone the target repo
2. Install its dependencies
3. Configure the agent to use `qwen2.5-coder:7b` as the workhorse model
4. Run baseline first (no loopguard), then guarded (with loopguard)

### 4.4 loopguard configuration for field study

```python
from ai_loopguard import Guard

guard = Guard(
    escalation_model=deepseek_v4_flash,
    workhorse_model_name="qwen2.5-coder",
    triggers={
        "test_failure": {"max_retries": 3},
        "repeated_error": {"max_retries": 3},
        "schema_invalid": {"max_retries": 3},
    },
    max_escalations_per_run=5,
    sanitize_context=True,
    redact_patterns=["sk-[a-zA-Z0-9]+", "AKIA[0-9A-Z]{16}"],
)

@guard.protect
def agent_step(state):
    output = workhorse_model.generate(state)
    guard.record_test_results(run_tests(output))
    return output
```

For LangGraph:
```python
from ai_loopguard.integrations.langgraph import LangGraphHandler

handler = LangGraphHandler(guard)

def my_node(state):
    output = model.generate(state)
    return handler.on_step_end(state["step"], state, output)
```

## 5. Baseline Run Procedure

For each task, run **without** loopguard:

1. Reset agent state (fresh environment, no prior context)
2. Run the agent on the task
3. Record:

```
task_id, repo, attempt, success (true/false), total_tokens, wall_clock_ms,
retries, error_type, error_message, final_output
```

4. Store raw data in `docs/field-study/<repo>/baseline/<task_id>.json`

## 6. Guarded Run Procedure

For the same task, run **with** loopguard:

1. Reset agent state
2. Instrument the agent step with `@guard.protect` or `LangGraphHandler`
3. Run the agent on the task
4. Record:

```
task_id, repo, attempt, success (true/false), total_tokens, wall_clock_ms,
retries, escalations, escalation_success_rate, cost_per_task_usd,
trigger_types_fired, escalation_model_called, loopguard_lines_of_code
```

5. Store raw data in `docs/field-study/<repo>/guarded/<task_id>.json`

## 7. Data Recording Format

### 7.1 Per-task raw data file

```json
{
  "task_id": "SWE-1",
  "repo": "swe-agent",
  "description": "Fix a function with a clear bug",
  "baseline": {
    "success": false,
    "total_tokens": 45000,
    "wall_clock_ms": 125000,
    "retries": 5,
    "error_type": "test_failure",
    "error_message": "test_parse_input failed on 3rd retry",
    "final_output": null
  },
  "guarded": {
    "success": true,
    "total_tokens": 28000,
    "wall_clock_ms": 95000,
    "retries": 3,
    "escalations": 1,
    "escalation_success": true,
    "cost_per_task_usd": 0.042,
    "trigger_types_fired": ["test_failure"],
    "escalation_model": "deepseek-v4-flash",
    "loopguard_loc": 4
  }
}
```

### 7.2 Aggregate results table

| Task | Baseline tokens | Guarded tokens | Token reduction | Baseline time | Guarded time | Time delta | Baseline success | Guarded success | Escalations | Esc success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

## 8. Analysis

### 8.1 Trigger coverage

For each task, verify which triggers fired and whether the escalation resolved the issue:

- `test_failure` — did the agent fix the test?
- `repeated_error` — did escalation suggest a different approach?
- `schema_invalid` — did escalation produce valid output?

### 8.2 Token reduction

For each stuck task (baseline failed), calculate:

```
token_reduction_pct = (baseline_tokens - guarded_tokens) / baseline_tokens * 100
```

If `baseline_tokens = 0` (task succeeded immediately without loopguard), exclude from token reduction calculation.

### 8.3 Latency impact

For each task:

```
latency_delta_pct = (guarded_time_ms - baseline_time_ms) / baseline_time_ms * 100
```

Negative = guarded is faster. Positive = guarded adds overhead.

### 8.4 Escalation success rate

```
escalation_success_rate = successful_escalations / total_escalations * 100
```

An escalation is "successful" if the escalation model's output resolves the agent's stuck state and the task completes successfully.

## 9. Documentation

All results go in `docs/field-study.md` with:

1. **Executive summary** — did loopguard meet the success criteria?
2. **Repos selected** — rationale for each
3. **Tasks** — description of each task and expected trigger
4. **Results table** — per-task comparison (baseline vs guarded)
5. **Aggregate metrics** — token reduction %, latency delta, escalation success rate
6. **Trigger analysis** — which triggers fired, which resolved
7. **Failures** — tasks where loopguard didn't help, with root cause analysis
8. **Methodology** — how to reproduce the study
9. **Drop-in cost** — lines of code added per repo

## 10. Implementation Order

1. Create `docs/field-study/` directory structure
2. Evaluate and confirm 3 repos (OQ-10 resolution)
3. Write per-repo setup scripts (`docs/field-study/<repo>/README.md`)
4. Run baseline for each of 15 tasks
5. Run guarded for each of 15 tasks
6. Aggregate results, compute metrics
7. Write `docs/field-study.md`
8. Update WBS S14 checkpoint
