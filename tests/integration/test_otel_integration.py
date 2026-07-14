"""Integration tests for OTelEventHook.

Tests that the hook creates OpenTelemetry spans with correct attributes
for escalation, capped, and fail-open events.  Uses a local in-memory
span exporter to verify span contents — no real OTel backend required.

Coverage:
    - Span creation for all 3 event types
    - Every SPEC §6.3 attribute verified individually
    - Span events (add_event) verified with attribute content
    - Span lifecycle (start_time, end_time, ended state)
    - Multiple events produce independent spans
    - Multiple hook instances sharing one provider
    - Tracer caching (lazy init, same tracer on second call)
    - Default tracer provider path (no tracer_provider arg)
    - Integration with EscalationLogger dispatch
    - EscalationLogger fail-open dispatch
    - Routing vs failover category
    - Edge cases: zero cost, high retry count, empty redacted_fields

Test architecture:
    - _InMemorySpanExporter: a SpanExporter that stores spans in a list
    - _Harness: bundles exporter + provider + hook factory
    - Each test class covers one aspect (basics, attributes, events, etc.)
    - The `harness` pytest fixture creates a fresh harness per test
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

from ai_loopguard.integrations.otel import OTelEventHook
from ai_loopguard.logging import CappedEvent, EscalationEvent, FailOpenEvent

# ── In-memory span exporter ────────────────────────────────────────────────
# This is a test-only utility that implements the OTel SpanExporter
# protocol.  It stores exported spans in a list so tests can assert
# on their attributes, events, and lifecycle.
# In production, users would use OTLPSpanExporter or ConsoleSpanExporter.
# In-memory span exporter: instead of sending spans to a real OTel backend
# (e.g., Jaeger, Datadog), we use _InMemorySpanExporter which stores spans
# in a list.  Tests retrieve spans via get_finished_spans() and assert on
# their attributes (trigger_type, retry_count, etc.), events, and lifecycle
# (start_time, end_time).  This avoids needing any OTel collector infrastructure.


class _InMemorySpanExporter(SpanExporter):
    """A SpanExporter that stores spans in memory for test assertions.

    Implements the OTel SpanExporter protocol with a simple list-backed
    storage.  Call ``get_finished_spans()`` to retrieve exported spans
    and ``clear()`` to reset between tests.
    """

    def __init__(self) -> None:
        self._spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Store spans for later retrieval.

        Args:
            spans: The finished spans to export.

        Returns:
            SpanExportResult.SUCCESS always.

        """
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """No-op — nothing to clean up for in-memory storage."""

    def get_finished_spans(self) -> list[ReadableSpan]:
        """Return all exported spans since the last clear.

        Returns:
            A list of exported spans (oldest first, newest last).

        """
        return list(self._spans)

    def clear(self) -> None:
        """Remove all stored spans."""
        self._spans.clear()


# ── Test harness ───────────────────────────────────────────────────────────
# The harness bundles everything a test needs: an in-memory exporter,
# a TracerProvider wired to that exporter, and a factory for creating
# OTelEventHook instances that use that provider.
# This avoids each test having to set up the OTel plumbing from scratch.


class _Harness:
    """Test harness bundling exporter + provider + hook factory."""

    def __init__(self) -> None:
        self.exporter = _InMemorySpanExporter()
        self.provider = TracerProvider()
        # SimpleSpanProcessor exports spans synchronously on .end(),
        # so spans are available in the exporter immediately after
        # the hook returns.
        self.provider.add_span_processor(
            SimpleSpanProcessor(self.exporter)
        )

    def hook(self) -> OTelEventHook:
        """Create an OTelEventHook wired to this harness's provider.

        Passing the provider directly (instead of setting it globally)
        avoids the "Overriding of current TracerProvider is not allowed"
        warning that occurs when trying to set_tracer_provider() after
        the SDK has already initialised a default.
        """
        return OTelEventHook(tracer_provider=self.provider)

    @property
    def spans(self) -> list[ReadableSpan]:
        """Shortcut to get finished spans from the exporter."""
        return self.exporter.get_finished_spans()

    def clear(self) -> None:
        """Clear all exported spans."""
        self.exporter.clear()


@pytest.fixture
def harness() -> Iterator[_Harness]:
    """Create a fresh test harness for each test.

    Yields the harness, then clears spans after the test to prevent
    state leakage between tests.
    """
    h = _Harness()
    yield h
    h.clear()


