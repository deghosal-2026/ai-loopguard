"""Bounded history container for step records.

Provides a thread-safe list wrapper that automatically truncates
the oldest entries when a configurable maximum is exceeded.
"""

from threading import Lock


class BoundedHistory:
    """A list wrapper that truncates on overflow.

    Thread-safe append operation. When the number of entries exceeds
    max_size the oldest entries are discarded.

    Attributes:
        max_size: Maximum number of entries to retain.

    """

    def __init__(self, max_size: int = 100) -> None:
        """Initialise the bounded history.

        Args:
            max_size: Maximum number of entries (default 100).

        """
        self.max_size = max_size
        self._items: list[object] = []
        # Single lock guards both append and items/__len__ read paths.
        # A read-write lock would improve throughput under high concurrency
        # but adds a dependency; for typical agent workloads (single-digit
        # steps) the contention is negligible.
        self._lock = Lock()

    def append(self, item: object) -> None:
        """Append an item and truncate if over limit.

        Args:
            item: The item to append.

        """
        with self._lock:
            self._items.append(item)
            # Slice-based truncation (not del self._items[:-N]) so the
            # list reference changes atomically — concurrent readers
            # holding the old reference don't see a partially-modified list.
            if len(self._items) > self.max_size:
                self._items = self._items[-self.max_size:]

    @property
    def items(self) -> list[object]:
        """Return a copy of the current items."""
        with self._lock:
            # Defensive copy: callers receive a snapshot isolated from
            # concurrent modifications.  Without this, iterating over
            # .items while another thread appends could raise
            # RuntimeError: list changed size during iteration.
            return list(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
