"""Internal utility modules — not part of the public API.

Contains:
- state.py: GuardState, StepRecord, TriggerResult (per-execution state)
- history.py: BoundedHistory (thread-safe, bounded list wrapper)
- prompts.py: Default escalation prompt template

These modules are implementation details and may change without notice.
"""
