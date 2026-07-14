# PRD — loopguard

| Field | Value |
|---|---|
| **Project** | loopguard — Circuit breaker & escalation for LLM agent loops |
| **Document type** | Product Requirements Document (What & Why) |
| **Status** | Draft |
| **Created** | 2026-07-10 |
| **Owner** | Debashish Ghosal |
| **Target release** | v0.1.0 (private → public after M1-M10 checklist, see `docs/WBS.md`) |
| **License** | MIT |

---

## 1. Problem

### 1.1 The core failure mode

Every team running AI agents hits the same wall: the cheap model gets stuck in a loop. It changes code, tests fail. It changes something else, a different test fails. It reverts, the original test fails again. Tokens burn. Nothing improves. This is where "cheap" becomes expensive.

### 1.2 The ecosystem gap

| Category | Existing tools | What they miss |
|---|---|---|
| **Agent runtimes** | LangGraph, CrewAI, AutoGen | No built-in quality layer. No failure detection. No escalation. |
| **Observability** | LangSmith, LangFuse | After-the-fact dashboards. No control loop. No intervention. |
| **Cost trackers** | agentcost-sdk, compute-cfo, runcost, l6e, agent-budget-controller | Per-call spend tracking only. No stuck-loop detection. No escalation. |
| **Budget protocols** | Agent Spend Protocol (ASP) | Pre-call budget enforcement. No failure-pattern detection. |
| **Full frameworks** | Overseer | Replaces your entire stack. Not a drop-in. |

**The missing middle:** nobody sits between frameworks and cost trackers — a quality/escalation layer that drops into whatever you're already using.

### 1.3 Why now

- **Model tiering is mainstream.** Cascade routing (FrugalGPT, Stanford) is the standard cost-optimization pattern: try cheap, escalate on failure. But the escalation half has no off-the-shelf implementation.
- **The Harness Effect.** Writer Inc. research shows "the orchestration layer can move cost per task more than switching between the cheapest and most expensive model." loopguard is part of that orchestration layer.
- **Cascade economics live or die on escalation rate.** TrueFoundry: if the cheap tier rarely resolves the task, you're paying for a cheap attempt plus an expensive call on every task — the worst of both worlds. Nobody tracks this as an SLO today.
- **No library exists for this.** Every team re-implements ad hoc retry limits and manual escalation. There is no `pip install` solution.

### 1.4 Cost of not solving this

| Failure | Impact |
|---|---|
| Undetected stuck loops | Token waste 5-10x per stuck task; user-facing latency spikes |
| No escalation path | Cheap model failures become hard failures; user sees errors instead of results |
| No escalation-rate SLO | Teams can't tell if their tiered routing is actually saving money |
| Per-call cost blindness | "Cheap" looks cheap per-call but is expensive per-completed-task |

---

## 2. Target users

### 2.1 Primary persona — Agent builder

> **"I'm running LangGraph/CrewAI agents in production and my cheap model gets stuck. I need it to detect the loop and hand off to a stronger model automatically."**

- AI/ML engineers and platform engineers building agentic systems
- Already using LangGraph, CrewAI, or raw Python agent loops
- Care about cost, reliability, and user experience
- Want a drop-in solution — not a framework migration

### 2.2 Secondary persona — Platform / SRE lead

> **"I need to know our escalation rate and real cost per completed task so I can defend our model-routing strategy to leadership."**

- Responsible for AI infrastructure cost and reliability
- Needs observability: escalation rate, cost per completed task, routing vs failover separation
- Wants structured logs and OpenTelemetry integration for existing dashboards

### 2.3 Tertiary persona — Open-source contributor

> **"I want to contribute to agent reliability tooling. Show me good first issues and a clear contribution path."**

- Python developer interested in the AI agent ecosystem
- Looking for meaningful OSS contributions in a growing space

---

## 3. Use cases & user stories

### UC-1: LangGraph agent stuck on a failing test (configurable escalation)

> **As a** LangGraph user, **when** my agent fails the same test 3 times in a row, **I want** loopguard to either auto-escalate to a stronger model or ask me first — so the loop breaks without burning tokens or spending without my consent.

**Scenario:**
1. A LangGraph graph is running a coding agent with a local model (e.g., Qwen 2.5 Coder via OMLX).
2. The agent modifies code, runs tests. Test `test_parser` fails. The agent tries again. `test_parser` fails again. Third attempt: same failure.
3. loopguard's `test_failure` trigger fires (pass → fail → fail → fail on the same test, 3 consecutive).
4. **Default mode (`on_escalate="auto"`):** loopguard packages context (failed diffs, test output, error messages), escalates to the configured cloud model (e.g., GPT-4), and returns its output. The graph continues with the escalated result.
5. **Interrupt mode (`on_escalate="interrupt"`):** loopguard packages context and surfaces a LangGraph interrupt to the user: "Agent is stuck on `test_parser` (3 failures). Escalate to GPT-4? [y/n]". The user confirms, then escalation proceeds.

**Validates:** FR-1.2 (test-failure detection), FR-2.1–FR-2.4 (escalation), FR-4.3 (LangGraph integration), configurable escalation behavior.

### UC-2: CrewAI crew with multiple agents hitting different triggers

> **As a** CrewAI user, **when** my crew has one agent returning malformed JSON and another hitting the same exception repeatedly, **I want** loopguard to detect both independently and escalate each — so the crew continues without manual intervention.

**Scenario:**
1. A CrewAI crew runs a research task with two agents: an Analyst (produces structured findings) and a Coder (writes automation scripts).
2. The Analyst agent returns malformed JSON 3 times in a row. loopguard's `schema_invalid` trigger fires. loopguard packages the failed outputs, escalates to a stronger model, and returns the corrected JSON. The crew continues.
3. Simultaneously, the Coder agent hits the same `ImportError` on 3 consecutive attempts. loopguard's `repeated_error` trigger fires. loopguard packages the error trace and previous code attempts, escalates, and returns the fixed code.
4. Both escalations are logged with trigger type, retry count, models involved, and cost impact. The crew's final output includes both agents' escalated results.

**Validates:** FR-1.1 (repeated error detection), FR-1.3 (schema validation failure), FR-2.4 (logging), FR-4.4 (CrewAI integration), simultaneous trigger handling.

### UC-3: Solo developer with a raw Python agent loop

> **As a** developer running a raw Python agent loop with no framework, **I want** to wrap my step function with `@guard.protect` and have loopguard detect stuck patterns and escalate — so I get the same reliability as framework users without adopting a framework.

**Scenario:**
1. A developer has a simple `while True` agent loop that calls `model.generate(prompt)` each step. No LangGraph, no CrewAI.
2. They add 4 lines: `from ai_loopguard import Guard`, create a `Guard(escalation_model=...)`, and decorate their step function with `@guard.protect`.
3. The model gets stuck repeating the same error. loopguard detects it after 3 retries, escalates to a stronger model with the failed context, and returns the escalated output.
4. The developer checks the JSONL log and sees the escalation event with cost impact. No framework adopted, no migration, just a decorator.

**Validates:** FR-4.1 (sync decorator), FR-1.1 (repeated error detection), FR-2.1–FR-2.3 (escalation), FR-3.4 (JSONL logging), framework-agnostic value proposition.

### UC-4: Platform team with async agent service and observability

