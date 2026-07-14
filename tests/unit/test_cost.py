"""Tests for CostTracker — per-completed-task cost and escalation rate.

Covers per WBS S6:
- Cost per completed task = sum of all step costs + escalation costs
- Escalation rate = escalations / total calls (0%, 50%, 100% cases)
- Routing vs failover: 3 routing + 2 failover → {routing: 3, failover: 2}
- Zero-cost task → cost is 0.0
- Task with only failed steps (no completion) → cost is None
- Thread safety: concurrent record_* calls don't corrupt state
"""

import threading

from ai_loopguard.cost import CostTracker, TaskCost


class TestTaskCost:
    """Tests for TaskCost dataclass."""

    def test_default_values(self) -> None:
        """TaskCost defaults to zero values."""
        tc = TaskCost(task_id="test-1")
        assert tc.retries == 0
        assert tc.escalations == 0
        assert tc.total_tokens == 0
        assert tc.total_cost_usd == 0.0
        assert tc.escalation_categories == {}

    def test_custom_values(self) -> None:
        """TaskCost accepts custom field values."""
        tc = TaskCost(
            task_id="test-2",
            retries=3,
            escalations=1,
            total_tokens=1000,
            total_cost_usd=0.05,
            escalation_categories={"routing": 1},
        )
        assert tc.retries == 3
        assert tc.escalations == 1
        assert tc.total_tokens == 1000
        assert tc.total_cost_usd == 0.05
        assert tc.escalation_categories["routing"] == 1


class TestCostTrackerRecordStep:
    """Tests for CostTracker.record_step()."""

    def test_record_step_creates_task(self) -> None:
        """First record_step for a task_id creates a TaskCost."""
        tracker = CostTracker()
        tracker.record_step("task-1", tokens=100, cost_usd=0.002)
        task = tracker._tasks.get("task-1")
        # First call creates the TaskCost with retries=1
        assert task is not None
        assert task.retries == 1
        assert task.total_tokens == 100
        assert task.total_cost_usd == 0.002

    def test_record_step_increments_existing(self) -> None:
        """Subsequent record_step calls increment the same task."""
        tracker = CostTracker()
        tracker.record_step("task-1", tokens=100, cost_usd=0.002)
        tracker.record_step("task-1", tokens=200, cost_usd=0.004)
        task = tracker._tasks["task-1"]
        # Second call increments retries and accumulates tokens/cost
        assert task.retries == 2
        assert task.total_tokens == 300
        assert task.total_cost_usd == 0.006

    def test_record_step_separate_tasks(self) -> None:
        """Different task_ids create separate TaskCost records."""
        tracker = CostTracker()
        tracker.record_step("task-A", tokens=100, cost_usd=0.002)
        tracker.record_step("task-B", tokens=50, cost_usd=0.001)
        # Task costs are isolated per task_id
        assert tracker._tasks["task-A"].total_tokens == 100
        assert tracker._tasks["task-B"].total_tokens == 50


class TestCostTrackerRecordEscalation:
    """Tests for CostTracker.record_escalation()."""

    def test_record_escalation_adds_cost(self) -> None:
        """Escalation tokens/cost are added to the task."""
        tracker = CostTracker()
        tracker.record_escalation(
            "task-1", tokens=500, cost_usd=0.01,
        )
        task = tracker._tasks["task-1"]
        # Escalations tracked separately from retries
        assert task.escalations == 1
        assert task.total_tokens == 500
        assert task.total_cost_usd == 0.01

    def test_record_escalation_defaults_to_routing(self) -> None:
        """Default escalation_category is 'routing'."""
        tracker = CostTracker()
        tracker.record_escalation("task-1", tokens=500, cost_usd=0.01)
        # routing is the default category when none is specified
        assert tracker._tasks["task-1"].escalation_categories["routing"] == 1

    def test_record_escalation_failover_category(self) -> None:
        """Explicit 'failover' category is tracked separately."""
        tracker = CostTracker()
        tracker.record_escalation(
            "task-1", tokens=500, cost_usd=0.01,
            escalation_category="failover",
        )
        assert tracker._tasks["task-1"].escalation_categories["failover"] == 1

    def test_mixed_routing_and_failover(self) -> None:
        """Routing and failover counts accumulate independently."""
        tracker = CostTracker()
        tracker.record_escalation("task-1", tokens=100, cost_usd=0.01)
        tracker.record_escalation("task-1", tokens=200, cost_usd=0.02)
        tracker.record_escalation(
            "task-1", tokens=300, cost_usd=0.03,
            escalation_category="failover",
        )
        task = tracker._tasks["task-1"]
        # Two routing + one failover
        assert task.escalation_categories["routing"] == 2
        assert task.escalation_categories["failover"] == 1

    def test_step_and_escalation_both_add(self) -> None:
        """Step and escalation costs combine in total."""
        tracker = CostTracker()
        tracker.record_step("task-1", tokens=100, cost_usd=0.002)
        tracker.record_step("task-1", tokens=150, cost_usd=0.003)
        tracker.record_escalation("task-1", tokens=500, cost_usd=0.01)
        task = tracker._tasks["task-1"]
        # retries and escalations are separate counters in TaskCost
        assert task.retries == 2
        assert task.escalations == 1
        # Total combines both retry + escalation costs
        assert task.total_tokens == 750
        assert task.total_cost_usd == 0.015


