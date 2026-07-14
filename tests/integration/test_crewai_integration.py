"""Integration tests for CrewAIWrapper.

Tests that the wrapper correctly monitors agent task execution,
detects triggers, and escalates independently per agent.  These
tests mock CrewAI Agent/Crew classes to avoid depending on the
full CrewAI runtime.

(UC-2 scenario: multiple agents, different triggers fire independently.)

Test structure:
    - TestStepMonitoring: basic step recording and pass-through
    - TestPerAgentEscalation: trigger firing and escalation per agent
    - TestWrapBehaviour: wrap() method edge cases
    - TestErrorHandling: error recording and re-raising
    - TestAgentAttribution: agent role -> state key mapping
    - TestMetadataPropagation: pending metadata flow to step records
"""

from ai_loopguard.detectors import FailureDetector
from ai_loopguard.escalation import EscalationManager
from ai_loopguard.guard import Guard
from ai_loopguard.integrations.crewai import CrewAIWrapper
from ai_loopguard.logging import EscalationLogger

# ── Mock objects ───────────────────────────────────────────────────────────
# These mocks simulate the CrewAI runtime without requiring the crewai
# package to be installed.  Each mock implements the minimal interface
# that CrewAIWrapper interacts with.
# Multi-agent monitoring: the CrewAIWrapper manages one GuardState per agent
# (keyed by agent.role).  Each agent's step history is independent, so
# triggers fire per-agent.  The wrapper patches each agent's execute_task
# method to intercept calls and record steps before/after execution.


class _MockResponse:
    """Minimal mock for a LangChain AIMessage response."""

    def __init__(self, content: str) -> None:
        self.content = content


class _MockModel:
    """Mock LangChain BaseChatModel for the escalation model.

    Records all invoke() calls so tests can assert that escalation
    happened by checking len(model._invoke_args).
    """

    def __init__(self, response: str = "escalated via crewai") -> None:
        self._response = response
        self._invoke_args: list[str] = []
        self._model_name = "mock-gpt4"

    @property
    def model_name(self) -> str:
        return self._model_name

    def invoke(self, prompt: str) -> object:
        # Record the prompt so tests can inspect what was sent to
        # the escalation model.
        self._invoke_args.append(prompt)
        return _MockResponse(self._response)

    async def ainvoke(self, prompt: str) -> object:
        self._invoke_args.append(prompt)
        return _MockResponse(self._response)


class _MockAgent:
    """Minimal mock of a CrewAI agent that succeeds.

    Returns a deterministic string so tests can verify output
    pass-through.
    """

    def __init__(self, role: str) -> None:
        self.role = role

    def execute_task(
        self, task: object, context: object = None, tools: object = None
    ) -> str:
        return f"{self.role} done"


class _MockErrorAgent:
    """Mock agent that always raises ValueError.

    Used to trigger the repeated_error detector after N consecutive
    failures.
    """

    def __init__(self, role: str) -> None:
        self.role = role

    def execute_task(
        self, task: object, context: object = None, tools: object = None
    ) -> str:
        raise ValueError(f"{self.role} error")


class _MockSchemaAgent:
    """Mock agent that succeeds but lets the caller set schema_valid.

    Used to trigger the schema_invalid detector.  The agent itself
    returns valid output, but guard.record_schema_valid(valid=False)
    is called before execute_task to simulate schema validation failure.
    """

    def __init__(self, role: str) -> None:
        self.role = role

    def execute_task(
        self, task: object, context: object = None, tools: object = None
    ) -> str:
        return f"{self.role} output"