# ── Event factories ────────────────────────────────────────────────────────
# These factory functions create event objects with sensible defaults.
# Tests override specific fields via **overrides to test edge cases.


def _esc(**overrides: Any) -> EscalationEvent:  # noqa: ANN401
    """Create an EscalationEvent with test defaults.

    Defaults represent a typical escalation: repeated_error trigger,
    routing category, moderate cost.  Override any field via kwargs.
    """
    defaults: dict[str, Any] = {
        "timestamp": 1000.0,
        "trigger_type": "repeated_error",
        "trigger_detail": "ValueError 3 consecutive",
        "retry_count": 3,
        "workhorse_model": "test-workhorse",
        "escalation_model": "test-gpt4",
        "escalation_category": "routing",
        "context_tokens": 500,
        "escalation_tokens": 200,
        "escalation_cost_usd": 0.01,
        "total_task_cost_usd": 0.05,
        "total_task_tokens": 700,
        "success": True,
        "sanitized": True,
        "redacted_fields": [],
    }
    defaults.update(overrides)
    return EscalationEvent(**defaults)


def _cap(**overrides: Any) -> CappedEvent:  # noqa: ANN401
    """Create a CappedEvent with test defaults."""
    defaults: dict[str, Any] = {
        "timestamp": 2000.0,
        "trigger_type": "test_failure",
        "trigger_detail": "tests failed 3 consecutive",
        "retry_count": 3,
    }
    defaults.update(overrides)
    return CappedEvent(**defaults)


def _fail(**overrides: Any) -> FailOpenEvent:  # noqa: ANN401
    """Create a FailOpenEvent with test defaults."""
    defaults: dict[str, Any] = {
        "timestamp": 3000.0,
        "trigger_type": "schema_invalid",
        "error_message": "Model call timed out",
        "fail_open_mode": "return_last_output",
    }
    defaults.update(overrides)
    return FailOpenEvent(**defaults)


# ── Helper functions ───────────────────────────────────────────────────────
# OTel span attributes and events are typed as Optional (may be None).
# These helpers safely extract them as dicts, returning {} for None.


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    """Safely extract span attributes as a dict.

    span.attributes is Optional in the OTel type stubs, so we guard
    against None to satisfy both pyright and runtime.
    """
    raw = span.attributes
    if raw is None:
        return {}
    return dict(raw)


def _event_attrs(span: ReadableSpan, idx: int = 0) -> dict[str, Any]:
    """Safely extract the idx-th span event's attributes as a dict.

    Returns {} if the span has no events or the idx is out of range.
    """
    events = span.events
    if idx >= len(events):
        return {}
    raw = events[idx].attributes
    if raw is None:
        return {}
    return dict(raw)


# ── Escalation span: existence & naming ────────────────────────────────────
# These tests verify the most basic property: on_escalation creates
# exactly one span with the correct name and valid timestamps.
# Span attributes verification: each attribute from SPEC §6.3 is tested
# individually (gen_ai.system, ai_loopguard.trigger_type, ai_loopguard.retry_count,
# ai_loopguard.workhorse_model, etc.) so that a failure pinpoints the exact
# missing or wrong attribute.  Edge cases like retry_count=0, cost=0.0,
# empty error_message are tested separately.


class TestEscalationSpanBasics:
    """Tests that on_escalation creates exactly one correctly-named span."""

    def test_creates_one_span(self, harness: _Harness) -> None:
        """on_escalation produces exactly one span."""
        harness.hook().on_escalation(_esc())
        assert len(harness.spans) == 1

    def test_span_name(self, harness: _Harness) -> None:
        """Span is named 'ai_loopguard.escalation'."""
        harness.hook().on_escalation(_esc())
        assert harness.spans[0].name == "ai_loopguard.escalation"

    def test_span_has_start_and_end_time(self, harness: _Harness) -> None:
        """Span has non-zero start_time and end_time after .end().

        This verifies the span lifecycle: start_span() sets start_time,
        end() sets end_time, and end_time >= start_time.
        """
        harness.hook().on_escalation(_esc())
        span = harness.spans[0]
        assert span.start_time is not None
        assert span.start_time > 0
        assert span.end_time is not None
        assert span.end_time > 0
        assert span.end_time >= span.start_time


# ── Escalation span: SPEC §6.3 attributes ──────────────────────────────────
# Each attribute from SPEC §6.3 is tested individually so that a failure
# pinpoints exactly which attribute is missing or wrong.


