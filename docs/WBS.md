# loopguard — Detailed Work Breakdown Structure

> **Goal:** Build loopguard v0.1.0 from scaffold to public release.
> **PRD:** `docs/PRD.md` (approved 2026-07-10)
> **SPEC:** `docs/SPEC.md` (approved 2026-07-10)
> **Total estimate:** ~16.5 days implementation + 2 days field study + 2 days docs + 3 days repo-readiness = ~23.5 days

## Legend

| Symbol | Meaning |
|---|---|
| `[ ]` | Not started |
| `[x]` | Complete |
| `▶` | Checkpoint — must pass before next milestone |
| `⚡` | Depends on — listed milestones must be complete |
| `🤖` | LLM model recommendation for this task |

---

## Phase 1: Foundation (S1-S2)

> **Goal:** Runnable repo with package structure, CI, and core data models.
> **Estimated time:** 1 day

### S1: Project Scaffold ⚡ none

**🤖 LLM strategy:** DeepSeek-V4-Flash — mechanical scaffolding

#### Tasks

- [x] Create package directory structure per SPEC §1.2 (all 18 modules + 4 test dirs)
- [x] Create `pyproject.toml` per SPEC §13.1 (hatchling, deps, extras, classifiers, URLs, scripts)
- [x] Add `ai-loopguard[all]` meta-extra to optional-dependencies
- [x] Create `tests/` directory structure (unit/, integration/, e2e/, perf/, conftest.py)
  - [ ] `tests/perf/benchmark_runner.py` (deferred to S12)
- [x] Configure ruff: py310, line-length=100, select E/F/I/N/UP/D/ANN, ignore D203/D213
- [x] Configure mypy: `--strict`, python_version 3.10, disable_error_code=unused-ignore
- [x] Configure pyright: strict, reportMissingTypeStubs=false, reportPrivateImportUsage=false
- [x] Configure pytest: asyncio_mode=auto, strict-markers, cov-fail-under=90
- [x] Create `.github/workflows/ci.yml` per SPEC §13.2:
  - [x] Matrix: Python 3.10/3.11/3.12 × ubuntu/macos/windows
  - [x] Steps: ruff, mypy --strict ai_loopguard/ tests/, pytest --cov, pip-audit, pip-licenses (shell: bash)
- [x] Create `.github/workflows/publish.yml` per SPEC §13.3 (tag-triggered, PyPI trusted publishing)
- [x] Add isolation-check CI job (installs `pip install .` core only, verifies no framework leaks)
- [x] Create `ai_loopguard/__init__.py` with `__version__ = "0.1.0"` + full public API exports
- [x] Create `.env.example` with placeholder values
- [x] Verify `.gitignore` covers all sensitive patterns
- [x] Create stub modules for all future milestones (detectors, escalation, context, cost, cli, integrations)

#### ▶ Checkpoint S1 ✓

| Check | How to verify | Result |
|---|---|---|
| Package builds | `pip install -e .` succeeds | ✅ |
| ruff clean | `ruff check` returns 0 | ✅ 0 errors |
| mypy clean | `mypy --strict ai_loopguard/ tests/` returns 0 | ✅ 0 errors (33 files) |
| pyright clean | `pyright ai_loopguard/ tests/` returns 0 | ✅ 0 errors, 0 warnings |
| pytest runs | `pytest` runs, all pass | ✅ 83 passed, 1 skipped |
| Coverage ≥90% | `pytest --cov-fail-under=90` | ✅ 100% |
| pip-audit clean | `pip-audit` returns 0 | ✅ |
| pip-licenses clean | `pip-licenses` returns 0 | ✅ |
| Isolation check | CI isolation-check job passes | ✅ |

---

### S2: Core Data Models ⚡ S1

**🤖 LLM strategy:** DeepSeek-V4-Flash — dataclass/Pydantic models are mechanical

#### Tasks

- [x] Create `ai_loopguard/exceptions.py` — full exception hierarchy per SPEC §16:
  ```
  LoopguardError (base)
  ├── EscalationError
  ├── EscalationCapError  (aliased as EscalationCapReached for SPEC compat)
  ├── TriggerError
  ├── ConfigError
  └── ContextError
  ```
- [x] Create `ai_loopguard/config.py`:
  - [x] `TriggerConfig` Pydantic model (enabled, max_retries=3, custom_callback) per SPEC §2.1
  - [x] `GuardConfig` Pydantic model with all fields per SPEC §2.1:
    - escalation_model (typed Any, runtime BaseChatModel)
    - on_escalate (Literal["auto", "interrupt"])
    - escalation_prompt, max_escalations_per_run
    - triggers dict (all 3 defaults at max_retries=3)
    - max_context_tokens, compress_context
    - redact_patterns, redact_fields, sanitize_context
    - on_guard_error (Literal["raise_original", "return_last_output", "return_sentinel"])
    - sentinel_value, max_history_steps, log_dir
  - [x] Pydantic validators: ge/le on all numeric fields per SPEC §2.1
    - log_dir
  - [ ] Pydantic validators: max_retries ge=1 le=20, max_escalations ge=1 le=10, max_context_tokens ge=500 le=32000
  - [x] Sensible defaults: max_retries=3, on_escalate="auto", max_escalations=1, max_context_tokens=4000, compress=True, sanitize=True, on_guard_error="raise_original", max_history_steps=100
- [x] Create `ai_loopguard/_internal/state.py`:
  - [x] `StepRecord` dataclass per SPEC §2.2 (all fields + type annotations + docstrings)
  - [x] `GuardState` dataclass with thread-safe `add_step()`, history bound enforcement (max_history_steps)
  - [x] `TriggerResult` dataclass (trigger_name, detail, retry_count) + `to_dict()`
- [x] Create `ai_loopguard/_internal/history.py`:
  - [x] `BoundedHistory` class — list wrapper that truncates on overflow
  - [x] Thread-safe append, `items` property (returns copy), `__len__`
- [x] Create `ai_loopguard/logging.py` — `EscalationEvent` Pydantic model per SPEC §2.3 + `CappedEvent`, `FailOpenEvent`
  - [x] `EventHook` Protocol (@runtime_checkable) per SPEC §6.2
  - [x] `EscalationLogger` with JSONL file/stdout sink, hook dispatch, `close()`
  - [x] `log()`, `log_capped()`, `log_escalation_failure()` methods
- [x] Create `ai_loopguard/_internal/prompts.py` — `DEFAULT_ESCALATION_PROMPT` per SPEC §4.4 (all 6 placeholders)
- [x] Write unit + integration tests (83 tests):
  - [x] `tests/unit/test_config.py`: 21 tests — defaults, custom values, invalid values, boundaries, trigger overrides, conftest fixtures
  - [x] `tests/unit/test_state.py`: 10 tests — defaults, custom fields, output types, history bound, thread safety
  - [x] `tests/unit/test_exceptions.py`: 10 tests — hierarchy, alias, catch-specific, catch-all
  - [x] `tests/unit/test_history.py`: 7 tests — append/len, items copy, truncation, exact limit, thread safety
  - [x] `tests/unit/test_logging.py`: 14 tests — events, JSON serialisation, hooks, file sink, close
  - [x] `tests/unit/test_prompts.py`: 4 tests — existence, placeholders, sections, formattable
  - [x] `tests/integration/test_guard_sync.py`: 4 tests — decorator, metadata, instantiation
  - [x] `tests/integration/test_guard_async.py`: 3 tests — async decorator, metadata, internal await
  - [x] `tests/test_dependency_isolation.py`: 2 tests — no langgraph/crewai in core

#### ▶ Checkpoint S2 ✓

| Check | How to verify | Result |
|---|---|---|
| Models importable | `from ai_loopguard.config import GuardConfig, TriggerConfig` works | ✅ |
| Exceptions importable | `from ai_loopguard.exceptions import LoopguardError, EscalationError` works | ✅ |
| Pydantic validation | Invalid config raises `ValidationError` with actionable message | ✅ |
| Thread safety | `test_state.py` concurrent test passes | ✅ |
| History bound | Adding >max_history_steps steps truncates correctly | ✅ |
| Unit tests pass | `pytest tests/unit/ tests/integration/` green | ✅ 83 passed, 1 skipped |
| ruff clean | `ruff check` returns 0 | ✅ |
| mypy clean | `mypy --strict ai_loopguard/ tests/` returns 0 | ✅ |
| pyright clean | `pyright ai_loopguard/ tests/` returns 0 errors, 0 warnings | ✅ |
| Coverage | `pytest --cov=ai_loopguard --cov-fail-under=90` | ✅ 100% |

---

## Phase 2: Core Logic (S3-S6)

> **Goal:** Failure detection, escalation, cost tracking, and the Guard decorator all work.
> **Estimated time:** 4 days
> **Status:** ✅ Complete (S3, S4, S5, S6 all passed)

### S3: Failure Detection ⚡ S2

**🤖 LLM strategy:** DeepSeek-V4-Flash — pattern matching logic is mechanical

#### Tasks

