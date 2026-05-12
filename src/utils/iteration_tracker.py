"""
Iteration tracker for workflow state.
"""


class IterationTracker:
    """
    Tracks current iteration number in the workflow.

    Simple counter that starts at 0 and increments with each iteration.
    """

    def __init__(self):
        """Initialize tracker at iteration 0."""
        self._current = 0

    @property
    def current(self) -> int:
        """Get current iteration number."""
        return self._current

    def increment(self):
        """Move to next iteration."""
        self._current += 1

    def reset(self):
        """Reset to iteration 0."""
        self._current = 0

    def set(self, iteration: int):
        """Set to specific iteration number."""
        if iteration < 0:
            raise ValueError("Iteration must be non-negative")
        self._current = iteration

    def __repr__(self) -> str:
        return f"IterationTracker(current={self._current})"
