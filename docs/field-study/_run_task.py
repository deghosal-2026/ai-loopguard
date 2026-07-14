"""Field study task executor — runs a single agent task with or without loopguard.

Called by runner.py via subprocess. Accepts task parameters as JSON on stdin
and outputs JSON result on stdout.

Usage (by runner.py):
    echo '{"repo": "swe-agent", "task_id": "SWE-1", "mode": "baseline", ...}' | python _run_task.py
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any


class MockWorkhorse:
    """Simulates a cheap model that ALWAYS fails — agent gets stuck forever.

    This models a weak model (e.g., Qwen 2.5 7B) that keeps making the same
    mistake repeatedly.  In a real field study, this would be the workhorse
    model connected to an external agent repo (SWE-agent, Aider, etc.).
    """

    def __init__(self, error_msg: str = "syntax error: unexpected indent") -> None:
        self.count: int = 0
        self.error_msg: str = error_msg

    def generate(self, prompt: str) -> str:
        self.count += 1
        # Always raise — the workhorse never solves the task on its own.
        # This forces the agent into a stuck loop, which is what loopguard
        # is designed to detect and resolve via escalation.
        raise ValueError(self.error_msg)


class MockEscalationModel:
    """Simulates a strong model that resolves the issue on first call.

    Models a cloud escalation model (e.g., DeepSeek V4 Flash) that receives
    the packaged context and returns a fix.  In a real field study, this
    would be an API call to a stronger model.
    """

    def __init__(self) -> None:
        self.call_id: int = 0

    def invoke(self, prompt: str) -> str:
        # Simulate API latency — a real escalation call takes 10-50ms.
        self.call_id += 1
        time.sleep(0.01)
        return "escalated-fix: rewrote the function with correct logic"

    async def ainvoke(self, prompt: str) -> str:
        return self.invoke(prompt)


def run_baseline(params: dict[str, Any]) -> dict[str, Any]:
    """Run task WITHOUT loopguard — agent loops until cap, all attempts fail.

    The workhorse always fails, so without loopguard the agent burns all
    max_attempts tokens and never succeeds.  This is the "stuck loop"
    scenario that loopguard is designed to prevent.
    """
    max_attempts: int = params.get("max_attempts", 10)
    error_msg: str = params.get("error_msg", "syntax error: unexpected indent")

    worker = MockWorkhorse(error_msg=error_msg)
    start = time.perf_counter()
    attempts = 0
    last_error: str | None = None

    for _ in range(max_attempts):
        attempts += 1
        time.sleep(0.005)  # Simulate model inference latency
        try:
            worker.generate("fix the code")
        except ValueError as e:
            # Without loopguard, the agent just retries and fails again.
            last_error = str(e)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return {
        "success": False,  # Baseline always fails — workhorse never succeeds
        "attempts": attempts,
        "wall_clock_ms": elapsed_ms,
        "last_error": last_error,
        "total_tokens": attempts * 500,  # Simulate 500 tokens per attempt
    }


def run_guarded(params: dict[str, Any]) -> dict[str, Any]:
    """Run task WITH loopguard — detects stuck loop, escalates, succeeds.

    The workhorse always fails, but after 3 consecutive identical errors,
    loopguard's repeated_error trigger fires and calls the escalation model.
    The escalation model returns a fix, and the guarded function returns
    that fix instead of re-raising.

    Key insight: @guard.protect catches the ValueError internally and
    returns the escalation output.  The calling code should check the
    return value, NOT catch exceptions.
    """
    from ai_loopguard import Guard

    max_attempts: int = params.get("max_attempts", 10)
    error_msg: str = params.get("error_msg", "syntax error: unexpected indent")
    trigger_name: str = params.get("trigger", "repeated_error")

    escalation_model = MockEscalationModel()
    # Configure triggers based on the task's expected trigger type.
    # All tasks use repeated_error as the primary trigger since the
    # workhorse always raises the same ValueError.
    triggers: dict[str, dict[str, int]] = {
        trigger_name: {"max_retries": 3},
    }

    guard = Guard(
        escalation_model=escalation_model,
        workhorse_model_name="mock-workhorse",
        triggers=triggers,
    )

    worker = MockWorkhorse(error_msg=error_msg)
    start = time.perf_counter()
    attempts = 0
    success = False

    @guard.protect
    def agent_step(prompt: str) -> str:
        return worker.generate(prompt)

    for _ in range(max_attempts):
        attempts += 1
        time.sleep(0.005)  # Simulate model inference latency
        # @guard.protect catches ValueError internally and returns:
        #   - None when no trigger has fired yet (calls 1-2)
        #   - escalation output when trigger fires (call 3+)
        result = agent_step("fix the code")
        if result is not None:
            # Escalation produced output — task resolved.
            success = True
            break

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    escalated = guard._state.escalation_count > 0

    return {
        "success": success,
        "attempts": attempts,
        "wall_clock_ms": elapsed_ms,
        "last_error": error_msg if not success else None,
        "total_tokens": attempts * 500,
        "escalations": guard._state.escalation_count,
        "escalation_success": success,
        "trigger_types_fired": [trigger_name] if escalated else [],
        "loopguard_loc": 4,
    }


def main() -> None:
    params: dict[str, Any] = json.loads(sys.stdin.read())
    mode: str = params.pop("mode", "baseline")
    task_id: str = params.get("task_id", "unknown")

    if mode == "baseline":
        result = run_baseline(params)
    else:
        result = run_guarded(params)

    result["task_id"] = task_id
    result["mode"] = mode
    print(json.dumps(result))


if __name__ == "__main__":
    main()