> **As a** platform engineer running an async agent service in production, **I want** to wrap the handler with `@guard.aprotect` and have escalation events flow to our existing observability stack via OpenTelemetry — so I can track escalation rate and cost per completed task in our dashboards.

**Scenario:**
1. A platform team runs an async agent service that processes user requests. Each request calls an async handler that runs an agent loop.
2. They wrap the handler with `@guard.aprotect` and configure OTel hooks via `ai-loopguard[otel]`.
3. When the agent gets stuck (test failures, schema errors, or custom triggers), loopguard escalates and emits an OTel span event with: trigger type, retry count, models involved, cost impact, escalation rate, and cost per completed task.
4. The team's existing Grafana / Datadog / Jaeger dashboard picks up the spans. They create an alert: "Escalation rate > 30% → investigate routing config."
5. The platform lead generates a weekly report from the CLI: total escalations, escalation rate, cost breakdown, most common triggers. They use this to defend the model-routing strategy to leadership.

**Validates:** FR-4.2 (async decorator), FR-3.1–FR-3.6 (metrics, JSONL, OTel hooks), FR-6.1–FR-6.2 (CLI), platform/SRE persona.

---

## 4. Competitive analysis

### 4.1 Feature matrix

| Feature | loopguard | LangGraph (built-in) | CrewAI (built-in) | agentcost-sdk | compute-cfo | agent-budget-controller | l6e | Overseer | ASP |
|---|---|---|---|---|---|---|---|---|---|
| Stuck-loop detection | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Escalation to stronger model | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ (downgrades only) | ❌ | ✅ | ❌ |
| Test-failure cycle detection | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Schema validation trigger | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Custom trigger callbacks | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Escalation rate as SLO | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Cost per completed task | ✅ | ❌ | ❌ | ❌ (per-call) | ❌ (budget) | ❌ (per-scope) | ❌ (per-run) | ❌ | ❌ |
| Routing vs failover separation | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| JSONL structured logs | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| OpenTelemetry integration | ✅ (extra) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Drop-in (no framework migration) | ✅ | N/A | N/A | ✅ (monkey-patch) | ❌ (wraps infra) | ❌ (wraps agent) | ❌ (wraps run) | ❌ (full framework) | ❌ (protocol) |
| Framework-agnostic | ✅ | N/A | N/A | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| Sync + async support | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | N/A |
| CLI for log analysis | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### 4.2 Why loopguard wins

| Competitor | What they do | Why they're not enough | loopguard's advantage |
|---|---|---|---|
| **LangGraph / CrewAI** | Agent frameworks with retry primitives | No failure detection, no escalation, no cost-per-task | Drops into both; adds the quality layer they lack |
| **agentcost-sdk** | Per-call cost tracking via monkey-patching | No detection, no escalation, after-the-fact only | Detects and acts in real time; tracks per-completed-task not per-call |
| **compute-cfo** | Budget enforcement at infra level | No loop detection, no escalation, not agent-aware | Agent-loop-aware; escalation is the control loop, not just a budget gate |
| **agent-budget-controller** | Per-scope budgets with auto-downgrade | Downgrades on budget, not on failure; no stuck-loop detection | Escalates on failure patterns, not just budget; tracks escalation rate as SLO |
| **l6e** | Per-run budget + model routing | No failure pattern detection; routing is pre-call, not reactive | Reactive escalation based on observed failures; logs routing vs failover separately |
| **Overseer** | Full framework with quality layer | Replaces your entire stack; not a drop-in | Drop-in library; keeps your framework; 500-line core, not a framework |
| **ASP** | Pre-call budget enforcement protocol | Pre-call only; no failure detection, no escalation | Post-failure detection + escalation; complementary to ASP's pre-call enforcement |

### 4.3 Positioning

```
                 Pre-call               In-flight              Post-hoc
                 ────────               ────────               ────────
Budget/routing:  ASP, TierForge, l6e    ─                      ─
Failure detect:  ─                      loopguard              ─
Cost tracking:   ─                      ─                      agentcost-sdk, LangSmith
Full framework:  ─                      Overseer (all-in-one)  ─
```

loopguard owns the **in-flight failure detection + escalation** column. Nobody else does.

---

## 5. Goals & non-goals

### 5.1 Goals — what loopguard WILL do

| # | Goal | Why it matters |
|---|---|---|
| G1 | Detect stuck agent loops (repeated errors, test-failure cycles, schema failures, hallucination cycles, custom triggers) | This is the core value — knowing the agent is stuck before tokens spiral |
| G2 | Escalate to a stronger model after N retries with packaged context | Break the loop automatically; hand off to a model that can solve it |
| G3 | Track escalation rate and cost per completed task as first-class metrics | These are the SLOs that determine if tiered routing is working |
| G4 | Drop into LangGraph, CrewAI, and raw Python with minimal code change | Framework-agnostic — users don't migrate, they wrap |
| G5 | Provide structured observability (JSONL + OpenTelemetry hooks) | Integrates with existing dashboards; no lock-in to a specific observability stack |
| G6 | Ship as a pip-installable package with optional extras | `pip install ai-loopguard` for core; `ai-loopguard[langgraph]`, `ai-loopguard[crewai]`, `ai-loopguard[otel]` for integrations |

### 5.2 Non-goals — what loopguard will NOT do

| # | Non-goal | Why |
|---|---|---|
| NG1 | **Not a framework.** loopguard does not define how you build agents. | Frameworks already do this well. loopguard wraps what you've built. |
| NG2 | **Not a cost tracker.** loopguard does not track per-call token spend as its primary function. | Cost trackers already do this. loopguard's cost metric is per-completed-task, which is different and more useful. |
| NG3 | **Not a model router.** loopguard does not decide which model to use for a given task upfront. | That's routing (TierForge, l6e). loopguard handles the failure side: when the chosen model gets stuck. |
| NG4 | **Not a full observability platform.** loopguard emits events; it does not store, visualize, or alert. | That's LangSmith/LangFuse's job. loopguard feeds them via OTel hooks. |
| NG5 | **Not a self-grading system.** loopguard does not let the cheap model judge its own confidence. | Self-grading is unreliable. Triggers are deterministic (tests, schema validation, error patterns) or user-defined. |

### 5.3 Explicit out-of-scope examples (expected feature requests we will reject)

| Expected request | Response | Redirect to |
|---|---|---|
| "Add pre-call model routing based on task complexity" | Out of scope — loopguard is reactive, not predictive | TierForge, l6e |
| "Add per-call token budget enforcement" | Out of scope — that's pre-call budgeting | ASP, agent-budget-controller |
| "Add a web dashboard for escalation metrics" | Out of scope — loopguard emits events, doesn't visualize | LangSmith, LangFuse, Grafana (via OTel hooks) |
| "Replace LangGraph / CrewAI with loopguard's own agent runtime" | Out of scope — loopguard is a library, not a framework | LangGraph, CrewAI |
| "Let the agent self-report confidence and escalate on low confidence" | Out of scope — self-grading is unreliable (NG5) | Use deterministic triggers (tests, schema validation) |

---

## 6. Assumptions & constraints

### 6.1 Assumptions