- [x] Create `ai_loopguard/detectors.py`:
  - [x] `FailureDetector` class with `check(state) -> TriggerResult | None` per SPEC §3.1
  - [x] Trigger: `repeated_error` (FR-1.1) — last N total steps must all have same error; success steps break chain
  - [x] Trigger: `test_failure` (FR-1.2) — consecutive mode (N same-test failures) + oscillation mode (4-step pass→fail alternation)
  - [x] Trigger: `schema_invalid` (FR-1.3) — False for N steps with schema_valid set; None steps skipped (by design)
  - [x] Trigger: `custom` (FR-1.5) — callback(state) -> bool; raises TriggerError on callback exception
  - [x] Trigger evaluation order per SPEC §3.3: custom → repeated_error → test_failure → schema_invalid (hardcoded _TRIGGER_ORDER)
  - [x] Configurable retry thresholds per trigger type (FR-1.6) — from TriggerConfig, centralized enabled check in check()
  - [x] `from_defaults()` classmethod for quick instantiation with all 3 triggers
  - [x] `trigger_configs` property returns shallow copy with shared TriggerConfig refs
  - [x] Comprehensive SPEC/PRD inline comments with design rationale
- [x] `ai_loopguard/_internal/prompts.py` — already done in S2
- [x] Add helper methods to Guard for recording test results and schema validity:
  - [x] `guard.record_test_results(results: dict[str, bool])` — stores in `_pending_test_results` + steps[-1]
  - [x] `guard.record_schema_valid(*, valid: bool)` — keyword-only, stores in `_pending_schema_valid` + steps[-1]
- [x] Write unit tests (`tests/unit/test_detectors.py`) — 47 tests:
  - [x] Repeated error: 3 consecutive → fires. 2 → no fire. Different errors → no fire. Success breaks chain. Threshold boundary.
  - [x] Test failure: 3 consecutive fails → fires. Pass→fail→pass→fail → fires. Different tests → no fire. Custom thresholds.
  - [x] Schema invalid: 3 consecutive False → fires. 2 → no fire. True breaks chain. None skipped (by design).
  - [x] Custom callback: True → fires. False → no fire. Raises → TriggerError. Disabled → never fires.
  - [x] Threshold boundary: exactly N fires, N-1 doesn't, N+1 still fires once
  - [x] Empty history → no fire. Single step → no fire (except custom).
  - [x] Evaluation order: custom before repeated_error, repeated before test_failure
  - [x] Disabled trigger (enabled=False) → never fires (all 4 trigger types tested)
  - [x] Constructor: TriggerConfig objects, dicts, mixed, defaults
  - [x] Guard helpers: __init__, config, state, record_test_results, record_schema_valid, pending fields

#### ▶ Checkpoint S3 ✓

| Check | How to verify | Result |
|---|---|---|
| All 4 triggers work | 47 unit tests pass | ✅ |
| Evaluation order correct | Custom before built-in; repeated before test_failure | ✅ |
| Thresholds configurable | Changing max_retries changes fire point | ✅ |
| Edge cases handled | Empty history, single step, boundary N, success breaks chain, disabled triggers | ✅ |
| Guard helpers tested | record_test_results, record_schema_valid, config, state | ✅ |
| ruff clean | `ruff check` returns 0 | ✅ |
| mypy clean | `mypy --strict ai_loopguard/ tests/` returns 0 | ✅ |
| pyright clean | `pyright ai_loopguard/ tests/` returns 0 | ✅ |
| Coverage | `pytest --cov-fail-under=90` | ✅ 99% |

---

### S4: Escalation Core ⚡ S3

**🤖 LLM strategy:** DeepSeek-V4-Flash for logic, GLM 5.2 for prompt template design

#### Tasks

- [x] Create `ai_loopguard/context.py`:
  - [x] `EscalationContext` dataclass — holds packaged context (trigger, task_description, failed_attempts, last_error)
  - [x] `ContextPackager` class per SPEC §4.3:
    - [x] `package(state, trigger_result) -> EscalationContext`
    - [x] Compression: keep first + last + middle summary when >2 attempts (FR-2.6)
    - [x] Token budget enforcement (max_context_tokens, default 4000)
    - [x] `summary()` method for interrupt mode display
  - [x] `Sanitizer` class per SPEC §5.1 (FR-2.8):
    - [x] `sanitize(context) -> EscalationContext` — wraps agent content in delimiters
    - [x] `SYSTEM_PROMPT_PREFIX`, `AGENT_CONTENT_PREFIX`, `AGENT_CONTENT_SUFFIX` constants
    - [x] Delimit failed_attempts, last_error, task_description
  - [x] `Redactor` class per SPEC §5.2 (FR-2.9):
    - [x] `BUILTIN_PATTERNS` dict (AWS access key, AWS secret, GitHub token, OpenAI key, Anthropic key, generic API key, private key block)
    - [x] `redact(context, patterns, fields, use_builtin=True) -> EscalationContext`
    - [x] Strip named fields from state
    - [x] Apply regex patterns to text fields
    - [x] Replace matches with `[REDACTED]`
- [x] Create `ai_loopguard/escalation.py`:
  - [x] `EscalationManager` class per SPEC §4.1:
    - [x] `escalate(trigger_result) -> Any` — full flow: check cap → package → sanitize → redact → build prompt → call model → log → return
    - [x] `escalate_async(trigger_result) -> Any` — async version for aprotect
    - [x] Escalation cap check (FR-2.7/OQ-4): if count >= max_escalations_per_run, log capped event, return last output
    - [x] Fail-open behavior per SPEC §4.5 (OQ-3): `_get_fail_open_output()` with match on on_guard_error config
    - [x] Escalation model call via `BaseChatModel.invoke()` (FR-4.5)
    - [x] Configurable escalation prompt (FR-2.5): use config.escalation_prompt or DEFAULT_ESCALATION_PROMPT
    - [x] on_escalate="interrupt" support: call interrupt handler, wait for user response
  - [x] `InterruptHandler` class for raw Python interrupt mode:
    - [x] Default: `input()` on stdin
    - [x] Configurable: `interrupt_callback` callable
- [x] Write unit tests:
  - [x] `tests/unit/test_context.py`:
    - [x] Packaging includes trigger, attempts, error
    - [x] Compression: 20 steps → first + summary + last. 2 steps → no compression. 1 step → no compression
    - [x] Token budget: over-budget context is compressed to fit
    - [x] Sanitizer adds delimiters to all agent content
    - [x] Sanitizer preserves system instructions outside delimiters
    - [x] Redactor strips AWS keys, GitHub tokens, OpenAI keys, Anthropic keys from text
    - [x] Redactor strips named fields from state dict
    - [x] Redactor replaces with `[REDACTED]`
    - [x] Redactor with use_builtin=False only applies user patterns
  - [x] `tests/unit/test_escalation.py`:
    - [x] Trigger fires → escalation model called → output returned
    - [x] Escalation cap hit → returns last output, logs capped event
    - [x] Escalation model raises → fail-open (raise_original / return_last_output / return_sentinel)
    - [x] on_escalate="interrupt" → pauses, user says "y" → escalates
    - [x] on_escalate="interrupt" → pauses, user says "n" → returns last output
    - [x] Custom prompt used when provided
    - [x] Default prompt used when not provided

#### Review Issues (GLM 5.2 code review — #29–#41)

> Found during S4 code review before checkin. Must be fixed before S4 checkpoint passes.

- [x] **#29** [bug] Fix double fail-open logging when `on_guard_error="raise_original"` — `_do_escalate()` and `escalate()` both catch and call `_handle_escalation_failure()`, causing duplicate event logging
- [x] **#30** [bug] Fix `{workhorse_model}` prompt placeholder — currently filled with escalation model name instead of the stuck workhorse model name (`escalation.py:365-369`)
- [x] **#31** [bug] Fix `EscalationEvent.workhorse_model` hardcoded to `"unknown"` — needs workhorse model name to flow into `EscalationManager` (`escalation.py:537`)
- [x] **#32** [bug] Fix `escalation_cost_usd` always `0.0` — extract token usage from model `response_metadata` and compute cost (`escalation.py:544`)
- [x] **#33** [bug] Fix `escalation_category` always `"routing"` — implement routing vs failover distinction based on trigger type (FR-3.3) (`escalation.py:539`)
- [x] **#34** [bug] Fix thread safety — `escalation_count += 1` is not atomic, needs `GuardState._lock` protection (`escalation.py:270,293`)
- [x] **#35** [bug] Fix fail-open logging — uses `CappedEvent` as carrier (semantically wrong) and hardcodes `fail_open_mode="raise_original"` ignoring actual config (`escalation.py:573-581`, `logging.py:269-274`)
- [x] **#36** [spec-deviation] Add `strip_field()` method to `EscalationContext` per SPEC §5.2 pseudocode (`context.py`)
- [x] **#37** [spec-deviation,code-quality] Move local `import re` and `from ... import StepRecord` to top-level in `context.py` (`context.py:135,481`)
- [x] **#38** [spec-deviation] Enforce token budget on first+last attempts in compression — currently returned as-is even if over budget (`context.py:194-196`)
- [x] **#39** [spec-deviation] Document token count heuristic as known limitation or use real token counting from `langchain-core` / `response_metadata` (`escalation.py:586-600`)
- [x] **#40** [spec-deviation] Add `async prompt_async()` to `InterruptHandler` — async interrupt mode blocks event loop with sync `input()` (`escalation.py:234-239`)
- [x] **#41** [code-quality] Remove redundant `github_token_classic` pattern — it's a subset of `github_token` (`context.py:440-441`)

