# Field Study — ai-loopguard v0.1.0

> **Status:** Pending — run the field study to populate results
> **Plan:** `docs/field-study-plan.md`
> **Runner:** `python docs/field-study/runner.py <command> <repo>`
>
> Repos: [SWE-agent](swe-agent/README.md), [Aider](aider/README.md), [LangGraph](langgraph/README.md)

## Setup

1. Clone the 3 external repos (see per-repo READMEs)
2. Install dependencies
3. Run baseline + guarded tasks:

```bash
# Run everything
python docs/field-study/runner.py all swe-agent
python docs/field-study/runner.py all aider
python docs/field-study/runner.py all langgraph

# Compare and generate reports
python docs/field-study/runner.py compare swe-agent
python docs/field-study/runner.py compare aider
python docs/field-study/runner.py compare langgraph

# Generate full report
python docs/field-study/runner.py report
```

Reports are saved to `docs/field-study/<repo>/report.md` and `docs/field-study/report.md`.

## Results

<!-- Results will be populated after running the field study -->

### 1. SWE-agent

*Results pending*

### 2. Aider

*Results pending*

### 3. LangGraph

*Results pending*

## Summary

| Metric | Value | Target | Pass |
|--------|-------|--------|------|
| Task success rate | — | >70% | ⏳ |
| Time reduction | — | >40% | ⏳ |
| Latency delta | — | flat or better | ⏳ |
| Escalation success rate | — | >70% | ⏳ |
| Avg LOC added | — | <10 | ⏳ |

## Methodology

See [`docs/field-study-plan.md`](docs/field-study-plan.md) for full methodology.

Raw data: `docs/field-study/<repo>/baseline/` and `docs/field-study/<repo>/guarded/` (JSON per task).
Aggregate: `docs/field-study/<repo>/results.jsonl` (append-only log of every run).