class TestCostPerCompletedTask:
    """Tests for get_cost_per_completed_task()."""

    def test_cost_returns_total(self) -> None:
        """get_cost_per_completed_task returns total cost for a task."""
        tracker = CostTracker()
        tracker.record_step("task-1", tokens=100, cost_usd=0.002)
        tracker.record_escalation("task-1", tokens=500, cost_usd=0.01)
        # Total = step costs + escalation costs
        cost = tracker.get_cost_per_completed_task("task-1")
        assert cost == 0.012

    def test_zero_cost_task(self) -> None:
        """A task with only zero-cost steps returns 0.0."""
        tracker = CostTracker()
        tracker.record_step("task-1", tokens=0, cost_usd=0.0)
        # Zero-cost edge case: tokens and cost are both 0
        cost = tracker.get_cost_per_completed_task("task-1")
        assert cost == 0.0

    def test_unknown_task_returns_none(self) -> None:
        """A task with no recorded data returns None."""
        tracker = CostTracker()
        # Unknown task_id returns None (not 0.0) to distinguish from zero-cost
        cost = tracker.get_cost_per_completed_task("nonexistent")
        assert cost is None


class TestEscalationRate:
    """Tests for get_escalation_rate()."""

    def test_zero_rate_when_no_calls(self) -> None:
        """No guarded calls → rate is 0.0."""
        tracker = CostTracker()
        # Division by zero guard: no calls → rate is 0.0
        assert tracker.get_escalation_rate() == 0.0

    def test_zero_rate_when_no_escalations(self) -> None:
        """Guarded calls but no escalations → rate is 0.0."""
        tracker = CostTracker()
        tracker.record_guarded_call()
        tracker.record_guarded_call()
        # 2 calls, 0 escalations → rate is 0.0
        assert tracker.get_escalation_rate() == 0.0

    def test_fifty_percent_rate(self) -> None:
        """2 calls, 1 escalation → rate is 0.5."""
        tracker = CostTracker()
        tracker.record_guarded_call()
        tracker.record_guarded_call()
        tracker.record_escalation("task-1", tokens=100, cost_usd=0.01)
        # 2 calls, 1 escalation → rate = 1/2 = 0.5
        assert tracker.get_escalation_rate() == 0.5

    def test_one_hundred_percent_rate(self) -> None:
        """2 calls, 2 escalations → rate is 1.0."""
        tracker = CostTracker()
        tracker.record_guarded_call()
        tracker.record_guarded_call()
        tracker.record_escalation("task-1", tokens=100, cost_usd=0.01)
        tracker.record_escalation("task-1", tokens=100, cost_usd=0.01)
        # 2 calls, 2 escalations → rate = 2/2 = 1.0
        assert tracker.get_escalation_rate() == 1.0

    def test_rate_with_multiple_tasks(self) -> None:
        """Escalations across multiple tasks count toward rate."""
        tracker = CostTracker()
        tracker.record_guarded_call()  # task-1
        tracker.record_guarded_call()  # task-2
        tracker.record_guarded_call()  # task-3
        tracker.record_guarded_call()  # task-4
        tracker.record_escalation("task-1", tokens=100, cost_usd=0.01)
        tracker.record_escalation("task-2", tokens=100, cost_usd=0.01)
        # 4 calls, 2 escalations across tasks → rate = 2/4 = 0.5
        assert tracker.get_escalation_rate() == 0.5