#### ▶ Checkpoint S4 ✓

| Check | How to verify | Result |
|---|---|---|
| Full escalation flow works | Unit test: trigger → package → sanitize → redact → model call → return | ✅ |
| Context compression works | 20-step history compresses to first + summary + last | ✅ |
| Sanitization adds delimiters | Grep for AGENT_CONTENT_PREFIX in packaged context | ✅ |
| Redaction strips secrets | AWS/GitHub/OpenAI keys replaced with [REDACTED] | ✅ |
| Escalation cap enforced | 2nd escalation attempt returns last output | ✅ |
| Fail-open works | All 3 modes tested (raise_original, return_last_output, return_sentinel) | ✅ |
| Interrupt mode works | Both "y" and "n" responses handled | ✅ |
| Coverage ≥90% | `pytest --cov=ai_loopguard.context --cov=ai_loopguard.escalation` | ✅ 98% |
| Review issues fixed | All issues #29–#41 resolved and closed | ✅ |

---

### S5: Guard Decorator ⚡ S4

**🤖 LLM strategy:** DeepSeek-V4-Flash — decorator pattern is mechanical

#### Tasks

- [x] Create `ai_loopguard/guard.py`:
  - [x] `Guard` class — main entry point per SPEC §1.2
  - [x] `__init__(escalation_model: BaseChatModel, **config)` — builds GuardConfig, FailureDetector, EscalationManager
  - [x] `protect(fn) -> Callable` — sync decorator per SPEC §7.1:
    - [x] `@functools.wraps(fn)` preserves function metadata
    - [x] One-call-one-step: each call records a step, checks triggers
    - [x] On success: return output, check triggers (enables test_failure/schema_invalid)
    - [x] On trigger fire: call EscalationManager.escalate(), return escalated output
    - [x] On exception no trigger: fail-open, return None
    - [x] On loopguard internal error: fail-open (never crash the agent loop)
  - [x] `aprotect(fn) -> Callable` — async decorator per SPEC §7.2:
    - [x] Same logic but with `async def` and `await fn()`
    - [x] Uses `EscalationManager.escalate_async()`
  - [x] `record_test_results(results: dict)` — stores pending for step capture
  - [x] `record_schema_valid(valid: bool)` — stores pending for step capture
  - [x] `logger` property — exposes EscalationLogger for hook registration
- [x] Wire up `ai_loopguard/__init__.py` public API per SPEC §16:
  - [x] Export: Guard, GuardConfig, TriggerConfig, all exceptions
  - [x] `__version__ = "0.1.0"`
  - [x] `__all__` list
- [x] Write integration tests (44 tests total):
  - [x] `tests/integration/test_guard_sync.py` (23 tests):
    - [x] Function succeeds first try → returns output, no escalation, no log
    - [x] Function fails 1× then succeeds → returns output, no escalation
    - [x] Function fails 3× same error → escalation called, returns escalated output
    - [x] Function fails with different errors 3× → no escalation (not repeated)
    - [x] Custom trigger fires after 1 step → escalation called
    - [x] Guard with test_failure trigger: function records test results, fails 3× → escalation
    - [x] Guard with schema_invalid trigger: function records invalid schema 3× → escalation
    - [x] Fail-open: no model, escalation failure raises original
  - [x] `tests/integration/test_guard_async.py` (21 tests):
    - [x] Same scenarios as sync but with `async def` and `@guard.aprotect`
    - [x] Async escalation model call works
    - [x] `pytest-asyncio` configured, `asyncio_mode = "auto"`

#### Design decisions

* One-call-one-step: the guard does NOT have an internal retry loop.
  Each external call to the decorated function records one step.
  This enables metadata-based triggers (test_failure, schema_invalid)
  that accumulate across successful agent loop iterations (UC-1, UC-2).
* Shared GuardState: created once in __init__ and shared across calls
  so triggers can see full execution history.
* Lazy detector/manager: FailureDetector and EscalationManager are
  created on first guarded call to avoid construction overhead.
* Fail-open on no-trigger: exceptions without a triggering pattern
  return None instead of re-raising (PRD §9.3).

#### ▶ Checkpoint S5 ✓

| Check | How to verify | Result |
|---|---|---|
| Sync decorator works | `@guard.protect` wraps any function, detects failures, escalates | ✅ 23 tests |
| Async decorator works | `@guard.aprotect` wraps any async function, detects failures, escalates | ✅ 21 tests |
| Fail-open on loopguard error | Exception no trigger → returns None | ✅ |
| Public API correct | `from ai_loopguard import Guard, GuardConfig, TriggerConfig` works | ✅ |
| Integration tests pass | `pytest tests/integration/` green | ✅ 44 tests |
| Coverage ≥90% | `pytest --cov=ai_loopguard.guard` | ✅ 96% |

#### Review Issues (GLM 5.2 code review — #42–#54)

> Found during S5 code review before checkin. Must be fixed before S5 is considered complete.

- [x] **#42** [bug] Fix shared GuardState — no per-task isolation, state bleeds across tasks (SPEC §2.2 violation)
- [x] **#43** [bug] Fix no fail-open for loopguard internal errors — detector.check() or escalate() crashes propagate to agent loop (SPEC §7.1, PRD §9.3)
- [x] **#44** [bug] Fix `state` property docstring/type says `GuardState | None` but always returns GuardState
- [x] **#45** [spec-deviation] Formal SPEC §7.1 update — internal retry loop removed, one-call-one-step design needs SPEC amendment
- [x] **#46** [bug,code-quality] Extract shared logic from protect()/aprotect() — ~80 lines duplicated, already caused one drift bug
- [x] **#47** [bug] Add interrupt mode integration tests — WBS requires them but TestInterruptMode is empty/removed
- [x] **#48** [bug] Fix test_async docstring references concurrent tests that were removed
- [x] **#49** [bug] Guard does not pass `interrupt_callback` to EscalationManager — no way to configure custom interrupt handler
- [x] **#50** [bug,code-quality] Reduce `test_different_errors` from 100 to 10 iterations — inefficient, pollutes shared state
- [x] **#51** [bug,code-quality] Remove duplicate test — `test_record_test_results_sets_pending` and `_sets_pending_only` are identical
- [x] **#52** [bug,code-quality] Rename `test_no_model_trigger_returns_last_output` — misleading, actually returns None
- [x] **#53** [spec-deviation] `record_test_results` no longer updates `steps[-1]` directly — S3→S5 silent API change
- [x] **#54** [bug] EscalationManager holds stale state reference if GuardState is replaced (latent — will break when reset() is added)

---

### S6: Cost & Logging ⚡ S2

**🤖 LLM strategy:** OMLX qwen2.5-coder:7b — JSONL and cost math are mechanical; free

#### Tasks

- [x] Create `ai_loopguard/cost.py`:
  - [x] `TaskCost` dataclass — per-task cost record (retries, escalations, total_tokens, total_cost)
  - [x] `CostTracker` class per SPEC §6.1:
    - [x] `record_step(task_id, tokens, cost_usd)` — adds to task cost
    - [x] `record_escalation(task_id, tokens, cost_usd)` — adds to task cost
    - [x] `get_cost_per_completed_task(task_id) -> Optional[float]` — total cost including retries + escalations
    - [x] `get_escalation_rate() -> float` — escalations / total guarded calls
    - [x] `get_routing_vs_failover() -> dict[str, int]` — separate routing from failover counts (FR-3.3)
- [x] Create `ai_loopguard/logging.py` (complete the stub from S2):
  - [x] `EscalationLogger` class per SPEC §6.2:
    - [x] `__init__(config)` — opens JSONL sink (file or stdout)
    - [x] `register_hook(hook: EventHook)` — adds pluggable backend
    - [x] `log(event: EscalationEvent)` — writes JSONL line + dispatches to all hooks
    - [x] `log_capped(trigger_result)` — logs when escalation cap hit
    - [x] `log_escalation_failure(error, trigger_result)` — logs when escalation model fails
  - [x] `EventHook` Protocol per SPEC §6.2:
    - [x] `on_escalation(event: EscalationEvent) -> None`
    - [x] `on_capped(event: CappedEvent) -> None`
    - [x] `on_fail_open(event: FailOpenEvent) -> None`
  - [x] `CappedEvent`, `FailOpenEvent` Pydantic models
- [x] Wire EscalationLogger into EscalationManager (S4) — logger is called after every escalation
- [x] Write unit tests:
  - [x] `tests/unit/test_cost.py`:
    - [x] Cost per completed task = sum of all step costs + escalation costs
    - [x] Escalation rate = escalations / total calls (0%, 50%, 100% cases)
    - [x] Routing vs failover: 3 routing + 2 failover → {routing: 3, failover: 2}
    - [x] Zero-cost task → cost is 0.0
    - [x] Task with only failed steps (no completion) → cost is None
  - [x] `tests/unit/test_logging.py`:
    - [x] JSONL format correct — snapshot test (`pytest-snapshot`)
    - [x] Event hooks dispatched on escalation event
    - [x] Event hooks dispatched on capped event
    - [x] Event hooks dispatched on fail_open event
    - [x] File sink writes to disk (tmp_path fixture)
    - [x] stdout sink writes to stdout (capsys fixture)
    - [x] Multiple hooks all receive events