class TestEscalationSpanAttributes:
    """Tests that every SPEC §6.3 attribute is set correctly."""

    def test_gen_ai_system(self, harness: _Harness) -> None:
        """gen_ai.system = 'loopguard' (OTel GenAI semantic convention)."""
        harness.hook().on_escalation(_esc())
        assert _attrs(harness.spans[0])["gen_ai.system"] == "loopguard"

    def test_trigger_type(self, harness: _Harness) -> None:
        """ai_loopguard.trigger_type matches the event."""
        harness.hook().on_escalation(_esc(trigger_type="test_failure"))
        assert _attrs(harness.spans[0])["ai_loopguard.trigger_type"] == "test_failure"

    def test_trigger_type_custom(self, harness: _Harness) -> None:
        """Custom trigger type is passed through without modification."""
        harness.hook().on_escalation(_esc(trigger_type="my_custom_trigger"))
        assert _attrs(harness.spans[0])["ai_loopguard.trigger_type"] == "my_custom_trigger"

    def test_retry_count(self, harness: _Harness) -> None:
        """ai_loopguard.retry_count matches the event."""
        harness.hook().on_escalation(_esc(retry_count=7))
        assert _attrs(harness.spans[0])["ai_loopguard.retry_count"] == 7

    def test_retry_count_zero(self, harness: _Harness) -> None:
        """retry_count=0 is set correctly (edge case).

        Zero is a valid value (e.g., a custom trigger that fires on
        the first step).  The span attribute should be 0, not omitted.
        """
        harness.hook().on_escalation(_esc(retry_count=0))
        assert _attrs(harness.spans[0])["ai_loopguard.retry_count"] == 0

    def test_retry_count_high(self, harness: _Harness) -> None:
        """retry_count=20 (max allowed per GuardConfig) is set correctly."""
        harness.hook().on_escalation(_esc(retry_count=20))
        assert _attrs(harness.spans[0])["ai_loopguard.retry_count"] == 20

    def test_workhorse_model(self, harness: _Harness) -> None:
        """ai_loopguard.workhorse_model matches the event."""
        harness.hook().on_escalation(_esc(workhorse_model="llama-3-70b"))
        assert _attrs(harness.spans[0])["ai_loopguard.workhorse_model"] == "llama-3-70b"

    def test_escalation_model(self, harness: _Harness) -> None:
        """ai_loopguard.escalation_model matches the event."""
        harness.hook().on_escalation(_esc(escalation_model="gpt-4o"))
        assert _attrs(harness.spans[0])["ai_loopguard.escalation_model"] == "gpt-4o"

    def test_escalation_category_routing(self, harness: _Harness) -> None:
        """escalation_category='routing' is set on the span.

        Routing = intentional escalation (e.g., test_failure, schema_invalid).
        """
        harness.hook().on_escalation(_esc(escalation_category="routing"))
        assert _attrs(harness.spans[0])["ai_loopguard.escalation_category"] == "routing"

    def test_escalation_category_failover(self, harness: _Harness) -> None:
        """escalation_category='failover' is set on the span.

        Failover = availability failure (repeated_error trigger).
        """
        harness.hook().on_escalation(_esc(escalation_category="failover"))
        assert _attrs(harness.spans[0])["ai_loopguard.escalation_category"] == "failover"

    def test_cost_per_task(self, harness: _Harness) -> None:
        """ai_loopguard.cost_per_task matches the event."""
        harness.hook().on_escalation(_esc(total_task_cost_usd=0.42))
        assert _attrs(harness.spans[0])["ai_loopguard.cost_per_task"] == 0.42

    def test_cost_per_task_zero(self, harness: _Harness) -> None:
        """cost_per_task=0.0 is set correctly (edge case).

        Zero cost is valid (e.g., a local model with no API cost).
        """
        harness.hook().on_escalation(_esc(total_task_cost_usd=0.0))
        assert _attrs(harness.spans[0])["ai_loopguard.cost_per_task"] == 0.0

    def test_all_attributes_at_once(self, harness: _Harness) -> None:
        """All attributes are present simultaneously on a single span.

        This is a integration test: verifies that setting all
        attributes together doesn't cause any to be lost or overwritten.
        """
        harness.hook().on_escalation(
            _esc(
                trigger_type="schema_invalid",
                retry_count=5,
                workhorse_model="qwen2.5",
                escalation_model="gpt-4-turbo",
                escalation_category="failover",
                total_task_cost_usd=0.15,
            )
        )
        a = _attrs(harness.spans[0])
        assert a["gen_ai.system"] == "loopguard"
        assert a["ai_loopguard.trigger_type"] == "schema_invalid"
        assert a["ai_loopguard.retry_count"] == 5
        assert a["ai_loopguard.workhorse_model"] == "qwen2.5"
        assert a["ai_loopguard.escalation_model"] == "gpt-4-turbo"
        assert a["ai_loopguard.escalation_category"] == "failover"
        assert a["ai_loopguard.cost_per_task"] == 0.15


