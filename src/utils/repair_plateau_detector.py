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
    apply_evidence_alignment() then runs the evidence gate
    (InterpretResults causal analysis x deterministic diagnostics) and
    redirects it to MODEL_OVERCONSTRAINT_REPAIR when the interpretation does
    not attribute the failure to the requirements. The diagnostics corroborate
    but do not veto: their "modeling" verdicts establish where the
    contradiction sits, not whether the requirement it encodes is sound.

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
# Evidence gate outcome: the escalated issues persisted, but the result
# interpretation does not attribute the failure to the requirements (cause
# model, mixed, or unknown) -> the directive demands a targeted model repair
# instead of requirements diagnosis.
MODEL_OVERCONSTRAINT_REPAIR = "MODEL_OVERCONSTRAINT_REPAIR"
# Ownership audit outcome: constructs that belong to no live requirement
# (orphans) plus the helpers they strand. These are DELETED, not regenerated -
# an orphan's requirement no longer exists, so there is nothing to rebuild from.
REMOVE_STALE_CONSTRUCTS = "REMOVE_STALE_CONSTRUCTS"
# Probation outcome: a requirement update is on probation but nothing in the
# model can be traced to it, so no evidence about it can ever arrive. Not a
# repair strategy - the model may be perfectly healthy; it is an encoding
# obligation, and the alternative to issuing it is waiting forever.
ENCODE_PROVISIONAL = "ENCODE_PROVISIONAL"
# Contest outcome: the user undid a requirement update the solver implicated.
# The document changed back; the model still encodes what it used to say, so
# the encoding has to follow the revert or the two disagree silently.
REVERT_REQUIREMENT = "REVERT_REQUIREMENT"

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
        if next_entry is not None and getattr(next_entry, "kind", "repair") != "diagnostic":
            # A Mode 3 iteration attempted no fix. Listing its DIAGNOSTIC EXECUTION
            # report here would forbid the RE from ever applying the repair that
            # experiment was run to validate - the exact failure Mode 3 exists to
            # remove.
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
# Evidence gate: the result interpretation (InterpretResults) decides the cause;
# the deterministic diagnostics corroborate where it sits, and do not veto it
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


