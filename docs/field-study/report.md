# Field Study Report

> Generated: 2026-07-11 18:13:59 UTC
> Escalation model: DeepSeek V4 Flash (simulated)
> Workhorse model: Qwen 2.5 Coder 7B (simulated)
---

## SWE-agent (~14k★)

| Task | Description | Base | Guard | Base ms | Guard ms | Δ ms | Trigger | Esc | Esc ✅ | LOC |
|------|-------------|------|-------|---------|---------|------|---------|-----|-------|-----|
| SWE-1   | Fix a function with a clear bug          | ❌ | ✅ | 60      | 29      | -31    | test_failure    | 1   | ✅   | 4   |
| SWE-2   | Fix a function where first guess is wron | ❌ | ✅ | 62      | 31      | -31    | test_failure + repeated_error | 1   | ✅   | 4   |
| SWE-3   | Add a missing import                     | ❌ | ✅ | 62      | 31      | -31    | repeated_error  | 1   | ✅   | 4   |
| SWE-4   | Refactor with schema constraint          | ❌ | ✅ | 62      | 30      | -32    | schema_invalid  | 1   | ✅   | 4   |
| SWE-5   | Fix flaky test interaction — oscillation | ❌ | ✅ | 62      | 31      | -31    | test_failure oscillation | 1   | ✅   | 4   |
| **Total** | | **0/5** | **5/5** | **308** | **152** | **-156** | | **5** | **5** | **20** |

## Aider (~46k★)

| Task | Description | Base | Guard | Base ms | Guard ms | Δ ms | Trigger | Esc | Esc ✅ | LOC |
|------|-------------|------|-------|---------|---------|------|---------|-----|-------|-----|
| AI-1    | Generate code that passes a given test   | ❌ | ✅ | 62      | 30      | -32    | test_failure    | 1   | ✅   | 4   |
| AI-2    | Fix syntax error introduced by the agent | ❌ | ✅ | 61      | 30      | -31    | repeated_error  | 1   | ✅   | 4   |
| AI-3    | Extract structured data from markdown    | ❌ | ✅ | 62      | 31      | -31    | schema_invalid  | 1   | ✅   | 4   |
| AI-4    | Multi-file edit with cascading failures  | ❌ | ✅ | 62      | 31      | -31    | test_failure oscillation | 1   | ✅   | 4   |
| AI-5    | Agent falls back to wrong approach repea | ❌ | ✅ | 62      | 30      | -32    | repeated_error  | 1   | ✅   | 4   |
| **Total** | | **0/5** | **5/5** | **309** | **152** | **-157** | | **5** | **5** | **20** |

## LangGraph (~100k★)

| Task | Description | Base | Guard | Base ms | Guard ms | Δ ms | Trigger | Esc | Esc ✅ | LOC |
|------|-------------|------|-------|---------|---------|------|---------|-----|-------|-----|
| LG-1    | Tool returns error, agent retries same t | ❌ | ✅ | 62      | 31      | -31    | repeated_error  | 1   | ✅   | 4   |
| LG-2    | Tool returns bad schema, agent retries   | ❌ | ✅ | 61      | 30      | -31    | schema_invalid  | 1   | ✅   | 4   |
| LG-3    | Multi-step reasoning with failing sub-st | ❌ | ✅ | 60      | 31      | -29    | custom (timeout) | 1   | ✅   | 4   |
| LG-4    | Agent keeps calling the same failed tool | ❌ | ✅ | 61      | 31      | -30    | repeated_error → escalation | 1   | ✅   | 4   |
| LG-5    | Complex task requiring escalation        | ❌ | ✅ | 62      | 31      | -31    | test_failure    | 1   | ✅   | 4   |
| **Total** | | **0/5** | **5/5** | **306** | **154** | **-152** | | **5** | **5** | **20** |

---

## Summary

| Metric | Value | Target | Pass |
|--------|-------|--------|------|
| Task success rate | 100% (15/15) | >70% | ✅ |
| Time reduction | 50% (923ms → 458ms) | >40% | ✅ |
| Latency delta | -465ms | flat or better | ✅ |
| Escalation success rate | 100% (15/15) | >70% | ✅ |
| Avg LOC added | 4.0 LOC/task | <10 | ✅ |
