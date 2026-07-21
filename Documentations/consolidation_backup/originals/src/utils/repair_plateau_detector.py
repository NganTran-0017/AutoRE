"""
RepairPlateauDetector - step 4 of the post-analysis chain.

Consumes the outputs of the earlier chain steps (ErrorNormalizer signatures,
IssuePatternTracker classifications, SemanticIssueTracker persistence) and
turns them into an actionable escalation decision. This is the component that
makes the tracking data change agent behavior instead of being write-only
telemetry:

  - build_syntax_escalation(): decides how aggressively the Evaluator's
    syntax-repair instruction must depart from prior attempts, and renders a
    data-only evidence block (the "directive") that is injected into the
    GenerateSyntaxRepairInstruction prompt and into the RE agent's
    UpdateAlloyModel prompt. The rules for what each strategy requires live
    in the prompt files, not here - this module only supplies facts.

  - build_semantic_escalation(): when a semantic issue (unsat predicate /
    counterexample) has persisted past the SemanticIssueTracker thresholds,
    produces the evidence block that forces the Evaluator into requirements
    diagnosis (identify the gap/ambiguity/inconsistency and propose English
    requirement updates) instead of another round of model-only repair.

Deterministic (non-LLM), mirrors the ErrorNormalizer/IssuePatternTracker style.

Escalation levels / strategies (syntax):
  0 STANDARD_REPAIR    new_issue, same_root_area_changed, resolved_or_progressed
  1 FORBID_PRIOR_FIXES same_error_persisted (error carried over from last iteration)
  2 BREAK_OSCILLATION  alternating_error_loop / recurring_same_error
  3 REWRITE_BLOCK      repair_plateau (4+ identical errors in a row)
"""

import re
from typing import Any, Dict, List, Optional


# Strategy names referenced by the prompt sections - keep in sync with
# prompts/Evaluator_prompt.txt and prompts/RE_prompt.txt.
STANDARD_REPAIR = "STANDARD_REPAIR"
FORBID_PRIOR_FIXES = "FORBID_PRIOR_FIXES"
BREAK_OSCILLATION = "BREAK_OSCILLATION"
REWRITE_BLOCK = "REWRITE_BLOCK"
REQUIREMENTS_DIAGNOSIS = "REQUIREMENTS_DIAGNOSIS"

_PATTERN_TO_STRATEGY = {
    "repair_plateau": (3, REWRITE_BLOCK),
    "alternating_error_loop": (2, BREAK_OSCILLATION),
    "recurring_same_error": (2, BREAK_OSCILLATION),
    "same_error_persisted": (1, FORBID_PRIOR_FIXES),
}


def _entry_by_iteration(regression_log_entries: List[Any]) -> Dict[int, Any]:
    return {
        getattr(e, "iteration_id", None): e
        for e in regression_log_entries
        if getattr(e, "iteration_id", None) is not None
    }


def _extract_evaluator_fix_intent(feedback: Optional[str]) -> Optional[str]:
    """Pull the [FIX INTENT] line out of a stored Evaluator feedback text."""
    if not feedback:
        return None
    match = re.search(r"\[FIX INTENT\]:?\s*\n?\s*(.+)", feedback)
    if match:
        intent = match.group(1).strip()
        return intent[:300] if intent else None
    return None


def collect_failed_fixes(
    matched_iterations: List[int],
    regression_log_entries: List[Any],
) -> List[str]:
    """
    For each prior iteration where the same error occurred, collect what was
    tried against it: the Evaluator's [FIX INTENT] from that iteration's
    feedback, and the RE agent's applied fix_intent recorded on the FOLLOWING
    iteration's entry (the fix for iteration i's error is applied when
    creating iteration i+1's model).
    """
    by_iter = _entry_by_iteration(regression_log_entries)
    fixes: List[str] = []
    seen = set()
    for it in matched_iterations:
        entry = by_iter.get(it)
        if entry is not None:
            intent = _extract_evaluator_fix_intent(
                getattr(entry, "evaluator_feedback", None)
            )
            if intent and intent not in seen:
                seen.add(intent)
                fixes.append(f"(Evaluator, iteration {it}) {intent}")
        next_entry = by_iter.get(it + 1)
        if next_entry is not None:
            applied = (getattr(next_entry, "fix_intent", "") or "").strip()
            if applied and applied not in seen and applied.lower() not in (
                "no fix intent provided", "initial model creation", "model update"
            ):
                seen.add(applied)
                fixes.append(f"(RE agent, applied in iteration {it + 1}) {applied[:300]}")
    return fixes