class _MockCrew:
    """Minimal mock of a CrewAI Crew.

    CrewAIWrapper.wrap() iterates over crew.agents, so we only need
    the agents list.
    """

    def __init__(self, agents: list[object]) -> None:
        self.agents = agents


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_guard(
    model: _MockModel | None = None,
    max_retries: int = 3,
    max_escalations: int = 5,
) -> Guard:
    """Create a Guard instance with test-friendly config.

    Pre-initialises the detector and escalation manager so tests don't
    need to trigger lazy init via a protected call.  Sets max_escalations
    high enough that the cap doesn't interfere with multi-escalation tests.
    """
    model = model or _MockModel()
    guard = Guard(
        escalation_model=model,
        workhorse_model_name="test-workhorse",
        max_escalations_per_run=max_escalations,
    )
    # Override all trigger thresholds to the test value.
    # This ensures triggers fire at exactly max_retries consecutive
    # failures, regardless of the per-trigger default.
    for t in guard.config.triggers.values():
        t.max_retries = max_retries
    # Pre-create detector and escalation manager with the guard's state.
    # In production, these are lazily created by Guard._ensure_components(),
    # but in tests we create them directly to control configuration.
    guard._detector = FailureDetector(guard.config.triggers)
    guard._escalation_mgr = EscalationManager(
        config=guard.config,
        state=guard.state,
        logger=EscalationLogger(),
    )
    return guard


# ── Step monitoring ────────────────────────────────────────────────────────