class TestRoutingVsFailover:
    """Tests for get_routing_vs_failover()."""

    def test_no_escalations_returns_zero(self) -> None:
        """No escalations → routing=0, failover=0."""
        tracker = CostTracker()
        breakdown = tracker.get_routing_vs_failover()
        # Empty state returns zeros (not None or KeyError)
        assert breakdown == {"routing": 0, "failover": 0}

    def test_all_routing(self) -> None:
        """3 routing escalations → routing=3, failover=0."""
        tracker = CostTracker()
        for _ in range(3):
            tracker.record_escalation(
                "task-1", tokens=100, cost_usd=0.01,
            )
        breakdown = tracker.get_routing_vs_failover()
        # Default category is routing
        assert breakdown["routing"] == 3
        assert breakdown["failover"] == 0

    def test_all_failover(self) -> None:
        """2 failover escalations → routing=0, failover=2."""
        tracker = CostTracker()
        for _ in range(2):
            tracker.record_escalation(
                "task-1", tokens=100, cost_usd=0.01,
                escalation_category="failover",
            )
        breakdown = tracker.get_routing_vs_failover()
        # Only failover recorded
        assert breakdown["routing"] == 0
        assert breakdown["failover"] == 2

    def test_mixed_scenario(self) -> None:
        """3 routing + 2 failover across tasks → {routing: 3, failover: 2}."""
        tracker = CostTracker()
        # Task-1: two routing
        tracker.record_escalation("task-1", tokens=100, cost_usd=0.01)
        tracker.record_escalation("task-1", tokens=200, cost_usd=0.02)
        # Task-1: one failover
        tracker.record_escalation(
            "task-1", tokens=300, cost_usd=0.03,
            escalation_category="failover",
        )
        # Task-2: one routing, one failover
        tracker.record_escalation(
            "task-2", tokens=50, cost_usd=0.005,
            escalation_category="routing",
        )
        tracker.record_escalation(
            "task-2", tokens=50, cost_usd=0.005,
            escalation_category="failover",
        )
        breakdown = tracker.get_routing_vs_failover()
        # Aggregates across all tasks
        assert breakdown["routing"] == 3
        assert breakdown["failover"] == 2


class TestClear:
    """Tests for clear()."""

    def test_clear_removes_all_tasks(self) -> None:
        """After clear, tasks dict is empty."""
        tracker = CostTracker()
        tracker.record_step("task-1", tokens=100, cost_usd=0.01)
        tracker.record_guarded_call()
        tracker.clear()
        # Both task data and guarded call counter are reset
        assert len(tracker._tasks) == 0
        assert tracker._total_guarded_calls == 0

    def test_clear_resets_rate(self) -> None:
        """After clear, escalation rate returns to 0."""
        tracker = CostTracker()
        tracker.record_guarded_call()
        tracker.record_escalation("task-1", tokens=100, cost_usd=0.01)
        assert tracker.get_escalation_rate() == 1.0
        tracker.clear()
        # After clear, both numerator and denominator are zero → rate is 0.0
        assert tracker.get_escalation_rate() == 0.0


class TestConcurrency:
    """Tests for thread safety."""

    def test_concurrent_record_step(self) -> None:
        """Concurrent record_step calls don't corrupt state."""
        tracker = CostTracker()
        n = 100
        errors: list[Exception] = []

        def record(i: int) -> None:
            try:
                tracker.record_step(
                    f"task-{i % 10}",
                    tokens=10,
                    cost_usd=0.001,
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No threading errors under contention
        assert len(errors) == 0
        total_tokens = sum(t.total_tokens for t in tracker._tasks.values())
        assert total_tokens == n * 10

    def test_concurrent_record_escalation(self) -> None:
        """Concurrent record_escalation calls don't corrupt state."""
        tracker = CostTracker()
        n = 50
        errors: list[Exception] = []

        def record(i: int) -> None:
            try:
                cat = "routing" if i % 2 == 0 else "failover"
                tracker.record_escalation(
                    "task-shared", tokens=100, cost_usd=0.01,
                    escalation_category=cat,
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 50 concurrent writes succeed without corruption
        assert len(errors) == 0
        task = tracker._tasks["task-shared"]
        assert task.escalations == n
        routing = task.escalation_categories.get("routing", 0)
        failover = task.escalation_categories.get("failover", 0)
        assert routing + failover == n