| # | Assumption | Rationale |
|---|---|---|
| A1 | The user runs a **local model (OMLX / Ollama)** as the workhorse and a **cloud model (OpenAI / Anthropic / etc.)** as the escalation target | This is the cost-conscious tiered workflow. loopguard is optimized for this pattern but does not hardcode it — any LangChain `BaseChatModel` works for either role. |
| A2 | The user already has a working agent loop (LangGraph graph, CrewAI crew, or raw Python) | loopguard wraps existing code; it does not create agents from scratch. |
| A3 | The user's escalation model is a LangChain `BaseChatModel` | Core dependency on `langchain-core` for model binding. Users without LangChain can use the raw callable interface (planned for v0.2.0 adapter). |
| A4 | The user's agent loop is either synchronous or asynchronous (asyncio) | Both patterns are common in agent frameworks; loopguard supports both from v0.1.0. |
| A5 | Failure patterns are detectable from observable signals (exceptions, test results, schema validation, error messages) | loopguard does not introspect model internals; it watches the agent's observable outputs. |
| A6 | The user wants to minimize tokens spent on stuck loops | The primary economic motivation for using loopguard. |

### 6.2 Constraints

| # | Constraint | Detail |
|---|---|---|
| C1 | **License:** MIT | Must remain permissive; no GPL or copyleft dependencies |
| C2 | **Distribution:** PyPI only | No conda, no Docker image, no brew — pip is the channel |
| C3 | **Core dependencies must be minimal** | `langchain-core` + `pydantic` only. All framework integrations are optional extras. |
| C4 | **No telemetry or phone-home** | loopguard does not collect, transmit, or report usage data. Ever. |
| C5 | **Python 3.10+** | Locks the feature set (match statements, modern typing). No 3.9 support. |
| C6 | **No C extensions or compiled code** | Pure Python. Maximizes portability across OS/architectures. |
| C7 | **Local model compatibility** | Must work with OMLX-served models (Qwen, Llama, DeepSeek) and Ollama, not just cloud APIs |

---

## 7. Success metrics

### 7.1 Product success — how we know loopguard works

| Metric | Target | How to measure |
|---|---|---|
| Escalation resolves the task | >70% of escalations produce a successful result | Field study: run loopguard across 15 agent tasks, measure post-escalation success rate |
| Token waste reduction | >40% fewer tokens consumed on stuck-loop tasks vs unguarded baseline | Field study: same tasks with and without loopguard, compare total tokens |
| Latency improvement | Median task completion time improves or stays flat with loopguard | Field study: measure wall-clock time per completed task |
| Drop-in friction | <10 lines of code to add loopguard to an existing agent | Code review: count lines changed in integration examples |

### 7.2 Adoption success — how we know the market wants this

| Metric | v0.1.0 target (first 30 days public) | v0.2.0 target (90 days) |
|---|---|---|
| GitHub stars | 50+ | 200+ |
| PyPI downloads | 100+ | 1,000+ |
| External issues opened | 3+ | 10+ |
| External PRs merged | 1+ | 3+ |
| Good first issues claimed | 2+ | 5+ |

### 7.3 Quality bar — how we know the library is trustworthy

| Metric | Target |
|---|---|
| Test coverage | ≥90% on core modules |
| CI passing | 100% on main across Python 3.10/3.11/3.12 × ubuntu/macos/windows |
| Type check clean | `mypy --strict` passes |
| Lint clean | `ruff check` passes |
| Zero known security vulnerabilities | `pip-audit` clean |
| Field study validated | 15 agent tasks across 3 external repos with documented results |

---

## 8. Functional requirements

### 8.1 Failure detection (FR-1)

| ID | Requirement | Priority |
|---|---|---|
| FR-1.1 | The library MUST detect repeated identical errors (same exception type or message N consecutive times) | P0 |
| FR-1.2 | The library MUST detect test-failure loops (a test passes, then fails, then passes again on the same test) | P0 |
| FR-1.3 | The library MUST detect schema validation failures (output fails parsing N consecutive times) | P0 |
| FR-1.4 | The library MUST detect hallucination cycles (agent claims to fix something it already attempted) | P1 |
| FR-1.5 | The library MUST support user-defined custom trigger callbacks | P1 |
| FR-1.6 | The library MUST allow configurable retry thresholds per trigger type | P0 |
| FR-1.7 | The library MUST track failure history across steps within a single guarded execution | P0 |

### 8.2 Escalation (FR-2)

