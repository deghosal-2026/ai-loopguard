"""CrewAI step wrapper integration.

Requires: pip install ai-loopguard[crewai]

This module provides CrewAIWrapper, which wraps each agent's task
execution in a CrewAI crew to monitor for stuck patterns using
loopguard's Guard.

Each agent gets independent monitoring (UC-2 scenario):
different triggers can fire for different agents simultaneously.

Marked "experimental" per PRD §17 risk — CrewAI has frequent breaking
changes, so the integration API may evolve.
"""

from __future__ import annotations

import functools
import time
from typing import TYPE_CHECKING, Any

from ai_loopguard._internal.state import GuardState, StepRecord

if TYPE_CHECKING:
    # Guard is only needed for type hints; the actual import would
    # create a circular dependency at runtime since Guard imports
    # integrations lazily.
    from ai_loopguard.guard import Guard


class CrewAIWrapper:
    """Wraps CrewAI agent step execution for stuck pattern detection.

    Connects loopguard's detection and escalation pipeline into a
    CrewAI crew. Call ``wrap(crew)`` to instrument all agents in the
    crew.  Each agent is monitored independently with its own step
    history, enabling different triggers to fire for different agents
    simultaneously (UC-2).

    Usage::

        from ai_loopguard import Guard
        from ai_loopguard.integrations.crewai import CrewAIWrapper

        guard = Guard(escalation_model=gpt4, workhorse_model_name="qwen")
        wrapper = CrewAIWrapper(guard)
        crew = wrapper.wrap(crew)
        result = crew.kickoff()

    Attributes:
        guard: The loopguard Guard instance handling detection and
            escalation.

    Note:
        Marked "experimental" — CrewAI has frequent breaking changes,
        so the integration API may evolve.

    Thread safety:
        The state-swapping in ``_wrap_agent_step`` is NOT thread-safe
        for concurrent agent execution.  CrewAI v0.50+ runs agents
        sequentially by default, so this is acceptable for v0.1.0.
        If concurrent execution is needed, use separate Guard instances
        per agent instead of a shared wrapper.

    """

    def __init__(self, guard: Guard) -> None:
        """Initialise the wrapper with a loopguard Guard.

        Args:
            guard: A configured Guard instance.  The guard's config
                controls trigger thresholds, escalation model, and
                interrupt behaviour.

        """
        self._guard = guard
        # Per-agent state map: agent role -> GuardState.
        # This is the key mechanism for UC-2 (independent agent monitoring).
        # Without per-agent isolation, steps from different agents would
        # bleed into a single history and triggers would fire incorrectly.
        # A separate Guard instance per agent would also work but would
        # require the user to configure multiple Guards; the wrapper
        # handles this transparently with a shared Guard + per-agent states.
        self._agent_states: dict[str, GuardState] = {}

    def wrap(self, crew: Any) -> Any:  # noqa: ANN401
        """Wrap each agent in the crew with step monitoring.

        Iterates over ``crew.agents`` and wraps each agent's
        ``execute_task`` method to record steps, check triggers, and
        escalate if needed.

        Args:
            crew: A CrewAI Crew instance.

        Returns:
            The same crew instance with wrapped agents.

        """
        # Mutate agents in place — this is the CrewAI convention.
        # The crew object itself is not copied; we return it for
        # fluent chaining (wrapper.wrap(crew).kickoff()).
        for agent in crew.agents:
            original = agent.execute_task
            agent.execute_task = self._wrap_agent_step(original, agent)
        return crew

    def _wrap_agent_step(
        self,
        original_step: Any,  # noqa: ANN401
        agent: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Wrap an agent's step method with guard monitoring.

        Args:
            original_step: The original ``execute_task`` method.
            agent: The CrewAI agent being wrapped.

        Returns:
            A wrapped version that records steps and checks triggers
            independently for this agent.

        """
        guard = self._guard
        # Use the agent's role as the key — CrewAI agents are identified
        # by their role string, which is unique within a crew.
        agent_name: str = getattr(agent, "role", str(agent))

        @functools.wraps(original_step)
        def wrapper(
            task: Any,  # noqa: ANN401
            context: Any = None,  # noqa: ANN401
            tools: Any = None,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> Any:  # noqa: ANN401
            # Lazily create per-agent state on the first call for this
            # agent.  Avoids pre-allocating states for agents that never
            # execute (e.g., configured but not assigned tasks).
            # _ensure_components() is NOT called here because we only
            # need the detector/mgr if a trigger fires — delaying
            # component init until the trigger check path saves imports.
            agent_state = self._agent_states.get(agent_name)
            if agent_state is None:
                agent_state = GuardState(
                    max_history_steps=guard.config.max_history_steps,
                )
                self._agent_states[agent_name] = agent_state

            # Catch ALL exceptions, not just specific types.  The
            # repeated_error trigger needs to see any failure type
            # (ValueError, RuntimeError, custom exceptions) to detect
            # repeated patterns.  Narrower catching would miss non-standard
            # exceptions from CrewAI internals.
            try:
                output = original_step(task, context, tools, **kwargs)
                error = None
            except Exception as exc:
                output = None
                error = exc

            # Consume the guard's pending metadata.  These fields are set
            # by guard.record_test_results() between step calls but are NOT
            # automatically applied to the per-agent state.  We manually
            # transfer them to the per-agent StepRecord and clear them so
            # they don't leak to the next agent's step.
            test_results = guard._pending_test_results
            schema_valid = guard._pending_schema_valid
            guard._pending_test_results = None
            guard._pending_schema_valid = None

            # Record the step in the per-agent state, not the guard's
            # shared state.  This ensures triggers evaluate only this
            # agent's history, not a mix of all agents.
            agent_state.add_step(
                StepRecord(
                    step_num=len(agent_state.steps),
                    output=output,
                    error=error,
                    error_type=type(error).__name__ if error else None,
                    error_message=str(error) if error else None,
                    test_results=test_results,
                    schema_valid=schema_valid,
                    # Use real wall-clock time for time-based analysis
                    # (e.g., --since filtering in the CLI).
                    timestamp=time.time(),
                )
            )

            # Check triggers using the per-agent state.
            # The detector is shared (it only holds config, no state),
            # but we pass the agent's state so triggers see only this
            # agent's step history.
            # Lazy-init the guard's detector and escalation manager if
            # they haven't been created yet (e.g., when using the wrapper
            # directly without @guard.protect).
            detector, mgr = guard._ensure_components()

            trigger_result = detector.check(agent_state)
            if trigger_result is None:
                # No trigger fired — re-raise the error if there was one,
                # otherwise return the successful output.
                if error:
                    raise error
                return output

            # A trigger fired — escalate (mgr is guaranteed non-None
            # because _ensure_components() was called above).

            # Temporarily swap the EscalationManager's state to the
            # per-agent state for context packaging, cap checking, and
            # fail-open output.  NOT thread-safe for concurrent agents —
            # CrewAI v0.50+ runs agents sequentially, so this is safe
            # for v0.1.0.  For concurrent agents, use separate Guard
            # instances per agent.
            original_state = mgr._state
            mgr._state = agent_state
            try:
                return mgr.escalate(trigger_result)
            finally:
                # Restore even if escalate() raises — prevents state
                # leakage between agents in subsequent calls.
                mgr._state = original_state

        return wrapper
