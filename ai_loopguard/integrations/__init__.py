"""Framework integrations for LangGraph, CrewAI, and OpenTelemetry.

Each integration is an optional extra:
- loopguard[langgraph] → LangGraphHandler (callback handler)
- loopguard[crewai] → CrewAIWrapper (step wrapper)
- loopguard[otel] → OTelEventHook (OpenTelemetry spans)

Core install has zero framework dependencies (FR-4.6).
"""

# Intentionally empty — all integration modules use lazy imports so that
# ``from ai_loopguard.integrations import ...`` only pulls in the optional
# dependency when the specific module is referenced.  This keeps the core
# install free of langgraph/crewai/opentelemetry at import time (FR-4.6).
# Users who do ``from ai_loopguard.integrations.langgraph import LangGraphHandler``
# still get the dep only when they explicitly request it.