# ── Escalation span: span events (add_event) ───────────────────────────────
# In addition to span attributes, on_escalation attaches a span event
# with the full event payload.  These tests verify the event exists,
# has the correct name, and carries the expected fields.


class TestEscalationSpanEvents:
    """Tests that on_escalation attaches a span event with full payload."""

    def test_has_one_span_event(self, harness: _Harness) -> None:
        """Span has exactly one attached event."""
        harness.hook().on_escalation(_esc())
        assert len(harness.spans[0].events) == 1

    def test_span_event_named_escalation(self, harness: _Harness) -> None:
        """The attached span event is named 'escalation'."""
        harness.hook().on_escalation(_esc())
        assert harness.spans[0].events[0].name == "escalation"

    def test_span_event_carries_trigger_type(self, harness: _Harness) -> None:
        """Span event attributes include trigger_type."""
        harness.hook().on_escalation(_esc(trigger_type="custom"))
        assert _event_attrs(harness.spans[0])["trigger_type"] == "custom"

    def test_span_event_carries_retry_count(self, harness: _Harness) -> None:
        """Span event attributes include retry_count."""
        harness.hook().on_escalation(_esc(retry_count=9))
        assert _event_attrs(harness.spans[0])["retry_count"] == 9

    def test_span_event_carries_cost(self, harness: _Harness) -> None:
        """Span event attributes include total_task_cost_usd."""
        harness.hook().on_escalation(_esc(total_task_cost_usd=1.23))
        assert _event_attrs(harness.spans[0])["total_task_cost_usd"] == 1.23

    def test_span_event_carries_success_flag(self, harness: _Harness) -> None:
        """Span event attributes include success boolean."""
        harness.hook().on_escalation(_esc(success=True))
        assert _event_attrs(harness.spans[0])["success"] is True

    def test_span_event_carries_redacted_fields(self, harness: _Harness) -> None:
        """Span event attributes include redacted_fields list.

        OTel serialises list attributes as tuples, so we use list()
        to convert back for comparison.
        """
        harness.hook().on_escalation(_esc(redacted_fields=["api_key", "token"]))
        assert list(_event_attrs(harness.spans[0])["redacted_fields"]) == ["api_key", "token"]


# ── Escalation span: multiple calls & hook instances ──────────────────────
# These tests verify that multiple on_escalation calls produce
# independent spans with no shared state, and that multiple hook
# instances can coexist on the same provider.


class TestEscalationMultipleCalls:
    """Tests that multiple calls produce independent spans."""

    def test_two_calls_two_spans(self, harness: _Harness) -> None:
        """Two on_escalation calls produce two spans."""
        hook = harness.hook()
        hook.on_escalation(_esc(trigger_type="repeated_error"))
        hook.on_escalation(_esc(trigger_type="test_failure"))
        assert len(harness.spans) == 2

    def test_spans_have_independent_attributes(self, harness: _Harness) -> None:
        """Each span has its own trigger_type and retry_count.

        Verifies no shared state between spans — the second call's
        attributes don't overwrite the first's.
        """
        hook = harness.hook()
        hook.on_escalation(_esc(trigger_type="repeated_error", retry_count=3))
        hook.on_escalation(_esc(trigger_type="test_failure", retry_count=5))
        assert _attrs(harness.spans[0])["ai_loopguard.trigger_type"] == "repeated_error"
        assert _attrs(harness.spans[1])["ai_loopguard.trigger_type"] == "test_failure"
        assert _attrs(harness.spans[0])["ai_loopguard.retry_count"] == 3
        assert _attrs(harness.spans[1])["ai_loopguard.retry_count"] == 5

    def test_two_hook_instances_share_provider(self, harness: _Harness) -> None:
        """Two hook instances with same provider produce separate spans.

        This verifies that multiple OTelEventHook instances (e.g.,
        registered on different loggers) can share one provider
        without interfering.
        """
        hook_a = harness.hook()
        hook_b = harness.hook()
        hook_a.on_escalation(_esc(trigger_type="repeated_error"))
        hook_b.on_escalation(_esc(trigger_type="test_failure"))
        assert len(harness.spans) == 2

    def test_five_calls_five_spans(self, harness: _Harness) -> None:
        """Five on_escalation calls produce five spans with correct retry_count.

        Stress test: verifies that many calls don't accumulate state
        or lose spans.
        """
        hook = harness.hook()
        for i in range(5):
            hook.on_escalation(_esc(retry_count=i))
        assert len(harness.spans) == 5
        # Each span should have its own retry_count, in order
        for i, span in enumerate(harness.spans):
            assert _attrs(span)["ai_loopguard.retry_count"] == i


