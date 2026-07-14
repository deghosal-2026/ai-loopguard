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

---

## Summary

| Metric | Value | Target | Pass |
|--------|-------|--------|------|
| Task success rate | 100% (5/5) | >70% | ✅ |
| Time reduction | 51% (308ms → 152ms) | >40% | ✅ |
| Latency delta | -156ms | flat or better | ✅ |
| Escalation success rate | 100% (5/5) | >70% | ✅ |
| Avg LOC added | 4.0 LOC/task | <10 | ✅ |
