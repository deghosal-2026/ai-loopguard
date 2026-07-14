# Field Study Report

> Generated: 2026-07-11 18:13:59 UTC
> Escalation model: DeepSeek V4 Flash (simulated)
> Workhorse model: Qwen 2.5 Coder 7B (simulated)
---

## Aider (~46k★)

| Task | Description | Base | Guard | Base ms | Guard ms | Δ ms | Trigger | Esc | Esc ✅ | LOC |
|------|-------------|------|-------|---------|---------|------|---------|-----|-------|-----|
| AI-1    | Generate code that passes a given test   | ❌ | ✅ | 62      | 30      | -32    | test_failure    | 1   | ✅   | 4   |
| AI-2    | Fix syntax error introduced by the agent | ❌ | ✅ | 61      | 30      | -31    | repeated_error  | 1   | ✅   | 4   |
| AI-3    | Extract structured data from markdown    | ❌ | ✅ | 62      | 31      | -31    | schema_invalid  | 1   | ✅   | 4   |
| AI-4    | Multi-file edit with cascading failures  | ❌ | ✅ | 62      | 31      | -31    | test_failure oscillation | 1   | ✅   | 4   |
| AI-5    | Agent falls back to wrong approach repea | ❌ | ✅ | 62      | 30      | -32    | repeated_error  | 1   | ✅   | 4   |
| **Total** | | **0/5** | **5/5** | **309** | **152** | **-157** | | **5** | **5** | **20** |

---

## Summary

| Metric | Value | Target | Pass |
|--------|-------|--------|------|
| Task success rate | 100% (5/5) | >70% | ✅ |
| Time reduction | 51% (309ms → 152ms) | >40% | ✅ |
| Latency delta | -157ms | flat or better | ✅ |
| Escalation success rate | 100% (5/5) | >70% | ✅ |
| Avg LOC added | 4.0 LOC/task | <10 | ✅ |
