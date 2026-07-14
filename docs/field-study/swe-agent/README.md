# SWE-agent Field Study Setup

## Prerequisites

```bash
git clone https://github.com/SWE-agent/SWE-agent.git ../SWE-agent
cd ../SWE-agent
pip install -e ".[dev]"
```

## Running tasks

From the monorepo root:

```bash
# Run all baseline tasks
python docs/field-study/runner.py all baseline swe-agent

# Run all guarded tasks
python docs/field-study/runner.py all guarded swe-agent

# Compare results
python docs/field-study/runner.py compare swe-agent

# Generate report
python docs/field-study/runner.py report swe-agent
```

## Task descriptions

| ID | Description | Expected trigger |
|----|-------------|-----------------|
| SWE-1 | Fix a function with a clear bug | test_failure |
| SWE-2 | Fix a function where first guess is wrong | test_failure + repeated_error |
| SWE-3 | Add a missing import | repeated_error |
| SWE-4 | Refactor with schema constraint | schema_invalid |
| SWE-5 | Fix flaky test interaction — oscillation | test_failure oscillation |
