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
    produces the evidence block that escalates the Evaluator past
    model-only repair. The initial strategy is REQUIREMENTS_DIAGNOSIS;
    apply_evidence_alignment() then runs the two-key evidence gate
    (InterpretResults causal analysis x deterministic diagnostics) and may
    redirect it to MODEL_OVERCONSTRAINT_REPAIR when either source shows the
    cause is in the encoding, not the requirements.

Deterministic (non-LLM), mirrors the ErrorNormalizer/IssuePatternTracker style.

Escalation levels / strategies (syntax):
  0 STANDARD_REPAIR         new_issue, same_root_area_changed, resolved_or_progressed
  1 FORBID_PRIOR_FIXES      same_error_persisted (error carried over from last iteration)
  2 BREAK_OSCILLATION       alternating_error_loop / recurring_same_error
  3 REWRITE_BLOCK           repair_plateau (4+ identical errors in a row)
  4 REGENERATE_BLOCK        plateau survived a REWRITE_BLOCK attempt: delete the
                            block and rebuild it from the requirements it encodes
  5 REQUIREMENTS_DIAGNOSIS  plateau survived REGENERATE_BLOCK too: patching,
                            rewriting and regenerating all failed - diagnose the
                            requirement the block encodes and propose updates
"""

from typing import Any, Dict, List, Optional


# Strategy names referenced by the prompt sections - keep in sync with
# prompts/Evaluator_prompt.txt and prompts/RE_prompt.txt.
STANDARD_REPAIR = "STANDARD_REPAIR"
FORBID_PRIOR_FIXES = "FORBID_PRIOR_FIXES"
BREAK_OSCILLATION = "BREAK_OSCILLATION"
REWRITE_BLOCK = "REWRITE_BLOCK"
REGENERATE_BLOCK = "REGENERATE_BLOCK"
REQUIREMENTS_DIAGNOSIS = "REQUIREMENTS_DIAGNOSIS"
# Semantic rung 5: user approved requirement updates -> regenerate the
# affected predicates/facts from the updated requirements (semantic
# analogue of REGENERATE_BLOCK).
REGENERATE_PREDICATES = "REGENERATE_PREDICATES"
# Two-key evidence gate outcome: the escalated issues persisted, but the
# combined evidence (InterpretResults causal analysis x deterministic
# diagnostics) points at the encoding, not the requirements -> the directive
# demands a targeted model repair instead of requirements diagnosis.
MODEL_OVERCONSTRAINT_REPAIR = "MODEL_OVERCONSTRAINT_REPAIR"

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
    """Pull the [FIX INTENT] section out of a stored Evaluator feedback text,
    collapsed to a single line and truncated for directive conciseness.

    Delegates to the canonical regression_log.extract_fix_intent parser
    (previously a near-duplicate regex lived here)."""
    if not feedback:
        return None
    from .regression_log import extract_fix_intent
    intent = " ".join(extract_fix_intent(feedback).split())
    return intent[:300] if intent else None


# Ordered rule table classifying a prescribed repair into operation families
# (first match = primary family). Mirrors ErrorNormalizer's rule-table style.
_REPAIR_RULES = [
    ("no_change", r"no model changes|keep (the )?model as-is|no change (is )?needed|maintain(ing)? the model"),
    ("rewrite_block", r"rewrite [^.]*from scratch|regenerate [^.]*block|rewrite the (entire|whole)"),
    ("construct_conversion", r"convert [^.]* to an? ?(pred|fun|fact|assert)\b|replace [^.]*\bfun\b[^.]*\bpred\b|\bfun\b[^.]* with a? ?pred\b|use pred instead of fun|change [^.]*\bfun\b[^.]*\bpred\b"),
    ("remove_return_type", r"remove [^.]*return type|remove [^.]*: ?Bool|omit [^.]*return type|drop [^.]*return type"),
    ("add_open_import", r"open util/|add [^.]*open statement|util/ordering"),
    ("comment_out", r"comment[- ]out|comment out"),
    ("quantifier_change", r"set comprehension|quantifier|replace [^.]*\bone\b[^.]*\b(some|lone|all)\b"),
    ("replace_operator_or_token", r"replace [^.]*operator|change [^.]*operator|instead of [^.]*(\^|~|\.\^|next\[|prev\[)"),
    ("add_constraint", r"add (a |new |missing )?(fact|constraint|guard|condition)|strengthen"),
    ("remove_or_relax_constraint", r"remove (a |the )?(fact|constraint|guard)|delete [^.]*fact|relax|weaken"),
    ("adjust_scope", r"\bscope\b|\brun [^.]* for \d|trace length|adjust [^.]*bound"),
    ("rename_symbol", r"\brename\b"),
    ("delimiter_fix", r"brace|bracket|parenthes|semicolon|delimiter|closing '?\}'?"),
]

import re as _re


def normalize_repair(
    feedback: Optional[str],
    error_signature: Optional[Dict[str, Any]] = None,
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Normalize a prescribed repair into a stable, wording-independent signature -
    the fix-side analogue of ErrorNormalizer's error signature.

    Classifies the [FIX INTENT] + [REPAIR INSTRUCTIONS] text into operation
    families via the rule table above and anchors them to the repaired block
    (from the error signature). Two differently-worded prescriptions of the
    same operation on the same target produce the SAME normalized_signature,
    so already-failed repairs can be rejected deterministically instead of by
    fuzzy text similarity.

    Returns:
        {
          "operation_families": [primary, ...],   # all matched, rule order
          "target": "fun leq" | "unknown",
          "strategy": strategy or "",
          "normalized_signature": "repair:<family>[+<family>...]:<target>"
        }
    """
    result = {
        "operation_families": [],
        "target": "unknown",
        "strategy": strategy or "",
        "normalized_signature": "",
    }
    try:
        sig = error_signature or {}
        construct = (sig.get("affected_construct") or "").strip()
        symbol = (sig.get("affected_symbol") or "").strip()
        target = f"{construct} {symbol}".strip() or "unknown"
        result["target"] = target

        text = feedback or ""
        try:
            from .regression_log import extract_fix_intent_and_repair_instructions
            extracted = extract_fix_intent_and_repair_instructions(text)
            if extracted:
                text = extracted
        except Exception:
            pass

        families = []
        for family, pattern in _REPAIR_RULES:
            if _re.search(pattern, text, _re.IGNORECASE):
                families.append(family)
        if not families:
            families = ["other_edit"]
        # Cap at 3 families so verbose instructions don't destabilize the key
        families = families[:3]

        result["operation_families"] = families
        result["normalized_signature"] = f"repair:{'+'.join(families)}:{target}"
        return result
    except Exception:
        result["operation_families"] = ["other_edit"]
        result["normalized_signature"] = f"repair:other_edit:{result['target']}"
        return result


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
          "escalation_level": 0-5,
          "strategy": STANDARD_REPAIR | FORBID_PRIOR_FIXES | BREAK_OSCILLATION |
                      REWRITE_BLOCK | REGENERATE_BLOCK | REQUIREMENTS_DIAGNOSIS,
          "rewrite_block": bool,       # RE must rebuild the enclosing block
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

        # Escalation-ladder memory: if this exact error already survived a
        # higher-rung strategy in a prior iteration, climb to the next rung
        # instead of repeating it:
        #   3 REWRITE_BLOCK -> 4 REGENERATE_BLOCK (delete the block, rebuild it
        #     from the requirements it encodes, not from the broken text)
        #   4 REGENERATE_BLOCK -> 5 REQUIREMENTS_DIAGNOSIS (patching, rewriting
        #     AND regenerating all failed - the requirement itself is suspect)
        prior_strategy_iters: Dict[str, List[int]] = {}
        if strategy == REWRITE_BLOCK and matched:
            by_iter_ladder = _entry_by_iteration(regression_log_entries)
            for it in matched:
                prior = by_iter_ladder.get(it)
                esc = getattr(prior, "repair_escalation", None) if prior is not None else None
                prior_strategy = (esc or {}).get("strategy")
                if prior_strategy in (REWRITE_BLOCK, REGENERATE_BLOCK):
                    prior_strategy_iters.setdefault(prior_strategy, []).append(it)
            if REGENERATE_BLOCK in prior_strategy_iters:
                level, strategy = 5, REQUIREMENTS_DIAGNOSIS
            elif REWRITE_BLOCK in prior_strategy_iters:
                level, strategy = 4, REGENERATE_BLOCK
        failed_fixes = collect_failed_fixes(
            matched + root_matched, regression_log_entries
        )

        lines = [
            f"ESCALATION LEVEL: {level}",
            f"STRATEGY: {strategy}",
            f"PATTERN: {pattern_type}",
        ]
        if strategy == REGENERATE_BLOCK:
            rewrite_iters = prior_strategy_iters.get(REWRITE_BLOCK, [])
            lines.append(
                f"PRIOR REWRITE ATTEMPT FAILED: this block was already rewritten in "
                f"iteration(s) {', '.join(str(i) for i in rewrite_iters)} and the same error persists."
            )
        elif strategy == REQUIREMENTS_DIAGNOSIS:
            regen_iters = prior_strategy_iters.get(REGENERATE_BLOCK, [])
            lines.append(
                f"PRIOR REGENERATION FAILED: this block was already regenerated from the "
                f"requirements in iteration(s) {', '.join(str(i) for i in regen_iters)} "
                f"(after an earlier full rewrite also failed) and the same error persists."
            )

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

        # Normalized repair operations already prescribed for this error -
        # compact strategy history so the same operation type is not retried
        by_iter = _entry_by_iteration(regression_log_entries)
        tried_ops: List[str] = []
        for it in matched + root_matched:
            prior = by_iter.get(it)
            repair_sig = getattr(prior, "repair_signature", None) if prior is not None else None
            op = (repair_sig or {}).get("normalized_signature")
            if op and op not in tried_ops:
                tried_ops.append(op)
        if tried_ops:
            lines.append("REPAIR OPERATIONS ALREADY ATTEMPTED (normalized - do not prescribe these operation types again):")
            for op in tried_ops:
                lines.append(f"  - {op}")

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
            "rewrite_block": strategy in (REWRITE_BLOCK, REGENERATE_BLOCK),
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

    Note: at level 3 the strategy starts as REQUIREMENTS_DIAGNOSIS; the
    caller is expected to run apply_evidence_alignment() afterwards, which
    may rewrite it to MODEL_OVERCONSTRAINT_REPAIR.
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


