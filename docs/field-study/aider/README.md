# Aider Field Study Setup

## Prerequisites

```bash
git clone https://github.com/Aider-AI/aider.git ../aider
cd ../aider
pip install -e ".[dev]"
```

## Running tasks

From the monorepo root:

```bash
# Run all baseline tasks
python docs/field-study/runner.py all baseline aider

# Run all guarded tasks
python docs/field-study/runner.py all guarded aider

# Compare results
python docs/field-study/runner.py compare aider

# Generate report
python docs/field-study/runner.py report aider
```

## Task descriptions

| ID | Description | Expected trigger |
|----|-------------|-----------------|
| AI-1 | Generate code that passes a given test | test_failure |
| AI-2 | Fix syntax error introduced by the agent | repeated_error |
| AI-3 | Extract structured data from markdown | schema_invalid |
| AI-4 | Multi-file edit with cascading failures | test_failure oscillation |
| AI-5 | Agent falls back to wrong approach repeatedly | repeated_error |
