"""Tests for BoundedHistory container.

Covers:
- Basic append, length, and items retrieval
- Items property returns a safe copy (no mutation of internal state)
- Truncation: oldest entries discarded when max_size exceeded
- No truncation at exact limit boundary
- Default max_size = 100
- Thread safety: concurrent appends with multiple writers

BoundedHistory is used internally by GuardState, but it's designed as
a general-purpose utility — hence the `object` item type.
"""

import threading

from ai_loopguard._internal.history import BoundedHistory


class TestBoundedHistory:
    """Tests for BoundedHistory thread-safe list wrapper."""

    # ── basic operations ────────────────────────────────────────────

    def test_append_and_len(self) -> None:
        """Appended items increase length. Empty history has length 0."""
        h = BoundedHistory(max_size=5)
        assert len(h) == 0

        h.append("a")
        h.append("b")
        assert len(h) == 2

    def test_empty_items(self) -> None:
        """Items on an empty history returns [] not None."""
        h = BoundedHistory(max_size=5)
        # Empty history returns empty list, not None — avoids None checks in callers
        assert h.items == []

    def test_max_size_default(self) -> None:
        """max_size defaults to 100 when not specified."""
        h = BoundedHistory()
        assert h.max_size == 100

    # ── items copy semantics ────────────────────────────────────────

    def test_items_returns_copy(self) -> None:
        """Items returns a copy — mutating it doesn't affect internal state."""
        h = BoundedHistory(max_size=5)
        h.append(1)
        h.append(2)
        items = h.items
        assert items == [1, 2]

        # Mutate the returned copy — internal state must be unchanged
        items.append(3)
        assert h.items == [1, 2]  # Still only [1, 2], NOT [1, 2, 3]

    # ── truncation behaviour ────────────────────────────────────────

    def test_truncation(self) -> None:
        """When len > max_size, oldest items are discarded (FIFO)."""
        h = BoundedHistory(max_size=3)
        for i in range(10):
            h.append(i)
        assert len(h) == 3
        # The last 3 items should be retained: 7, 8, 9
        # Oldest (0-6) are discarded
        assert h.items == [7, 8, 9]

    def test_no_truncation_at_exact_limit(self) -> None:
        """Adding exactly max_size items does NOT trigger truncation."""
        h = BoundedHistory(max_size=5)
        for i in range(5):
            h.append(i)
        # Truncation only fires when len > max, not len == max
        assert len(h) == 5
        assert h.items == [0, 1, 2, 3, 4]

    # ── thread safety ───────────────────────────────────────────────

    def test_thread_safety(self) -> None:
        """5 concurrent writers × 100 items each should complete without errors."""
        h = BoundedHistory(max_size=1000)
        errors: list[Exception] = []

        def append_items() -> None:
            try:
                for i in range(100):
                    h.append(i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=append_items) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # No thread should have errored
        assert len(errors) == 0
        # 5 threads × 100 items = 500 — max_size=1000 so all retained
        # Thread safety via internal lock prevents concurrent modification errors
        assert len(h) == 500
