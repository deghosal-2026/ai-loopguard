"""Thread-safe state tracking for guarded executions.

GuardState holds the step-by-step history for a single guarded call.
It is designed to be safe for concurrent access (threading.Lock) so
that a single Guard instance can be shared across multiple agent runs.

Key design decisions:
- One GuardState per guarded call (not per Guard instance)
- History is bounded by max_history_steps (T3 mitigation)
- All mutations go through add_step() which acquires the lock
- StepRecord is a plain dataclass (no validation needed at this layer)
"""

from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class StepRecord:
    """A single step in a guarded execution.

    Records what the agent produced (output), whether it errored,
    optional test/schema metadata, and cost tracking fields.

    Fields:
        step_num: Zero-indexed step number within the guarded call.
        output: The return value of the guarded function for this step.
            None if the function raised an exception.
        error: The exception object if the function raised, else None.
        error_type: Exception class name (e.g., "ValueError").
        error_message: The exception's str() representation.
        test_results: Dict of test_name -> pass/fail. Used by the
            test_failure trigger (FR-1.2). None if not applicable.
        schema_valid: Whether the output passed schema validation.
            Used by the schema_invalid trigger (FR-1.3). None if N/A.
        tokens_used: Tokens consumed by this step's model call.
        cost_usd: Dollar cost of this step's model call.
        timestamp: Unix timestamp of when this step completed.

    """

    # step_num is the only required field; everything else defaults so
    # callers can construct partial records without boilerplate.
    step_num: int
    output: Any  # Agent outputs are arbitrary types (str, dict, etc.)
    # error/error_type/error_message split avoids serialising full tracebacks
    # into log events and prompt templates — str(error) suffices for context.
    error: Exception | None = None
    error_type: str | None = None
    error_message: str | None = None
    # test_results and schema_valid are None by default because most steps
    # don't run tests or schema checks; triggers short-circuit on None.
    test_results: dict[str, bool] | None = None
    schema_valid: bool | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    # Default 0.0 because not all callers provide real timestamps (e.g.,
    # LangGraphHandler passes 0.0 explicitly).  A zero value signals
    # "timestamp not collected" rather than epoch 1970 — consumers should
    # check for 0.0 and handle accordingly.
    timestamp: float = 0.0


@dataclass
class TriggerResult:
    """Result of a trigger evaluation — returned when a trigger fires.

    Provides context about which trigger fired, a human-readable detail,
    and the retry count that crossed the threshold. This is consumed by
    the EscalationManager to build the escalation context and log event.

    Fields:
        trigger_name: Which trigger fired (e.g., "repeated_error").
        detail: Human-readable description for logging and prompts.
        retry_count: The number of consecutive failures that triggered
            this escalation.

    """

    trigger_name: str
    detail: str
    retry_count: int

    def to_dict(self) -> dict[str, str | int]:
        """Serialise to a plain dict for logging and context packaging."""
        return {
            "trigger_name": self.trigger_name,
            "detail": self.detail,
            "retry_count": self.retry_count,
        }


@dataclass
class GuardState:
    """Per-execution state. One instance per guarded call. Thread-safe.

    A fresh GuardState is created at the start of each protected call
    (via @guard.protect or @guard.aprotect). It accumulates step records
    until the function succeeds or a trigger fires.

    Fields:
        steps: Ordered list of StepRecord, bounded by max_history_steps.
        escalation_count: Number of escalations that have occurred in
            this guarded call. Capped by max_escalations_per_run.
        total_tokens: Cumulative tokens across all steps.
        total_cost_usd: Cumulative cost across all steps.
        max_history_steps: Hard cap on retained history (T3 mitigation).
            When exceeded, oldest records are discarded.

    """

    # Steps are appended via add_step(), never mutated in-place, so readers
    # holding a reference see a consistent snapshot — no copy-on-read needed.
    steps: list[StepRecord] = field(default_factory=list[StepRecord])
    # escalation_count is protected by _lock in increment_escalation_count()
    # and escalation_cap_reached(); raw += 1 outside those methods is unsafe.
    escalation_count: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    max_history_steps: int = 100
    # _lock is excluded from compare/eq because Lock objects don't support
    # equality; repr=False avoids noise in debug output.
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def add_step(self, record: StepRecord) -> None:
        """Append a step record and enforce the history bound.

        Thread-safe: uses a Lock to prevent concurrent modification.
        When the step count exceeds max_history_steps the oldest
        records are discarded (T3 mitigation — prevents unbounded
        memory growth from runaway agent loops).

        Args:
            record: The step record to append.

        """
        with self._lock:
            self.steps.append(record)
            # Accumulate cost tracking alongside steps so total_tokens and
            # total_cost_usd are always consistent with steps — no separate
            # replay or recomputation needed on read.
            self.total_tokens += record.tokens_used
            self.total_cost_usd += record.cost_usd
            # Enforce history bound — discard oldest records (T3).
            # Uses slice assignment (not del self.steps[:-N]) so the list
            # reference changes atomically; a concurrent reader holding the
            # old reference still sees a valid (albeit stale) snapshot.
            if len(self.steps) > self.max_history_steps:
                self.steps = self.steps[-self.max_history_steps :]

    def increment_escalation_count(self) -> int:
        """Atomically increment the escalation count and return the new value.

        Thread-safe: uses the same Lock as add_step() to prevent race
        conditions on concurrent escalation attempts (PRD §9.3).
        This addresses #34 — the raw `+= 1` operator is not atomic.

        Returns:
            The new escalation count after incrementing.

        """
        with self._lock:
            self.escalation_count += 1
            return self.escalation_count

    def escalation_cap_reached(self, max_allowed: int) -> bool:
        """Check whether the escalation cap has been reached.

        Thread-safe: acquires the lock to read escalation_count
        consistently. Prevents the TOCTOU race between checking
        and incrementing in separate lock acquisitions.

        The caller is expected to hold no lock when calling this
        method — it acquires _lock internally.  Pairing cap check
        with increment_escalation_count() in one lock acquisition
        would be ideal but would require extending the lock's scope
        to the caller, which is not feasible across package boundaries.

        Args:
            max_allowed: Maximum escalations allowed (from GuardConfig).

        Returns:
            True if escalation_count >= max_allowed.

        """
        with self._lock:
            return self.escalation_count >= max_allowed