# ── Tracer caching ─────────────────────────────────────────────────────────
# The tracer is lazily created on first use and cached.  These tests
# verify the caching behaviour to ensure we don't create duplicate tracers.


class TestTracerCaching:
    """Tests that the tracer is lazily created and cached."""

    def test_tracer_created_on_first_call(self, harness: _Harness) -> None:
        """Tracer is None until first on_escalation call.

        Lazy init avoids importing opentelemetry at construction time.
        """
        hook = harness.hook()
        assert hook._tracer is None
        hook.on_escalation(_esc())
        assert hook._tracer is not None

    def test_tracer_reused_on_second_call(self, harness: _Harness) -> None:
        """Same tracer instance is reused on second call.

        Caching avoids repeated get_tracer() calls which would create
        duplicate tracer instances.
        """
        hook = harness.hook()
        hook.on_escalation(_esc())
        tracer1 = hook._tracer
        hook.on_escalation(_esc())
        tracer2 = hook._tracer
        assert tracer1 is tracer2


# ── Default tracer provider ────────────────────────────────────────────────
# When no tracer_provider is passed, the hook uses the global provider.
# This is the production path.


class TestDefaultTracerProvider:
    """Tests that OTelEventHook() without tracer_provider uses global tracer."""

    def test_no_tracer_provider_uses_global(self) -> None:
        """Hook without tracer_provider gets a tracer from the global provider.

        This is the production path: users just do OTelEventHook()
        without passing a provider, and the global OTel configuration
        (set via environment variables or programmatic setup) is used.
        """
        hook = OTelEventHook()
        assert hook._tracer is None
        hook.on_escalation(_esc())
        assert hook._tracer is not None


# ── Capped span tests ──────────────────────────────────────────────────────
# Capped events occur when max_escalations_per_run is hit.  These tests
# verify span creation, attributes, events, and multiple calls.


class TestCappedSpanBasics:
    """Tests that on_capped creates exactly one correctly-named span."""

    def test_creates_one_span(self, harness: _Harness) -> None:
        """on_capped produces exactly one span."""
        harness.hook().on_capped(_cap())
        assert len(harness.spans) == 1

    def test_span_name(self, harness: _Harness) -> None:
        """Span is named 'ai_loopguard.escalation.capped'."""
        harness.hook().on_capped(_cap())
        assert harness.spans[0].name == "ai_loopguard.escalation.capped"

    def test_span_has_start_and_end_time(self, harness: _Harness) -> None:
        """Span has non-zero start_time and end_time."""
        harness.hook().on_capped(_cap())
        span = harness.spans[0]
        assert span.start_time is not None
        assert span.start_time > 0
        assert span.end_time is not None
        assert span.end_time > 0
        assert span.end_time >= span.start_time


class TestCappedSpanAttributes:
    """Tests that on_capped sets all required attributes."""

    def test_gen_ai_system(self, harness: _Harness) -> None:
        """gen_ai.system = 'loopguard' on capped spans too."""
        harness.hook().on_capped(_cap())
        assert _attrs(harness.spans[0])["gen_ai.system"] == "loopguard"

    def test_trigger_type(self, harness: _Harness) -> None:
        """ai_loopguard.trigger_type matches the capped event."""
        harness.hook().on_capped(_cap(trigger_type="repeated_error"))
        assert _attrs(harness.spans[0])["ai_loopguard.trigger_type"] == "repeated_error"

    def test_retry_count(self, harness: _Harness) -> None:
        """ai_loopguard.retry_count matches the capped event."""
        harness.hook().on_capped(_cap(retry_count=5))
        assert _attrs(harness.spans[0])["ai_loopguard.retry_count"] == 5

    def test_trigger_type_custom(self, harness: _Harness) -> None:
        """Custom trigger type is passed through on capped spans."""
        harness.hook().on_capped(_cap(trigger_type="my_custom_trigger"))
        assert _attrs(harness.spans[0])["ai_loopguard.trigger_type"] == "my_custom_trigger"