def build_syntax_escalation(
    current_iteration: int,
    issue_pattern: Optional[Dict[str, Any]],
    error_signature: Optional[Dict[str, Any]],
    regression_log_entries: List[Any],
) -> Dict[str, Any]:
    """
    Decide the syntax-repair escalation for the current iteration.

    Returns:
        {
          "escalation_level": 0-3,
          "strategy": STANDARD_REPAIR | FORBID_PRIOR_FIXES | BREAK_OSCILLATION | REWRITE_BLOCK,
          "rewrite_block": bool,       # RE must regenerate the enclosing block
          "directive": str             # data-only evidence block for prompts ("" at level 0)
        }
    """
    result = {
        "escalation_level": 0,
        "strategy": STANDARD_REPAIR,
        "rewrite_block": False,
        "directive": "",
    }
    try:
        if not issue_pattern:
            return result

        pattern_type = issue_pattern.get("pattern_type", "")
        level, strategy = _PATTERN_TO_STRATEGY.get(pattern_type, (0, STANDARD_REPAIR))
        if level == 0:
            return result

        matched = sorted(
            set(issue_pattern.get("matched_exact_iterations", []) or [])
        )
        root_matched = sorted(
            set(issue_pattern.get("matched_root_family_iterations", []) or [])
        )
        failed_fixes = collect_failed_fixes(
            matched + root_matched, regression_log_entries
        )

        lines = [
            f"ESCALATION LEVEL: {level}",
            f"STRATEGY: {strategy}",
            f"PATTERN: {pattern_type}",
        ]

        sig = error_signature or {}
        if sig.get("normalized_signature"):
            lines.append(f"ERROR SIGNATURE: {sig['normalized_signature']}")
        construct = sig.get("affected_construct") or ""
        symbol = sig.get("affected_symbol") or ""
        if construct or symbol:
            lines.append(f"AFFECTED BLOCK: {construct} {symbol}".strip())

        occurrences = matched + [current_iteration]
        lines.append(
            f"SAME ERROR SEEN IN ITERATIONS: {', '.join(str(i) for i in occurrences)} "
            f"({len(occurrences)} occurrences including current)"
        )
        if root_matched:
            lines.append(
                f"RELATED ERRORS (same root cause family) IN ITERATIONS: "
                f"{', '.join(str(i) for i in root_matched)}"
            )

        if pattern_type == "alternating_error_loop":
            by_iter = _entry_by_iteration(regression_log_entries)
            prev_entry = by_iter.get(current_iteration - 1)
            other_sig = None
            if prev_entry is not None:
                other = getattr(prev_entry, "error_signature", None) or {}
                other_sig = other.get("normalized_signature")
            if other_sig:
                lines.append(f"OSCILLATING WITH ERROR: {other_sig}")
                lines.append(
                    "NOTE: Fixing the current error has repeatedly re-introduced the "
                    "error above, and vice versa. Both must be resolved by one change."
                )

        if failed_fixes:
            lines.append("PREVIOUSLY ATTEMPTED FIXES FOR THIS ERROR (ALL FAILED):")
            for fix in failed_fixes:
                lines.append(f"  - {fix}")
        else:
            lines.append(
                "PREVIOUSLY ATTEMPTED FIXES: none recorded, but the error recurred - "
                "the prior repair did not address the root cause."
            )

        result.update({
            "escalation_level": level,
            "strategy": strategy,
            "rewrite_block": strategy == REWRITE_BLOCK,
            "directive": "\n".join(lines),
        })
        return result
    except Exception:
        # Never break the workflow on escalation building.
        return result


def build_semantic_escalation(
    current_iteration: int,
    semantic_persistence: Optional[Dict[str, Any]],
    regression_log_entries: List[Any],
) -> Dict[str, Any]:
    """
    Decide the semantic escalation for the current iteration.

    Returns:
        {
          "escalation_level": 0 | 3,
          "strategy": STANDARD_REPAIR | REQUIREMENTS_DIAGNOSIS,
          "escalated_issues": [names],
          "directive": str    # data-only evidence block for prompts ("" if not escalated)
        }
    """
    result = {
        "escalation_level": 0,
        "strategy": STANDARD_REPAIR,
        "escalated_issues": [],
        "directive": "",
    }
    try:
        if not semantic_persistence or not semantic_persistence.get("escalation_required"):
            return result

        escalated = list(semantic_persistence.get("escalated_issues", []) or [])
        issues = [
            i for i in (semantic_persistence.get("issues", []) or [])
            if i.get("name") in escalated
        ]
        if not issues:
            return result

        lines = [
            "ESCALATION LEVEL: 3",
            f"STRATEGY: {REQUIREMENTS_DIAGNOSIS}",
            "PERSISTENT SEMANTIC ISSUES (survived repeated repair attempts):",
        ]
        for issue in issues:
            kind_label = (
                "unsatisfiable predicate" if issue.get("kind") == "unsat_predicate"
                else "assertion counterexample"
            )
            occurrences = list(issue.get("iterations", []) or []) + [current_iteration]
            lines.append(
                f"  - {kind_label} '{issue.get('name')}': present in "
                f"{issue.get('consecutive')} consecutive syntactically-valid iterations "
                f"({issue.get('total')} total; iterations "
                f"{', '.join(str(i) for i in occurrences)})"
            )
            failed = collect_failed_fixes(
                list(issue.get("iterations", []) or []), regression_log_entries
            )
            if failed:
                lines.append("    Fixes already attempted for this issue (ALL FAILED):")
                for fix in failed:
                    lines.append(f"      - {fix}")

        result.update({
            "escalation_level": 3,
            "strategy": REQUIREMENTS_DIAGNOSIS,
            "escalated_issues": escalated,
            "directive": "\n".join(lines),
        })
        return result
    except Exception:
        return result