# --------------------------------------------------------------------------- #
# Two-key evidence gate: requirements diagnosis only when BOTH the result
# interpretation (InterpretResults) and the deterministic diagnostics agree
# --------------------------------------------------------------------------- #

# Phrase lists for classifying the interpretation's "Likely Cause" line.
# Deliberately phrase-based (not bare "model"/"requirement" substrings) so
# wording like "the model of the requirements" doesn't double-count.
_REQ_CAUSE_PHRASES = [
    "requirement issue", "requirement-level", "requirement inconsisten",
    "requirement ambigu", "requirement conflict", "requirement gap",
    "requirements conflict", "conflicting requirements", "missing requirement",
    "ambiguous requirement", "inconsistent requirement", "requirements are inconsistent",
]
_MODEL_CAUSE_PHRASES = [
    "model issue", "modeling", "modelling", "encoding", "overconstraint",
    "over-constraint", "overconstrained", "model error", "model bug",
    "contradiction in the model", "model-level",
]


def summarize_interpretation_cause(interpretation: Optional[str]) -> Dict[str, Any]:
    """
    Extract the causal verdict from an InterpretResults response.

    Reads the structured lines the InterpretResults prompt mandates:
      - "Likely Cause: ..."   (RESULT INTERPRETATION section)
      - "Classification: ..." (OUTCOME CLASSIFICATION section)

    Returns:
        {
          "cause": "model" | "requirement" | "mixed" | "unknown",
          "classification": str | None,   # e.g. "unintended_regression"
          "likely_cause_text": str | None,
        }
    """
    result: Dict[str, Any] = {
        "cause": "unknown", "classification": None, "likely_cause_text": None,
    }
    if not interpretation:
        return result

    m = _re.search(r'^[ \t]*-?[ \t]*Likely Cause:[ \t]*(.+)$',
                   interpretation, _re.MULTILINE | _re.IGNORECASE)
    likely = m.group(1).strip() if m else None
    m = _re.search(r'^[ \t]*Classification:[ \t]*(.+)$',
                   interpretation, _re.MULTILINE | _re.IGNORECASE)
    classification = m.group(1).strip() if m else None

    result["likely_cause_text"] = likely
    result["classification"] = classification

    text = (likely or "").lower()
    req_hit = any(p in text for p in _REQ_CAUSE_PHRASES)
    model_hit = any(p in text for p in _MODEL_CAUSE_PHRASES)
    if req_hit and model_hit:
        result["cause"] = "mixed"
    elif req_hit:
        result["cause"] = "requirement"
    elif model_hit:
        result["cause"] = "model"
    # An unintended regression means the latest edit broke the model - a
    # modeling cause even when the Likely Cause line is missing or vague.
    if result["cause"] in ("unknown",) and classification \
            and "unintended_regression" in classification.lower():
        result["cause"] = "model"
    return result


