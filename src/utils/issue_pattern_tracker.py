"""
IssuePatternTracker - deterministic cross-iteration error pattern detection.

Second step in the post-analysis chain:
    ErrorNormalizer -> IssuePatternTracker -> ResolutionStatusTracker -> RepairPlateauDetector

Compares the current iteration's normalized error signature (produced by
ErrorNormalizer) against the errors seen in a sliding window of recent
iterations, through three widening match levels:

    1. Exact signature match       (same normalized_signature)
    2. Root-family match           (same root_error_family, different signature)
    3. Related-region match        (same construct/symbol or model_region)

and classifies the resulting pattern. Output (stored on the current
iteration's regression-log entry as `issue_pattern`):

    {
      "matched_exact_iterations": [],
      "matched_root_family_iterations": [],
      "repeat_count_exact": 0,
      "repeat_count_root_family": 0,
      "pattern_type": ""
    }

pattern_type is one of:
    new_issue, same_error_persisted, same_root_area_changed,
    recurring_same_error, alternating_error_loop, repair_plateau,
    resolved_or_progressed
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .logger import SafeLogMixin


# Pattern type constants
NEW_ISSUE = "new_issue"
SAME_ERROR_PERSISTED = "same_error_persisted"
SAME_ROOT_AREA_CHANGED = "same_root_area_changed"
RECURRING_SAME_ERROR = "recurring_same_error"
ALTERNATING_ERROR_LOOP = "alternating_error_loop"
REPAIR_PLATEAU = "repair_plateau"
RESOLVED_OR_PROGRESSED = "resolved_or_progressed"


class IssuePatternTracker(SafeLogMixin):
    """Deterministic workflow step that classifies the current error pattern."""

    def __init__(self, window: int = 6, plateau_consecutive: int = 3, logger=None):
        """
        Args:
            window: How many previous iterations to look back over.
            plateau_consecutive: Number of consecutive prior identical
                signatures (ending at N-1) that escalates a persisted error to
                a repair_plateau. Default 3 -> 4 identical in a row overall.
            logger: Optional logger with a .log(str) method.
        """
        self.window = window
        self.plateau_consecutive = plateau_consecutive
        self.logger = logger

    def run(
        self,
        current_iteration: int,
        current_signature: Optional[Dict[str, Any]],
        regression_log_entries: List[Any],
    ) -> Dict[str, Any]:
        """
        Classify the current error against the recent-error window.

        Args:
            current_iteration: The current iteration id.
            current_signature: The current iteration's error_signature dict
                (from ErrorNormalizer), or None if there is no error.
            regression_log_entries: All regression-log entries (each may carry
                an `error_signature` for its iteration).

        Returns:
            The issue_pattern dict described in the module docstring.
        """
        result = {
            "matched_exact_iterations": [],
            "matched_root_family_iterations": [],
            "repeat_count_exact": 0,
            "repeat_count_root_family": 0,
            "pattern_type": "",
        }

        # No current error -> the model resolved or progressed past the error.
        if not current_signature or not current_signature.get("normalized_signature"):
            result["pattern_type"] = RESOLVED_OR_PROGRESSED
            return result

        cur_sig = current_signature.get("normalized_signature")
        cur_root = current_signature.get("root_error_family")
        cur_region = self._region_key(current_signature)

        # Index prior signatures by iteration id (within window only).
        low = current_iteration - self.window
        sig_by_iter: Dict[int, Optional[Dict[str, Any]]] = {}
        for entry in regression_log_entries:
            it = getattr(entry, "iteration_id", None)
            if it is None or it >= current_iteration or it < low:
                continue
            sig_by_iter[it] = getattr(entry, "error_signature", None)

        exact_iters: List[int] = []
        root_iters: List[int] = []
        region_match = False

        for it in sorted(sig_by_iter):
            sig = sig_by_iter[it]
            if not sig or not sig.get("normalized_signature"):
                continue
            if sig.get("normalized_signature") == cur_sig:
                exact_iters.append(it)
            elif cur_root and sig.get("root_error_family") == cur_root:
                root_iters.append(it)
            elif cur_region and self._region_key(sig) == cur_region:
                region_match = True

        result["matched_exact_iterations"] = exact_iters
        result["matched_root_family_iterations"] = root_iters
        result["repeat_count_exact"] = len(exact_iters)
        result["repeat_count_root_family"] = len(exact_iters) + len(root_iters)

        # Sequence signals (order matters, not just membership).
        consecutive_exact = self._consecutive_exact(current_iteration, cur_sig, sig_by_iter)
        prev_sig = self._sig_at(current_iteration - 1, sig_by_iter)

        # Classify (first matching rule wins).
        if consecutive_exact >= self.plateau_consecutive:
            pattern = REPAIR_PLATEAU
        elif consecutive_exact >= 1:
            pattern = SAME_ERROR_PERSISTED
        elif exact_iters:
            # Exact match exists but not immediately before -> came back after a gap.
            if self._is_alternating(current_iteration, cur_sig, prev_sig, sig_by_iter):
                pattern = ALTERNATING_ERROR_LOOP
            else:
                pattern = RECURRING_SAME_ERROR
        elif root_iters or region_match:
            pattern = SAME_ROOT_AREA_CHANGED
        else:
            pattern = NEW_ISSUE

        result["pattern_type"] = pattern
        self._log(
            f"[ISSUE_PATTERN] iter={current_iteration} pattern={pattern} "
            f"exact={exact_iters} root_family={root_iters} "
            f"consecutive_exact={consecutive_exact}"
        )
        return result

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _region_key(signature: Dict[str, Any]) -> str:
        """Level-3 locality key: construct+symbol, falling back to model_region."""
        construct = (signature.get("affected_construct") or "").strip()
        symbol = (signature.get("affected_symbol") or "").strip()
        if symbol and symbol.lower() != "unknown":
            return f"{construct}:{symbol}"
        region = (signature.get("model_region") or "").strip()
        return region if region and region.lower() != "unknown" else ""

    @staticmethod
    def _sig_at(iteration: int, sig_by_iter: Dict[int, Optional[Dict[str, Any]]]) -> Optional[str]:
        sig = sig_by_iter.get(iteration)
        if not sig:
            return None
        return sig.get("normalized_signature")

    def _consecutive_exact(
        self,
        current_iteration: int,
        cur_sig: str,
        sig_by_iter: Dict[int, Optional[Dict[str, Any]]],
    ) -> int:
        """Count identical signatures in an unbroken run ending at N-1.

        A missing entry or a differing/absent signature breaks the run.
        """
        count = 0
        it = current_iteration - 1
        while it in sig_by_iter:
            if self._sig_at(it, sig_by_iter) == cur_sig:
                count += 1
                it -= 1
            else:
                break
        return count

    def _is_alternating(
        self,
        current_iteration: int,
        cur_sig: str,
        prev_sig: Optional[str],
        sig_by_iter: Dict[int, Optional[Dict[str, Any]]],
    ) -> bool:
        """Detect an A,B,A(,B,A...) oscillation ending at the current iteration.

        Requires: current == sig(N-2), current != sig(N-1) (both present).
        If sig(N-3) is present it must equal sig(N-1) (the other phase),
        strengthening confidence; if absent, the 3-point A-B-A is accepted.
        """
        sig_n2 = self._sig_at(current_iteration - 2, sig_by_iter)
        if prev_sig is None or sig_n2 is None:
            return False
        if not (cur_sig == sig_n2 and cur_sig != prev_sig):
            return False
        sig_n3 = self._sig_at(current_iteration - 3, sig_by_iter)
        if sig_n3 is not None:
            return sig_n3 == prev_sig
        return True
