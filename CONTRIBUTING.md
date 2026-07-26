# Contributing to ai-loopguard

Thanks for your interest in contributing! This guide covers everything you need to get started, from cloning the repo to landing a pull request.

> **Package:** `ai-loopguard` on PyPI · **Import:** `ai_loopguard` · **CLI:** `loopguard` · **Repo:** `deghosal-2026/ai-loopguard`

---

## Getting started

### Prerequisites

- Python **3.10+** (tested through 3.14)
- `git`
- A fork of [`deghosal-2026/ai-loopguard`](https://github.com/deghosal-2026/ai-loopguard)

### Clone and install

```bash
git clone https://github.com/<your-username>/ai-loopguard.git
cd ai-loopguard
pip install -e ".[dev]"
```

This installs the package in editable mode along with the full dev toolchain: `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-snapshot`, `ruff`, `mypy`, `pip-audit`, and `pip-licenses`.

### Verify your setup

```bash
# Run the full non-perf test suite with coverage
pytest

# Lint
ruff check

# Typecheck
mypy --strict ai_loopguard/ tests/
```

If all three pass, you're ready to contribute.

---

## Development workflow

### Branch naming

Create a branch off `main` using one of these prefixes:

| Prefix | Use for |
| --- | --- |
| `feature/` | New functionality or triggers |
| `fix/` | Bug fixes |
| `docs/` | Documentation-only changes |
| `refactor/` | Code reorganization with no behavior change |
| `test/` | Test additions or improvements |
| `chore/` | Tooling, deps, CI, release tasks |

Examples: `feature/hallucination-trigger`, `fix/redactor-aws-key`, `docs/contributing`.

### Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/). The allowed types are:

```
feat:     a new feature (triggers, integrations, CLI commands)
fix:      a bug fix
docs:     documentation only
refactor: code change that neither fixes a bug nor adds a feature
test:     adding or correcting tests
chore:    build, CI, tooling, deps, release tasks
```

Format:

```
<type>: <imperative summary under 72 chars>

<optional body explaining why and what>

<optional footer: BREAKING CHANGE:, Closes #123>
```

Examples:

```
feat: add hallucination_cycle trigger with 3-lookback window
fix: redactor now strips AWS session tokens correctly
docs: add trigger guide for custom callbacks
test: cover interrupt mode with negative consent path
```

## Testing Policy

- **Every new feature must include tests.** Major functionality added to the codebase must be accompanied by automated tests in the test suite.
- **Coverage targets:** Aim for ≥80% line coverage on new code. Pull requests that reduce overall coverage below the fail_under threshold will be flagged.
- **Test types:** Prefer unit tests for business logic, integration tests for API routes.
- **Running tests:** `pytest` — ensure all tests pass before opening a PR.
- **Test data:** Use fixtures and factories rather than production data. Never commit real credentials or tokens.

### Push and open a PR

1. Push your branch to your fork.
2. Open a pull request against `main` on `deghosal-2026/ai-loopguard`.
3. Link the related issue in the PR body (`Closes #123` or `Refs #123`).
4. Ensure CI is green before requesting review.

---

## Code standards

| Standard | Tool | Requirement |
| --- | --- | --- |
| Linting | `ruff check` | Zero errors. Line length **100**. Rules: `E, F, I, N, UP, D, ANN`. |
| Types | `mypy --strict ai_loopguard/ tests/` | Zero errors. `python_version = "3.10"`. |
| Coverage | `pytest --cov=ai_loopguard` | **≥ 90%** enforced via `--cov-fail-under=90`. |
| Warnings | `pytest` | No warnings allowed — fix the root cause, don't suppress. |
| Docstrings | `D` ruleset | Required on **all** public functions, classes, and methods. |

### Style notes

- Target `py310` — don't use syntax or stdlib features introduced after 3.10 unless guarded.
- Keep functions focused; prefer composition over inheritance.
- Use Pydantic v2 models for all configuration.
- No `# type: ignore` without a justification comment. `unused-ignore` is disabled.

---

## Testing

The suite is organized into four layers, selected via pytest markers.

| Layer | Marker | Directory | What it covers |
| --- | --- | --- | --- |
| Unit | `@pytest.mark.unit` | `tests/unit/` | Individual components in isolation: detectors, context packager, redactor, config, state, cost tracker, logging, CLI. |
| Integration | `@pytest.mark.integration` | `tests/integration/` | Cross-component flows: sync/async `@guard.protect`, LangGraph handler, CrewAI wrapper, OTel hook. |
| End-to-end | `@pytest.mark.e2e` | `tests/e2e/` | Full escalation pipelines: trigger → package → sanitize → redact → model invoke → log. |
| Performance | `@pytest.mark.perf` | `tests/perf/` | Benchmarks with regression detection against `benchmarks/baseline.json`. |

### Running tests

```bash
# Default: all non-perf tests with coverage (enforced ≥90%)
pytest

# Single layer
pytest -m unit
pytest -m integration
pytest -m e2e

# Performance benchmarks (skipped by default)
pytest -m perf --benchmark-env=local

# A specific file
pytest tests/unit/test_detectors.py -v

# With a marker and verbose
pytest -m "unit and not slow" -v
```

Markers are registered in `pyproject.toml` under `[tool.pytest.ini_options]` and `--strict-markers` is on — typos in marker names will fail the run.

### Adding tests

1. **Pick the right layer.** If it tests one function in isolation → `unit`. If it crosses components but uses stubs/fakes → `integration`. If it exercises the full escalation pipeline → `e2e`. If it measures timing/throughput → `perf`.
2. **Add the marker.** Every test module and/or test function should carry the appropriate marker:
   ```python
   import pytest

   @pytest.mark.unit
   def test_repeated_error_triggers_after_threshold():
       ...
   ```
3. **Use async where needed.** `asyncio_mode = "auto"` is set — async test functions work without `@pytest.mark.asyncio`.
4. **Keep coverage above 90%.** If your change adds uncovered lines, add tests or adjust the suite. CI fails below the threshold.

---

## Project structure

```
ai-loopguard/
├── ai_loopguard/               # Source package
│   ├── __init__.py             # Public API exports (Guard, GuardConfig, ...)
│   ├── config.py               # GuardConfig, TriggerConfig (Pydantic v2)
│   ├── guard.py                # Guard class, @guard.protect decorator
│   ├── detectors.py            # FailureDetector — trigger checks
│   ├── context.py              # ContextPackager, Sanitizer, Redactor
│   ├── escalation.py           # EscalationManager — full pipeline
│   ├── cost.py                 # CostTracker — per-task cost, escalation rate
│   ├── logging.py              # Structured escalation event logging
│   ├── exceptions.py           # GuardError and subclasses
│   ├── cli.py                  # `loopguard` CLI (Click-based)
│   ├── _internal/              # Internal helpers (not public API)
│   └── integrations/
│       ├── langgraph.py        # LangGraphHandler
│       ├── crewai.py           # CrewAIWrapper
│       └── otel.py             # OTelEventHook
├── tests/
│   ├── unit/                   # @pytest.mark.unit
│   ├── integration/            # @pytest.mark.integration
│   ├── e2e/                    # @pytest.mark.e2e
│   ├── perf/                   # @pytest.mark.perf
│   ├── conftest.py             # Shared fixtures
│   └── test_dependency_isolation.py
├── docs/                       # Specs, plans, trigger/integration guides
├── benchmarks/                 # baseline.json, history.jsonl, findings
├── pyproject.toml
└── README.md
```

---

## Adding a new trigger

Triggers detect a specific stuck-loop pattern and are evaluated by `FailureDetector`. To add one:

### 1. Add a `TriggerConfig`

In `ai_loopguard/config.py`, add a Pydantic config model with validated constraints:

```python
class HallucinationCycleConfig(TriggerConfig):
    max_retries: int = Field(default=3, ge=1, le=20)
    lookback_window: int = Field(default=3, ge=2, le=10)
```

Register it on `GuardConfig` so users can enable it via `triggers={...}`.

### 2. Implement the check in `FailureDetector`

In `ai_loopguard/detectors.py`, add a method that inspects `GuardState` step history and returns a trigger result:

```python
def _check_hallucination_cycle(self, state: GuardState) -> TriggerResult | None:
    ...
```

Wire it into the detector's evaluation loop alongside the existing checks (`repeated_error`, `test_failure`, `schema_invalid`, `custom`).

### 3. Add unit tests

In `tests/unit/test_detectors.py`, cover:

- Triggers at exactly the threshold.
- Does **not** trigger below the threshold.
- Resets correctly after `guard.reset()`.
- Handles empty / short history edge cases.

### 4. Add an e2e test

In `tests/e2e/`, add a test that runs the full pipeline: trigger fires → context is packaged → escalation model is invoked → event is logged. Use a fake model with a `.invoke()` stub.

### 5. Update docs

Document the trigger in `docs/triggers.md` (create if missing) — what it detects, configuration options, defaults, and an example `Guard` setup.

---

## Adding a new integration

Integrations wrap `Guard` for a specific framework. The pattern: a handler or wrapper class that calls into the guard at the right lifecycle point.

### 1. Create the integration module

```bash
ai_loopguard/integrations/<name>.py
```

Implement a handler or wrapper that accepts a `Guard` instance and exposes framework-appropriate hooks (e.g., `on_step_end`, `wrap`, event callbacks).

### 2. Add an optional dependency extra

In `pyproject.toml` under `[project.optional-dependencies]`:

```toml
<name> = ["<framework-package>>=X.Y,<X.Y+1"]
```

Also add it to the `all` extra so it's included in dev/evaluation installs.

### 3. Implement the handler/wrapper

Follow the existing patterns in `langgraph.py`, `crewai.py`, and `otel.py`. The integration should:

- Accept a `Guard` instance in its constructor.
- Call `guard.record_*` / `guard.protect` / detector hooks at framework lifecycle points.
- Preserve the framework's native types and return values.
- Fail open by default — never break the host framework if the guard errors.

### 4. Add integration tests

In `tests/integration/`, add a test file that exercises the handler with a fake `Guard` and framework stubs. Cover:

- Normal step completion.
- Trigger firing → escalation.
- Fail-open behavior on guard internal error.

### 5. Add e2e tests

In `tests/e2e/`, add a test that runs the integration against a minimal but real framework flow and asserts the escalation event is logged.

### 6. Write an integration guide

Add `docs/integrations/<name>.md` with: install command, minimal example, configuration options, and known limitations.

---

## Performance benchmarks

Performance regressions are caught automatically. The benchmark layer lives in `tests/perf/` and is selected with `@pytest.mark.perf`.

### Running benchmarks

```bash
pytest -m perf --benchmark-env=local
```

Benchmarks are **excluded from the default `pytest` run** so day-to-day development stays fast.

### How regression detection works

- **`benchmarks/baseline.json`** — the pinned reference medians for each benchmark. Checked into the repo.
- **`benchmarks/history.jsonl`** — append-only log of every benchmark run (timestamp, environment, medians).
- **Threshold:** a benchmark **fails** if its adjusted median is **> 25% slower** than the baseline median.
- **Updating the baseline:** only when an intentional performance change lands. Open a PR that updates `baseline.json` and includes the `history.jsonl` entry justifying the new numbers.

Current benchmarks and targets (from v0.1.0):

| Benchmark | Target |
| --- | --- |
| Detection overhead | 1 ms |
| Context packaging | 100 ms |
| Import time | 200 ms |
| Escalation full flow | 50 ms |
| Redaction throughput | 10 ms |
| Sanitization throughput | 5 ms |
| Memory footprint | 50 MB |

See `benchmarks/performance-benchmarks.md` for full methodology and `docs/performance-test-plan.md` for the plan.

---

## Issue and PR guidelines

### Issues

- Use the GitHub issue templates (bug report, feature request, trigger proposal).
- Bug reports must include: Python version, `ai-loopguard` version, minimal repro, expected vs actual behavior.
- Feature requests should describe the **use case** first, the proposed API second.

### Pull requests

- **Link the issue** in the PR description (`Closes #N` or `Refs #N`).
- **Features require tests.** A PR adding behavior without test coverage will not merge.
- **Features require docs.** If you add a trigger, integration, or CLI flag, update the relevant `docs/` page and `README.md` if user-facing.
- **Keep PRs focused.** One feature or fix per PR. Split mixed changes into stacked PRs.
- **CI must be green.** `pytest`, `ruff check`, and `mypy --strict` all pass before review.
- **Coverage must not drop below 90%.**

---

## Code of conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/) code of conduct. See [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) for the full text. By participating, you agree to uphold its terms.
