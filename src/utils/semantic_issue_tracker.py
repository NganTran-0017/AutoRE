"""
SemanticIssueTracker - step 3 of the post-analysis chain.

Where ErrorNormalizer/IssuePatternTracker answer "what is this syntax error
and how is it behaving over time?", this component does the same for SEMANTIC
issues: unsatisfiable predicates and assertion counterexamples. These are the
issues that, when persistent, indicate a requirement-level problem (gap,
ambiguity, or inconsistency) rather than a modeling slip - and they are
exactly the issues the 0618 run spent 9+ iterations "fixing" without ever
escalating to requirement clarification.

Deterministic (non-LLM). Reads the per-iteration VerificationResult snapshots
already stored on the regression-log entries:
  - current_result.unsatisfied_predicates  (run commands with no instance)
  - current_result.counterexamples         (assertions with a counterexample)

Key concept - "measurable" iterations: an iteration whose model failed to
parse (syntax == "Error"/"Pending") tells us nothing about whether a semantic
issue persists; it neither extends nor breaks a persistence run. Only
iterations with syntax == "OK" count. This matters because real runs
interleave syntax-error iterations with semantic-issue iterations.

Output (stored on the entry as `semantic_issue_persistence`):
{
  "issues": [
    {
      "name": "EmergencyBypassFIFOScenario",
      "kind": "unsat_predicate" | "counterexample",
      "consecutive": 3,          # unbroken run over measurable iterations, including current
      "total": 4,                # occurrences in the window, including current
      "iterations": [17, 18, 20],  # prior window iterations where it occurred
      "first_seen": 17
    }, ...
  ],
  "escalated_issues": ["EmergencyBypassFIFOScenario"],
  "escalation_required": true    # any issue crossed a threshold
}
"""

from typing import Any, Dict, List, Optional

from .logger import SafeLogMixin


UNSAT_PREDICATE = "unsat_predicate"
COUNTEREXAMPLE = "counterexample"


class SemanticIssueTracker(SafeLogMixin):
    """Deterministic tracker of persistent semantic issues across iterations."""

    def __init__(
        self,
        window: int = 10,
        consecutive_threshold: int = 3,
        total_threshold: int = 4,
        logger=None,
    ):
        """
        Args:
            window: How many previous iterations to look back over.
            consecutive_threshold: An issue present in this many consecutive
                measurable iterations (including current) requires escalation
                to requirements diagnosis.
            total_threshold: An issue present in this many measurable window
                iterations overall (including current, gaps allowed) also
                requires escalation - catches on/off recurrence.
            logger: Optional logger with a .log(str) method.
        """
        self.window = window
        self.consecutive_threshold = consecutive_threshold
        self.total_threshold = total_threshold
        self.logger = logger

    def run(
        self,
        current_iteration: int,
        current_result: Any,
        regression_log_entries: List[Any],
        current_is_diagnostic: bool = False,
    ) -> Dict[str, Any]:
        """
        Track persistence of the current iteration's semantic issues.

        Args:
            current_iteration: The current iteration id.
            current_result: The current iteration's VerificationResult
                (must expose .syntax, .unsatisfied_predicates, .counterexamples).
            regression_log_entries: All regression-log entries.
            current_is_diagnostic: True when this iteration ran RE Mode 3
                (diagnostic experiments). A measurement attempted no repair, so
                it is no evidence that repair is failing - it is skipped exactly
                like a syntax-broken iteration, and diagnostic iterations in the
                window are likewise not counted as measurable.

        Returns:
            The semantic_issue_persistence dict described in the module docstring.
        """
        result: Dict[str, Any] = {
            "issues": [],
            "escalated_issues": [],
            "escalation_required": False,
        }

        try:
            # A syntax-broken iteration has no semantic verdicts to track.
            if current_result is None or getattr(current_result, "syntax", "") != "OK":
                return result

            # A diagnostic iteration attempted no repair. Counting it would make
            # careful diagnosis climb the escalation ladder faster than doing
            # nothing at all.
            if current_is_diagnostic:
                self._log(
                    f"[SEMANTIC_ISSUE_TRACKER] iter={current_iteration} is a diagnostic "
                    f"iteration - not counted toward persistence"
                )
                return result

            from .semantic_diagnostics import is_probe_name

            current_issues = [
                (name, UNSAT_PREDICATE)
                for name in (getattr(current_result, "unsatisfied_predicates", None) or [])
                # A probe's UNSAT is a completed experiment, not a stuck requirement.
                if not is_probe_name(name)
            ] + [
                (name, COUNTEREXAMPLE)
                for name in (getattr(current_result, "counterexamples", None) or [])
            ]
            if not current_issues:
                return result

            # Index prior measurable iterations in the window: iter -> result.
            low = current_iteration - self.window
            measurable: Dict[int, Any] = {}
            for entry in regression_log_entries:
                it = getattr(entry, "iteration_id", None)
                if it is None or it >= current_iteration or it < low:
                    continue
                if getattr(entry, "kind", "repair") == "diagnostic":
                    continue  # measured, not repaired - no evidence either way
                res = getattr(entry, "current_result", None)
                if res is not None and getattr(res, "syntax", "") == "OK":
                    measurable[it] = res

            measurable_iters_desc = sorted(measurable, reverse=True)

            for name, kind in current_issues:
                prior_iters = [
                    it for it in sorted(measurable)
                    if self._has_issue(measurable[it], name, kind)
                ]

                # Consecutive run over measurable iterations ending at current.
                consecutive = 1  # current iteration counts
                for it in measurable_iters_desc:
                    if self._has_issue(measurable[it], name, kind):
                        consecutive += 1
                    else:
                        break

                total = len(prior_iters) + 1  # + current
                issue_info = {
                    "name": name,
                    "kind": kind,
                    "consecutive": consecutive,
                    "total": total,
                    "iterations": prior_iters,
                    "first_seen": prior_iters[0] if prior_iters else current_iteration,
                }
                result["issues"].append(issue_info)

                if (consecutive >= self.consecutive_threshold
                        or total >= self.total_threshold):
                    result["escalated_issues"].append(name)

            result["escalation_required"] = bool(result["escalated_issues"])

            if result["escalation_required"]:
                self._log(
                    f"[SEMANTIC_ISSUE_TRACKER] iter={current_iteration} "
                    f"ESCALATION REQUIRED for: {result['escalated_issues']}"
                )
            elif result["issues"]:
                self._log(
                    f"[SEMANTIC_ISSUE_TRACKER] iter={current_iteration} tracking "
                    f"{len(result['issues'])} semantic issue(s), none escalated yet"
                )
            return result
        except Exception as exc:  # never break the workflow on tracking
            self._log(f"[SEMANTIC_ISSUE_TRACKER] Failed to track issues: {exc}")
            return result

    @staticmethod
    def _has_issue(result: Any, name: str, kind: str) -> bool:
        if kind == UNSAT_PREDICATE:
            names = getattr(result, "unsatisfied_predicates", None) or []
        else:
            names = getattr(result, "counterexamples", None) or []
        return name in names
