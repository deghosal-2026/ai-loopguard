"""LangGraph callback handler integration.

This module provides LangGraphHandler, which monitors node execution
within a LangGraph graph for stuck patterns. It integrates with
loopguard's Guard to detect when an agent node is looping on the same
failure and escalate to a stronger model.

Two escalation modes (SPEC §4.2, OQ-7 resolution):
    - Auto (default): trigger fires → escalate directly → return output.
    - Interrupt: trigger fires → call LangGraph's native ``interrupt()``
      → user confirms → escalate → graph resumes via ``Command(resume)``.

Usage::

    from ai_loopguard import Guard
    from ai_loopguard.integrations.langgraph import LangGraphHandler

    guard = Guard(escalation_model=gpt4, workhorse_model_name="qwen")
    handler = LangGraphHandler(guard)

    # Use in a LangGraph node function
    def my_node(state):
        output = model.generate(state)
        return handler.on_step_end(state["step"], state, output)

Requires: pip install ai-loopguard[langgraph]
"""

from typing import TYPE_CHECKING, Any

from ai_loopguard._internal.state import StepRecord

if TYPE_CHECKING:
    from ai_loopguard.guard import Guard


class LangGraphHandler:
    """Monitors LangGraph node steps for stuck patterns and escalates.

    Connects loopguard's detection and escalation pipeline into a
    LangGraph graph. Call ``on_step_end()`` from within any node
    function that should be guarded.

    When on_escalate="interrupt" and a trigger fires, this handler
    uses LangGraph's native ``interrupt()`` to pause the graph and
    prompt the user. If the user confirms, escalation proceeds and
    the graph resumes via ``Command(resume=...)``.

    Attributes:
        guard: The loopguard Guard instance handling detection and
            escalation.

    """

    def __init__(self, guard: "Guard") -> None:
        """Initialise the handler with a loopguard Guard.

        Args:
            guard: A configured Guard instance. The guard's config
                controls trigger thresholds, escalation model, and
                interrupt behaviour.

        """
        self._guard = guard

    def on_step_end(
        self,
        step: int,
        state: dict[str, Any],
        output: Any,  # noqa: ANN401
        error: Exception | None = None,
    ) -> Any:  # noqa: ANN401
        """Record a step and check triggers after a node executes.

        Called after each LangGraph node step. Records the step in
        the guard's state, checks all enabled triggers, and escalates
        if one fires.

        Args:
            step: The current step number (zero-indexed).
            state: The full LangGraph state dict at this step.
            output: The node's output (return value).
            error: Optional exception if the node raised. When set,
                the step is recorded as a failure, enabling the
                repeated_error trigger.

        Returns:
            The original output if no trigger fires, or the escalation
            model's output if escalation occurs.

        """
        guard = self._guard

        # Capture pending metadata (set via guard.record_test_results /
        # guard.record_schema_valid before calling on_step_end)
        test_results = guard._pending_test_results
        schema_valid = guard._pending_schema_valid
        guard._pending_test_results = None
        guard._pending_schema_valid = None

        # Record the step in GuardState
        # Timestamp is 0.0 because LangGraph steps don't carry wall-clock
        # time; the guard's internal prompts use step_num for ordering.
        guard.state.add_step(
            StepRecord(
                step_num=step,
                output=output,
                error=error,
                error_type=type(error).__name__ if error else None,
                error_message=str(error) if error else None,
                test_results=test_results,
                schema_valid=schema_valid,
                timestamp=0.0,
            )
        )

        # Check triggers
        detector = guard._detector
        if detector is None:
            return output

        trigger_result = detector.check(guard.state)
        if trigger_result is None:
            return output

        # Trigger fired — handle escalation mode
        mgr = guard._escalation_mgr
        if mgr is None:
            return output

        # Check escalation cap first — before entering the interrupt/auto
        # branch so that capped events are logged consistently regardless
        # of which escalation mode is configured.
        if guard.state.escalation_cap_reached(
            guard.config.max_escalations_per_run
        ):
            return mgr._handle_cap(trigger_result)

        if guard.config.on_escalate == "interrupt":
            # Use LangGraph's native interrupt (OQ-7) — bypasses
            # EscalationManager's own interrupt check to avoid
            # double prompting.
            # Import is inside the branch because langgraph is an optional
            # dependency; the import at module level would crash if the
            # extra is not installed, even when interrupt mode is unused.
            from langgraph.types import Command, interrupt

            context = mgr._package_context(trigger_result)
            summary = mgr._packager.summary(context)
            user_response = interrupt(
                f"Agent stuck ({trigger_result.trigger_name}: "
                f"{trigger_result.detail}). "
                f"Escalate to "
                f"{getattr(guard.config.escalation_model, 'model_name', 'stronger model')}? "
                f"[y/n]: {summary}"
            )
            if isinstance(user_response, str) and user_response.strip().lower() == "y":
                escalated = mgr._do_escalate(trigger_result)
                # Command(resume=...) tells LangGraph to continue the
                # graph with the escalation output as the node's return
                # value — the graph's edge condition sees the output and
                # routes normally from there.
                return Command(resume=escalated)
            return output

        # Auto mode — escalate directly
        return mgr.escalate(trigger_result)