def summarize_diagnostics_evidence(
    diagnostics: Optional[Dict[str, Any]],
    traceability: Optional[Any] = None,
    recently_changed: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Classify each predicate's deterministic-diagnosis result (from
    semantic_diagnostics.diagnose_unsat_predicates) as modeling evidence,
    requirement evidence, or inconclusive.

    Per-predicate verdicts:
      scope_artifact         SAT at enlarged bounds -> modeling (bounds, not requirements)
      internal_contradiction UNSAT with all facts disabled -> modeling
      stale_requirement_encoding  the UNSAT is caused by a leftover encoding of
                             a REQUIREMENT changed in a recent iteration (via the
                             traceability map): either the diagnosed predicate
                             itself (internal_contradiction) or a top-level fact
                             blocking it (localized) traces to a changed
                             requirement -> REQUIREMENT evidence (route to
                             regeneration, not model overconstraint)
      requirement_conflict   minimal blocking set implicates >=2 requirements
      single_requirement     blocking set implicates exactly one requirement ->
                             that requirement is internally inconsistent
                             (self-contradictory) -> REQUIREMENT evidence
      inconclusive           no verdict (variant failures / missing data)

    Args:
        traceability: optional object with requirements_for(construct_name) ->
            [req_id, ...] (a TraceabilityStore). Used to detect stale encodings.
        recently_changed: requirement IDs changed in a recent iteration.
    """
    changed = set(recently_changed or [])
    per_issue: Dict[str, str] = {}
    for name, entry in (diagnostics or {}).items():
        sweep = (entry or {}).get("scope_sweep") or {}
        localization = (entry or {}).get("localization") or {}
        if sweep.get("performed") and sweep.get("sat_at_larger_scope") is True:
            per_issue[name] = "scope_artifact"
        elif localization.get("verdict") == "internal_contradiction":
            # A predicate that is UNSAT with all facts disabled is normally a
            # modeling defect - UNLESS it encodes a just-changed requirement, in
            # which case it is the stale encoding of the superseded requirement.
            if traceability is not None and changed and (
                set(traceability.requirements_for(name)) & changed
            ):
                per_issue[name] = "stale_requirement_encoding"
            else:
                per_issue[name] = "internal_contradiction"
        elif localization.get("verdict") == "localized":
            # A fact blocking the predicate that encodes a just-changed
            # requirement is the stale encoding of the superseded requirement
            # (same root cause as the internal_contradiction case, but carried
            # by a top-level fact rather than the predicate body). The localizer
            # names the blocking facts; the map ties an un-prefixed one (e.g.
            # EmergencyUniqueness) back to its requirement.
            blockers = localization.get("blocking_facts") or []
            if traceability is not None and changed and any(
                set(traceability.requirements_for(f)) & changed for f in blockers
            ):
                per_issue[name] = "stale_requirement_encoding"
            else:
                implicated = localization.get("implicated_requirements") or []
                per_issue[name] = (
                    "requirement_conflict" if len(implicated) >= 2
                    else "single_requirement"
                )
        else:
            per_issue[name] = "inconclusive"

    # A single implicated requirement is still requirement-level evidence: a
    # requirement can be internally inconsistent (self-contradictory), so its own
    # facts blocking the predicate is a requirement defect, not a modeling one.
    modeling = {"scope_artifact", "internal_contradiction"}
    requirement = {
        "requirement_conflict", "single_requirement", "stale_requirement_encoding",
    }
    return {
        "ran": bool(per_issue),
        "per_issue": per_issue,
        "modeling_evidence": any(v in modeling for v in per_issue.values()),
        "requirement_evidence": any(v in requirement for v in per_issue.values()),
    }


_DIAG_VERDICT_LABELS = {
    "scope_artifact": "SAT at enlarged bounds -> bounded-search artifact (MODELING/scope evidence)",
    "internal_contradiction": "UNSAT with all facts disabled -> contradiction inside the predicate body or sig declarations (MODELING evidence)",
    "stale_requirement_encoding": "the UNSAT is caused by a construct (the predicate itself, or a fact blocking it) that encodes a requirement changed in a recent iteration -> stale/superseded encoding left in the model (REQUIREMENT evidence; regenerate it)",
    "requirement_conflict": "minimal blocking fact set implicates 2+ requirements (REQUIREMENT evidence)",
    "single_requirement": "minimal blocking fact set implicates exactly one requirement -> that requirement is internally inconsistent/self-contradictory (REQUIREMENT evidence)",
    "inconclusive": "no usable verdict (diagnostic variants failed or were skipped)",
}


def apply_evidence_alignment(
    semantic_escalation: Dict[str, Any],
    interpretation: Optional[str],
    traceability: Optional[Any] = None,
    recently_changed: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Evidence gate over a level-3 semantic escalation.

    The InterpretResults causal analysis decides. Requirements diagnosis is
    mandated whenever it attributes the failure to the requirements, and
    redirected to MODEL_OVERCONSTRAINT_REPAIR whenever it does not (cause
    `model`, `mixed`, or `unknown`) - in that case the strategy field and the
    directive's STRATEGY line are rewritten.

    The deterministic diagnostics corroborate; they do not veto. A `modeling`
    verdict says WHERE the contradiction sits - inside a predicate body
    (`internal_contradiction`) or below the bounds (`scope_artifact`) - not
    whether the requirement that body transcribes is sound. A predicate that
    faithfully encodes a self-contradictory requirement measures as
    `internal_contradiction`, so treating that as a refutation of the
    interpretation buried the requirement defect it was reporting. Both
    remaining cases are handled downstream rather than here: the escalation
    prompt's DETERMINISTIC DIAGNOSIS block overrides the binding rules per
    issue for a scope artifact (`adjust scope/trace and rerun`), and the
    REQUIREMENTS_DIAGNOSIS rulebook carries an explicit `model overconstraint`
    exception for an encoding that is provably too strong.

    In every case an "EVIDENCE ALIGNMENT (computed)" block is appended to the
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
        diag = summarize_diagnostics_evidence(
            semantic_escalation.get("diagnostics"),
            traceability=traceability,
            recently_changed=recently_changed,
        )

        interp_supports_req = interp["cause"] == "requirement"
        if not interp_supports_req:
            strategy = MODEL_OVERCONSTRAINT_REPAIR
            reason = (
                "the result interpretation does not attribute the failure to the "
                f"requirements (verdict: {interp['cause']})"
            )
        elif diag["ran"] and diag["modeling_evidence"] and not diag["requirement_evidence"]:
            strategy = REQUIREMENTS_DIAGNOSIS
            reason = (
                "the result interpretation attributes the failure to the "
                "requirements; the deterministic diagnosis located the "
                "contradiction in the encoding, which establishes WHERE it sits, "
                "not whether the requirement that encoding transcribes is sound - "
                "so it corroborates the location without refuting the cause"
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
# Delivering the escalation: only the rulebook that applies
# --------------------------------------------------------------------------- #

# The PersistentIssueEscalation section carries one binding-rules block per
# candidate strategy, and they are mutually exclusive: REQUIREMENTS_DIAGNOSIS
# mandates the requirement entries MODEL_OVERCONSTRAINT_REPAIR forbids. Which
# one applies was already settled deterministically by apply_evidence_alignment
# before the prompt is built, so shipping both leaves the model holding two
# opposed rulebooks and a pointer to the right one - a resolution step it can
# get wrong, paid for on every escalated iteration.
_BINDING_RULES_HEADER = "**BINDING RULES when STRATEGY is "
# Emitted by build_semantic_escalation / apply_evidence_alignment above.
_STRATEGY_LINE = "STRATEGY: "
# Only meaningful while both blocks are present.
_MULTI_BLOCK_POINTER = (
    "Read ONLY the block matching the STRATEGY line above; the other does not "
    "apply this iteration."
)


def strategy_from_directive(directive: Optional[str]) -> Optional[str]:
    """The strategy the evidence settled on, read back off the directive text.

    Returns None when the directive names none, or names more than one and they
    disagree - both mean "not settled", and the caller must not act on a guess.
    Disagreement is a real state, not a parsing artifact: _stage_stall_diagnosis
    appends its own REQUIREMENTS_DIAGNOSIS block to an escalation the evidence
    gate may have redirected to MODEL_OVERCONSTRAINT_REPAIR, and then both
    rulebooks genuinely apply - to different issues.
    """
    if not directive:
        return None
    named = {
        line.split(_STRATEGY_LINE, 1)[1].strip()
        for line in directive.splitlines()
        if _STRATEGY_LINE in line and line.strip().startswith(_STRATEGY_LINE)
    }
    return named.pop() if len(named) == 1 else None


def select_binding_rules(section: str, directive: Optional[str]) -> str:
    """Drop the binding-rules blocks that do not apply to this iteration.

    Returns `section` unchanged whenever the choice is not certain: fewer than
    two blocks, no settled strategy, or a strategy no block is written for. The
    unchanged section is the behaviour that shipped before this selection
    existed, so the fallback is never worse than not selecting.
    """
    if not section or section.count(_BINDING_RULES_HEADER) < 2:
        return section

    strategy = strategy_from_directive(directive)
    if not strategy:
        return section

    head, _, rest = section.partition(_BINDING_RULES_HEADER)
    blocks = [_BINDING_RULES_HEADER + b for b in rest.split(_BINDING_RULES_HEADER)]
    kept = [b for b in blocks if b.startswith(_BINDING_RULES_HEADER + strategy)]
    if len(kept) != 1:
        # The strategy is real but no block states its rules (the syntax-ladder
        # strategies, for one). Every block still applies as written - keep them.
        return section

    head = head.replace(_MULTI_BLOCK_POINTER, "")
    while "\n\n\n" in head:
        head = head.replace("\n\n\n", "\n\n")
    return head.rstrip() + "\n\n" + kept[0].rstrip() + "\n"


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


# ---------------------------------------------------------------------- #
# RE Mode 3 - the Evaluator's next-action decision is the diagnostic signal #
# ---------------------------------------------------------------------- #
# The presence of injected DIAGNOSTIC CANDIDATES text cannot select the mode:
# it fires on essentially every UNSAT iteration and carries raw candidates the
# Evaluator may not have adopted. The decision is the signal, and it is parsed
# here the same deterministic way the gate decision and the STRATEGY line are.

DIAGNOSTIC_DECISION = "run diagnostic experiments"

NEXT_ACTION_DECISIONS = (
    "keep fix",
    "refine/narrow fix",
    "partially revert",
    "escalate to requirement clarification",
    "adjust scope/trace and rerun",
    DIAGNOSTIC_DECISION,
)

# Which construct kind a hypothesis is stated at. Only `predicate` survives
# Phase 2 filtering, but the level must be parsed to be able to drop the others.
DIAGNOSTIC_LEVELS = ("predicate", "fact", "scope")

_PLAN_FIELDS = ("construct", "hypothesis", "level", "reading")


def _section_lines(text: str, header_keywords: str) -> Optional[List[str]]:
    """
    Lines of a `=== SECTION ===` block, from the header to the next `=== ... ===`
    header or EOF. Returns None when the section is absent (distinct from a
    section that is present but empty, which returns []).
    """
    import re
    header = re.compile(rf"^===\s*{header_keywords}\s*===", re.IGNORECASE)
    any_header = re.compile(r"^===\s*.+?\s*===")
    lines = (text or "").split("\n")
    start = next((i for i, l in enumerate(lines) if header.match(l.strip())), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if any_header.match(lines[i].strip())),
        len(lines),
    )
    return lines[start + 1:end]


def _clean_field_value(value: str) -> str:
    """Strip markdown emphasis and template placeholders ("[exact name]" -> "")."""
    import re
    value = re.sub(r"[*`_]", "", value or "").strip()
    if value.startswith("[") and value.endswith("]"):
        return ""
    if value.lower() in ("none", "n/a", "na", "-"):
        return ""
    return value


def parse_next_action_decision(feedback: Optional[str]) -> Optional[str]:
    """
    Read the `Decision:` line out of `=== NEXT ACTION DECISION ===` and normalize
    it to one of NEXT_ACTION_DECISIONS.

    Returns None when the section, the line, or an unambiguous match is missing -
    including when the line names two or more decisions (an echoed template).
    Refusing is the safe outcome: every caller falls back to prior behaviour.
    """
    import re

    section = _section_lines(feedback or "", r"NEXT\s+ACTION\s+DECISION")
    if not section:
        return None

    line = next(
        (l for l in section if re.match(r"^\s*[-*]?\s*(\*\*)?decision\b", l, re.IGNORECASE)),
        None,
    )
    if line is None or ":" not in line:
        return None

    text = line.split(":", 1)[1]
    text = re.sub(r"[*`_\[\]]", " ", text).lower()
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if not text:
        return None

    for decision in NEXT_ACTION_DECISIONS:
        if text == decision:
            return decision
    matched = [d for d in NEXT_ACTION_DECISIONS if d in text]
    return matched[0] if len(matched) == 1 else None


def parse_diagnostic_plan(feedback: Optional[str]) -> Dict[str, Any]:
    """
    Parse `=== DIAGNOSTIC PLAN ===` into structured items.

    Each item is introduced by a `Construct:` line and carries Hypothesis, Level
    and Reading. An item missing any field, or naming a level outside
    DIAGNOSTIC_LEVELS, is dropped with a reason rather than half-honoured - a
    hypothesis with no reading declared BEFORE the run is exactly the post-hoc
    reading this mode exists to prevent.

    Returns {"items": [{construct, hypothesis, level, reading}], "dropped":
    [{"construct", "reason"}]}. Callers must log the drops; nothing here is
    allowed to disappear silently.
    """
    import re

    result: Dict[str, Any] = {"items": [], "dropped": []}
    section = _section_lines(feedback or "", r"DIAGNOSTIC\s+PLAN")
    if not section:
        return result

    field_line = re.compile(
        rf"^\s*[-*]?\s*(\*\*)?({'|'.join(_PLAN_FIELDS)})(\*\*)?\s*:\s*(.*)$",
        re.IGNORECASE,
    )

    raw_items: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    field: Optional[str] = None
    for line in section:
        match = field_line.match(line)
        if match:
            field = match.group(2).lower()
            value = match.group(4).strip()
            if field == "construct":
                current = {"construct": value}
                raw_items.append(current)
            elif current is not None:
                current[field] = value
        elif current is not None and field and line.strip():
            # Continuation of the field above (a wrapped hypothesis or reading).
            current[field] = (current.get(field, "") + " " + line.strip()).strip()

    for raw in raw_items:
        item = {f: _clean_field_value(raw.get(f, "")) for f in _PLAN_FIELDS}
        name = item["construct"] or "(unnamed)"
        if not item["construct"]:
            result["dropped"].append({"construct": name, "reason": "no construct named"})
            continue
        if item["level"].lower() not in DIAGNOSTIC_LEVELS:
            result["dropped"].append({
                "construct": name,
                "reason": f"level '{raw.get('level', '')}' is not one of "
                          f"{'/'.join(DIAGNOSTIC_LEVELS)}",
            })
            continue
        if not item["hypothesis"]:
            result["dropped"].append({"construct": name, "reason": "no hypothesis stated"})
            continue
        if not item["reading"]:
            result["dropped"].append({
                "construct": name,
                "reason": "no reading declared before the run",
            })
            continue
        item["level"] = item["level"].lower()
        result["items"].append(item)

    return result


def _declared_or_mentioned(model_text: str) -> Any:
    """
    Predicate over construct names: True when the name is a declared block
    (fact/pred/assert/fun/sig) or appears anywhere in the model as a whole word.

    Deliberately the weakest form of "exists in the model". A false drop turns a
    diagnostic iteration into a repair iteration silently, which is worse than
    letting through a name that only appears in a comment - the analyzer will
    simply not produce a probe verdict for it, and T1's manifest reports it as
    `not run`.
    """
    import re

    names = set()
    try:
        from .semantic_diagnostics import extract_all_blocks
        names = {b["name"] for b in extract_all_blocks(model_text or "")}
    except Exception:
        pass
    names |= set(re.findall(r"^\s*(?:one\s+|abstract\s+)*sig\s+(\w+)",
                            model_text or "", re.MULTILINE))

    def exists(name: str) -> bool:
        if name in names:
            return True
        return bool(re.search(rf"\b{re.escape(name)}\b", model_text or ""))

    return exists


def filter_diagnostic_plan(
    items: List[Dict[str, str]],
    model_text: Optional[str] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Phase 2 guard rails: the Evaluator judges WHETHER to diagnose, code decides
    WHAT survives.

    Drops, each with a reason:
      - level `fact`   - the deterministic localizer already tests facts by
                         disabling them one at a time, and a fact constrains the
                         probe too, so a predicate-level probe cannot answer it
                         (this is the `EmergencyUnique` case);
      - level `scope`  - only when the scope sweep already ran for that construct;
                         an unswept construct keeps the item, because a larger-scope
                         probe is a new `run` command and stays additive;
      - unknown name   - a construct that appears nowhere in the model is untestable
                         as written.

    Filtering with neither model_text nor diagnostics returns the items unchanged:
    missing evidence must not silently discard a plan.
    """
    result: Dict[str, Any] = {"items": [], "dropped": []}
    exists = _declared_or_mentioned(model_text) if model_text else None
    swept = {
        name
        for name, entry in (diagnostics or {}).items()
        if ((entry or {}).get("scope_sweep") or {}).get("performed")
    }

    for item in items or []:
        name = item.get("construct", "")
        level = (item.get("level") or "").lower()

        if level == "fact":
            result["dropped"].append({
                "construct": name,
                "reason": "fact-level hypothesis: the deterministic localizer already "
                          "tests facts by disabling them, and a fact constrains the probe too",
            })
            continue
        if level == "scope" and name in swept:
            result["dropped"].append({
                "construct": name,
                "reason": "scope-level hypothesis already measured by the scope sweep",
            })
            continue
        if exists is not None and not exists(name):
            result["dropped"].append({
                "construct": name,
                "reason": "names a construct that does not appear in the model",
            })
            continue
        result["items"].append(item)

    return result