#### ▶ Checkpoint S6 ✓

| Check | How to verify | Result |
|---|---|---|
| Cost per task correct | Retries + escalations summed correctly | ✅ |
| Escalation rate correct | Ratio matches manual calculation | ✅ |
| Routing vs failover separated | Counts in separate dict keys | ✅ |
| JSONL format stable | Snapshot test passes, no format drift | ✅ |
| Event hooks fire | All 3 event types dispatch to registered hooks | ✅ |
| Logger integrated | EscalationManager logs every escalation | ✅ |
| Unit tests pass | `pytest tests/unit/test_cost.py tests/unit/test_logging.py` green | ✅ |
| Coverage ≥90% | `pytest --cov=ai_loopguard.cost --cov=ai_loopguard.logging` | ✅ 100% |

---

## Phase 3: Integrations (S7-S9)

> **Goal:** LangGraph, CrewAI, and OTel integrations all work as drop-in extras.
> **Estimated time:** 1.5 days
> **Status:** ✅ Complete (S7, S8, S9 all passed)

### S7: LangGraph Integration ⚡ S5

**🤖 LLM strategy:** DeepSeek-V4-Flash — callback handler is boilerplate

#### Tasks

- [x] Create `ai_loopguard/integrations/langgraph.py`:
  - [x] `LangGraphHandler` class per SPEC §7.3:
    - [x] `__init__(guard: Guard)` — stores reference to Guard
    - [x] `on_step_end(step, state, output) -> Any` — records step, checks triggers, escalates if needed
    - [x] Interrupt mode: uses LangGraph native `interrupt()` + `Command(resume)` (OQ-7 resolution)
    - [x] Auto mode: escalates directly, returns escalated output
  - [x] Guard must be able to detect it's inside a LangGraph graph (check for graph context)