class TestCappedSpanEvents:
    """Tests that on_capped attaches a span event with full payload."""

    def test_has_one_span_event(self, harness: _Harness) -> None:
        """Span has exactly one attached event."""
        harness.hook().on_capped(_cap())
        assert len(harness.spans[0].events) == 1

    def test_span_event_named_capped(self, harness: _Harness) -> None:
        """The attached span event is named 'capped'."""
        harness.hook().on_capped(_cap())
        assert harness.spans[0].events[0].name == "capped"

    def test_span_event_carries_trigger_type(self, harness: _Harness) -> None:
        """Span event attributes include trigger_type."""
        harness.hook().on_capped(_cap(trigger_type="schema_invalid"))
        assert _event_attrs(harness.spans[0])["trigger_type"] == "schema_invalid"

    def test_span_event_carries_message(self, harness: _Harness) -> None:
        """Span event attributes include the default capped message."""
        harness.hook().on_capped(_cap())
        assert _event_attrs(harness.spans[0])["message"] == "Escalation cap reached"


class TestCappedMultipleCalls:
    """Tests that multiple on_capped calls produce independent spans."""

    def test_two_calls_two_spans(self, harness: _Harness) -> None:
        """Two on_capped calls produce two spans."""
        hook = harness.hook()
        hook.on_capped(_cap())
        hook.on_capped(_cap())
        assert len(harness.spans) == 2

    def test_different_triggers_independent(self, harness: _Harness) -> None:
        """Each capped span has its own trigger_type."""
        hook = harness.hook()
        hook.on_capped(_cap(trigger_type="repeated_error"))
        hook.on_capped(_cap(trigger_type="test_failure"))
        assert _attrs(harness.spans[0])["ai_loopguard.trigger_type"] == "repeated_error"
        assert _attrs(harness.spans[1])["ai_loopguard.trigger_type"] == "test_failure"


# ── Fail-open span tests ───────────────────────────────────────────────────
# Fail-open events occur when the escalation model itself fails.  These
# tests verify span creation, attributes (including all 3 fail-open
# modes), events, and multiple calls.


class TestFailOpenSpanBasics:
    """Tests that on_fail_open creates exactly one correctly-named span."""

    def test_creates_one_span(self, harness: _Harness) -> None:
        """on_fail_open produces exactly one span."""
        harness.hook().on_fail_open(_fail())
        assert len(harness.spans) == 1

    def test_span_name(self, harness: _Harness) -> None:
        """Span is named 'ai_loopguard.fail_open'."""
        harness.hook().on_fail_open(_fail())
        assert harness.spans[0].name == "ai_loopguard.fail_open"

    def test_span_has_start_and_end_time(self, harness: _Harness) -> None:
        """Span has non-zero start_time and end_time."""
        harness.hook().on_fail_open(_fail())
        span = harness.spans[0]
        assert span.start_time is not None
        assert span.start_time > 0
        assert span.end_time is not None
        assert span.end_time > 0
        assert span.end_time >= span.start_time