| ID | Requirement | Priority |
|---|---|---|
| FR-2.1 | When a trigger threshold is hit, the library MUST escalate to a configured escalation model | P0 |
| FR-2.2 | The library MUST package context for the escalation model (what was attempted, what failed, the agent's state) | P0 |
| FR-2.3 | The library MUST return the escalation model's output as the result of the guarded call | P0 |
| FR-2.4 | The library MUST log every escalation event with: trigger type, retry count, models involved, cost impact | P0 |
| FR-2.5 | The library MUST support configurable escalation prompts (default provided, user can override) | P1 |
| FR-2.6 | The library SHOULD compress/summarize context before escalating to limit token cost | P1 |
| FR-2.7 | The library MUST support configurable escalation behavior: `on_escalate="auto"` (default) or `on_escalate="interrupt"` (ask user before spending tokens) | P0 |
| FR-2.8 | The library MUST sanitize escalation context to prevent prompt injection — clear system vs user separation, delimiters around agent-produced content | P0 |
| FR-2.9 | The library MUST support configurable redaction of sensitive fields (regex patterns or field names) in escalation context before sending to the escalation model | P0 |

### 8.3 Metrics & observability (FR-3)

| ID | Requirement | Priority |
|---|---|---|
| FR-3.1 | The library MUST track and expose escalation rate (escalations / total guarded calls) | P0 |
| FR-3.2 | The library MUST track and expose cost per completed task (including retries, failed loops, and escalation calls) | P0 |
| FR-3.3 | The library MUST separate routing events (intentional escalation) from failover events (availability failure) in logs | P1 |
| FR-3.4 | The library MUST emit structured JSONL logs for every escalation event | P0 |
| FR-3.5 | The library MUST provide an event hook interface for pluggable observability backends | P0 |
| FR-3.6 | The library SHOULD provide an OpenTelemetry GenAI integration via an optional extra | P1 |

### 8.4 Integrations (FR-4)

| ID | Requirement | Priority |
|---|---|---|
| FR-4.1 | The library MUST provide a `@guard.protect` decorator for any sync Python function | P0 |
| FR-4.2 | The library MUST provide an `@guard.aprotect` decorator for any async Python function | P0 |
| FR-4.3 | The library MUST provide a LangGraph callback handler integration via `ai-loopguard[langgraph]` | P0 |
| FR-4.4 | The library MUST provide a CrewAI step wrapper integration via `ai-loopguard[crewai]` | P0 |
| FR-4.5 | The library MUST accept a LangChain `BaseChatModel` as the escalation model | P0 |
| FR-4.6 | Integrations MUST be optional extras — core install has no framework dependencies | P0 |

### 8.5 Configuration (FR-5)

| ID | Requirement | Priority |
|---|---|---|
| FR-5.1 | The library MUST accept configuration via keyword arguments to `Guard(...)` | P0 |
| FR-5.2 | The library MUST provide a typed configuration model (Pydantic) with validation | P0 |
| FR-5.3 | The library MUST support environment variable override for configuration values | P1 |
| FR-5.4 | The library MUST support YAML config file loading for advanced deployments | P1 |
| FR-5.5 | The library MUST provide sensible defaults (max_retries=3, sensible trigger thresholds) | P0 |

### 8.6 CLI (FR-6)

| ID | Requirement | Priority |
|---|---|---|
| FR-6.1 | The library MUST provide a CLI to analyze escalation patterns from JSONL logs | P1 |
| FR-6.2 | The CLI SHOULD summarize: total escalations, escalation rate, cost breakdown, most common trigger types | P1 |
| FR-6.3 | The CLI SHOULD filter by date range, trigger type, and model | P2 |

---

## 9. Non-functional requirements

### 9.1 Compatibility

| Requirement | Detail |
|---|---|
| Python | 3.10, 3.11, 3.12 |
| OS | Linux, macOS, Windows |
| LangGraph | Latest stable (at time of release) |
| CrewAI | Latest stable (at time of release) |
| LangChain | `langchain-core` latest stable (core dependency for model binding) |
| Local models | OMLX (Qwen, Llama, DeepSeek), Ollama |

### 9.2 Performance

| Requirement | Target |
|---|---|
| Guarded call overhead (no escalation) | <1ms per step — detection must not bottleneck the agent loop |
| Escalation overhead (context packaging + model call) | Dominated by model latency; packaging must be <100ms |
| Memory footprint | Failure history bounded by configurable max-steps; no unbounded growth |
| Import time | <200ms for `import ai_loopguard` (core, no extras) |

### 9.3 Reliability

| Requirement | Detail |
|---|---|
| loopguard MUST NOT crash the agent loop | If loopguard itself fails (detection bug, model call error), the original function's behavior must be preserved. Fail-open, not fail-closed. |
| Escalation model failures MUST be caught | If the escalation model fails, log the event and return the last original output (or raise a configurable behavior) |
| Thread safety | A Guard instance MUST be safe to use across concurrent agent runs (thread-safe failure history) |

### 9.4 Security

| Requirement | Detail |
|---|---|
| No hardcoded API keys or endpoints | All model credentials come from the user's environment/config |
| No telemetry or phone-home | loopguard does not collect or transmit usage data |
| Context sanitization | Escalation context MUST be sanitized against prompt injection (see §10 Threat Model, T1) |
| Context redaction | Sensitive fields MUST be redactable before sending to escalation model (see §10 Threat Model, T2) |
| Supply chain | All dependencies pinned with hashes in lockfile; `pip-audit` in CI |

### 9.5 Developer experience

| Requirement | Detail |
|---|---|
| Time to first value | A new user can install, configure, and guard a function in <5 minutes |
| API discoverability | Full type annotations; IDE autocomplete works for all public APIs |
| Error messages | All user-facing errors are actionable (what went wrong + how to fix) |

### 9.6 Performance benchmark methodology

The performance targets in §9.2 are verifiable. This section defines how they are measured so results are reproducible and defensible.

| Target | Benchmark | How to measure | Hardware | Baseline |
|---|---|---|---|---|
| **Detection overhead <1ms per step** | `FailureDetector.check()` on 100-step history with 3 enabled triggers | `tests/perf/test_overhead.py`: time 1000 calls of `check()`, divide by 1000, report median + p99. Use `time.perf_counter_ns()` for nanosecond precision. | CI runner (ubuntu-latest). Results are directional, not absolute — track regressions over time. | Empty history (0 steps) as overhead floor. Subtract floor from measured time. |
| **Context packaging <100ms** | `ContextPackager.package()` on 20-step history, 2KB average output, compression enabled | `tests/perf/test_packaging.py`: time 100 packaging calls, report median + p99. Measure wall-clock time including compression. | CI runner (ubuntu-latest). | 1-step history as floor (no compression needed). |
| **Import time <200ms** | `import ai_loopguard` with no extras installed | `tests/perf/test_import.py`: use `python -X importtime -c "import ai_loopguard"` and parse the self-time for the top-level package. Run 10 times, report median. | CI runner. Cold import (no `__pycache__`). | `import sys` as floor (sub-millisecond). |

**Benchmark execution rules:**
- Benchmarks run in CI but are **non-gating** (perf varies by runner hardware). Results are tracked over time to detect regressions.
- A regression >25% on any target triggers a warning in CI output (not a failure). The maintainer investigates manually.
- Benchmark results are published in `docs/performance-benchmarks.md` after each release with the CI runner specs and methodology.
- Field study (§11.3) provides real-world latency data that complements these micro-benchmarks.

---

## 10. Threat model

### 10.1 Overview

loopguard sits between an agent loop and an escalation model. It packages the agent's failed outputs and sends them to a potentially external (cloud) model. This creates two attack surfaces: the content being packaged, and the channel it's sent over. The threat model below identifies the risks and the requirements that mitigate them.

### 10.2 Threats

| ID | Threat | Description | Impact | Mitigation (FR ref) |
|---|---|---|---|---|
| **T1** | **Prompt injection via escalation context** | The agent's failed output may contain malicious instructions from external data it processed (e.g., a web page, a file, a tool result). When loopguard packages this and sends it to the escalation model, the injected instructions could cause the escalation model to: leak system prompts, ignore the escalation task, produce harmful output, or exfiltrate data. | High — escalation model could be hijacked | FR-2.8: Sanitize context with clear system vs user separation. Delimit agent-produced content. Strip or escape known injection patterns. |
| **T2** | **Secret / PII leakage to escalation model** | The agent's state may contain API keys, credentials, tokens, or PII that get packaged and sent to a cloud model (GPT-4, Claude). This leaks sensitive data to a third party. | High — data breach, credential exposure | FR-2.9: Configurable redaction fields (regex patterns or field names). Applied before context is sent. User defines what to redact. |
| **T3** | **Unbounded failure history (memory exhaustion)** | A malicious or buggy agent loop could produce thousands of steps, causing loopguard's failure history to grow unbounded, exhausting memory. | Medium — DoS, crash | §9.2: Failure history bounded by configurable max-steps. Hard cap with configurable default. |
| **T4** | **Escalation model unavailable or compromised** | The escalation model endpoint could be down, return errors, or be compromised (model replacement, response tampering). | Medium — escalation fails, or returns malicious output | §9.3: Escalation model failures are caught. If escalation fails, log and fail-open (return last original output). |
| **T5** | **Supply chain compromise** | A dependency (langchain-core, pydantic, or an optional extra) could be compromised with malicious code. | Medium — code execution, data exfiltration | §9.4: Dependencies pinned with hashes. `pip-audit` in CI. Review new dependencies before adding. |
| **T6** | **Excessive escalation cost (economic DoS)** | A malicious or buggy agent loop could trigger repeated escalations, each calling an expensive cloud model, racking up costs. | Medium — unexpected billing | OQ-4: Max escalations per run (to be defined in SPEC). Configurable cap on escalations per guarded execution. |

### 10.3 Trust boundaries

```
┌─────────────────────────────────────────────────────────┐
│  User's environment (trusted)                            │
│                                                          │
│  ┌──────────┐     ┌───────────┐     ┌─────────────────┐ │
│  │  Agent   │────▶│ loopguard │────▶│ Escalation model │ │
│  │  loop    │     │           │     │  (untrusted)     │ │
│  │ (trusted)│     │ (trusted) │     │                  │ │
│  └──────────┘     └───────────┘     └─────────────────┘ │
│       │                │                      │          │
│       │           T1: sanitize          T2: redact       │
│       │           T3: bound history      T4: catch fail  │
│       │           T6: cap escalations                     │
│                                                          │
└─────────────────────────────────────────────────────────┘
         T5: supply chain (pinned deps, pip-audit)
```

**Trust boundary 1 (agent loop → loopguard):** The agent's output crosses into loopguard's monitoring. loopguard must treat agent output as untrusted (T1, T3).

**Trust boundary 2 (loopguard → escalation model):** Context crosses from the user's environment to a potentially external cloud model. loopguard must sanitize (T1) and redact (T2) before crossing this boundary.

**Trust boundary 3 (dependencies → loopguard):** Third-party packages cross into the user's environment. Pinned hashes and pip-audit mitigate (T5).

---

## 11. Testing & validation strategy

### 11.1 Test layers

| Layer | Scope | What it validates | Location | CI? |
|---|---|---|---|---|
| **Unit** | Individual components: `FailureDetector`, `EscalationTrigger`, `ContextPackager`, `CostTracker`, `GuardDecorator`, config model | Each component works in isolation; edge cases (empty history, threshold boundaries, malformed input) | `tests/unit/` | Yes (every push) |
| **Integration** | `Guard` wrapping real Python functions (sync + async); mock LLM models; trigger interactions; config loading | Components work together; the decorator wraps correctly; triggers fire in the right order | `tests/integration/` | Yes (every push) |
| **E2E** | Full escalation flow: agent gets stuck → trigger fires → context packaged → escalation model called → output returned → event logged | The end-to-end user journey works with mock models simulating stuck patterns | `tests/e2e/` | Yes (every push) |
| **Field study** | Real agent tasks on 3 external repos with real models (local workhorse + cloud escalation) | loopguard actually detects stuck loops and escalation resolves them in real-world conditions; token reduction and latency measured | `docs/field-study.md` + raw data in `docs/field-study/` | No (manual, pre-release) |

### 11.2 Test infrastructure

| Requirement | Detail |
|---|---|
| Mock LLM models | Unit/integration/e2e tests use mock models that simulate stuck patterns (repeated errors, test failures, schema failures) — no real API calls in CI |
| Async test support | `pytest-asyncio` for async decorator and async integration tests |
| Coverage tool | `pytest-cov`; enforce ≥90% on core modules via `--cov-fail-under=90` |
| Snapshot testing | `pytest-snapshot` for JSONL log format validation (log structure doesn't drift) |
| Doc tests | `pytest --doctest-modules` — every code example in docstrings is runnable |
| CI matrix | Python 3.10/3.11/3.12 × ubuntu-latest/macos-latest/windows-latest |

### 11.3 Field study methodology

| Element | Detail |
|---|---|
| **Scope** | 15 agent tasks across 3 external open-source repos |
| **Repo selection** | 3 external repos with active agent loops (e.g., SWE-agent, OpenDevin, or similar). Must have: test suite, agent loop that can get stuck, diverse task types. |
| **Task selection** | 5 tasks per repo, chosen to include: coding tasks (test-failure trigger), data extraction tasks (schema-invalid trigger), tasks with known failure modes (repeated-error trigger) |
| **Baseline** | Run each task without loopguard — record: total tokens, wall-clock time, success/failure, number of retries |
| **Guarded** | Run the same tasks with loopguard — record: total tokens, wall-clock time, success/failure, number of retries, number of escalations, escalation success rate, cost per completed task |
| **Comparison** | Token reduction %, latency delta, escalation success rate, drop-in lines of code |
| **Documentation** | Results published in `docs/field-study.md` with: per-task table, aggregate summary, methodology, reproducibility instructions. Raw logs in `docs/field-study/`. |
| **Success criteria** | >70% escalation success rate, >40% token reduction on stuck tasks, median latency improves or stays flat |

### 11.4 Quality gates

| Gate | When | Criteria |
|---|---|---|
| **Pre-merge** | Every PR | CI green (unit + integration + e2e), coverage ≥90%, ruff clean, mypy strict clean |
| **Pre-release** | Before each version tag | Field study re-run (if core logic changed), pip-audit clean, all doc examples runnable, CHANGELOG updated |
| **Pre-public** | Before flipping private → public | M1-M10 checklist complete (see `docs/WBS.md`), field study published, all quality gates met |

---

## 12. Documentation requirements

### 12.1 Documentation deliverables for v0.1.0

| # | Document | Audience | Format | Location |
|---|---|---|---|---|
| D1 | **Quick start** | New users | Copy-pasteable 5-minute guide: install, configure, guard a function, see it escalate | `README.md` |
| D2 | **API reference** | All users | Every public class, method, and decorator with docstrings, auto-generated | `docs/api/` (mkdocs + mkdocstrings or Sphinx) |
| D3 | **Integration guide — LangGraph** | LangGraph users | Callback handler setup, `on_escalate` modes (auto + interrupt), full example | `docs/integrations/langgraph.md` |
| D4 | **Integration guide — CrewAI** | CrewAI users | Step wrapper setup, multi-agent trigger example, full example | `docs/integrations/crewai.md` |
| D5 | **Integration guide — raw Python** | Framework-free users | `@guard.protect` and `@guard.aprotect` decorator examples, sync + async | `docs/integrations/raw-python.md` |
| D6 | **Trigger reference** | All users | Every trigger type with examples: `test_failure`, `repeated_error`, `schema_invalid`, `hallucination_cycle`, custom callback | `docs/triggers.md` |
| D7 | **Metrics & observability guide** | Platform / SRE users | How to read escalation rate, cost per completed task, routing vs failover; how to wire OTel hooks; how to use the CLI to analyze logs | `docs/observability.md` |
| D8 | **Contributor onboarding guide** | OSS contributors | Fork, clone, setup dev env, run tests, submit PR; points to good first issues | `CONTRIBUTING.md` |

### 12.2 Documentation quality bar

| Requirement | Target |
|---|---|
| Every code example in docs MUST be runnable | CI tests doc snippets with `doctest` or `pytest --doctest-modules` |
| Every public API MUST have a docstring | `ruff` pydoclint check in CI |
| Quick start MUST work in <5 minutes | Validated by a fresh-environment test before each release |
| Integration guides MUST include a complete end-to-end example | Not just snippets — a full runnable script |

---

## 13. Release scope & roadmap

### 13.1 v0.1.0 — Initial public release

| Scope | In | Out |
|---|---|---|
| Failure detection | FR-1.1, FR-1.2, FR-1.3, FR-1.5, FR-1.6, FR-1.7 | FR-1.4 (hallucination cycle — deferred to v0.2.0) |
| Escalation | FR-2.1 through FR-2.9 (including configurable `on_escalate`, context sanitization, redaction) | — |
| Metrics & observability | FR-3.1 through FR-3.6 | — |
| Integrations | FR-4.1 through FR-4.6 (sync + async + LangGraph + CrewAI + LangChain model binding) | — |
| Configuration | FR-5.1, FR-5.2, FR-5.5 (kwargs + Pydantic + defaults) | FR-5.3, FR-5.4 (env/YAML — deferred to v0.2.0) |
| CLI | FR-6.1, FR-6.2 (basic log analysis) | FR-6.3 (filters — v0.2.0) |
| Documentation | D1–D8 (all 8 documents) | — |
| Security | T1 sanitization, T2 redaction, T3 bounded history, T4 fail-open | — |
| Testing | 4-layer suite (unit + integration + e2e + field study) | — |

### 13.2 v0.2.0 — Post-launch iteration

| Scope | Rationale |
|---|---|
| Hallucination cycle detection (FR-1.4) | Harder pattern; needs field-study data to tune |
| Environment + YAML config (FR-5.3, FR-5.4) | Power users want config files; ship after core is proven |
| CLI filters (FR-6.3) | Add once users have enough logs to need filtering |
| Community-driven features | Based on issue feedback from v0.1.0 users |

### 13.3 Roadmap gates

```
v0.1.0 (public launch)
  │
  │  Gate: M1-M10 checklist complete (see docs/WBS.md)
  │  Gate: field study validated (15 tasks, 3 external repos)
  │  Gate: quality bar met (90% coverage, mypy strict, ruff clean, pip-audit clean)
  │  Gate: threat model mitigations implemented (T1-T6)
  │
  ▼
v0.2.0 (post-launch iteration)
  │
  │  Gate: v0.1.0 shipped + 30 days of user feedback
  │  Gate: ≥3 external issues opened
  │
  ▼
v1.0.0 (stable release)
  │
  │  Gate: 10+ external PyPI users
  │  Gate: 1+ external contributor with merged PR
  │  Gate: 90 days in production without critical bugs
  │
  ▼
v1.x.y (stable, semver-compliant)
```

### 13.4 Stability promise

| Version | Stability |
|---|---|
| 0.x.y | Breaking changes allowed between minor versions. Documented in CHANGELOG. No semver stability guarantee. |
| 1.0.0 | First stable release. Breaking changes only in 2.0.0. Marked with `@stable` in docs. |
| Trigger for 1.0.0 | 10+ external users + 1 external contributor + 90 days in production without critical bugs |

---

## 14. Backwards compatibility, deprecation & support policy

### 14.1 Deprecation policy

When a public API is deprecated, the following timeline applies:

| Step | Release | Action |
|---|---|---|
| 1 | Release N (deprecating release) | Add `DeprecationWarning` to the API. Document in CHANGELOG. Add migration guide in `docs/migrations/`. |
| 2 | Release N+1 (grace release) | API still works. Warning still emitted. Migration guide updated if needed. |
| 3 | Release N+2 (removal release) | API removed. Using it raises `ImportError` or `AttributeError` with a message pointing to the migration guide. |

**Rules:**
- Deprecation warnings MUST include the version where the API will be removed and a link to the migration guide.
- Only public APIs (documented in the API reference, D2) are covered by this policy. Internal/private APIs can change without warning.
- Breaking changes within a minor version are NOT allowed (semver). A deprecation cycle spans minor versions only.

### 14.2 Backwards compatibility rules

| Rule | Detail |
|---|---|
| **Patch releases (0.x.Y → 0.x.Y+1)** | Bug fixes and security patches only. No API changes. No deprecations. Fully backwards compatible. |
| **Minor releases (0.X.y → 0.X+1.0)** | New features allowed. Deprecations allowed (with warning). No removals. Existing public APIs continue to work. |
| **Major releases (0.x.y → 1.0.0)** | Breaking changes allowed. Deprecated APIs from previous cycle are removed. Migration guides provided for all breaking changes. |
| **Post-1.0.0** | Semver strictly enforced. Breaking changes only in major versions (2.0.0, 3.0.0). |

### 14.3 Support policy

| Version | Bug fixes | Security patches | Duration |
|---|---|---|---|
| **Latest minor release** | ✅ Yes | ✅ Yes | Until next minor release ships |
| **Previous minor release** | ❌ No | ❌ No | EOL when next minor ships |
| **Pre-1.0.0 (all 0.x.y)** | Latest minor only | Latest minor only | No long-term support |

**What this means:**
- When v0.2.0 ships, v0.1.x is end-of-life. Users should upgrade.
- Security vulnerabilities in EOL versions are documented in `SECURITY.md` with a recommendation to upgrade.
- No backports to EOL versions. Patches land in the latest minor only.

### 14.4 Migration support

| Release type | Migration guide | Location |
|---|---|---|
| Minor release with deprecations | Yes — for each deprecated API | `docs/migrations/v0.X.0.md` |
| Major release (1.0.0) | Yes — comprehensive migration guide | `docs/migrations/v1.0.0.md` |
| Patch release | No — fully backwards compatible | N/A |

---

## 15. Packaging & distribution

| Channel | Detail |
|---|---|
| PyPI | `pip install ai-loopguard` (core) |
| Extras | `ai-loopguard[langgraph]`, `ai-loopguard[crewai]`, `ai-loopguard[otel]` |
| Core dependencies | `langchain-core` (model binding interface), `pydantic` (configuration) |
| Optional dependencies | `langgraph` (via extra), `crewai` (via extra), `opentelemetry-sdk` (via extra) |
| Python package | Standard `pyproject.toml` (setuptools or hatchling) |
| License | MIT |

### 15.2 Dependencies policy

#### Core dependencies

| Rule | Detail |
|---|---|
| **Maximum core deps** | 2: `langchain-core` (model binding) + `pydantic` (config). No exceptions without a PR review. |
| **License check** | All core deps MUST be MIT, BSD, or Apache-2.0. No GPL, LGPL, or copyleft. Verified at add time and in CI via `pip-licenses`. |
| **Maintenance check** | Core deps MUST have a release within the last 12 months. Abandoned deps are replaced. |
| **Security check** | Core deps MUST pass `pip-audit` with zero known vulnerabilities. Checked in CI on every push. |
| **Version pinning** | Core deps pinned to a minor range (e.g., `>=0.3.0,<0.4.0`). Patch updates allowed automatically. Minor updates require CI validation. |

#### Optional dependencies (extras)

| Rule | Detail |
|---|---|
| **Isolation** | Each extra is a self-contained integration. Installing `ai-loopguard[langgraph]` must not pull in `crewai` or `opentelemetry-sdk`. |
| **License check** | Same as core — MIT, BSD, or Apache-2.0 only. |
| **Version pinning** | Extras pinned to a minor range. Frameworks with frequent breaking changes (CrewAI) get tighter ranges. |
| **Stability tier** | Each extra is labeled in docs as: **stable** (tested, production-ready) or **experimental** (works but API may change). v0.1.0: LangGraph = stable, CrewAI = experimental (per §17 risk). |
| **Adding a new extra** | Requires: (1) justification that it's a distinct integration, not core functionality, (2) isolated tests, (3) documentation, (4) CI matrix entry. |

#### Dependency review process

```
New dependency proposed → 
  Is it core or extra? →
    Core: PR review + license check + pip-audit + justification that it can't be an extra
    Extra: PR review + license check + pip-audit + isolation test (doesn't leak into core)
  → Merge or reject
```

#### Dependency audit

| Audit | Frequency | Tool | Action on failure |
|---|---|---|---|
| Security vulnerabilities | Every push | `pip-audit` | Block CI — must fix before merge |
| License compliance | Every push | `pip-licenses` | Block CI — must replace dep |
| Maintenance staleness | Monthly | Manual review of dep release dates | Open issue if dep is stale (>12 months) |
| Dependency count | Monthly | `pip list` diff | Open issue if core deps >2 or total deps grew unexpectedly |

### 15.3 Naming & branding

| Element | Value | Rationale |
|---|---|---|
| **Package name (PyPI)** | `ai-loopguard` | Lowercase, hyphenated. Distinct from the `ai_loopguard` import name (hyphen vs underscore). |
| **Import name** | `ai_loopguard` | Distinct from PyPI name `ai-loopguard` (underscore vs hyphen). `from ai_loopguard import Guard` reads naturally. |
| **CLI command** | `loopguard` | Matches product name. `loopguard analyze logs.jsonl` is clear. |
| **GitHub repo** | `ai-loopguard` | PyPI name differed from import name. URL: `github.com/deghosal-2026/ai-loopguard`. |
| **Tagline** | "Circuit breaker and escalation for LLM agent loops." | One sentence. Says what it is (circuit breaker) and what it's for (LLM agent loops). |
| **Short description** | "Detects stuck agent loops and escalates to a stronger model. Drop-in for LangGraph, CrewAI, or raw Python." | For GitHub About field, PyPI long description, social posts. |
| **Logo / wordmark** | TBD (v0.2.0 or post-launch) | Not blocking for v0.1.0. Can be added after public launch if the project gets traction. |
| **Color** | TBD (if logo is designed) | Not blocking. |
| **Naming collision check** | `loopguard` not available on PyPI (taken by another project). Fallback: `ai-loopguard` (PyPI), `ai-loopguard` (GitHub). Import is `ai_loopguard`. **OQ-5 resolved:** name confirmed as `ai-loopguard`. |

**Naming rules:**
- All lowercase. No CamelCase, no hyphens in the import name.
- PyPI package name and GitHub repo name are `ai-loopguard`; import name is `ai_loopguard`; CLI command is `loopguard`. Users `pip install ai-loopguard` then `from ai_loopguard import Guard`.
- The wordmark (if designed) can use different casing (e.g., "LoopGuard") for visual branding, but the code-facing name is always `ai_loopguard`.

---

## 16. Community & governance

### 16.1 Governance model

loopguard is **maintainer-managed**. The project owner (Debashish Ghosal) reviews and merges all PRs, makes architectural decisions, and triages issues. Formal governance (contributor ladder, co-maintainer promotion, steering committee) will be defined as the community grows.

### 16.2 Community channels

| Channel | Purpose |
|---|---|
| GitHub Issues | Bug reports, feature requests, trigger pattern discussions |
| GitHub Discussions | Q&A, usage questions, "how do I..." posts (separated from bug reports) |
| Pull Requests | Code contributions, documentation improvements |

### 16.3 Contribution path

```
User opens issue → Maintainer triages → 
  Bug? → Label "bug" → Contributor picks up → PR → Review → Merge
  Feature? → Label "feature" → Maintainer evaluates scope → 
    In scope? → Contributor picks up → PR → Review → Merge
    Out of scope? → Redirect (see §5.3)
  Good first issue? → Label "good first issue" → New contributor picks up → PR → Review → Merge
```

### 16.4 Governance evolution triggers

| Trigger | Action |
|---|---|
| 5+ regular contributors | Define contributor ladder (contributor → reviewer → maintainer) |
| 1+ co-maintainer | Document decision-making process (RFC process for breaking changes) |
| 100+ GitHub stars | Consider a steering committee or working group |

### 16.5 Feedback & iteration plan

#### Post-launch feedback channels

| Channel | What we collect | How we use it | Cadence |
|---|---|---|---|
| GitHub Issues (bug) | Reproduction steps, loopguard version, Python version, framework, trigger type | Triage → fix in next patch or minor release | Weekly triage |
| GitHub Issues (feature) | Use case, why current API doesn't cover it, proposed solution | Triage → in-scope (add to v0.2.0 backlog) or out-of-scope (redirect, §5.3) | Weekly triage |
| GitHub Discussions (Q&A) | Usage questions, "how do I configure X", integration questions | Answer publicly → feed common questions into FAQ / docs | Weekly review |
| PyPI download stats | Install count, Python version distribution | Adoption signal — tracks growth | Monthly check |
| GitHub stars / forks / watchers | Project visibility signal | Adoption signal — tracks community interest | Monthly check |
| Field study contributions | Users running loopguard on their own agent tasks and sharing results | Validate real-world value → publish community case studies | Ongoing |

#### Iteration cadence

| Period | Action |
|---|---|
| **Weekly** | Triage all new issues and discussions. Respond within 48 hours. Label and route. |
| **Monthly** | Review adoption metrics (downloads, stars, issues). Write a monthly retrospective in GitHub Discussions. Identify top 3 requested features for next release. |
| **Per-release (v0.x.0)** | Close the feedback loop: publish release notes, blog post, and comment on issues that informed the release. Update roadmap based on what we learned. |
| **Quarterly** | Review the competitive landscape (§4). Check if any new tools have entered the space. Adjust positioning if needed. Review governance triggers (§16.4). |

#### Feedback-to-roadmap pipeline

```
User reports issue / asks question
  → Triaged (weekly)
  → Categorized: bug | feature | docs | Q&A | out-of-scope
  → Bugs → immediate fix queue (next patch)
  → Features → v0.2.0 backlog (prioritized by: frequency of request × severity × alignment with goals §5.1)
  → Docs gaps → docs fix queue (next patch or minor)
  → Q&A → answer + feed into FAQ if repeated
  → Out-of-scope → redirect (§5.3) + document the request in a "rejected features" list (transparency)
```

#### Community feedback signals we watch for

| Signal | What it means | Action |
|---|---|---|
| Same question asked 3+ times | Documentation gap | Add to FAQ or improve the relevant doc section |
| Same feature requested 3+ times | Real need not covered | Evaluate for v0.2.0 scope |
| External field study shared | Community validation | Publish as a case study; link from README |
| Contributor submits PR for integration X | Demand for that integration | Review and merge if it meets quality bar; add to supported extras |
| Issue with "workaround" in title or body | API gap that users are hacking around | Evaluate whether the workaround should become a first-class API |

---

## 17. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **LangChain breaking changes** in `langchain-core` affect model binding | Medium | High | Pin langchain-core version range; test against latest in CI weekly; provide adapter shim if interface changes |
| **CrewAI API instability** — CrewAI changes step interfaces frequently | Medium | Medium | Pin CrewAI version range; mark CrewAI integration as "experimental" in v0.1.0 docs; isolate in extras |
| **False positive escalations** — loopguard escalates when the agent wasn't actually stuck | Medium | High | Default to conservative thresholds (3 retries); make all thresholds configurable; log near-miss events for tuning |
| **Escalation model cost** — escalating to frontier model is expensive | Low | Medium | Context compression before escalation; cost-per-completed-task metric makes the tradeoff visible; configurable max escalations per run |
| **Scope creep** — requests for routing, budgeting, full observability | High | Medium | Non-goals are explicit (NG1-NG5); explicit out-of-scope examples (§5.3); route feature requests to companion projects; maintain focus |
| **No adoption** — library ships but nobody uses it | Medium | High | Ship with field-study data proving value; blog post series; post to LangGraph/CrewAI communities; good first issues to attract contributors |
| **Local model incompatibility** — loopguard doesn't work with specific OMLX/Ollama models | Low | Medium | Test against Qwen, Llama, DeepSeek in CI; document compatible models; accept community-reported compatibility issues |
| **Prompt injection via escalation context** (T1) | Medium | High | FR-2.8: sanitize context with system/user separation; delimit agent content; document the threat in integration guides |
| **Secret leakage to escalation model** (T2) | Medium | High | FR-2.9: configurable redaction before sending to cloud model; document redaction config in quick start and observability guide |

---

## 18. Open questions

| # | Question | Owner | Needed by |
|---|---|---|---|
| OQ-1 | What is the default escalation prompt? (The project file suggests "The workhorse is stuck in a loop. Here's what it tried. Break the cycle." — is this the v0.1.0 default, or do we want a more structured prompt?) | — | SPEC phase |
| OQ-2 | Context packaging: do we send raw failed attempts or a compressed summary? What is the max token budget for the escalation context? | — | SPEC phase |
| OQ-3 | Fail-open behavior: if loopguard itself throws, do we return the last successful output, re-raise the original error, or return a sentinel? Should this be configurable? | — | SPEC phase |
| OQ-4 | Max escalations per run: should we cap how many times a single guarded execution can escalate (e.g., max 1)? What happens if the escalation model also gets stuck? | — | SPEC phase |
| OQ-5 | PyPI package name availability: **Resolved** — `loopguard` was taken; using `ai-loopguard` (PyPI + GitHub), import is `ai_loopguard`. | — | Resolved |
| OQ-6 | Do we need a `ai-loopguard[all]` meta-extra that installs all integrations? | — | v0.1.0 packaging |
| OQ-7 | LangGraph interrupt mode (`on_escalate="interrupt"`): does loopguard use LangGraph's `interrupt()` + `Command(resume)` pattern directly, or does it abstract it behind its own interface? | — | SPEC phase |
| OQ-8 | Context sanitization (FR-2.8): what sanitization technique? Delimiters only, or also strip known injection patterns? Should we integrate with an existing prompt injection detector? | — | SPEC phase |
| OQ-9 | Redaction (FR-2.9): default redaction patterns (e.g., AWS keys, GitHub tokens) shipped out of the box, or user-defined only? | — | SPEC phase |
| OQ-10 | Which 3 external repos for the field study? Candidates: SWE-agent, OpenDevin, Aider, or others? | — | Before field study |

---

## 19. Glossary

### 19.1 loopguard terms

| Term | Definition |
|---|---|
| **Circuit breaker** | A pattern from distributed systems: when a service fails repeatedly, stop calling it and fall back. In loopguard, when an agent model fails repeatedly, stop retrying and escalate to a stronger model. |
| **Stuck loop** | An agent execution where the model repeats the same failing pattern without progress — same error, same test failure, same schema violation, or same hallucinated "fix." |
| **Escalation** | The act of handing off a stuck task from the workhorse (cheap) model to a stronger (more capable, more expensive) model, with packaged context explaining what was tried and what failed. |
| **Escalation rate** | The ratio of escalated tasks to total guarded tasks. The primary SLO for tiered routing: if this is too high, routing isn't saving money. |
| **Cost per completed task** | The total cost of getting a task done — including all retries, failed loops, and escalation calls. Unlike per-call cost, this reflects the real economics of model tiering. |
| **Routing vs failover** | Routing = intentional escalation (the cheap model got stuck, we chose to escalate). Failover = availability failure (the cheap model is down, we had to switch). Logged separately. |
| **Trigger** | A detected failure pattern that can cause escalation: `test_failure`, `repeated_error`, `schema_invalid`, `hallucination_cycle`, or a custom callback. |
| **Fail-open** | If loopguard itself encounters an error, it must not crash the agent loop. The original function's behavior is preserved. |
| **Context packaging** | The process of compressing and structuring what the agent tried (failed outputs, error messages, state) before sending it to the escalation model. |
| **Context sanitization** | The process of delimiting and separating agent-produced content from system instructions in the escalation context, to prevent prompt injection. |
| **Context redaction** | The process of stripping sensitive fields (API keys, credentials, PII) from the escalation context before sending it to a cloud model. |
| **Workhorse model** | The primary (usually cheaper, often local) model that handles agent steps. |
| **Escalation model** | The stronger (usually cloud, more expensive) model that receives escalated tasks when the workhorse gets stuck. |
| **Guard** | The loopguard object that wraps an agent step function and monitors it for stuck patterns. |
| **Guarded call** | A single invocation of a `@guard.protect`-decorated function. |

### 19.2 General AI / agent terms

| Term | Definition |
|---|---|
| **Agent loop** | A repeating cycle where an LLM takes a step (generates output, calls a tool, runs code), observes the result, and takes the next step until the task is complete. |
| **LLM** | Large Language Model — a neural network trained on text that generates text responses. Examples: GPT-4, Claude, Qwen, Llama, DeepSeek. |
| **Token** | The unit of text that LLMs process. Roughly 4 characters or 0.75 words per token. Pricing is per-token (input + output). |
| **Hallucination** | When an LLM generates output that is plausible-sounding but incorrect, fabricated, or disconnected from reality. In agent loops, this manifests as claiming to fix something that isn't fixed. |
| **Schema validation** | Checking that an LLM's output conforms to a expected format (JSON schema, Pydantic model, dataclass). Failure means the output can't be parsed into the expected structure. |
| **HITL** | Human-in-the-loop — a pattern where a human reviews or approves an agent's action before it proceeds. loopguard's `on_escalate="interrupt"` mode is a HITL pattern. |
| **BaseChatModel** | The LangChain interface for chat-based LLMs. loopguard uses this as the model binding interface — any LangChain-compatible model (OpenAI, Anthropic, Ollama, OMLX) works. |
| **Cascade routing** | A cost-optimization pattern: try the cheapest model first, escalate to a more expensive one only if the cheap model fails. Also called "model cascading" or "FrugalGPT pattern." |
| **OMLX** | Open Model Language eXchange — a local model serving platform. loopguard is designed to work with OMLX-served models (Qwen, Llama, DeepSeek) as the workhorse. |
| **OpenTelemetry (OTel)** | An open standard for distributed tracing and observability. loopguard emits OTel span events for escalation, allowing integration with Grafana, Datadog, Jaeger, etc. |
| **Prompt injection** | An attack where malicious instructions are embedded in data that an LLM processes, causing it to execute unintended actions. In loopguard's context, agent output may contain injected instructions that reach the escalation model. |
| **Deprecation warning** | A Python `DeprecationWarning` (or `FutureWarning`) emitted by an API that will be removed in a future version. Signals to users that they should migrate to the replacement API. |

---

## 20. References

| Reference | Relevance |
|---|---|
| [FrugalGPT (Stanford)](https://arxiv.org/abs/2305.05176) | Cascade routing — try cheap, escalate on failure. loopguard implements the escalation half. |
| The Harness Effect (Writer Inc.) | "The orchestration layer can move cost per task more than switching models." loopguard is part of that layer. |
| TrueFoundry cascade economics | "Cascade economics live or die on how often the cheap tier resolves the task." loopguard tracks escalation rate as the SLO. |
| "Don't Burn Your AI Budget" (Dev.to, published) | The escalation circuit breaker pattern, validated with 7 references. Origin of this project. |
| [Keep a Changelog](https://keepachangelog.com/) | Changelog format standard used for deprecation and release documentation. |
| [Semantic Versioning](https://semver.org/) | Versioning standard. Applied post-1.0.0; 0.x.y has relaxed rules. |
| [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) | Code of conduct standard for open-source projects. |
| Project description | Internal project notes (not public) |

---

## 21. Sign-off

| Role | Name | Date | Status |
|---|---|---|---|
| Product owner | Debashish Ghosal | 2026-07-10 19:48:54 PDT | **Approved** |
