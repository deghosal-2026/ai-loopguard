"""OpenTelemetry event hook integration.

Requires: pip install ai-loopguard[otel]

This module provides OTelEventHook, which implements the EventHook
protocol and emits OpenTelemetry spans for every escalation, capped
escalation, and fail-open event.

Span attributes follow OpenTelemetry GenAI semantic conventions where
applicable, prefixed with ``gen_ai.system``, plus custom ``loopguard.*``
attributes for loopguard-specific telemetry (SPEC §6.3).

Usage::

    from ai_loopguard import Guard
    from ai_loopguard.integrations.otel import OTelEventHook

    guard = Guard(escalation_model=gpt4)
    guard.logger.register_hook(OTelEventHook())

Requires: pip install ai-loopguard[otel]
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # TracerProvider is only needed for the constructor type hint.
    # Importing opentelemetry at module level would break dependency
    # isolation — the core package must not require opentelemetry.
    from opentelemetry.sdk.trace import TracerProvider

    from ai_loopguard.logging import CappedEvent, EscalationEvent, FailOpenEvent


class OTelEventHook:
    """EventHook implementation that emits OpenTelemetry spans.

    Creates a span for every escalation, capped, and fail-open event
    dispatched by the EscalationLogger.  Each span carries structured
    attributes matching the event's fields (trigger type, retry count,
    model names, costs, etc.) plus a span event with the full JSON
    payload for detailed analysis.

    Attributes:
        _tracer: The OpenTelemetry tracer instance (lazy-created).

    """

    def __init__(
        self,
        tracer_provider: TracerProvider | None = None,
    ) -> None:
        """Initialise the hook.

        Args:
            tracer_provider: Optional OpenTelemetry TracerProvider to use.
                When None (default), uses the global provider via
                ``opentelemetry.trace.get_tracer()``.  Tests should pass
                a custom provider to capture spans in-memory.

        """
        # _tracer is lazy — not created until the first event arrives.
        # This avoids importing opentelemetry at construction time,
        # which would fail if the [otel] extra is not installed.
        self._tracer: Any = None
        self._tracer_provider = tracer_provider

    def _get_tracer(self) -> Any:  # noqa: ANN401
        """Lazy-import opentelemetry and create the tracer.

        Delayed import avoids pulling in opentelemetry at module load
        time, so ``from ai_loopguard.integrations.otel import OTelEventHook``
        is always safe (only raises at runtime if the extra is missing).

        Returns:
            An OpenTelemetry Tracer instance.

        """
        # Return cached tracer if already created — avoids repeated
        # get_tracer() calls which would create duplicate tracers.
        if self._tracer is not None:
            return self._tracer

        # Import inside the method so the [otel] extra is only required
        # when the hook is actually used, not at import time.
        from opentelemetry import trace

        if self._tracer_provider is not None:
            # Use the explicitly-provided provider (tests pass this to
            # capture spans in-memory without polluting the global state).
            self._tracer = trace.get_tracer(
                "loopguard", tracer_provider=self._tracer_provider
            )
        else:
            # Use the global tracer provider — this is the production
            # path where the user has configured OTel via standard
            # environment variables or programmatic setup.
            self._tracer = trace.get_tracer("ai_loopguard")
        return self._tracer

    def on_escalation(self, event: EscalationEvent) -> None:
        """Create a span for an escalation event.

        Span name: ``ai_loopguard.escalation``.

        Attributes (SPEC §6.3):
            - ``gen_ai.system`` = ``"loopguard"``
            - ``ai_loopguard.trigger_type``
            - ``ai_loopguard.retry_count``
            - ``ai_loopguard.workhorse_model``
            - ``ai_loopguard.escalation_model``
            - ``ai_loopguard.cost_per_task``
            - ``ai_loopguard.escalation_category`` (routing / failover)

        A span event with the full event dict is attached for detail.

        Args:
            event: The escalation event with trigger, cost, and model
                details.

        """
        tracer = self._get_tracer()
        # start_span (not start_as_current_span) because we don't need
        # this span to be the active span in a context — we just need
        # it exported.  This avoids polluting any parent context.
        span = tracer.start_span("ai_loopguard.escalation")

        # gen_ai.system is the OTel GenAI semantic convention for
        # identifying the AI system.  Set on every span type.
        span.set_attribute("gen_ai.system", "loopguard")

        # Core trigger attributes — these are the primary filtering
        # dimensions for querying escalations in a tracing backend.
        span.set_attribute("ai_loopguard.trigger_type", event.trigger_type)
        span.set_attribute("ai_loopguard.retry_count", event.retry_count)

        # Model attribution: which model got stuck vs which model was
        # escalated to.  Useful for cost analysis and model selection.
        span.set_attribute("ai_loopguard.workhorse_model", event.workhorse_model)
        span.set_attribute("ai_loopguard.escalation_model", event.escalation_model)

        # escalation_category distinguishes intentional routing
        # (routing) from availability failures (failover) per FR-3.3.
        span.set_attribute(
            "ai_loopguard.escalation_category", event.escalation_category
        )

        # Cost attribution for per-task cost analysis.
        span.set_attribute(
            "ai_loopguard.cost_per_task", event.total_task_cost_usd
        )

        # Attach the full event as a span event for detailed analysis.
        # This carries fields not surfaced as span attributes (e.g.,
        # success, sanitized, redacted_fields) so they're queryable
        # in the tracing backend without adding more span attributes.
        span.add_event("escalation", event.model_dump())
        span.end()

    def on_capped(self, event: CappedEvent) -> None:
        """Create a span for a capped escalation event.

        Span name: ``ai_loopguard.escalation.capped``.

        Args:
            event: The capped event with trigger details.

        """
        tracer = self._get_tracer()
        span = tracer.start_span("ai_loopguard.escalation.capped")

        # Capped events carry less data than escalation events —
        # only trigger type and retry count, plus the default message.
        # We still attach the full payload as a span event so downstream
        # dashboards can drill into cap-related fields.
        span.set_attribute("gen_ai.system", "loopguard")
        span.set_attribute("ai_loopguard.trigger_type", event.trigger_type)
        span.set_attribute("ai_loopguard.retry_count", event.retry_count)

        # Full payload as span event for detail (includes the
        # "Escalation cap reached" message field).
        span.add_event("capped", event.model_dump())
        span.end()

    def on_fail_open(self, event: FailOpenEvent) -> None:
        """Create a span for a fail-open event.

        Span name: ``ai_loopguard.fail_open``.

        Args:
            event: The fail-open event with error and mode details.

        """
        tracer = self._get_tracer()
        span = tracer.start_span("ai_loopguard.fail_open")

        # Fail-open events carry the trigger type, the error message
        # from the failed escalation model call, and which fail-open
        # strategy was used (raise_original, return_last_output,
        # return_sentinel).
        span.set_attribute("gen_ai.system", "loopguard")
        span.set_attribute("ai_loopguard.trigger_type", event.trigger_type)
        span.set_attribute(
            "ai_loopguard.fail_open_mode", event.fail_open_mode
        )
        span.set_attribute("ai_loopguard.error_message", event.error_message)

        # Full payload as span event for detail.
        span.add_event("fail_open", event.model_dump())
        span.end()