def summarize_diagnostics_evidence(diagnostics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Classify each predicate's deterministic-diagnosis result (from
    semantic_diagnostics.diagnose_unsat_predicates) as modeling evidence,
    requirement evidence, or inconclusive.

    Per-predicate verdicts:
      scope_artifact         SAT at enlarged bounds -> modeling (bounds, not requirements)
      internal_contradiction UNSAT with all facts disabled -> modeling
      requirement_conflict   minimal blocking set implicates >=2 requirements
      single_requirement     blocking set implicates <2 requirements -> modeling-leaning
                             (one requirement cannot be inconsistent with itself)
      inconclusive           no verdict (variant failures / missing data)
    """
    per_issue: Dict[str, str] = {}
    for name, entry in (diagnostics or {}).items():
        sweep = (entry or {}).get("scope_sweep") or {}
        localization = (entry or {}).get("localization") or {}
        if sweep.get("performed") and sweep.get("sat_at_larger_scope") is True:
            per_issue[name] = "scope_artifact"
        elif localization.get("verdict") == "internal_contradiction":
            per_issue[name] = "internal_contradiction"
        elif localization.get("verdict") == "localized":
            implicated = localization.get("implicated_requirements") or []
            per_issue[name] = (
                "requirement_conflict" if len(implicated) >= 2
                else "single_requirement"
            )
        else:
            per_issue[name] = "inconclusive"

    modeling = {"scope_artifact", "internal_contradiction", "single_requirement"}
    return {
        "ran": bool(per_issue),
        "per_issue": per_issue,
        "modeling_evidence": any(v in modeling for v in per_issue.values()),
        "requirement_evidence": any(v == "requirement_conflict" for v in per_issue.values()),
    }


_DIAG_VERDICT_LABELS = {
    "scope_artifact": "SAT at enlarged bounds -> bounded-search artifact (MODELING/scope evidence)",
    "internal_contradiction": "UNSAT with all facts disabled -> contradiction inside the predicate body or sig declarations (MODELING evidence)",
    "requirement_conflict": "minimal blocking fact set implicates 2+ requirements (REQUIREMENT evidence)",
    "single_requirement": "minimal blocking fact set implicates fewer than 2 requirements (MODELING-leaning: one requirement cannot conflict with itself)",
    "inconclusive": "no usable verdict (diagnostic variants failed or were skipped)",
}


def apply_evidence_alignment(
    semantic_escalation: Dict[str, Any],
    interpretation: Optional[str],
) -> Dict[str, Any]:
    """
    Two-key evidence gate over a level-3 semantic escalation.

    Requirements diagnosis stays mandated ONLY when both evidence sources
    support a requirement-level cause:
      - the InterpretResults causal analysis points at the requirements, AND
      - the deterministic diagnostics either corroborate it (a blocking set
        implicating >=2 requirements) or produced no verdict (counterexample
        issues, capped predicates, failed variants) - in which case the
        interpretation alone decides.
    Otherwise the escalation is redirected to MODEL_OVERCONSTRAINT_REPAIR:
    the strategy field and the directive's STRATEGY line are rewritten.

    In both cases an "EVIDENCE ALIGNMENT (computed)" block is appended to the
    directive so GenerateSemanticFeedback sees both evidence streams and the
    binding conclusion. Best-effort: on any error the escalation is left
    unchanged.
    """
    result: Dict[str, Any] = {"applied": False}
    try:
        if not semantic_escalation or semantic_escalation.get("escalation_level", 0) <= 0 \
                or not semantic_escalation.get("directive"):
            return result

        interp = summarize_interpretation_cause(interpretation)
        diag = summarize_diagnostics_evidence(semantic_escalation.get("diagnostics"))

        interp_supports_req = interp["cause"] == "requirement"
        if not interp_supports_req:
            strategy = MODEL_OVERCONSTRAINT_REPAIR
            reason = (
                "the result interpretation does not attribute the failure to the "
                f"requirements (verdict: {interp['cause']})"
            )
        elif diag["ran"] and diag["modeling_evidence"] and not diag["requirement_evidence"]:
            strategy = MODEL_OVERCONSTRAINT_REPAIR
            reason = (
                "the deterministic diagnosis shows modeling evidence and no "
                "requirement-level conflict"
            )
        elif diag["ran"] and diag["requirement_evidence"]:
            strategy = REQUIREMENTS_DIAGNOSIS
            reason = (
                "BOTH the result interpretation and the deterministic diagnosis "
                "support a requirement-level cause"
            )
        else:
            # Diagnostics absent or inconclusive: the interpretation decides.
            strategy = REQUIREMENTS_DIAGNOSIS
            reason = (
                "the result interpretation attributes the failure to the "
                "requirements and the deterministic diagnosis is "
                "unavailable/inconclusive for the escalated issues"
            )

        lines = ["", "EVIDENCE ALIGNMENT (computed from both evidence sources):"]
        interp_desc = f"  - Result interpretation (InterpretResults) verdict: {interp['cause'].upper()}"
        if interp["likely_cause_text"]:
            interp_desc += f' - Likely Cause: "{interp["likely_cause_text"][:300]}"'
        if interp["classification"]:
            interp_desc += f" - Outcome classification: {interp['classification'][:100]}"
        lines.append(interp_desc)
        if diag["ran"]:
            lines.append("  - Deterministic diagnosis verdicts:")
            for name, verdict in diag["per_issue"].items():
                lines.append(f"      - '{name}': {_DIAG_VERDICT_LABELS[verdict]}")
        else:
            lines.append("  - Deterministic diagnosis: not available for the escalated issues")
        if strategy == REQUIREMENTS_DIAGNOSIS:
            lines.append(f"  - CONCLUSION: requirements diagnosis AUTHORIZED - {reason}.")
        else:
            lines.append(
                f"  - CONCLUSION: MODEL REPAIR REQUIRED - {reason}. "
                "Requirement-level diagnosis is NOT permitted for the escalated "
                "issues this iteration."
            )

        directive = semantic_escalation["directive"]
        if strategy != semantic_escalation.get("strategy"):
            directive = directive.replace(
                f"STRATEGY: {REQUIREMENTS_DIAGNOSIS}", f"STRATEGY: {strategy}", 1
            )
            semantic_escalation["strategy"] = strategy
        semantic_escalation["directive"] = directive + "\n" + "\n".join(lines)

        result = {
            "applied": True,
            "strategy": strategy,
            "reason": reason,
            "interpretation_cause": interp["cause"],
            "interpretation_classification": interp["classification"],
            "diagnostics_per_issue": diag["per_issue"],
        }
        semantic_escalation["evidence_alignment"] = result
        return result
    except Exception:
        return result


# --------------------------------------------------------------------------- #
# Rung 5 of the semantic ladder: user decision gate + targeted regeneration
# --------------------------------------------------------------------------- #

_GATE_ACCEPT_WORDS = {"accept", "accepted", "approve", "approved", "yes", "y", "ok", "agree"}
_GATE_REJECT_WORDS = {"reject", "rejected", "decline", "declined", "no", "n"}


def classify_gate_decision(user_input: Optional[str]) -> str:
    """
    Classify the user's response to the requirement-update decision gate.

    Returns one of:
      'accepted'    - bare approval keyword
      'rejected'    - bare rejection keyword
      'edited'      - substantive text (corrections / replacement wording);
                      treated as approval with modifications
      'provisional' - empty input or timeout: proceed under a provisional
                      assumption recorded in the Q&A database
    """
    if user_input is None or not user_input.strip():
        return "provisional"
    word = user_input.strip().lower().rstrip(".!")
    if word in _GATE_ACCEPT_WORDS:
        return "accepted"
    if word in _GATE_REJECT_WORDS:
        return "rejected"
    return "edited"


def remove_requirement_updates(feedback: str) -> str:
    """
    Deterministically remove the `=== REQUIREMENT UPDATES ===` section from a
    feedback text (used when the user REJECTS the proposed updates, so
    _step7_update_requirements cannot apply them). The section runs from its
    header to the next `=== ... ===` header or EOF. Returns the feedback
    unchanged if the section is absent.
    """
    import re
    lines = feedback.split("\n")
    header = re.compile(r"^===\s*REQUIREMENT[S]?\s+UPDATE[S]?\s*===", re.IGNORECASE)
    any_header = re.compile(r"^===\s*.+?\s*===")
    start = next((i for i, l in enumerate(lines) if header.match(l.strip())), None)
    if start is None:
        return feedback
    end = next(
        (i for i in range(start + 1, len(lines)) if any_header.match(lines[i].strip())),
        len(lines),
    )
    return "\n".join(lines[:start] + lines[end:])


def build_regeneration_escalation(
    current_iteration: int,
    semantic_escalation: Dict[str, Any],
    user_decision: str,
    proposed_updates: Optional[str],
) -> Dict[str, Any]:
    """
    Build the rung-5 escalation: the user accepted (possibly with edits, or
    provisionally by timeout) the requirement updates proposed for persistent
    semantic issues, so the RE agent must REGENERATE the affected constructs
    from the updated requirements instead of patching them.

    Regeneration targets are the escalated issue names plus, when rungs 2-3
    produced a measured diagnosis, the proven blocking facts. As everywhere in
    this module, the directive carries facts only - the behavioral rules live
    in the RE prompt's ESCALATION OVERRIDE section.

    Returns the same shape as the other builders, plus:
      'user_decision':      accepted | edited | provisional
      'regenerate_targets': [construct names]
    """
    result = {
        "escalation_level": 5,
        "strategy": REGENERATE_PREDICATES,
        "escalated_issues": list(semantic_escalation.get("escalated_issues") or []),
        "user_decision": user_decision,
        "regenerate_targets": [],
        "directive": "",
    }
    try:
        targets = list(result["escalated_issues"])
        implicated: List[str] = []
        diagnostics = semantic_escalation.get("diagnostics") or {}
        for predicate, diag in diagnostics.items():
            localization = (diag or {}).get("localization") or {}
            for fact in localization.get("blocking_facts") or []:
                if fact not in targets:
                    targets.append(fact)
            for rid in localization.get("implicated_requirements") or []:
                if rid not in implicated:
                    implicated.append(rid)
        result["regenerate_targets"] = targets

        decision_label = {
            "accepted": "ACCEPTED by the user",
            "edited": "ACCEPTED by the user WITH EDITS (see the final feedback's REQUIREMENT UPDATES)",
            "provisional": ("PROVISIONAL - the user did not respond; proceeding under a "
                            "provisional assumption recorded in the Q&A database"),
        }.get(user_decision, user_decision)

        lines = [
            "ESCALATION LEVEL: 5",
            f"STRATEGY: {REGENERATE_PREDICATES}",
            f"USER DECISION ON PROPOSED REQUIREMENT UPDATES: {decision_label}",
            "The requirements document is being updated accordingly - it is the "
            "source of truth for the regenerated constructs.",
            "REGENERATE (delete and rebuild from the UPDATED requirements - do NOT patch):",
        ]
        for name in targets:
            lines.append(f"  - {name}")
        if implicated:
            lines.append(
                "IMPLICATED REQUIREMENTS (from the measured minimal blocking set): "
                + ", ".join(implicated)
            )
        if proposed_updates:
            lines.append("APPROVED REQUIREMENT UPDATES:")
            for line in proposed_updates.strip().splitlines():
                lines.append(f"  {line}")
        result["directive"] = "\n".join(lines)
        return result
    except Exception:
        return result