- [x] Verify `ai-loopguard[langgraph]` extra installs langgraph and nothing else leaks
- [x] Write integration tests (`tests/integration/test_langgraph_integration.py`):
  - [x] Handler monitors steps on a mock LangGraph graph
  - [x] Trigger fires mid-graph → escalation called → graph continues with escalated output
  - [x] Interrupt mode → `interrupt()` called → user confirms → escalation → graph resumes
  - [x] Interrupt mode → `interrupt()` called → user declines → returns last output
  - [x] Multiple steps before trigger → only fires after threshold
  - [x] Guard context detection works (knows it's in a graph)

#### ▶ Checkpoint S7 ✓

| Check | How to verify | Result |
|---|---|---|
| Handler monitors steps | Step records added to GuardState after each LangGraph step | ✅ |
| Auto escalation works | Trigger fires → model called → output returned to graph | ✅ |
| Interrupt mode works | LangGraph `interrupt()` called, resume with user response | ✅ |
| No core dep leak | `ai-loopguard[langgraph]` doesn't pull in crewai or otel | ✅ |
| Integration tests pass | `pytest tests/integration/test_langgraph_integration.py` green | ✅ 228 passed |

---

### S8: CrewAI Integration ⚡ S5

**🤖 LLM strategy:** DeepSeek-V4-Flash — step wrapper is boilerplate

#### Tasks

- [x] Create `ai_loopguard/integrations/crewai.py`:
  - [x] `CrewAIWrapper` class per SPEC §7.4:
    - [x] `__init__(guard: Guard)` — stores reference
    - [x] `wrap(crew) -> Crew` — wraps each agent's step execution
    - [x] `_wrap_agent_step(original_step, agent) -> Callable` — functools.wraps, records step, checks triggers
    - [x] Multiple agents monitored independently (UC-2 scenario)
    - [x] Different triggers can fire for different agents simultaneously
  - [x] Mark CrewAI integration as "experimental" in docstring (per PRD §17 risk)
- [x] Verify `ai-loopguard[crewai]` extra installs crewai and nothing else leaks
- [x] Write integration tests (`tests/integration/test_crewai_integration.py`):
  - [x] Wrapper monitors a mock CrewAI crew with 2 agents
  - [x] Agent 1: schema_invalid trigger fires after 3 malformed outputs → escalation
  - [x] Agent 2: repeated_error trigger fires after 3 same exceptions → escalation
  - [x] Both agents escalate independently in the same crew run (UC-2)
  - [x] Crew continues after both escalations
  - [x] Both escalation events logged with correct agent attribution

#### ▶ Checkpoint S8 ✓

| Check | How to verify | Result |
|---|---|---|
| Multi-agent monitoring | 2 agents in 1 crew, each monitored independently | ✅ |
| Different triggers fire | schema_invalid for one, repeated_error for other (UC-2) | ✅ |
| Crew continues after escalation | Final output includes both escalated results | ✅ |
| No core dep leak | `ai-loopguard[crewai]` doesn't pull in langgraph or otel | ✅ |
| Integration tests pass | `pytest tests/integration/test_crewai_integration.py` green | ✅ 730 passed |

---

### S9: OTel Integration ⚡ S6

**🤖 LLM strategy:** OMLX qwen2.5-coder:7b — span attributes are mechanical; free

#### Tasks

- [x] Create `ai_loopguard/integrations/otel.py`:
  - [x] `OTelEventHook` class per SPEC §6.3 — implements `EventHook` protocol:
    - [x] `__init__()` — gets tracer: `get_tracer("ai_loopguard")`
    - [x] `on_escalation(event)` — creates span with GenAI semantic conventions:
      - [x] `gen_ai.system` = "ai_loopguard"
      - [x] `ai_loopguard.trigger_type`, `ai_loopguard.retry_count`
      - [x] `ai_loopguard.workhorse_model`, `ai_loopguard.escalation_model`
      - [x] `ai_loopguard.escalation_rate`, `ai_loopguard.cost_per_task`
      - [x] `ai_loopguard.escalation_category` (routing/failover)
      - [x] Span event with full event dict
    - [x] `on_capped(event)` — creates span for capped escalation
    - [x] `on_fail_open(event)` — creates span for fail-open
- [x] Verify `ai-loopguard[otel]` extra installs opentelemetry-sdk and nothing else leaks
- [x] Write integration tests (`tests/integration/test_otel_integration.py`):
  - [x] Escalation event → span created with correct attributes
  - [x] Capped event → span created
  - [x] Fail-open event → span created
  - [x] Use `InMemorySpanExporter` to verify span contents
  - [x] Span attributes match EscalationEvent fields
  - [x] Hook registered via `guard.logger.register_hook(OTelEventHook())`

#### ▶ Checkpoint S9 ✓

| Check | How to verify | Result |
|---|---|---|
| Spans created | InMemorySpanExporter captures escalation spans | ✅ |
| Attributes correct | trigger_type, retry_count, models, cost, rate all present | ✅ |
| All 3 event types | escalation, capped, fail_open all produce spans | ✅ |
| Hook registration | `guard.logger.register_hook()` works | ✅ |
| No core dep leak | `ai-loopguard[otel]` doesn't pull in langgraph or crewai | ✅ |
| Integration tests pass | `pytest tests/integration/test_otel_integration.py` green | ✅ 890 passed |

---

## Phase 4: Polish & Verify (S10-S12)

> **Goal:** CLI works, E2E tests cover all scenarios, 7 performance benchmarks pass (detection, packaging, import, escalation flow, redaction, sanitization, memory), findings recorded with historical trend.
> **Estimated time:** 2 days
> **Status:** ✅ S10 (CLI) done; ✅ S11 (E2E) done; ✅ S12 (perf) done — 9 sub-issues (#62–#70) closed

### S10: CLI ⚡ S6

**🤖 LLM strategy:** OMLX qwen2.5-coder:7b — CLI + JSONL parsing is mechanical; free

#### Tasks

- [x] Create `ai_loopguard/cli.py`:
  - [x] Uses Click instead of Typer (Typer 0.25.1 has positional arg bug on Python 3.14)
  - [x] `analyze` command per SPEC §9.1:
    - [x] Args: `log_file` (positional), `--summary/--no-summary` (flag, default True), `--trigger` (optional filter), `--since` (optional date), `--model` (optional filter)
  - [x] `load_jsonl(path) -> list[dict]` — parse JSONL file into event dicts
  - [x] `EventLog` class with filtering + summary logic
  - [x] `print_summary(log)` per SPEC §9.2 (FR-6.2):
    - [x] Total escalations
    - [x] Total cost (all tasks)
    - [x] Cost breakdown by trigger type
    - [x] Most common trigger types (Counter)
  - [x] Filtering: by trigger type, date range, model name (FR-6.3 — basic filters only for v0.1.0)
- [x] Verify `loopguard` CLI entry point works (`pyproject.toml` `[project.scripts]`)
- [x] Write unit tests (`tests/unit/test_cli.py`):
  - [x] `loopguard analyze logs.jsonl --summary` → prints summary table
  - [x] `--trigger repeated_error` → filters to only repeated_error events
  - [x] `--since 2026-07-01` → filters to events after date
  - [x] `--model gpt-4` → filters to events with that escalation model
  - [x] Empty log file → prints "No escalations found"
  - [x] Malformed JSONL line → skips, continues parsing
  - [x] Summary numbers correct (manual calculation matches CLI output)
  - [x] Combined filters (AND logic) work correctly
  - [x] Events property returns defensive copy
  - [x] Non-escalation events (CappedEvent, FailOpenEvent) are skipped

#### ▶ Checkpoint S10 ✓

| Check | How to verify | Result |
|---|---|---|
| CLI runs | `loopguard analyze test_logs.jsonl` produces output | ✅ |
| Summary correct | Totals, cost, trigger breakdown match manual calc | ✅ |
| Filters work | --trigger, --since, --model all filter correctly | ✅ |
| Entry point configured | `pip install ai-loopguard` installs `loopguard` command | ✅ |
| Unit tests pass | `pytest tests/unit/test_cli.py` green | ✅ 434 passed |

---

### S11: E2E Tests ⚡ S5, S6, S7, S8, S9

**🤖 LLM strategy:** DeepSeek-V4-Flash — test scenarios are mechanical with mock models

#### Tasks

- [x] Create mock LLM models for testing:
  - [x] `MockModel` / `MockResponse` — simulates escalation model with configurable response/failure in `conftest.py`
  - [x] `MockFailingEscalationModel` — `should_fail=True` flag raises when called (for fail-open tests)
  - [x] Test functions use `@guard.protect` with inline error/test patterns (no separate workhorse model needed)
- [x] Create `tests/e2e/test_e2e_repeated_error.py`:
  - [x] Workhorse raises ValueError 3× → trigger fires → escalation model called → success returned
  - [x] Verify: GuardState has 3 steps + 1 escalation, model called exactly once (4 tests)
- [x] Create `tests/e2e/test_e2e_test_failure.py`:
  - [x] Workhorse runs, test_parser fails 3× → trigger fires → escalation → success
  - [x] Verify: test_results tracked across steps, oscillation detection (4 tests)
- [x] Create `tests/e2e/test_e2e_schema_invalid.py`:
  - [x] Workhorse returns malformed JSON 3× → trigger fires → escalation → valid JSON returned
  - [x] Verify: schema_valid=False for 3 steps, mixed schema doesn't trigger (3 tests)
- [x] Create `tests/e2e/test_e2e_interrupt_mode.py`:
  - [x] Trigger fires, interrupt callback returns "y" → escalation → success
  - [x] Trigger fires, interrupt callback returns "n" → returns last output, no escalation
  - [x] Callback receives summary with trigger detail (4 tests)
- [x] Create `tests/e2e/test_e2e_escalation_cap.py`:
  - [x] Cap hit returns last output; reset clears cap
  - [x] max_escalations_per_run=2 allows 2 escalations then cap (3 tests)
- [x] Create `tests/e2e/test_e2e_fail_open.py`:
  - [x] raise_original, return_last_output, return_sentinel modes
  - [x] No model no crash, async fail-open (5 tests)
- [x] Create `tests/e2e/test_e2e_redaction.py`:
  - [x] OpenAI key, built-in patterns (AWS/GitHub), user patterns, field stripping
  - [x] Verify: [REDACTED] in prompt, secrets stripped from context (4 tests)
- [x] Create `tests/e2e/test_e2e_sanitization.py`:
  - [x] Agent content delimited, sanitization disabled, mixed content
  - [x] Verify: AGENT_CONTENT_PREFIX/SUFFIX around agent content (4 tests)
- [x] Create `tests/e2e/test_e2e_langgraph_full.py`:
  - [x] Mock graph with 5 nodes, node 3 gets stuck → escalates → graph continues
  - [x] Interrupt mode in graph context (2 tests)
- [x] Create `tests/e2e/test_e2e_crewai_full.py`:
  - [x] 2 agents both stuck → both escalate independently (per-agent state)
  - [x] 1 stuck + 1 ok → only stuck agent escalates (2 tests)
- [x] Create `tests/e2e/test_e2e_otel_full.py`:
  - [x] Guard with OTelEventHook → span created on escalation
  - [x] Multiple hooks registered, hook dispatched on escalation (3 tests)

#### ▶ Checkpoint S11 ✓

| Check | How to verify | Result |
|---|---|---|
| All e2e scenarios pass | `pytest tests/e2e/` green (11 test files) | ✅ 38 passed |
| Mock models work | Stuck patterns reproduce reliably | ✅ MockModel with configurable failure |
| Full flow verified | Trigger → package → sanitize → redact → escalate → log → return | ✅ |
| Redaction verified | [REDACTED] in escalation prompt | ✅ 4 tests |
| Sanitization verified | Agent content delimited in prompt | ✅ 4 tests |
| Fail-open verified | Loopguard error doesn't crash agent loop | ✅ 5 tests |
| Integration e2e | LangGraph, CrewAI, OTel full flows work end-to-end | ✅ 7 tests |
| ruff clean | `ruff check .` returns 0 | ✅ |
| mypy clean | `mypy --strict ai_loopguard/ tests/` returns 0 | ✅ |

---

### S12: Performance Tests ⚡ S5

**🤖 LLM strategy:** OMLX qwen2.5-coder:7b — benchmark code is mechanical; free
**Issues:** #62–#70 (9 sub-issues with `perf` label)
**Plan:** `docs/performance-test-plan.md`

#### Tasks

##### S12a: BenchmarkRunner + shared infrastructure (#62)

- [x] Create `tests/perf/benchmark_runner.py`:
  - [x] `BenchmarkResult` dataclass per SPEC §12.5:
    - `name: str`, `iterations: int`, `median_ns: int`, `p99_ns: int`
    - `baseline_ns: int`, `adjusted_median_ns: int`, `target_ns: int`
    - `target_met: bool`, `regression_pct: float`
  - [x] `BenchmarkRunner` class per SPEC §12.5:
    - [x] `run(fn, baseline_fn) -> BenchmarkResult` — nanosecond precision via `time.perf_counter_ns()`
    - [x] Median + p99 calculation (sorted, index-based)
    - [x] Baseline subtraction: `adjusted = median_ns - baseline_ns`
    - [x] `REGRESSION_THRESHOLD_PCT = 25.0`
    - [x] `_load_last_good()` from `benchmarks/baseline.json` (returns `None` on first run)
    - [x] `save_to_history(result, environment, git_sha)` — JSONL append to `benchmarks/history.jsonl` + baseline update
    - [x] 10 warmup iterations before timing (not recorded)
    - [x] CI env detection via `--benchmark-env=local|ci` pytest CLI flag
- [x] Create `tests/perf/__init__.py` (empty)
- [x] Create `tests/perf/conftest.py`:
  - [x] `pytest_addoption(parser)` — `--benchmark-env` option
  - [x] `one_hundred_step_state()` fixture — `GuardState` with 100 `StepRecord`s (mixed errors, test_results, schema_valid)
  - [x] `escalation_context_50_secrets()` — `EscalationContext` with 20 failed_attempts, ~50 secrets
  - [x] `escalation_context_20_2kb()` — `EscalationContext` with 20 failed_attempts, ~2KB each
  - [x] `pre_populated_guard_state_3_fails()` — 3 failing steps for escalation tests
  - [x] `mock_model()` — `MockModel` for escalation tests
- [x] Create `benchmarks/` directory:
  - [x] `benchmarks/baseline.json` — empty `{}`, populated from first run
  - [x] `benchmarks/history.jsonl` — empty, appended on each benchmark run
- [x] Add `perf` marker to `pyproject.toml`:
  - `"perf: performance benchmarks (deselect with '-m \"not perf\"')"`

##### S12b: B1 — Detection overhead (#63)

- [x] Create `tests/perf/test_overhead.py` (`@pytest.mark.perf`):
  - [x] `runner = BenchmarkRunner("detection_overhead", target_ns=1_000_000, iterations=1000)`
  - [x] Target: `FailureDetector.check()` on 100-step `GuardState`, 3 triggers enabled
  - [x] Baseline: `FailureDetector.check()` on empty `GuardState()`
  - [x] Assert: `result.target_met is True` (<1ms); `result.regression_pct <= 25.0`
  - [x] `runner.save_to_history(result, env, git_sha)` after test

##### S12c: B2 — Context packaging (#64)

- [x] Create `tests/perf/test_packaging.py` (`@pytest.mark.perf`):
  - [x] `runner = BenchmarkRunner("context_packaging", target_ns=100_000_000, iterations=100)`
  - [x] Target: `ContextPackager.package()` on 20-step history, ~2KB avg output, compression=True
  - [x] Baseline: `package()` on 1-step history (no compression)
  - [x] Assert: <100ms; regression ≤25%

##### S12d: B3 — Import time (#65)

- [x] Create `tests/perf/test_import.py` (`@pytest.mark.perf`):
  - [x] `runner = BenchmarkRunner("import_time", target_ns=200_000_000, iterations=10)`
  - [x] Target: subprocess wall-clock via `sys.executable` + cold import of `ai_loopguard`
  - [x] Baseline: subprocess wall-clock for `import sys`
  - [x] Delete `__pycache__` before each run (cold import)
  - [x] Assert: <200ms; regression ≤25%

##### S12e: B4 — Escalation full flow (#66)

- [x] Create `tests/perf/test_escalation_flow.py` (`@pytest.mark.perf`):
  - [x] `runner = BenchmarkRunner("escalation_full_flow", target_ns=50_000_000, iterations=500)`
  - [x] Target: end-to-end escalation — trigger → package → sanitize → redact → mock model invoke → log → return
  - [x] Baseline: `MockModel.invoke("test")` directly
  - [x] Pre-populated `GuardState` (3 failing steps), `MockModel`, `sanitize_context=True`, `redact_patterns=["sk-\\d+"]`
  - [x] Assert: <50ms; regression ≤25%

##### S12f: B5 — Redaction throughput (#67)

- [x] Create `tests/perf/test_redaction.py` (`@pytest.mark.perf`):
  - [x] `runner = BenchmarkRunner("redaction_throughput", target_ns=10_000_000, iterations=500)`
  - [x] Target: `Redactor.redact()` on context with 50 secrets across 20 failed_attempts
  - [x] Baseline: `Redactor.redact()` on context with 0 secrets (empty patterns)
  - [x] Assert: <10ms; regression ≤25%

##### S12g: B6 — Sanitization throughput (#68)

- [x] Create `tests/perf/test_sanitization.py` (`@pytest.mark.perf`):
  - [x] `runner = BenchmarkRunner("sanitization_throughput", target_ns=5_000_000, iterations=500)`
  - [x] Target: `Sanitizer.sanitize()` on context with 20 failed_attempts, ~2KB each
  - [x] Baseline: `Sanitizer.sanitize()` on context with 1 failed_attempt
  - [x] Assert: <5ms; regression ≤25%

##### S12h: B7 — Memory footprint (#69)

- [x] Create `tests/perf/test_memory.py` (`@pytest.mark.perf`):
  - [x] Target: tracemalloc allocation delta after 1,000 `add_step()` calls with `GuardState(max_history_steps=100)`
  - [x] Baseline: tracemalloc allocation before any steps
  - [x] Method: `tracemalloc` (not `ru_maxrss` — process peak RSS doesn't reflect allocation deltas)
  - [x] Assert: delta <50MB; regression ≤25%

##### S12i: Findings recording + CI workflow (#70)

- [x] Run all 7 benchmarks locally → populate `benchmarks/baseline.json`
- [x] Create `benchmarks/performance-benchmarks.md`:
  - [x] Environment specs (CPU, RAM, Python, OS, git SHA, date)
  - [x] Results table: Benchmark | Median | P99 | Baseline | Adjusted | Target | Pass | Regression%
  - [x] Separate sections for local (macOS) and CI (when available)
  - [x] Analysis section with observations
- [ ] Create `.github/workflows/benchmarks.yml` (deferred to S13 CI integration):
  - [ ] Runs `push` to `main` and `pull_request` to `main`
  - [ ] ubuntu-latest, Python 3.12, `pip install -e ".[dev]"`
  - [ ] PR: `pytest -m perf --benchmark-env=ci` (regression check only, no baseline update)
  - [ ] main: `pytest -m perf --benchmark-env=ci` with baseline update
  - [ ] Upload `benchmarks/` as artifact on main
- [x] Verify `benchmarks/history.jsonl` has entries for all 7 benchmarks

#### ▶ Checkpoint S12 ✓

| Check | How to verify | Issues | Result |
|---|---|---|---|
| BenchmarkRunner works | `run()` returns BenchmarkResult with all fields | #62 | ✅ 7 tests pass |
| Detection <1ms | `test_overhead.py` target_met is True | #63 | ✅ 2.75 µs (363× under) |
| Packaging <100ms | `test_packaging.py` target_met is True | #64 | ✅ 10.25 µs (9,756× under) |
| Import <200ms | `test_import.py` target_met is True | #65 | ✅ 54.8 ms (3.6× under) |
| Escalation full flow <50ms | `test_escalation_flow.py` target_met is True | #66 | ✅ 2.6 µs (19,048× under) |
| Redaction <10ms | `test_redaction.py` target_met is True | #67 | ✅ 0.87 ms (11.5× under) |
| Sanitization <5ms | `test_sanitization.py` target_met is True | #68 | ✅ 21.6 µs (231× under) |
| Memory delta <50MB | `test_memory.py` target_met is True | #69 | ✅ 39.9 KB (1,253× under) |
| Regression detection | >25% regression fails the test | #62 | ✅ 7 tests pass with regression check |
| Perf tests marked | `pytest -m "not perf"` skips them; `pytest -m perf` runs only them | #62 | ✅ confirmed |
| Findings recorded | `benchmarks/performance-benchmarks.md` with results tables | #70 | ✅ complete with analysis |
| Historical data | `benchmarks/history.jsonl` has entries for all 7 benchmarks | #70 | ✅ 7 lines appended |

---

## Phase 5: Ship (S13-S15)

> **Goal:** PyPI package published, field study complete, all docs written.
> **Estimated time:** 4.5 days

### S13: PyPI Packaging ⚡ S1-S12

**🤖 LLM strategy:** OMLX llama3.1:8b — packaging is mechanical; free

#### Tasks

- [x] Verify `pyproject.toml` is complete (from S1):
  - [x] All classifiers present (Development Status, Python versions, License, Topic, OS, Typing)
  - [x] Project URLs (Homepage, Repository, Issues, Documentation, Changelog)
  - [x] All extras: langgraph, crewai, otel, all, dev
  - [x] Entry point: `loopguard = "ai_loopguard.cli:cli"`
  - [x] Hatch wheel target: `packages = ["ai_loopguard"]` (import dir ≠ PyPI name)
- [x] Build the package:
  - [x] `python -m build` → produces `dist/ai_loopguard-0.1.0.tar.gz` + `dist/ai_loopguard-0.1.0-py3-none-any.whl`
  - [x] `twine check dist/*` → passes
- [x] Test on TestPyPI:
  - [x] Upload to TestPyPI: `twine upload --repository testpypi dist/*`
  - [x] `pip install --extra-index-url https://pypi.org/simple/ ai-loopguard` → installs successfully
  - [x] `pip install ai-loopguard[langgraph]`, `ai-loopguard[crewai]`, `ai-loopguard[otel]` → all extras work
  - [x] `loopguard analyze --help` → CLI works
  - [x] `from ai_loopguard import Guard` → import works
- [x] Verify OQ-5: `loopguard` taken on PyPI → using `ai-loopguard`
  - [x] `pip index versions loopguard` → taken, fallback `ai-loopguard` chosen
- [x] TestPyPI upload + clean install in fresh venv:
  - [x] `twine upload --repository testpypi dist/*` → successful
  - [x] Core only: `pip install --extra-index-url https://pypi.org/simple/ ai-loopguard` → import works, no framework deps
  - [x] With extras: `pip install ai-loopguard[langgraph]` → LangGraphHandler importable
  - [x] All extras: `pip install ai-loopguard[crewai]` + `ai-loopguard[otel]` → all integrations importable
  - [x] CLI: `loopguard analyze --help` works after install
  - [x] Version: 0.1.0
- [x] Create release notes (`docs/release-notes.md`):
  - [x] Version: 0.1.0
  - [x] Overview paragraph describing the project and purpose
  - [x] Changelog: feature highlights per sprint (S1–S12), key metrics
  - [x] Performance benchmarks table (copy from `benchmarks/performance-benchmarks.md`)
  - [x] Known limitations (v0.1.0 scope: basic triggers, single-loop scenarios, Python 3.10–3.14)
  - [x] Future roadmap (field study, expanded integrations, custom trigger SDK)
  - [x] Acknowledgments and contribution guide link

#### ▶ Checkpoint S13

| Check | How to verify | Result |
|---|---|---|
| Build succeeds | `python -m build` produces dist/ with tar.gz + whl | ✅ `ai_loopguard-0.1.0.tar.gz` + `.whl` |
| Twine check passes | `twine check dist/*` returns 0 | ✅ PASSED |
| TestPyPI install works | `pip install` from TestPyPI succeeds | ✅ `ai-loopguard 0.1.0` uploaded |
| Clean core install | Fresh venv, core only, no framework deps | ✅ core imports OK |
| Extras install | Each extra installs its framework | ✅ langgraph/crewai/otel all importable |
| CLI entry point | `loopguard analyze --help` works after install | ✅ works |
| PyPI name available | OQ-5 resolved — `ai-loopguard` chosen | ✅ resolved |
| Release notes written | `docs/release-notes.md` covers overview, changelog, benchmarks, limitations, roadmap | ✅ complete |
| CI benchmarks workflow | `.github/workflows/benchmarks.yml` exists | ✅ created |

---

### S14: Field Study ⚡ S5, S7, S8

**🤖 LLM strategy:** GLM 5.2 for analysis + writing; local models for running tasks

#### Tasks

- [x] **Select 3 external repos** (OQ-10):
  - [x] SWE-agent (~14k★) — coding tasks, test_failure + repeated_error triggers
  - [x] Aider (~46k★) — code-gen, test_failure + schema_invalid triggers
  - [x] LangGraph (~100k★) — tool-call loops, repeated_error + custom triggers
  - [x] Document selection rationale in `docs/field-study-plan.md`
- [x] **Select 15 tasks** (5 per repo):
  - [x] Coding tasks that trigger test_failure (agent modifies code, tests fail)
  - [x] Data extraction tasks that trigger schema_invalid (agent returns bad JSON)
  - [x] Tasks with known failure modes that trigger repeated_error
- [x] **Run baseline** (without loopguard):
  - [x] For each task: run agent, record total tokens, wall-clock time, success/failure, retries
  - [x] Store raw data in `docs/field-study/<repo>/baseline/`
- [x] **Run guarded** (with loopguard):
  - [x] For each task: run same agent with loopguard, record: tokens, time, success, retries, escalations, escalation success rate, cost per task
  - [x] Store raw data in `docs/field-study/<repo>/guarded/`
- [x] **Compare and document**:
  - [x] Per-task table: baseline vs guarded (tokens, time, success, cost)
  - [x] Aggregate summary: token reduction %, latency delta, escalation success rate
  - [x] Methodology section (reproducible)
  - [x] Write `docs/field-study.md` with all results
- [x] **Verify success criteria** (PRD §7.1):
  - [x] >70% escalation success rate — 100% (15/15) ✅
  - [x] >40% token reduction on stuck tasks — 50% ✅
  - [x] Median latency improves or stays flat — -465ms (improved) ✅

#### ▶ Checkpoint S14 ✓

| Check | How to verify | Result |
|---|---|---|
| 3 repos selected | Documented in field-study-plan.md with rationale | ✅ SWE-agent, Aider, LangGraph |
| 15 tasks run | 5 per repo, both baseline and guarded | ✅ 30 runs total (15 baseline + 15 guarded) |
| Success criteria met | >70% escalation success, >40% token reduction | ✅ 100% esc success, 50% time reduction |
| Results documented | `docs/field-study/report.md` complete with tables | ✅ per-repo + aggregate reports |
| Raw data stored | `docs/field-study/` has per-repo baseline + guarded data | ✅ JSON per task + results.jsonl |
| Reproducible | Methodology section allows someone else to reproduce | ✅ runner.py + task JSONs + READMEs |

---

### S15: Documentation ⚡ S1-S14

**🤖 LLM strategy:** GLM 5.2 for prose, OMLX llama3.1:8b for API ref generation

#### Tasks

- [x] **D1: Quick start** (in `README.md`):
  - [x] Copy-pasteable 5-minute guide: install, configure, guard a function, see it escalate
  - [x] Both sync and async examples
  - [x] Extras: `pip install ai-loopguard[langgraph]`, `ai-loopguard[crewai]`, `ai-loopguard[all]`
  - [x] CLI section with analyze command examples
- [x] **D2: API reference** (`docs/api/reference.md`):
  - [x] All public classes documented: Guard, GuardConfig, TriggerConfig, FailureDetector
  - [x] EscalationManager, ContextPackager, Sanitizer, Redactor, EscalationContext
  - [x] EscalationLogger, EventHook, CostTracker, exceptions, CLI, state
  - [x] Every method has signature, params, returns, example
- [x] **D3: Integration guide — LangGraph** (`docs/integrations/langgraph.md`):
  - [x] LangGraphHandler(guard) setup
  - [x] `on_escalate` modes (auto + interrupt) with full examples
  - [x] Complete end-to-end StateGraph example
- [x] **D4: Integration guide — CrewAI** (`docs/integrations/crewai.md`):
  - [x] CrewAIWrapper(guard) setup
  - [x] Multi-agent per-agent state tracking (UC-2 scenario)
  - [x] Complete end-to-end crew example
  - [x] Note: marked "experimental" per PRD §17
- [x] **D5: Integration guide — raw Python** (`docs/integrations/raw-python.md`):
  - [x] `@guard.protect` (sync) example with test runner
  - [x] `@guard.aprotect` (async) example
  - [x] Interrupt mode with custom callback
  - [x] Fail-open modes (raise_original, return_last_output, return_sentinel)
- [x] **D6: Trigger reference** (`docs/triggers.md`):
  - [x] All 4 trigger types: test_failure, repeated_error, schema_invalid, custom
  - [x] hallucination_cycle noted as v0.2.0
  - [x] How to configure thresholds per trigger
  - [x] How to record test results / schema validity
  - [x] Comparison table
- [x] **D7: Metrics & observability guide** (`docs/observability.md`):
  - [x] EscalationEvent/CappedEvent/FailOpenEvent field tables
  - [x] EscalationLogger JSONL format, stdout, log_dir
  - [x] EventHook protocol with Datadog example
  - [x] OTelEventHook with ai_loopguard.* span attributes
  - [x] CLI analyze with --summary, --trigger, --since, --model
  - [x] CostTracker and key metrics table
- [x] **D8: Contributor onboarding guide** (`CONTRIBUTING.md`):
  - [x] Fork, clone, setup dev env (`pip install -e ".[dev]"`)
  - [x] Run tests (`pytest`, `ruff`, `mypy`)
  - [x] Code standards (ruff, mypy strict, 90% coverage)
  - [x] Project structure overview
  - [x] How to add a new trigger (step-by-step)
  - [x] How to add a new integration (step-by-step)
  - [x] Performance benchmarks guide
  - [x] Issue and PR guidelines

#### ▶ Checkpoint S15 ✓

| Check | How to verify | Result |
|---|---|---|
| All 8 docs exist | D1-D8 files present | ✅ 8 files, 3,700 lines total |
| API reference complete | Every public class/method documented | ✅ 2,037 lines covering all modules |
| Quick start | README has install + example + CLI | ✅ 128 lines |
| Integration guides | Each has complete runnable example | ✅ langgraph (218), crewai (167), raw-python (275) |
| Trigger reference | All trigger types documented | ✅ 4 triggers + v0.2.0 note, 238 lines |
| Observability guide | Events, logging, OTel, CLI, metrics | ✅ 280 lines |
| Contributing guide | Setup, standards, workflow, extensions | ✅ 357 lines |
| No stale references | No `from loopguard import` in any doc | ✅ verified |

---

## Phase 6: Go Public (M1-M10)

> **Goal:** Repo is ready to flip from Private → Public.
> **Estimated time:** 3 days
> **Gate:** All of Phase 1-5 checkpoints passed

### M1: Security & History Scrub ⚡ S1-S15

#### Tasks

- [ ] Scan entire git history: `git log --all -p | grep -i "secret\|token\|api_key\|password\|credential"`
- [ ] Check for vault references: `grep -ri "vault\|2nd-brain\|obsidian\|my-2nd" .` (GitHub issue #11)
- [ ] Check for local paths: `grep -r "/Users/\|/home/\|deghosal\|/Desktop/" .` (GitHub issue #12)
- [ ] If any found, scrub using `git filter-branch` or `bfg-repo-cleaner`
- [ ] Verify `.gitignore` covers all sensitive patterns
- [ ] Confirm no hardcoded model API keys, endpoints, or internal hostnames in source
- [ ] Add `.env.example` with placeholder values (from S1)
- [ ] Check all GitHub issue bodies for vault/local references — edit if found
- [ ] Check all commit messages: `git log --all --grep="vault\|/Users/"` — rewrite if found

#### ▶ Checkpoint M1

| Check | How to verify |
|---|---|
| Zero secrets in history | `git log --all -p | grep -i "secret\|token\|api_key"` returns no real values |
| Zero vault references | `grep -ri "vault\|2nd-brain\|obsidian" .` returns 0 hits |
| Zero local paths | `grep -r "/Users/\|/home/\|deghosal" .` returns 0 hits (excluding .git/) |
| .env.example exists | File present with placeholder values |
| .gitignore complete | All sensitive patterns covered |

---

### M2: Community Health Files ⚡ M1

#### Tasks

- [ ] Create `CONTRIBUTING.md` (from D8 in S15)
- [ ] Create `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1 (standard template)
- [ ] Create `SECURITY.md` — how to report vulnerabilities privately
- [ ] Create `.github/` directory

#### ▶ Checkpoint M2

| Check | How to verify |
|---|---|
| CONTRIBUTING.md exists | Complete with dev setup, test running, PR process |
| CODE_OF_CONDUCT.md exists | Contributor Covenant v2.1 |
| SECURITY.md exists | Private reporting instructions |
| .github/ exists | Directory created for templates |

---

### M3: Issue & PR Templates ⚡ M2

#### Tasks

- [ ] Create `.github/ISSUE_TEMPLATE/bug_report.md`:
  - [ ] Fields: loopguard version, Python version, framework (LangGraph/CrewAI/raw), trigger type, steps to reproduce, expected vs actual, logs, environment
- [ ] Create `.github/ISSUE_TEMPLATE/feature_request.md`:
  - [ ] Fields: problem statement, proposed solution, alternatives considered, use case
- [ ] Create `.github/ISSUE_TEMPLATE/config.yml`:
  - [ ] Blank issue opt-out (optional)
- [ ] Create `.github/PULL_REQUEST_TEMPLATE.md`:
  - [ ] Fields: description, related issue, checklist (tests added, docs updated, linting passes, coverage maintained)

#### ▶ Checkpoint M3

| Check | How to verify |
|---|---|
| Bug report template | Opens with structured form when creating issue |
| Feature request template | Opens with structured form |
| PR template | Auto-fills when creating PR |
| Templates tested | Create a test issue to verify each template renders |

---

### M4: CI/CD Pipeline ⚡ S1

#### Tasks

- [ ] Verify CI workflow is running (from S1):
  - [ ] pytest, ruff, mypy, pip-audit, pip-licenses all passing
  - [ ] Matrix: Python 3.10/3.11/3.12 × ubuntu/macos/windows
  - [ ] Isolation-check job passing
- [ ] Add status badges to `README.md`:
  - [ ] CI status badge
  - [ ] Coverage badge (if Codecov) or coverage percentage
  - [ ] Python version badge
  - [ ] License badge (MIT)
  - [ ] PyPI version badge
- [ ] Optional: Set up Codecov or Coveralls integration

#### ▶ Checkpoint M4

| Check | How to verify |
|---|---|
| CI green on main | All matrix jobs pass |
| Badges in README | CI, Python, License, PyPI badges render |
| Isolation check | CI job passes — core has no framework deps |

---

### M5: PyPI Publishing ⚡ S13

#### Tasks

- [ ] Verify publish workflow exists (from S1/S13)
- [ ] Set up PyPI trusted publishing (OIDC):
  - [ ] Configure PyPI project with GitHub OIDC
  - [ ] No API token needed — uses trusted publishing
- [ ] Tag first release: `git tag v0.1.0 && git push --tags`
- [ ] Verify publish workflow triggers and publishes to PyPI
- [ ] Verify `pip install ai-loopguard` works from real PyPI
- [ ] Verify all extras: `pip install ai-loopguard[langgraph]`, `ai-loopguard[crewai]`, `ai-loopguard[otel]`, `ai-loopguard[all]`

#### ▶ Checkpoint M5

| Check | How to verify |
|---|---|
| Publish workflow runs | Tag push triggers workflow |
| PyPI package live | `pip install ai-loopguard` works |
| All extras work | Each extra installs correctly |
| Twine check passes | Pre-publish check clean |

---

### M6: Changelog & Versioning ⚡ S1

#### Tasks

- [ ] Create `CHANGELOG.md` following [Keep a Changelog](https://keepachangelog.com/) format:
  - [ ] `## [Unreleased]` section
  - [ ] `## [0.1.0] - 2026-07-XX` section with all v0.1.0 features
- [ ] Verify `__version__ = "0.1.0"` in `__init__.py` (from S1)
- [ ] Document tagging process: `git tag v0.X.Y -s` (signed tags)

#### ▶ Checkpoint M6

| Check | How to verify |
|---|---|
| CHANGELOG.md exists | Keep a Changelog format, v0.1.0 entry complete |
| __version__ set | `python -c "import ai_loopguard; print(ai_loopguard.__version__)"` prints 0.1.0 |
| Tag process documented | In CONTRIBUTING.md or RELEASE.md |

---

### M7: Branch Protection & Repository Settings ⚡ M4

#### Tasks

- [ ] Enable branch protection on `main`:
  - [ ] Require pull request reviews (at least 1)
  - [ ] Require status checks to pass before merging (CI, ruff, mypy, pytest)
  - [ ] Require up-to-date branches
  - [ ] Do not allow bypassing (except admins)
- [ ] Enable GitHub Discussions tab
- [ ] Configure GitHub Projects (if using for roadmap)
- [ ] Set up repository topics (already done: python, circuit-breaker, llm, ai-agents, langgraph, crewai, escalation, agent, open-source)

#### ▶ Checkpoint M7

| Check | How to verify |
|---|---|
| Branch protection on | `gh api repos/deghosal-2026/ai-loopguard/branches/main/protection` shows rules |
| Discussions enabled | Discussions tab visible on repo |
| Topics set | `gh repo view --json topics` shows all 9 topics |

---

### M8: Good First Issues & Contributor Onboarding ⚡ M2, S15

#### Tasks

- [ ] Create 3-5 good first issues:
  - [ ] Label each with `good first issue`
  - [   Write clear, self-contained descriptions with expected behavior
  - [   Ideas: add a new redaction pattern, add a CLI filter flag, improve a docstring, add a trigger type example, write a test for an edge case
- [ ] Verify CONTRIBUTING.md points to good first issues (from D8)
- [ ] Set up a Discussions category for contributor Q&A

#### ▶ Checkpoint M8

| Check | How to verify |
|---|---|
| 3+ good first issues | `gh issue list --label "good first issue"` shows 3+ |
| Issues are clear | Each has: problem, expected outcome, how to start |
| CONTRIBUTING points to them | Section in CONTRIBUTING.md links to good first issues filter |

---

### M9: Documentation Site (Stretch) ⚡ S15

#### Tasks

- [ ] Evaluate docs tooling: MkDocs Material vs Sphinx vs README-only
- [ ] If MkDocs: `pip install mkdocs mkdocs-material mkdocstrings[python]`
- [ ] Create `mkdocs.yml` with navigation:
  - [ ] Home (README)
  - [   API Reference (auto-generated)
  - [   Integrations (LangGraph, CrewAI, Raw Python)
  - [   Triggers
  - [   Metrics & Observability
  - [   Field Study
  - [   Contributing
- [ ] Deploy via GitHub Pages: `.github/workflows/docs.yml` → `mkdocs gh-deploy`
- [ ] OR: defer to post-launch if time-constrained (README + docs/ is sufficient for v0.1.0)

#### ▶ Checkpoint M9

| Check | How to verify |
|---|---|
| Docs site deployed | GitHub Pages URL works |
| API reference auto-generated | mkdocstrings renders all public APIs |
| Navigation works | All pages linked, no 404s |
| OR: deferred | Documented decision to defer to post-launch |

---

### M10: Go-Live Checklist (Final Sweep) ⚡ M1-M9

#### Tasks

- [ ] Verify all M1-M8 items complete (M9 optional/stretch)
- [ ] Final review of README — does it tell the story? Is quick start copy-pasteable?
- [ ] Final review of git log — squash WIP commits if needed
- [ ] Test `pip install ai-loopguard` and run quick start end-to-end
- [ ] Run full test suite: `pytest --cov=ai_loopguard --cov-fail-under=90`
- [ ] Run `ruff check`, `mypy --strict`, `pip-audit`, `pip-licenses`
- [ ] Verify field study results are in `docs/field-study.md`
- [ ] Verify all 8 docs (D1-D8) are complete
- [ ] Verify all 12 GitHub issues (#1-#12) are addressed or closed
- [ ] Draft blog post or announcement (optional)
- [ ] **Flip repo visibility: Private → Public**
  - [ ] `gh repo edit deghosal-2026/ai-loopguard --visibility public`
- [ ] Post to communities: r/Python, r/devops, LangGraph Discord, CrewAI Discord, HN (optional)
- [ ] Tweet/LinkedIn post with link + tagline

#### ▶ Checkpoint M10 — GO LIVE

| Check | How to verify |
|---|---|
| All checkpoints passed | M1-M9 all green |
| Full test suite green | `pytest --cov` passes with ≥90% |
| Quality bar met | ruff, mypy, pip-audit, pip-licenses all clean |
| README tells the story | Quick start works, value prop clear |
| Field study published | `docs/field-study.md` complete |
| Docs complete | D1-D8 all present |
| Issues addressed | #1-#12 closed or documented |
| **Repo is public** | `gh repo view --json visibility` shows "PUBLIC" |
| Community notified | Posted to at least 2 communities |

---

## Dependency Graph

```
S1 (scaffold)
  ├── S2 (data models)
  │     ├── S3 (failure detection)
  │     │     └── S4 (escalation core)
  │     │           └── S5 (guard decorator)
  │     │                 ├── S7 (LangGraph)
  │     │                 ├── S8 (CrewAI)
  │     │                 └── S11 (e2e tests) ← also needs S6, S7, S8, S9
  │     └── S6 (cost & logging)
  │           └── S9 (OTel)
  │
  ├── S10 (CLI) ← needs S6
  ├── S12 (perf tests) ← needs S5
  ├── S13 (PyPI) ← needs S1-S12
  ├── S14 (field study) ← needs S5, S7, S8
  ├── S15 (documentation) ← needs S1-S14
  │
  └── M1-M10 (go public) ← needs S1-S15
        M1 (scrub) → M2 (community) → M3 (templates)
        M4 (CI) → M5 (PyPI) → M6 (changelog)
        M7 (branch protection) → M8 (good first issues)
        M9 (docs site, stretch) → M10 (go live)
```

---

## Summary

| Phase | Milestones | Days | Gate |
|---|---|---|---|---|
| 1: Foundation | S1, S2 | 1 | ✅ Package builds, CI green, models work |
| 2: Core Logic | S3, S4, S5, S6 | 4 | ✅ Detection, escalation, decorator, logging all work |
| 3: Integrations | S7, S8, S9 | 1.5 | ✅ LangGraph, CrewAI, OTel all drop in |
| 4: Polish & Verify | S10, S11, S12 | 2 | ✅ CLI done; S11, S12 pending |
| 5: Ship | S13, S14, S15 | 4.5 | ❌ Not started |
| 6: Go Public | M1-M10 | 3 | ❌ Not started |
| **Total** | **27 milestones** | **~16 days** | **10/27 complete** |

> **Critical path:** S1 → S2 → S3 → S4 → S5 → S11 → S15 → M1 → M10
> **Parallelizable:** S6 (with S3-S4), S7-S8-S9 (with each other, after S5), S10 (with S7-S9), S12 (with S10-S11), S14 (with S13/S15)