DROPPED_ITEMS_HEADING = "=== DIAGNOSTIC ITEMS NOT RUN (already measured) ==="


def build_diagnostic_status_block(
    dropped: List[Dict[str, str]],
    diagnostics: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Render the guard-railed-away plan items with whatever the deterministic
    diagnosis already measured about each one.

    A dropped item must not simply vanish: the Evaluator proposed it because it
    wanted an answer, and for the two levels code drops - `fact` and `scope` -
    that answer already exists (the localizer disables facts one at a time; the
    sweep re-runs at enlarged bounds). Carrying the measurement is what turns a
    refusal into a result. The RE echoes this block in its DIAGNOSTIC EXECUTION
    report so the status reaches the Evaluator through the regression entry.

    Data only, as everywhere in this module. Returns "" when nothing was dropped.
    """
    if not dropped:
        return ""

    diagnostics = diagnostics or {}
    lines = [DROPPED_ITEMS_HEADING]
    for drop in dropped:
        name = drop.get("construct") or "(unnamed)"
        lines.append(f"- Construct: {name}")
        lines.append(f"  Not run: {drop.get('reason', 'no reason recorded')}")

        measured: List[str] = []
        # A fact: the localizer names the predicates it provably blocks.
        blocks = [
            pred for pred, entry in diagnostics.items()
            if name in (((entry or {}).get("localization") or {}).get("blocking_facts") or [])
        ]
        if blocks:
            measured.append(
                f"deterministic localizer: proven to block {', '.join(sorted(blocks))}"
            )
        # A predicate: its own sweep and localization verdicts.
        entry = diagnostics.get(name) or {}
        sweep = entry.get("scope_sweep") or {}
        if sweep.get("performed"):
            verdict = sweep.get("sat_at_larger_scope")
            measured.append(
                f"scope sweep ({sweep.get('swept_command', 'enlarged bounds')}): "
                + ("SAT at larger scope - bounded-search artifact"
                   if verdict is True else
                   "still UNSAT at larger scope - genuine over-constraint")
            )
        localization = entry.get("localization") or {}
        if localization.get("verdict"):
            blocking = ", ".join(localization.get("blocking_facts") or []) or "none"
            measured.append(
                f"localizer verdict: {localization['verdict']} (blocking facts: {blocking})"
            )

        if measured:
            for line in measured:
                lines.append(f"  Measured: {line}")
        else:
            lines.append(
                "  Measured: no deterministic result for this construct - it was dropped "
                "as untestable as written, not as already answered"
            )
    return "\n".join(lines)


def should_run_diagnostic_iteration(
    feedback: Optional[str],
    model_text: Optional[str] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Decide whether the RE's next model update is a diagnostic iteration (Mode 3)
    or an ordinary semantic repair (Mode 2).

    Both conditions must hold: the Evaluator chose `run diagnostic experiments`,
    AND at least one plan item survives parsing and the Phase 2 guard rails. A
    diagnostic decision with nothing usable behind it falls back to Mode 2 - the
    same deterministic downgrade used everywhere else in this module.

    Returns {"diagnostic", "decision", "items", "dropped", "reason"}.
    """
    decision = parse_next_action_decision(feedback)
    if decision != DIAGNOSTIC_DECISION:
        named = f"'{decision}'" if decision else "unparseable"
        return {
            "diagnostic": False,
            "decision": decision,
            "items": [],
            "dropped": [],
            "status_block": "",
            "reason": f"next-action decision is {named}, not '{DIAGNOSTIC_DECISION}'",
        }

    plan = parse_diagnostic_plan(feedback)
    if plan["items"]:
        guarded = filter_diagnostic_plan(plan["items"], model_text, diagnostics)
        plan = {
            "items": guarded["items"],
            "dropped": plan["dropped"] + guarded["dropped"],
        }
    if not plan["items"]:
        return {
            "diagnostic": False,
            "decision": decision,
            "items": [],
            "dropped": plan["dropped"],
            "status_block": build_diagnostic_status_block(plan["dropped"], diagnostics),
            "reason": "diagnostic decision carries no usable plan item - falling back "
                      "to semantic repair",
        }

    return {
        "diagnostic": True,
        "decision": decision,
        "items": plan["items"],
        "dropped": plan["dropped"],
        "status_block": build_diagnostic_status_block(plan["dropped"], diagnostics),
        "reason": f"{len(plan['items'])} plan item(s) survived parsing",
    }


PROBE_VERDICTS_HEADING = "=== DIAGNOSTIC EXPERIMENT RESULTS (measured) ==="

# Strategy name for the re-issue of a planned experiment that produced no probe.
RERUN_DIAGNOSTIC_PROBES = "RERUN_DIAGNOSTIC_PROBES"

# An item is re-issued once. A second miss abandons it rather than looping: two
# failures to express the same hypothesis is evidence about the hypothesis, not
# about the RE's diligence.
REISSUE_LIMIT = 2


def build_diagnostic_reissue(
    current_iteration: int,
    items: Optional[List[Dict[str, Any]]] = None,
    abandoned: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build a RERUN_DIAGNOSTIC_PROBES directive for plan items that were ordered
    but produced no probe.

    An unrun item is the one outcome that answers nothing: it cannot be read as
    refuted (that is the whole point of the `not_run` status), so the hypothesis
    just sits unmeasured while the readback correctly refuses to conclude from
    it. Asking again once is what turns that into either an answer or a stated
    impossibility.

    `items` are being re-issued (each carries its `attempt`); `abandoned` were
    already re-issued once and missed again - they are named so their silence is
    on the record rather than looking like they were never planned.

    Returns the usual directive shape; empty directive when there is nothing to say.
    """
    result: Dict[str, Any] = {
        "escalation_level": 5,
        "strategy": RERUN_DIAGNOSTIC_PROBES,
        "escalated_issues": [],
        "rerun_targets": [i.get("construct") for i in (items or [])],
        "abandoned_targets": [i.get("construct") for i in (abandoned or [])],
        "directive": "",
    }
    if not (items or abandoned):
        return result

    lines = [
        "ESCALATION LEVEL: 5",
        f"STRATEGY: {RERUN_DIAGNOSTIC_PROBES}",
        "TRIGGER: experiments were planned for the previous iteration and no probe "
        "reported for them. An experiment that did not run measured NOTHING - it is "
        "not a refuted hypothesis, so the question is still open.",
    ]

    if items:
        lines.append("")
        lines.append(
            "RE-RUN these experiments. They belong to this iteration's plan even though "
            "they are listed here rather than in the DIAGNOSTIC PLAN section: number "
            "their probes CONTINUING the plan's numbering, in the order listed below "
            "(if the plan holds 2 items, the first item here is probe3_). Write the "
            "probe exactly as described; if the hypothesis genuinely cannot be expressed "
            "as an additive probe, say so and name what blocks it. Do NOT omit it "
            "silently a second time:"
        )
        for item in items:
            lines.append(f"  - Construct: {item.get('construct', '')}")
            lines.append(f"    Hypothesis: {item.get('hypothesis', '')}")
            lines.append(f"    Declared reading: {item.get('reading', '')}")
            if (item.get("attempt") or 1) > 1:
                lines.append(
                    "    NOTE: this was already asked for once and produced no probe."
                )

    if abandoned:
        lines.append("")
        lines.append(
            "NOT RETRIED (asked twice, no probe either time) - these hypotheses remain "
            "UNMEASURED. Draw no conclusion from them; they are neither confirmed nor "
            "refuted:"
        )
        for item in abandoned:
            lines.append(f"  - {item.get('construct', '')}: {item.get('hypothesis', '')}")

    result["directive"] = "\n".join(lines)
    return result


_PROBE_RE = _re.compile(r'^probe(\d+)_(\w*)', _re.IGNORECASE)


def _probe_suffix(name: str) -> str:
    """`probe2_ScenarioMultiEmgA` -> `ScenarioMultiEmgA`."""
    m = _PROBE_RE.match(name or "")
    return m.group(2) if m else ""


def _construct_key(name: str) -> str:
    """Compare names without separators or case - the RE drops underscores."""
    return "".join(ch for ch in (name or "") if ch.isalnum()).lower()


def read_back_probe_verdicts(
    plan_items: Optional[List[Dict[str, str]]],
    satisfied: Optional[List[str]] = None,
    unsatisfied: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Phase 5 readback: join the probes' analyzer verdicts back onto the plan they
    were written from (T1 - the plan is a manifest, not a wish list).

    Each item gets one of three statuses, and the third is the reason this
    function exists:

      confirmed - a probe ran and its declared reading is met (SAT)
      refuted   - a probe ran and its declared reading is not met (UNSAT)
      not_run   - NO probe reported for this item

    `not_run` must never collapse into `refuted`. A probe that was never written
    produces no row in the analyzer output, and reading that silence as UNSAT is
    how "both hypotheses exonerated - so the defect is requirement-level" gets
    concluded from one experiment that ran and one that never existed.

    Probes are matched BY NAME first, by position only as a fallback. `probe<N>_`
    numbering is the RE's, not ours: an RE that probes the item it found easiest
    and calls it `probe1_` would, under positional matching alone, have every
    verdict attributed to the wrong hypothesis - reported confidently, since a
    full and plausible table is still produced. The suffix already carries the
    construct, so it is the more reliable key. Each probe is claimed once, so a
    plan item whose probe went to another item correctly reports `not_run`.
    """
    import re

    satisfied = list(satisfied or [])
    unsatisfied = list(unsatisfied or [])
    items = list(plan_items or [])
    all_probes = [n for n in satisfied + unsatisfied if _PROBE_RE.match(n)]

    claimed: Dict[int, str] = {}   # item index (1-based) -> probe name
    taken: set = set()

    def _claim(pred):
        for index, item in enumerate(items, start=1):
            if index in claimed:
                continue
            key = _construct_key(item.get("construct", ""))
            if not key:
                continue
            for probe in all_probes:
                if probe in taken:
                    continue
                if pred(key, _construct_key(_probe_suffix(probe))):
                    claimed[index], _ = probe, taken.add(probe)
                    break

    # Exact on the normalized suffix (`Scenario_MultiEmg_A` -> `ScenarioMultiEmgA`),
    # then containment, which is how a truncated or extended suffix still lands.
    _claim(lambda key, suffix: bool(suffix) and key == suffix)
    _claim(lambda key, suffix: bool(suffix) and (key in suffix or suffix in key))

    # Fallback: an unclaimed item takes `probe<i>_` if that probe is still free.
    misnumbered: List[str] = []
    for index, item in enumerate(items, start=1):
        if index in claimed:
            m = _PROBE_RE.match(claimed[index])
            if m and int(m.group(1)) != index:
                misnumbered.append(f"{claimed[index]} answers plan item {index}")
            continue
        prefix = re.compile(rf"^probe{index}_", re.IGNORECASE)
        free = [n for n in all_probes if n not in taken and prefix.match(n)]
        if free:
            claimed[index] = free[0]
            taken.add(free[0])

    results: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        probe = claimed.get(index)
        if probe and probe in satisfied:
            status = "confirmed"
        elif probe and probe in unsatisfied:
            status = "refuted"
        else:
            status, probe = "not_run", None
        results.append({
            "index": index,
            "construct": item.get("construct", ""),
            "hypothesis": item.get("hypothesis", ""),
            "reading": item.get("reading", ""),
            "probe": probe,
            "status": status,
        })

    return {
        "results": results,
        "probes": [r["probe"] for r in results if r["probe"]],
        "not_run": [r["construct"] for r in results if r["status"] == "not_run"],
        "all_refuted": bool(results) and all(r["status"] == "refuted" for r in results),
        "misnumbered": misnumbered,
        "unmatched_probes": sorted(n for n in all_probes if n not in taken),
    }


def build_probe_verdict_block(
    readback: Dict[str, Any],
    control: Optional[str] = None,
    probe_bodies: Optional[Dict[str, str]] = None,
) -> str:
    """
    Render the readback as measured evidence for the escalation directive - data
    only, alongside `blocking_facts`. The interpretation rules live in the prompt.

    "all refuted" is stated explicitly because it is the finding that is easiest
    to misread as failure: every candidate encoding was exonerated, which points
    at the requirement rather than the model - but only when every item actually
    ran, which is why `not_run` items suppress it.

    `control` is the CONTROL line from the diff check. It leads the block because
    a verdict measured on an altered model means nothing, and that has to be read
    before the verdicts, not after them.

    `probe_bodies` carries each probe's source. The declared reading is the RE's
    CLAIM about what the probe altered; the body is the only evidence of what it
    actually altered. Since the probes are gone from the model the Evaluator is
    handed, this block is where they survive.
    """
    results = (readback or {}).get("results") or []
    if not results:
        return ""

    lines = [PROBE_VERDICTS_HEADING]
    if control:
        lines.append(control)
    label = {
        "confirmed": "CONFIRMED (SAT)",
        "refuted": "REFUTED (UNSAT)",
        "not_run": "NOT RUN - no probe reported",
    }
    for r in results:
        lines.append(f"- Construct: {r['construct']}")
        lines.append(f"  Hypothesis: {r['hypothesis']}")
        lines.append(f"  Declared reading: {r['reading']}")
        lines.append(f"  Probe: {r['probe'] or 'none'}")
        lines.append(f"  Verdict: {label[r['status']]}")
        body = (probe_bodies or {}).get(r["probe"] or "")
        if body:
            lines.append("  Probe source (as executed):")
            lines.extend(f"    {ln}" for ln in body.splitlines())

    if readback.get("misnumbered"):
        # Corrected, not hidden: the numbering was wrong, so the RE will likely
        # get it wrong again, and a reader comparing this block to the model
        # would otherwise see numbers that do not line up.
        lines.append(
            "NOTE: probe numbering did not follow the plan order; matched by construct name "
            "instead (" + "; ".join(readback["misnumbered"]) + ")."
        )
    if readback.get("unmatched_probes"):
        lines.append(
            "NOTE: " + ", ".join(readback["unmatched_probes"]) + " ran but matches no plan "
            "item. It measures something that was not ordered - do not read it as evidence "
            "for any hypothesis below."
        )
    if readback.get("not_run"):
        lines.append(
            "NOTE: " + ", ".join(readback["not_run"]) + " produced no verdict. An item that "
            "did not run is UNMEASURED, not refuted - draw no conclusion from its absence."
        )
    elif readback.get("all_refuted"):
        lines.append(
            "NOTE: every hypothesis was refuted, and every item ran. The candidate encodings "
            "are exonerated as the cause; the remaining explanation is at the requirement level."
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Mode 3: the control check.
#
# A diagnostic iteration is only additive - probes are added, nothing existing is
# touched - and the whole meaning of a SAT/UNSAT verdict rests on that. Rolling
# the model back afterwards protects the MODEL from an illegal edit; it does not
# protect the EVIDENCE, because the analyzer already ran on the altered model and
# the verdict is already recorded. So the control is checked, not assumed.
# --------------------------------------------------------------------------- #

CONTROL_UNMODIFIED = "Control: UNMODIFIED (identical to the pre-experiment model outside the probes)"


def _normalize_model(text: str) -> List[str]:
    """
    Blank lines dropped and every whitespace run collapsed to one space.

    Alloy treats whitespace only as a token separator, so re-indenting or padding
    is not an edit. Being lenient here is deliberate: a false MODIFIED throws away
    a sound measurement, which costs more than letting a cosmetic change pass.
    """
    return [" ".join(ln.split()) for ln in (text or "").splitlines() if ln.strip()]


def strip_probes(model_text: str) -> str:
    """
    Remove every `probe<N>_` block and its own `run` command.

    What is left must equal the pre-experiment model. Run commands are removed by
    name rather than by position because a probe's run may sit anywhere among the
    others.
    """
    import re

    from .semantic_diagnostics import extract_all_blocks, is_probe_name

    lines = (model_text or "").splitlines()
    drop = set()
    probes = set()
    for b in extract_all_blocks(model_text or ""):
        if is_probe_name(b["name"]):
            probes.add(b["name"])
            drop.update(range(b["start"], b["end"] + 1))
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("run ", "check ")) and any(
            re.search(rf'\b{re.escape(p)}\b', stripped) for p in probes
        ):
            drop.add(i)
    return "\n".join(ln for i, ln in enumerate(lines) if i not in drop)


def extract_probe_bodies(model_text: str) -> Dict[str, str]:
    """Probe name -> its source, so the verdict survives the model it was measured on."""
    from .semantic_diagnostics import extract_all_blocks, is_probe_name

    lines = (model_text or "").splitlines()
    return {
        b["name"]: "\n".join(lines[b["start"]: b["end"] + 1])
        for b in extract_all_blocks(model_text or "")
        if is_probe_name(b["name"])
    }


def diff_diagnostic_control(
    diagnostic_model: str,
    baseline_model: str,
) -> Dict[str, Any]:
    """
    Did the diagnostic iteration change anything other than adding probes?

    Returns {"modified", "changed", "removed", "added", "probes", "status", "detail"}.
    `status` is the CONTROL line that leads the verdict block; `modified` True means
    every verdict from that iteration is void - the hypothesis was tested against a
    model nobody approved, so a SAT may be the edit talking, not the probe.

    With no baseline to compare against, report UNMODIFIED rather than guessing:
    the same refuse-when-unsure rule the guard rails use. A false MODIFIED discards
    a sound measurement, which is the more expensive mistake.
    """
    from .semantic_diagnostics import extract_all_blocks, is_probe_name

    probes = sorted(extract_probe_bodies(diagnostic_model).keys())
    result: Dict[str, Any] = {
        "modified": False,
        "changed": [],
        "removed": [],
        "added": [],
        "probes": probes,
        "status": CONTROL_UNMODIFIED,
        "detail": "",
    }
    if not (baseline_model or "").strip() or not (diagnostic_model or "").strip():
        return result

    stripped = strip_probes(diagnostic_model)
    if _normalize_model(stripped) == _normalize_model(baseline_model):
        return result

    def _split(text):
        """Named non-probe blocks (line-break-insensitive) and everything else."""
        lines = text.splitlines()
        blocks, owned = {}, set()
        for b in extract_all_blocks(text):
            if is_probe_name(b["name"]):
                continue
            span = range(b["start"], b["end"] + 1)
            owned.update(span)
            blocks[b["name"]] = " ".join(_normalize_model(
                "\n".join(lines[b["start"]: b["end"] + 1])))
        residual = _normalize_model(
            "\n".join(ln for i, ln in enumerate(lines) if i not in owned))
        return blocks, residual

    before, residual_before = _split(baseline_model)
    after, residual_after = _split(stripped)
    result["changed"] = sorted(n for n in before if n in after and before[n] != after[n])
    result["removed"] = sorted(n for n in before if n not in after)
    result["added"] = sorted(n for n in after if n not in before)

    parts = []
    if result["changed"]:
        parts.append(f"modified {', '.join(result['changed'])}")
    if result["removed"]:
        parts.append(f"deleted {', '.join(result['removed'])}")
    if result["added"]:
        parts.append(f"added non-probe {', '.join(result['added'])}")
    if not parts:
        if residual_before == residual_after:
            # Every block and every stray line matches - the earlier inequality was
            # line breaks alone. Not an edit.
            return result
        # A run command, a scope, an open statement. Named vaguely on purpose:
        # it is outside any block, but it is still a changed control.
        parts.append("changed text outside any named block (a run command, a scope, or an open)")

    result["modified"] = True
    result["detail"] = "; ".join(parts)
    result["status"] = (
        f"Control: MODIFIED - the RE {result['detail']}. Mode 3 permits additions only, so "
        f"these verdicts were measured against a model that is not the one under repair. "
        f"Treat every hypothesis below as UNANSWERED and do not act on its verdict."
    )
    return result


_DIAGNOSTIC_PLAN_HEADER = "=== DIAGNOSTIC PLAN ==="


def preserve_diagnostic_signal(draft: str, refined: str) -> Dict[str, Any]:
    """
    Carry a diagnostic decision and its plan across RefineFeedback.

    RefineFeedback rewrites the whole feedback and does not carry the response
    format, so a prompt rule cannot guarantee the decision line and the plan
    survive - and they select how the RE runs next, not merely what it reads.
    This is the same safety net `_inject_diagnostic_experiments` provides for the
    candidates, applied to the signal.

    The user's review may legitimately overturn the choice ("stop experimenting,
    just fix it"), so an override is respected and restoration only fires when
    the refined text names NO decision at all:

      refined decision                       action
      -------------------------------------  ----------------------------------
      any other recognized decision          'overridden' - leave it alone
      diagnostic, plan present               'intact'
      diagnostic, plan missing               restore the plan section
      unparseable / absent                   restore the decision line and plan

    Returns {"text", "action", "restored": [...]}.
    """
    import re

    result = {"text": refined, "action": "not_applicable", "restored": []}
    if parse_next_action_decision(draft) != DIAGNOSTIC_DECISION:
        return result

    draft_plan_lines = _section_lines(draft, r"DIAGNOSTIC\s+PLAN")
    plan_block = (
        _DIAGNOSTIC_PLAN_HEADER + "\n" + "\n".join(draft_plan_lines).strip()
        if draft_plan_lines else ""
    )

    refined_decision = parse_next_action_decision(refined)
    if refined_decision is not None and refined_decision != DIAGNOSTIC_DECISION:
        result["action"] = "overridden"
        return result

    text = refined
    restored = []

    if refined_decision is None:
        decision_line = f"Decision: {DIAGNOSTIC_DECISION}"
        lines = text.split("\n")
        header = re.compile(r"^===\s*NEXT\s+ACTION\s+DECISION\s*===", re.IGNORECASE)
        start = next((i for i, l in enumerate(lines) if header.match(l.strip())), None)
        if start is None:
            text = f"=== NEXT ACTION DECISION ===\n{decision_line}\n\n" + text.lstrip()
        else:
            existing = next(
                (i for i in range(start + 1, len(lines))
                 if re.match(r"^\s*[-*]?\s*(\*\*)?decision\b", lines[i], re.IGNORECASE)),
                None,
            )
            if existing is None:
                lines.insert(start + 1, decision_line)
            else:
                lines[existing] = decision_line
            text = "\n".join(lines)
        restored.append("decision")

    if plan_block and not parse_diagnostic_plan(text)["items"]:
        # Placed before REPAIR INSTRUCTIONS when that section exists, so the plan
        # reads where the schema puts it; trailing otherwise.
        marker = re.compile(r"^===\s*REPAIR\s+INSTRUCTIONS\s*===", re.IGNORECASE)
        lines = text.split("\n")
        at = next((i for i, l in enumerate(lines) if marker.match(l.strip())), None)
        if at is None:
            text = text.rstrip() + "\n\n" + plan_block + "\n"
        else:
            text = "\n".join(lines[:at] + plan_block.split("\n") + [""] + lines[at:])
        restored.append("plan")

    result["text"] = text
    result["action"] = "restored" if restored else "intact"
    result["restored"] = restored
    return result


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


def build_stale_construct_removal(
    current_iteration: int,
    audit: Dict[str, Any],
    closure: Dict[str, Any],
    already_removed: bool = False,
) -> Dict[str, Any]:
    """
    Build a REMOVE_STALE_CONSTRUCTS directive from an ownership audit.

    Unlike REGENERATE_PREDICATES, these constructs are NOT rebuilt: an orphan
    encodes a requirement that no longer exists, so there is nothing to rebuild
    it from - it must be DELETED. Dead helpers stranded by that deletion go with
    it (the closure's cascade).

    Args:
        current_iteration: iteration the audit was taken on.
        audit: audit_ownership() result (supplies why each construct is going).
        closure: compute_removable_closure() result (what may safely go).

    Returns {'strategy', 'remove_targets', 'directive', ...}; an empty directive
    when there is nothing safe to remove.
    """
    result: Dict[str, Any] = {
        "escalation_level": 5,
        "strategy": REMOVE_STALE_CONSTRUCTS,
        "escalated_issues": [],
        "remove_targets": list((closure or {}).get("remove") or []),
        "cascaded": list((closure or {}).get("cascaded") or []),
        "blocked": dict((closure or {}).get("blocked") or {}),
        # Kept so a later re-render (e.g. after a deterministic prune) can still
        # state WHY each construct went.
        "audit": {
            "orphan": dict((audit or {}).get("orphan") or {}),
            "dead": list((audit or {}).get("dead") or []),
            # Carried so the removal record can say WHAT went (fact vs assert),
            # not just its name - the removal log renders "[fact]" from this.
            "kinds": dict((audit or {}).get("kinds") or {}),
        },
        "directive": "",
    }
    if not result["remove_targets"]:
        return result
    try:
        orphans = (audit or {}).get("orphan") or {}
        dead = set((audit or {}).get("dead") or [])
        cascaded = set((closure or {}).get("cascaded") or [])

        lines = [
            "ESCALATION LEVEL: 5",
            f"STRATEGY: {REMOVE_STALE_CONSTRUCTS}",
            "TRIGGER: constructs in the model no longer belong to any live "
            "requirement.",
        ]
        if already_removed:
            lines.append(
                "The following constructs (and their run/check commands) have "
                "ALREADY BEEN REMOVED from the model you were given. Do NOT "
                "re-introduce them - their requirements no longer exist:"
            )
        else:
            lines.append(
                "DELETE these constructs entirely. Do NOT rewrite, weaken, or "
                "convert them to assertions - they encode requirements that no "
                "longer exist, so there is nothing to rebuild them from:"
            )
        for name in result["remove_targets"]:
            if name in orphans:
                owners = orphans[name]
                if isinstance(owners, str):
                    # A plain-language reason rather than a list of requirement
                    # IDs (a spent diagnostic probe encodes no requirement at
                    # all). Joining a string here spelled it out letter by
                    # letter, so state it as given.
                    why = owners
                else:
                    why = (f"encodes {', '.join(owners)}, which is no longer in "
                           f"the requirements")
            elif name in cascaded:
                why = "helper left with no caller once the constructs above are deleted"
            elif name in dead:
                why = "dead code: no caller and no run/check command"
            else:
                why = "no live requirement owner"
            lines.append(f"  - {name} ({why})")
        if result["blocked"]:
            lines.append(
                "STILL REFERENCED (do not delete yet - remove the references first):"
            )
            for name, referrers in result["blocked"].items():
                lines.append(f"  - {name} <- {', '.join(referrers)}")
        lines.append(
            "Continue from the model as given; keep every construct that still "
            "serves a live requirement."
            if already_removed else
            "After deleting, ensure no remaining construct references a deleted "
            "name, and keep every construct that still serves a live requirement."
        )
        result["directive"] = "\n".join(lines)
        return result
    except Exception:
        return result


def merge_stale_removals(
    current_iteration: int,
    existing: Optional[Dict[str, Any]],
    incoming: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Union two REMOVE_STALE_CONSTRUCTS directives into one.

    Several producers stage deletions into the same slot within one iteration -
    spent diagnostic probes, the constructs of a requirement the user removed,
    and the ownership audit's orphans. Assigning meant the last writer silently
    discarded the others, and a construct dropped that way is never retried: each
    producer only fires on the condition that first surfaced it.

    Merging keeps one directive with one consumer. The text is rebuilt from the
    merged inputs so it still states why each construct is going.
    """
    if not existing or not (existing.get("remove_targets") or []):
        return incoming
    if not incoming or not (incoming.get("remove_targets") or []):
        return existing

    def _audit(d):
        return d.get("audit") or {}

    audit = {
        "orphan": {**(_audit(existing).get("orphan") or {}),
                   **(_audit(incoming).get("orphan") or {})},
        "dead": sorted(set(_audit(existing).get("dead") or [])
                       | set(_audit(incoming).get("dead") or [])),
        "kinds": {**(_audit(existing).get("kinds") or {}),
                  **(_audit(incoming).get("kinds") or {})},
    }
    closure = {
        "remove": sorted(set(existing.get("remove_targets") or [])
                         | set(incoming.get("remove_targets") or [])),
        "cascaded": sorted(set(existing.get("cascaded") or [])
                           | set(incoming.get("cascaded") or [])),
        "blocked": {**(existing.get("blocked") or {}),
                    **(incoming.get("blocked") or {})},
    }
    return build_stale_construct_removal(
        current_iteration=current_iteration, audit=audit, closure=closure
    )


def build_encode_provisional(
    current_iteration: int,
    unencoded: Optional[List[Dict[str, Any]]] = None,
    unannotated: Optional[List[Dict[str, Any]]] = None,
    previous_targets: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build an ENCODE_PROVISIONAL directive for requirement updates that produced
    no traceable construct.

    A provisional requirement is decided by verifying its encoding, so an item
    nothing in the model can be traced to accumulates no evidence in either
    direction - it just sits, holding convergence open. That is a stall, and
    waiting quietly is the one response that cannot resolve it.

    The two causes need OPPOSITE remedies, so they are stated separately:
      - `unencoded`   - nothing in the model names or annotates the requirement.
                        It must be BUILT.
      - `unannotated` - constructs exist that declare no requirement at all, so
                        one of them plausibly encodes this item. It needs a
                        `//@req` LABEL, not a rebuild - rebuilding here would
                        duplicate a construct that is already there.

    Each entry is {'req_id', 'text', 'streak', 'candidates'} ('candidates' only
    for the unannotated case: the unowned constructs to choose among).

    `previous_targets` are IDs this directive already asked for in an earlier
    iteration. Naming them tells the RE its previous attempt did not land, so it
    does not repeat it - the same rule the unowned-blocking-facts finding uses.

    Returns the usual directive shape; an empty directive when nothing stalled.
    """
    result: Dict[str, Any] = {
        "escalation_level": 5,
        "strategy": ENCODE_PROVISIONAL,
        "escalated_issues": [],
        "encode_targets": [e.get("req_id") for e in (unencoded or [])],
        "annotate_targets": [e.get("req_id") for e in (unannotated or [])],
        "repeated": [],
        "directive": "",
    }
    if not (unencoded or unannotated):
        return result
    try:
        already = set(previous_targets or ())
        all_ids = result["encode_targets"] + result["annotate_targets"]
        result["repeated"] = [rid for rid in all_ids if rid in already]

        lines = [
            "ESCALATION LEVEL: 5",
            f"STRATEGY: {ENCODE_PROVISIONAL}",
            "TRIGGER: a requirement update is on probation, but no construct in "
            "the model can be traced to it - so verification can never decide it.",
            "This is a TRACEABILITY obligation, not a repair. The model may be "
            "entirely healthy. Do not weaken, delete or rewrite anything that "
            "works; make each requirement below traceable, and change nothing else.",
        ]
        if unencoded:
            lines.append(
                "BUILD - nothing in the model names or annotates these "
                "requirements. Encode each one, per the MODELING DISCIPLINE (a "
                "prospective R# becomes a predicate/assertion, never a fact), and "
                "either carry the ID in the construct's name or mark it `//@req <ID>`:"
            )
            for item in unencoded:
                lines.append(f"  - {item.get('req_id')}: {(item.get('text') or '').strip()}")
        if unannotated:
            lines.append(
                "LABEL ONLY - constructs exist that declare no requirement, so one "
                "of them likely already encodes these. Add `//@req <ID>` to the "
                "construct that encodes each. Do NOT build a second construct, and "
                "do not change any construct's logic:"
            )
            for item in unannotated:
                candidates = ", ".join((item.get("candidates") or [])[:8]) or "(none listed)"
                lines.append(f"  - {item.get('req_id')}: {(item.get('text') or '').strip()}")
                lines.append(f"      candidates declaring nothing: {candidates}")
        if result["repeated"]:
            lines.append(
                f"REPEATED: {', '.join(result['repeated'])}. This instruction was "
                f"already delivered in an earlier iteration and did not land, so "
                f"whatever you did last time did not make these traceable - do not "
                f"repeat it. If a requirement genuinely cannot be encoded, say so "
                f"explicitly and name what is ambiguous about it rather than "
                f"emitting a construct that does not encode it."
            )
        result["directive"] = "\n".join(lines)
        return result
    except Exception:
        return result


def build_unmodelable_requirement_diagnosis(
    current_iteration: int,
    items: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Evidence block for requirements the modeller could not encode at all.

    Three iterations of directives produced no construct traceable to the
    requirement, and the user chose to treat that as a fact about the
    REQUIREMENT rather than about the modeller. That is the same conclusion
    REQUIREMENTS_DIAGNOSIS already stands for - a requirement that resists
    encoding is ambiguous, unmodelable, or contradictory as stated - so it is
    delivered through the same channel rather than a new one.

    Each entry is {'req_id', 'text', 'reason', 'conflicts_with'}. Returns the
    directive text ("" when there is nothing to say); as everywhere in this
    module it carries facts only.
    """
    entries = [e for e in (items or []) if (e or {}).get("req_id")]
    if not entries:
        return ""
    lines = [
        f"STRATEGY: {REQUIREMENTS_DIAGNOSIS}",
        "UNMODELABLE REQUIREMENT(S): three consecutive iterations of explicit "
        "encoding directives produced no construct that could be traced to "
        "these requirements. The user has asked for them to be diagnosed "
        "rather than re-attempted.",
        "Treat the failure to encode as evidence about the REQUIREMENT TEXT. "
        "For each one, say what makes it resist formalisation - which term is "
        "undefined, which quantifier is ambiguous, which pair of clauses "
        "cannot both hold - and propose wording that can be encoded. Do not "
        "restate the requirement unchanged, and do not propose model repairs.",
    ]
    for item in entries:
        lines.append(f"  - {item.get('req_id')}: {(item.get('text') or '').strip()}")
        if item.get("reason"):
            lines.append(f"      modeller outcome: {item['reason']}")
        if item.get("conflicts_with"):
            lines.append(
                f"      also declared to contradict "
                f"{', '.join(item['conflicts_with'])} - unsettled, and a "
                f"contradiction the modeller cannot encode is a likely cause"
            )
    return "\n".join(lines)


def build_requirement_revert(
    current_iteration: int,
    deleted: Optional[List[Dict[str, Any]]] = None,
    restored: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build a REVERT_REQUIREMENT directive after a contested update was undone.

    A revert is a DOCUMENT edit, and on its own it desynchronises the model: the
    constructs written for the update are still there, encoding text the
    document no longer carries. The two cases need opposite remedies, so they
    are stated separately:

      - `deleted`  - a provisional ADD was removed from the document. Its
                     constructs now encode nothing and must be DELETED; there is
                     no requirement left to rebuild them from.
      - `restored` - a MODIFY was rolled back to its previous wording. Its
                     constructs encode the superseded text and must be
                     REGENERATED from the requirement as it now reads.

    Each entry is {'req_id', 'text', 'constructs'}. As everywhere in this
    module the directive carries facts only; the behavioural rules live in the
    RE prompt's ESCALATION OVERRIDE section.
    """
    result: Dict[str, Any] = {
        "escalation_level": 5,
        "strategy": REVERT_REQUIREMENT,
        "escalated_issues": [],
        "remove_targets": sorted(
            {c for e in (deleted or []) for c in (e.get("constructs") or [])}
        ),
        "regenerate_targets": sorted(
            {c for e in (restored or []) for c in (e.get("constructs") or [])}
        ),
        "reverted_ids": ([e.get("req_id") for e in (deleted or [])]
                         + [e.get("req_id") for e in (restored or [])]),
        "directive": "",
    }
    if not (deleted or restored):
        return result
    try:
        lines = [
            "ESCALATION LEVEL: 5",
            f"STRATEGY: {REVERT_REQUIREMENT}",
            "TRIGGER: a requirement update was implicated by verification and "
            "the user undid it. The requirements document has already been "
            "changed back; the model has not, so it currently encodes wording "
            "the document no longer carries.",
            "Bring the encoding back in line with the document. Do not "
            "re-litigate the requirement and do not weaken unrelated "
            "constructs - the failure this addresses was the requirement, not "
            "the model.",
        ]
        if deleted:
            lines.append(
                "DELETE - these requirements were removed from the document, so "
                "the constructs below encode nothing. Delete them outright "
                "(with any helper left stranded), and do not replace them:"
            )
            for item in deleted:
                names = ", ".join(item.get("constructs") or []) or "(none traced)"
                lines.append(f"  - {item.get('req_id')}: delete {names}")
        if restored:
            lines.append(
                "REGENERATE - these requirements were rolled back to earlier "
                "wording. Rebuild their constructs from the text below rather "
                "than patching what is there, per the MODELING DISCIPLINE:"
            )
            for item in restored:
                names = ", ".join(item.get("constructs") or []) or "(none traced)"
                lines.append(
                    f"  - {item.get('req_id')}: rebuild {names}\n"
                    f"      now reads: {(item.get('text') or '').strip()}"
                )
        result["directive"] = "\n".join(lines)
        return result
    except Exception:
        return result


def build_requirement_change_regeneration(
    current_iteration: int,
    changed_requirement_ids: List[str],
    regenerate_targets: List[str],
    updated_requirements: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a REGENERATE_PREDICATES escalation triggered by a REQUIREMENT CHANGE
    (not a persistence plateau).

    When a requirement is modified/superseded, the constructs that encoded its
    OLD meaning are stale and must be rebuilt from the new text - otherwise the
    stale encoding lingers and produces an internal model conflict. This emits
    the SAME directive shape and strategy as build_regeneration_escalation, so
    the RE prompt's ESCALATION OVERRIDE (delete + rebuild from the UPDATED
    requirements) handles it unchanged.

    Args:
        current_iteration: iteration the change was applied on.
        changed_requirement_ids: requirement IDs whose text just changed (e.g.
            from the requirement patch log: ["R6"]).
        regenerate_targets: construct names encoding those requirements (from the
            traceability map). If empty, returns an empty (no-op) directive.
        updated_requirements: the new requirements text (source of truth).

    Returns the same shape as the other builders, plus 'changed_requirement_ids'.
    """
    result = {
        "escalation_level": 5,
        "strategy": REGENERATE_PREDICATES,
        "escalated_issues": [],
        "changed_requirement_ids": list(changed_requirement_ids or []),
        "regenerate_targets": list(regenerate_targets or []),
        "directive": "",
    }
    if not regenerate_targets:
        return result
    try:
        lines = [
            "ESCALATION LEVEL: 5",
            f"STRATEGY: {REGENERATE_PREDICATES}",
            "TRIGGER: a requirement was changed; its previous encoding is now stale.",
            "CHANGED REQUIREMENTS: " + ", ".join(result["changed_requirement_ids"]),
            "The requirements document has been updated - it is the source of "
            "truth for the regenerated constructs.",
            "REGENERATE (delete and rebuild from the UPDATED requirements - do NOT "
            "patch; the old construct encodes the SUPERSEDED requirement text):",
        ]
        for name in result["regenerate_targets"]:
            lines.append(f"  - {name}")
        if updated_requirements:
            lines.append("UPDATED REQUIREMENTS:")
            for line in updated_requirements.strip().splitlines():
                lines.append(f"  {line}")
        result["directive"] = "\n".join(lines)
        return result
    except Exception:
        return result