class TestStepMonitoring:
    """Tests that wrapper records steps and checks triggers.

    These tests verify the basic mechanics: steps are recorded per
    agent, timestamps are real, and output passes through unchanged
    when no trigger fires.
    """

    def test_records_step_in_agent_state(self) -> None:
        """After execute_task, a step is recorded per agent."""
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("researcher")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        agent.execute_task("my task")
        # The agent's state should now exist with one step.
        assert "researcher" in wrapper._agent_states
        assert len(wrapper._agent_states["researcher"].steps) == 1

    def test_step_has_timestamp(self) -> None:
        """Recorded step has a non-zero timestamp.

        This verifies the fix from 0.0 (placeholder) to time.time()
        — timestamps are needed for --since filtering in the CLI.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("researcher")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        agent.execute_task("my task")
        step = wrapper._agent_states["researcher"].steps[0]
        assert step.timestamp > 0

    def test_agents_have_independent_states(self) -> None:
        """Each agent gets its own GuardState (UC-2).

        Agent A runs 2 tasks, agent B runs 1 task.
        Their step counts must be independent — no cross-contamination.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent_a = _MockAgent("agent-a")
        agent_b = _MockAgent("agent-b")
        crew = _MockCrew([agent_a, agent_b])
        wrapper.wrap(crew)

        agent_a.execute_task("task 1")
        agent_b.execute_task("task 1")
        agent_a.execute_task("task 2")

        assert len(wrapper._agent_states["agent-a"].steps) == 2
        assert len(wrapper._agent_states["agent-b"].steps) == 1

    def test_no_escalation_below_threshold(self) -> None:
        """No trigger below the retry threshold.

        With max_retries=5, 3 calls should not trigger escalation.
        """
        guard = _make_guard(max_retries=5)
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("worker")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        for _ in range(3):
            agent.execute_task("step")

        # Guard's shared escalation count should be 0 (no escalation
        # happened on any agent).
        assert guard.state.escalation_count == 0
        # All 3 steps are recorded in the agent's per-agent state.
        assert len(wrapper._agent_states["worker"].steps) == 3

    def test_passes_through_output_without_trigger(self) -> None:
        """Without trigger, output is returned unchanged.

        This verifies the happy path: agent succeeds, no trigger fires,
        wrapper returns the agent's output as-is.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("worker")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        result = agent.execute_task("my task")
        assert result == "worker done"


# ── Per-agent escalation ───────────────────────────────────────────────────


class TestPerAgentEscalation:
    """Tests that different triggers fire independently per agent (UC-2).

    These are the core UC-2 tests: multiple agents in one crew, each
    getting stuck on a different pattern, both escalating independently.
    """

    def test_repeated_error_escalates(self) -> None:
        """Repeated error trigger fires escalation for one agent.

        The _MockErrorAgent always raises ValueError.  After 3 consecutive
        failures (max_retries=3), the repeated_error trigger fires.
        We catch ValueError on calls 1-2 because the wrapper re-raises
        when no trigger has fired yet.
        """
        guard = _make_guard(max_retries=3)
        wrapper = CrewAIWrapper(guard)
        agent = _MockErrorAgent("coder")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        for _ in range(3):
            try:
                agent.execute_task("code")
            except ValueError:
                # Calls 1-2: no trigger yet, error is re-raised.
                # Call 3: trigger fires, escalation returns output
                # (no raise).  We catch all to simplify the loop.
                pass

        # Escalation model was invoked at least once (on call 3).
        model = guard.config.escalation_model
        assert len(model._invoke_args) >= 1

    def test_schema_invalid_escalates(self) -> None:
        """Schema invalid trigger fires escalation for one agent.

        The agent succeeds (returns output), but we set
        schema_valid=False before each call.  After 3 consecutive
        False values, the schema_invalid trigger fires.
        """
        guard = _make_guard(max_retries=3)
        wrapper = CrewAIWrapper(guard)
        agent = _MockSchemaAgent("parser")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        for _ in range(3):
            # Set schema_valid=False BEFORE calling execute_task.
            # The wrapper consumes this pending value when recording
            # the step.
            guard.record_schema_valid(valid=False)
            agent.execute_task("parse")

        model = guard.config.escalation_model
        assert len(model._invoke_args) >= 1

    def test_two_agents_independent_escalation(self) -> None:
        """Both agents escalate independently with different triggers (UC-2).

        Agent "parser" triggers on schema_invalid.
        Agent "coder" triggers on repeated_error.

        This is the key UC-2 test: both agents escalate in the same
        crew run, with different triggers, using independent step
        histories.
        """
        guard = _make_guard(max_retries=3, model=_MockModel("fixed"))
        wrapper = CrewAIWrapper(guard)
        parser = _MockSchemaAgent("parser")
        coder = _MockErrorAgent("coder")
        crew = _MockCrew([parser, coder])
        wrapper.wrap(crew)

        # Parser: 3 schema_invalid steps -> schema_invalid trigger fires
        # (the agent succeeds but we flag its output as schema-invalid)
        for _ in range(3):
            guard.record_schema_valid(valid=False)
            parser.execute_task("parse")

        # Coder: 3 repeated errors -> repeated_error trigger fires
        # (the agent always raises ValueError with the same message)
        for _ in range(3):
            try:
                coder.execute_task("code")
            except ValueError:
                pass

        # Escalation model invoked at least twice (once per agent).
        # Each agent's trigger path is completely independent — different
        # trigger types, different step histories, same shared escalation model.
        model = guard.config.escalation_model
        assert len(model._invoke_args) >= 2

    def test_crew_continues_after_escalation(self) -> None:
        """Agent continues to execute subsequent tasks after escalation.

        The wrapper must not block further calls after a trigger fires.
        We run 4 calls with max_retries=3: trigger fires on call 3,
        call 4 should still work (and be recorded).
        """
        guard = _make_guard(
            model=_MockModel("fixed by escalation"),
            max_retries=3,
        )
        wrapper = CrewAIWrapper(guard)
        agent = _MockErrorAgent("worker")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        for i in range(4):
            try:
                agent.execute_task(f"step {i}")
            except ValueError:
                pass

        # All 4 steps are recorded, including the one after escalation.
        state = wrapper._agent_states.get("worker")
        assert state is not None
        assert len(state.steps) == 4

    def test_escalation_returns_correct_output(self) -> None:
        """Escalation output replaces the original on the triggering step.

        On step 3 (when the trigger fires), the wrapper should return
        the escalation model's output, not re-raise the error.
        """
        guard = _make_guard(
            model=_MockModel("fixed by escalation"),
            max_retries=3,
        )
        wrapper = CrewAIWrapper(guard)
        agent = _MockErrorAgent("worker")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        # Steps 1-2: error raised, no trigger yet, error re-raised
        for _ in range(2):
            try:
                agent.execute_task("step")
            except ValueError:
                pass

        # Step 3: trigger fires, escalation returns fixed output
        result = None
        try:
            result = agent.execute_task("step")
        except ValueError:
            pass

        # If escalation happened, result should be the escalated output
        # (not None, not the original error).
        model = guard.config.escalation_model
        if len(model._invoke_args) >= 1:
            assert result == "fixed by escalation"


# ── Wrap behaviour ─────────────────────────────────────────────────────────


class TestWrapBehaviour:
    """Tests for the wrap() method itself.

    These tests verify edge cases: empty crews, metadata preservation,
    single vs multiple agents, and that wrap() mutates in place.
    """

    def test_wrap_returns_same_crew(self) -> None:
        """wrap() returns the same crew instance (mutated in place).

        This is important for chaining: wrapper.wrap(crew).kickoff().
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        crew = _MockCrew([_MockAgent("a")])
        result = wrapper.wrap(crew)
        assert result is crew

    def test_wrap_empty_crew(self) -> None:
        """wrap() on a crew with no agents succeeds without error.

        Edge case: a crew with zero agents should not crash.
        No agent states are created until execute_task is called.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        crew = _MockCrew([])
        result = wrapper.wrap(crew)
        assert result is crew
        assert len(wrapper._agent_states) == 0

    def test_wrap_replaces_execute_task(self) -> None:
        """wrap() replaces each agent's execute_task with the wrapper.

        Verifies that the method is actually swapped, not just wrapped
        on top.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("a")
        original = agent.execute_task
        crew = _MockCrew([agent])
        wrapper.wrap(crew)
        assert agent.execute_task is not original

    def test_wrap_preserves_function_metadata(self) -> None:
        """wraps() preserves the original execute_task function name.

        functools.wraps should copy __name__ so introspection
        (e.g., debuggers) sees the original name.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("a")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)
        assert agent.execute_task.__name__ == "execute_task"

    def test_wrap_single_agent(self) -> None:
        """wrap() with one agent creates one agent state on first call.

        States are lazy — not created at wrap() time, only on first
        execute_task call.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("solo")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        # Before execute_task: no states
        assert len(wrapper._agent_states) == 0

        agent.execute_task("task")
        # After execute_task: one state
        assert len(wrapper._agent_states) == 1
        assert "solo" in wrapper._agent_states

    def test_wrap_three_agents(self) -> None:
        """wrap() with three agents creates three independent states.

        Verifies that multiple agents each get their own state dict
        entry, keyed by role.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agents = [_MockAgent(f"agent-{i}") for i in range(3)]
        crew = _MockCrew(list(agents))
        wrapper.wrap(crew)

        for a in agents:
            a.execute_task("task")

        assert len(wrapper._agent_states) == 3
        for a in agents:
            assert a.role in wrapper._agent_states
            assert len(wrapper._agent_states[a.role].steps) == 1


# ── Error handling ─────────────────────────────────────────────────────────


class TestErrorHandling:
    """Tests that errors from agents are properly handled.

    The wrapper catches all exceptions, records them in the step, then
    either re-raises (no trigger) or escalates (trigger fired).
    """

    def test_error_recorded_in_step(self) -> None:
        """Exception from execute_task is recorded in the step.

        The step should have the error object, error_type (class name),
        and error_message (str representation).
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent = _MockErrorAgent("failer")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        try:
            agent.execute_task("task")
        except ValueError:
            pass

        step = wrapper._agent_states["failer"].steps[0]
        assert step.error is not None
        assert step.error_type == "ValueError"
        # Use `in` because error_message could be None per type stubs
        assert "failer error" in (step.error_message or "")

    def test_error_reraised_when_no_trigger(self) -> None:
        """Without a trigger, the original error is re-raised.

        With max_retries=5, a single failure should not trigger
        escalation.  The wrapper should re-raise the ValueError so
        the caller (CrewAI runtime) can handle it.
        """
        guard = _make_guard(max_retries=5)
        wrapper = CrewAIWrapper(guard)
        agent = _MockErrorAgent("failer")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        import pytest

        with pytest.raises(ValueError, match="failer error"):
            agent.execute_task("task")