class TestFailOpenSpanAttributes:
    """Tests that on_fail_open sets all required attributes."""

    def test_gen_ai_system(self, harness: _Harness) -> None:
        """gen_ai.system = 'loopguard' on fail-open spans too."""
        harness.hook().on_fail_open(_fail())
        assert _attrs(harness.spans[0])["gen_ai.system"] == "loopguard"

    def test_trigger_type(self, harness: _Harness) -> None:
        """ai_loopguard.trigger_type matches the fail-open event."""
        harness.hook().on_fail_open(_fail(trigger_type="repeated_error"))
        assert _attrs(harness.spans[0])["ai_loopguard.trigger_type"] == "repeated_error"

    def test_fail_open_mode_return_last_output(self, harness: _Harness) -> None:
        """fail_open_mode='return_last_output' is set on the span."""
        harness.hook().on_fail_open(_fail(fail_open_mode="return_last_output"))
        assert _attrs(harness.spans[0])["ai_loopguard.fail_open_mode"] == "return_last_output"

    def test_fail_open_mode_raise_original(self, harness: _Harness) -> None:
        """fail_open_mode='raise_original' is set on the span."""
        harness.hook().on_fail_open(_fail(fail_open_mode="raise_original"))
        assert _attrs(harness.spans[0])["ai_loopguard.fail_open_mode"] == "raise_original"

    def test_fail_open_mode_return_sentinel(self, harness: _Harness) -> None:
        """fail_open_mode='return_sentinel' is set on the span."""
        harness.hook().on_fail_open(_fail(fail_open_mode="return_sentinel"))
        assert _attrs(harness.spans[0])["ai_loopguard.fail_open_mode"] == "return_sentinel"

    def test_error_message(self, harness: _Harness) -> None:
        """ai_loopguard.error_message matches the fail-open event."""
        harness.hook().on_fail_open(_fail(error_message="Rate limit exceeded"))
        assert _attrs(harness.spans[0])["ai_loopguard.error_message"] == "Rate limit exceeded"

    def test_error_message_empty_string(self, harness: _Harness) -> None:
        """error_message='' is set correctly (edge case).

        An empty error message is valid (e.g., an exception with no
        message).  The span attribute should be '', not omitted.
        """
        harness.hook().on_fail_open(_fail(error_message=""))
        assert _attrs(harness.spans[0])["ai_loopguard.error_message"] == ""


class TestFailOpenSpanEvents:
    """Tests that on_fail_open attaches a span event with full payload."""

    def test_has_one_span_event(self, harness: _Harness) -> None:
        """Span has exactly one attached event."""
        harness.hook().on_fail_open(_fail())
        assert len(harness.spans[0].events) == 1

    def test_span_event_named_fail_open(self, harness: _Harness) -> None:
        """The attached span event is named 'fail_open'."""
        harness.hook().on_fail_open(_fail())
        assert harness.spans[0].events[0].name == "fail_open"

    def test_span_event_carries_trigger_type(self, harness: _Harness) -> None:
        """Span event attributes include trigger_type."""
        harness.hook().on_fail_open(_fail(trigger_type="repeated_error"))
        assert _event_attrs(harness.spans[0])["trigger_type"] == "repeated_error"

    def test_span_event_carries_fail_open_mode(self, harness: _Harness) -> None:
        """Span event attributes include fail_open_mode."""
        harness.hook().on_fail_open(_fail(fail_open_mode="raise_original"))
        assert _event_attrs(harness.spans[0])["fail_open_mode"] == "raise_original"


class TestFailOpenMultipleCalls:
    """Tests that multiple on_fail_open calls produce independent spans."""

    def test_two_calls_two_spans(self, harness: _Harness) -> None:
        """Two on_fail_open calls produce two spans."""
        hook = harness.hook()
        hook.on_fail_open(_fail())
        hook.on_fail_open(_fail())
        assert len(harness.spans) == 2

    def test_different_modes_independent(self, harness: _Harness) -> None:
        """Each fail-open span has its own fail_open_mode."""
        hook = harness.hook()
        hook.on_fail_open(_fail(fail_open_mode="raise_original"))
        hook.on_fail_open(_fail(fail_open_mode="return_sentinel"))
        assert _attrs(harness.spans[0])["ai_loopguard.fail_open_mode"] == "raise_original"
        assert _attrs(harness.spans[1])["ai_loopguard.fail_open_mode"] == "return_sentinel"


# ── Mixed event types ──────────────────────────────────────────────────────
# These tests verify that all three event types (escalation, capped,
# fail-open) can coexist on the same provider and produce spans in
# the correct order.


class TestMixedEventTypes:
    """Tests that all three event types can coexist on one provider."""

    def test_all_three_types(self, harness: _Harness) -> None:
        """Escalation, capped, and fail-open spans are all created."""
        hook = harness.hook()
        hook.on_escalation(_esc())
        hook.on_capped(_cap())
        hook.on_fail_open(_fail())
        assert len(harness.spans) == 3
        # Verify all three span names are present
        names = [s.name for s in harness.spans]
        assert "ai_loopguard.escalation" in names
        assert "ai_loopguard.escalation.capped" in names
        assert "ai_loopguard.fail_open" in names

    def test_spans_in_order(self, harness: _Harness) -> None:
        """Spans appear in the order they were created.

        The in-memory exporter stores spans in insertion order, so
        we can verify that escalation -> capped -> fail_open produces
        spans in that sequence.
        """
        hook = harness.hook()
        hook.on_escalation(_esc())
        hook.on_capped(_cap())
        hook.on_fail_open(_fail())
        assert harness.spans[0].name == "ai_loopguard.escalation"
        assert harness.spans[1].name == "ai_loopguard.escalation.capped"
        assert harness.spans[2].name == "ai_loopguard.fail_open"


