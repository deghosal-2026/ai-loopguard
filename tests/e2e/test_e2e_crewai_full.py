"""E2E: CrewAI integration — multi-agent crew, both get stuck and escalate.

Verifies:
- CrewAIWrapper wraps multiple agents
- Each agent is monitored independently
- Different triggers can fire for different agents
- Crew continues after all escalations
"""

from typing import Any

from tests.e2e.conftest import MockModel, make_guard


class MockCrewAgent:
    """Minimal mock of a CrewAI agent for E2E testing."""

    def __init__(self, name: str) -> None:
        """Store the agent name and initialise the call counter."""
        self.name = name
        self.call_count: int = 0

    def execute_task(self, task: str, context: Any = None, tools: Any = None, **kwargs: Any) -> str:  # type: ignore[misc]  # noqa: ANN401
        """Execute a task; some agents are stuck."""
        self.call_count += 1
        raise ValueError(f"{self.name} error on {task}")


class MockCrew:
    """Minimal mock of a CrewAI Crew for E2E testing."""

    def __init__(self, agents: list[MockCrewAgent]) -> None:
        """Store the list of mock agents."""
        self.agents = agents

    def kickoff(self) -> dict[str, str]:
        """Simulate crew execution — all agents run their tasks."""
        results: dict[str, str] = {}
        for agent in self.agents:
            try:
                agent.execute_task("task")
                results[agent.name] = "success"
            except ValueError:
                results[agent.name] = "failed"
        return results


class TestCrewAIE2E:
    """Full end-to-end flow for CrewAI integration."""

    def test_multi_agent_monitoring(self) -> None:
        """Two agents both stuck → both trigger independently."""
        model = MockModel(response="fixed by escalation")
        guard = make_guard(model=model)

        from ai_loopguard.integrations.crewai import CrewAIWrapper

        wrapper = CrewAIWrapper(guard=guard)
        agent1 = MockCrewAgent("agent-alpha")
        agent2 = MockCrewAgent("agent-beta")

        # Wrap the agents' step execution manually
        agent1_step = wrapper._wrap_agent_step(agent1.execute_task, agent1.name)
        agent2_step = wrapper._wrap_agent_step(agent2.execute_task, agent2.name)

        # 2-agent independent escalation: both agents raise ValueError on every
        # call.  After 3 calls each, both hit the repeated_error trigger.
        # Each agent escalates independently — the escalation model is called
        # twice (once per agent).  This tests that per-agent state tracking
        # doesn't conflate agents' step histories.
        for _ in range(3):
            try:
                agent1_step("task")
            except ValueError:
                pass
            try:
                agent2_step("task")
            except ValueError:
                pass

        # Both agents should have triggered escalation
        assert len(model._invoke_args) == 2
        # Escalation count is tracked per-agent, not on guard.state
        for state in wrapper._agent_states.values():
            assert state.escalation_count == 1

    def test_one_agent_stuck_one_ok(self) -> None:
        """Only the stuck agent triggers; the ok agent does not."""
        model = MockModel(response="fixed")
        guard = make_guard(model=model)

        from ai_loopguard.integrations.crewai import CrewAIWrapper

        wrapper = CrewAIWrapper(guard=guard)
        stuck_agent = MockCrewAgent("stuck-agent")

        stuck_step = wrapper._wrap_agent_step(stuck_agent.execute_task, "stuck-agent")
        ok_step = wrapper._wrap_agent_step(
            lambda task, context=None, tools=None, **kwargs: "ok result",  # type: ignore[arg-type,misc]
            "ok-agent",
        )

        # 1 stuck + 1 ok scenario: one agent repeatedly fails, the other
        # always succeeds.  Only the stuck agent should trigger escalation.
        # This tests that per-agent state isolation prevents "leakage" —
        # the ok agent's success steps don't fill the stuck agent's window.
        for _ in range(3):
            try:
                stuck_step("task")
            except ValueError:
                pass
            ok_step("task")

        assert len(model._invoke_args) == 1
        assert wrapper._agent_states["stuck-agent"].escalation_count == 1
        assert wrapper._agent_states["ok-agent"].escalation_count == 0