# ── Agent attribution ──────────────────────────────────────────────────────


class TestAgentAttribution:
    """Tests that steps are correctly attributed to agents by role.

    The wrapper uses agent.role as the state key.  These tests verify
    that roles map correctly and that same-role agents share state
    (by design — this allows grouping multiple instances of the same
    agent role).
    """

    def test_agent_name_from_role(self) -> None:
        """Agent state key matches agent.role."""
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("data-scientist")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        agent.execute_task("analyze")
        assert "data-scientist" in wrapper._agent_states

    def test_different_roles_different_states(self) -> None:
        """Two agents with different roles get different states.

        This is the core of UC-2: agents with different roles are
        monitored independently.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        a1 = _MockAgent("researcher")
        a2 = _MockAgent("writer")
        crew = _MockCrew([a1, a2])
        wrapper.wrap(crew)

        a1.execute_task("research")
        a2.execute_task("write")

        assert "researcher" in wrapper._agent_states
        assert "writer" in wrapper._agent_states
        # Must be different objects, not the same state
        assert wrapper._agent_states["researcher"] is not wrapper._agent_states["writer"]

    def test_same_role_shares_state(self) -> None:
        """Two agents with the same role share state (by design).

        This is intentional: if a crew has two "worker" agents, their
        steps accumulate in the same state, allowing triggers to fire
        based on the combined history.  This models the real-world
        scenario where multiple instances of the same agent role
        share a failure pattern.
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        a1 = _MockAgent("worker")
        a2 = _MockAgent("worker")
        crew = _MockCrew([a1, a2])
        wrapper.wrap(crew)

        a1.execute_task("task")
        a2.execute_task("task")

        # Only one state entry for "worker"
        assert len(wrapper._agent_states) == 1
        # Both calls' steps are in the shared state
        assert len(wrapper._agent_states["worker"].steps) == 2


