# LangGraph Field Study Setup

## Prerequisites

```bash
git clone https://github.com/langchain-ai/langgraph.git ../langgraph
cd ../langgraph
pip install -e "."
pip install ai-loopguard[langgraph]
```

## Running tasks

From the monorepo root:

```bash
# Run all baseline tasks
python docs/field-study/runner.py all baseline langgraph

# Run all guarded tasks
python docs/field-study/runner.py all guarded langgraph

# Compare results
python docs/field-study/runner.py compare langgraph

# Generate report
python docs/field-study/runner.py report langgraph
```

## Task descriptions

| ID | Description | Expected trigger |
|----|-------------|-----------------|
| LG-1 | Tool returns error, agent retries same tool | repeated_error |
| LG-2 | Tool returns bad schema, agent retries | schema_invalid |
| LG-3 | Multi-step reasoning with failing sub-step | custom (timeout) |
| LG-4 | Agent keeps calling the same failed tool | repeated_error → escalation |
| LG-5 | Complex task requiring escalation | test_failure |
