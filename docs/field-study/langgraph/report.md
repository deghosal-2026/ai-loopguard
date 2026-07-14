# Field Study Report

> Generated: 2026-07-11 18:13:59 UTC
> Escalation model: DeepSeek V4 Flash (simulated)
> Workhorse model: Qwen 2.5 Coder 7B (simulated)
---

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
| Task success rate | 100% (5/5) | >70% | ✅ |
| Time reduction | 50% (306ms → 154ms) | >40% | ✅ |
| Latency delta | -152ms | flat or better | ✅ |
| Escalation success rate | 100% (5/5) | >70% | ✅ |
| Avg LOC added | 4.0 LOC/task | <10 | ✅ |