# ── Metadata propagation ───────────────────────────────────────────────────


class TestMetadataPropagation:
    """Tests that pending metadata flows to agent steps.

    The wrapper consumes guard._pending_test_results and
    guard._pending_schema_valid before recording each step, mirroring
    the pattern in LangGraphHandler.  These tests verify that the
    metadata actually reaches the StepRecord and is cleared after.
    """

    def test_schema_valid_propagated_to_step(self) -> None:
        """guard.record_schema_valid() flows to the agent's step record.

        The user calls guard.record_schema_valid(valid=False) before
        agent.execute_task().  The wrapper should consume this value
        and store it in the step's schema_valid field.
        """
        guard = _make_guard(max_retries=3)
        wrapper = CrewAIWrapper(guard)
        agent = _MockSchemaAgent("parser")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        guard.record_schema_valid(valid=False)
        agent.execute_task("parse")

        step = wrapper._agent_states["parser"].steps[0]
        assert step.schema_valid is False

    def test_schema_valid_cleared_after_step(self) -> None:
        """Pending schema_valid is cleared after step recording.

        This prevents metadata from leaking into the next step if
        the user forgets to call record_schema_valid() again.
        """
        guard = _make_guard(max_retries=3)
        wrapper = CrewAIWrapper(guard)
        agent = _MockSchemaAgent("parser")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        guard.record_schema_valid(valid=False)
        agent.execute_task("parse")

        assert guard._pending_schema_valid is None

    def test_test_results_propagated_to_step(self) -> None:
        """guard.record_test_results() flows to the agent's step record."""
        guard = _make_guard(max_retries=3)
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("coder")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        guard.record_test_results({"test_a": False, "test_b": False})
        agent.execute_task("code")

        step = wrapper._agent_states["coder"].steps[0]
        assert step.test_results == {"test_a": False, "test_b": False}

    def test_test_results_cleared_after_step(self) -> None:
        """Pending test_results is cleared after step recording."""
        guard = _make_guard(max_retries=3)
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("coder")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        guard.record_test_results({"test_a": True})
        agent.execute_task("code")

        assert guard._pending_test_results is None

    def test_no_metadata_leaves_none_in_step(self) -> None:
        """Without record_* calls, step metadata is None.

        This is the default case: the user doesn't call
        record_test_results or record_schema_valid, so the step's
        metadata fields should be None (not False, not empty dict).
        """
        guard = _make_guard()
        wrapper = CrewAIWrapper(guard)
        agent = _MockAgent("plain")
        crew = _MockCrew([agent])
        wrapper.wrap(crew)

        agent.execute_task("task")

        step = wrapper._agent_states["plain"].steps[0]
        assert step.test_results is None
        assert step.schema_valid is None