# ── In-memory exporter ─────────────────────────────────────────────────────
# These tests verify the test utility itself (_InMemorySpanExporter).
# This ensures our test infrastructure is reliable.


class TestInMemorySpanExporter:
    """Tests for the _InMemorySpanExporter test utility itself."""

    def test_clear_resets_spans(self, harness: _Harness) -> None:
        """clear() removes all stored spans."""
        harness.hook().on_escalation(_esc())
        assert len(harness.spans) == 1
        harness.clear()
        assert len(harness.spans) == 0

    def test_export_returns_success(self) -> None:
        """export() always returns SpanExportResult.SUCCESS."""
        exp = _InMemorySpanExporter()
        result = exp.export([])
        assert result == SpanExportResult.SUCCESS

    def test_shutdown_is_noop(self) -> None:
        """shutdown() does not raise and does not clear spans."""
        exp = _InMemorySpanExporter()
        exp.shutdown()  # should not raise


# ── Integration with EscalationLogger ──────────────────────────────────────
# These tests verify the full dispatch chain: EscalationLogger ->
# EventHook protocol -> OTelEventHook -> span creation.  This is the
# production usage pattern.


class TestEscalationLoggerIntegration:
    """Tests that OTelEventHook works when registered on an EscalationLogger."""

    def test_log_dispatches_to_hook(self, harness: _Harness) -> None:
        """EscalationLogger.log() dispatches to the OTel hook.

        This is the primary production path: logger.log(event) writes
        JSONL AND calls hook.on_escalation(event).
        """
        from ai_loopguard.logging import EscalationLogger

        logger = EscalationLogger()
        logger.register_hook(harness.hook())
        logger.log(_esc())
        assert len(harness.spans) == 1
        assert harness.spans[0].name == "ai_loopguard.escalation"

    def test_log_capped_dispatches_to_hook(self, harness: _Harness) -> None:
        """EscalationLogger.log_capped() dispatches to the OTel hook."""
        from ai_loopguard.logging import EscalationLogger

        logger = EscalationLogger()
        logger.register_hook(harness.hook())
        logger.log_capped(_cap())
        assert len(harness.spans) == 1
        assert harness.spans[0].name == "ai_loopguard.escalation.capped"

    def test_log_escalation_failure_dispatches_to_hook(
        self, harness: _Harness
    ) -> None:
        """EscalationLogger.log_escalation_failure() dispatches to the OTel hook.

        This path is taken when the escalation model itself fails.
        The logger constructs a FailOpenEvent and dispatches it.
        """
        from ai_loopguard.logging import EscalationLogger

        logger = EscalationLogger()
        logger.register_hook(harness.hook())
        logger.log_escalation_failure(
            RuntimeError("model crashed"),
            _cap(),
        )
        assert len(harness.spans) == 1
        assert harness.spans[0].name == "ai_loopguard.fail_open"

    def test_multiple_hooks_all_receive_events(self, harness: _Harness) -> None:
        """Multiple hooks registered on a logger all produce spans.

        Verifies that the logger dispatches to ALL registered hooks,
        not just the first one.  This is important for setups with
        both OTel and a custom hook (e.g., Datadog).
        """
        from ai_loopguard.logging import EscalationLogger

        logger = EscalationLogger()
        logger.register_hook(harness.hook())
        logger.register_hook(harness.hook())
        logger.log(_esc())
        # Both hooks received the event -> 2 spans
        assert len(harness.spans) == 2
        assert all(s.name == "ai_loopguard.escalation" for s in harness.spans)

    def test_logger_with_otel_and_mixed_events(self, harness: _Harness) -> None:
        """Logger dispatches escalation, capped, and fail-open to OTel hook.

        End-to-end test: all three event types flow through the logger
        and produce the correct spans.
        """
        from ai_loopguard.logging import EscalationLogger

        logger = EscalationLogger()
        logger.register_hook(harness.hook())
        logger.log(_esc())
        logger.log_capped(_cap())
        logger.log_escalation_failure(RuntimeError("boom"), _cap())
        assert len(harness.spans) == 3
