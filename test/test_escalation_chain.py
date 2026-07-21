"""
Scenario tests for the post-analysis escalation chain:
SemanticIssueTracker (step 3) + RepairPlateauDetector escalation builders (step 4),
plus prompt wiring (new placeholders/sections render without errors).

Scenarios are modeled on the observed failure runs:
 - 0618: EmergencyBypassFIFOScenario UNSAT across iterations 18-21 with model-only
   fixes and no requirement escalation.
 - 0703/0706: same syntax error repeating / alternating across iterations.

Run: python test/test_escalation_chain.py   (from the repo root)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.regression_log import RegressionLogEntry, VerificationResult, ImpactAnalysis
from src.utils.semantic_issue_tracker import SemanticIssueTracker
from src.utils.issue_pattern_tracker import IssuePatternTracker
from src.utils.repair_plateau_detector import (
    build_syntax_escalation,
    build_semantic_escalation,
    REWRITE_BLOCK,
    REGENERATE_BLOCK,
    BREAK_OSCILLATION,
    REQUIREMENTS_DIAGNOSIS,
)


def make_entry(
    iteration,
    syntax="OK",
    unsat=None,
    cex=None,
    error_signature=None,
    evaluator_feedback=None,
    fix_intent="",
):
    return RegressionLogEntry(
        iteration_id=iteration,
        model_file_location=f"Output/AlloyModels/AlloyModel__{iteration}.als",
        fix_intent=fix_intent,
        source_ref="test",
        current_result=VerificationResult(
            syntax=syntax,
            unsatisfied_predicates=unsat or [],
            counterexamples=cex or [],
        ),
        previous_result=None,
        updated_lines="",
        expected_impact=ImpactAnalysis(),
        error_signature=error_signature,
        evaluator_feedback=evaluator_feedback,
    )


def sig(name):
    return {
        "normalized_signature": name,
        "root_error_family": name.split(":")[-1],
        "affected_construct": "fun",
        "affected_symbol": "leq",
        "model_region": "function_body",
    }


def test_semantic_persistence_0618():
    """0618 shape: syntax error at 17, then UNSAT pred + counterexample persist 18-21."""
    entries = [
        make_entry(17, syntax="Error"),
        make_entry(18, unsat=["EmergencyBypassFIFOScenario"], cex=["assertRequestProcessorClearance"],
                   fix_intent="Refactor EmergencyBypassFIFOScenario to require simultaneous processing"),
        make_entry(19, unsat=["EmergencyBypassFIFOScenario"], cex=["assertRequestProcessorClearance"],
                   fix_intent="Update mutex role assignment during Emergency",
                   evaluator_feedback="[FIX INTENT]:\nRefactor the bypass predicate scoping\n[REPAIR INSTRUCTIONS]: ..."),
        make_entry(20, unsat=["EmergencyBypassFIFOScenario"], cex=["assertRequestProcessorClearance"],
                   fix_intent="Add RequestProcessorClearance fact"),
        make_entry(21, unsat=["EmergencyBypassFIFOScenario"], cex=["assertRequestProcessorClearance"]),
    ]
    current = entries[-1]

    tracker = SemanticIssueTracker()
    persistence = tracker.run(21, current.current_result, entries)

    names = {i["name"]: i for i in persistence["issues"]}
    assert "EmergencyBypassFIFOScenario" in names, "unsat predicate must be tracked"
    assert "assertRequestProcessorClearance" in names, "counterexample must be tracked"

    ebs = names["EmergencyBypassFIFOScenario"]
    # measurable prior iterations 18,19,20 + current 21 -> consecutive 4;
    # iteration 17 is syntax-broken and must be skipped, not break the run
    assert ebs["consecutive"] == 4, f"expected 4 consecutive, got {ebs['consecutive']}"
    assert ebs["total"] == 4
    assert ebs["first_seen"] == 18
    assert persistence["escalation_required"] is True
    assert "EmergencyBypassFIFOScenario" in persistence["escalated_issues"]

    escalation = build_semantic_escalation(21, persistence, entries)
    assert escalation["escalation_level"] == 3
    assert escalation["strategy"] == REQUIREMENTS_DIAGNOSIS
    directive = escalation["directive"]
    assert "EmergencyBypassFIFOScenario" in directive
    assert "unsatisfiable predicate" in directive
    assert "Refactor the bypass predicate scoping" in directive  # evaluator FIX INTENT
    assert "Update mutex role assignment during Emergency" in directive  # RE applied fix
    print("PASS: semantic persistence + escalation (0618 scenario)")


def test_semantic_no_early_escalation():
    """A fresh issue (1-2 occurrences) must NOT escalate."""
    entries = [
        make_entry(5, unsat=["R1R2"]),
        make_entry(6, unsat=["R1R2"]),
    ]
    tracker = SemanticIssueTracker()
    persistence = tracker.run(6, entries[-1].current_result, entries)
    assert persistence["escalation_required"] is False
    assert persistence["issues"][0]["consecutive"] == 2
    escalation = build_semantic_escalation(6, persistence, entries)
    assert escalation["escalation_level"] == 0
    assert escalation["directive"] == ""
    print("PASS: no premature semantic escalation")


def test_syntax_plateau_rewrite_block():
    """Same syntax error 4 iterations in a row -> repair_plateau -> REWRITE_BLOCK."""
    a = sig("syntax_error:invalid_operator:fun:leq:function_body:type_mismatch")
    entries = [
        make_entry(i, syntax="Error", error_signature=a,
                   evaluator_feedback=f"[FIX INTENT]: patch attempt {i}\n...",
                   fix_intent=f"applied patch {i}")
        for i in (12, 13, 14)
    ]
    entries.append(make_entry(15, syntax="Error", error_signature=a))

    pattern = IssuePatternTracker().run(15, a, entries)
    assert pattern["pattern_type"] == "repair_plateau", pattern

    escalation = build_syntax_escalation(15, pattern, a, entries)
    assert escalation["escalation_level"] == 3
    assert escalation["strategy"] == REWRITE_BLOCK
    assert escalation["rewrite_block"] is True
    directive = escalation["directive"]
    assert "AFFECTED BLOCK: fun leq" in directive
    assert "patch attempt 12" in directive
    assert "applied patch 14" in directive  # RE fix applied in iteration 14 for iteration 13's error
    print("PASS: syntax plateau -> REWRITE_BLOCK escalation")


def test_syntax_alternating_loop():
    """A,B,A,B,A -> alternating_error_loop -> BREAK_OSCILLATION with partner named."""
    a = sig("errA:fun:leq")
    b = sig("errB:pred:precedes")
    entries = [
        make_entry(8, syntax="Error", error_signature=a),
        make_entry(9, syntax="Error", error_signature=b),
        make_entry(10, syntax="Error", error_signature=a),
        make_entry(11, syntax="Error", error_signature=b),
        make_entry(12, syntax="Error", error_signature=a),
    ]
    pattern = IssuePatternTracker().run(12, a, entries)
    assert pattern["pattern_type"] == "alternating_error_loop", pattern

    escalation = build_syntax_escalation(12, pattern, a, entries)
    assert escalation["escalation_level"] == 2
    assert escalation["strategy"] == BREAK_OSCILLATION
    assert "OSCILLATING WITH ERROR: errB:pred:precedes" in escalation["directive"]
    print("PASS: alternating loop -> BREAK_OSCILLATION escalation")


def test_escalation_ladder_climbs():
    """A plateau that already survived REWRITE_BLOCK escalates to
    REGENERATE_BLOCK (rebuild from requirements), and one that survived
    REGENERATE_BLOCK escalates to REQUIREMENTS_DIAGNOSIS (final rung)."""
    a = sig("syntax_error:invalid_operator:fun:leq:function_body:type_mismatch")
    entries = [make_entry(i, syntax="Error", error_signature=a) for i in (10, 11, 12, 13)]
    # Iteration 12 already ran under REWRITE_BLOCK and the error persisted
    entries[2].repair_escalation = {"escalation_level": 3, "strategy": "REWRITE_BLOCK",
                                    "rewrite_block": True, "directive": "d"}

    pattern = IssuePatternTracker().run(13, a, entries)
    assert pattern["pattern_type"] == "repair_plateau", pattern
    esc = build_syntax_escalation(13, pattern, a, entries)
    assert esc["escalation_level"] == 4 and esc["strategy"] == REGENERATE_BLOCK, esc
    assert esc["rewrite_block"] is True
    assert "PRIOR REWRITE ATTEMPT FAILED" in esc["directive"]
    assert "iteration(s) 12" in esc["directive"]

    # Iteration 13 then ran under REGENERATE_BLOCK and the error STILL persists
    entries[3].repair_escalation = {"escalation_level": 4, "strategy": "REGENERATE_BLOCK",
                                    "rewrite_block": True, "directive": "d"}
    entries.append(make_entry(14, syntax="Error", error_signature=a))

    pattern = IssuePatternTracker().run(14, a, entries)
    assert pattern["pattern_type"] == "repair_plateau", pattern
    esc = build_syntax_escalation(14, pattern, a, entries)
    assert esc["escalation_level"] == 5 and esc["strategy"] == REQUIREMENTS_DIAGNOSIS, esc
    assert "PRIOR REGENERATION FAILED" in esc["directive"]

    # A plain plateau with no prior high-rung strategy stays at REWRITE_BLOCK
    plain = [make_entry(i, syntax="Error", error_signature=a) for i in (20, 21, 22, 23)]
    pattern = IssuePatternTracker().run(23, a, plain)
    esc = build_syntax_escalation(23, pattern, a, plain)
    assert esc["strategy"] == REWRITE_BLOCK and esc["escalation_level"] == 3
    print("PASS: escalation ladder REWRITE_BLOCK -> REGENERATE_BLOCK -> REQUIREMENTS_DIAGNOSIS")


def test_entry_round_trip():
    """New entry fields must serialize and load back (incl. old logs without them)."""
    entry = make_entry(3, unsat=["X"])
    entry.semantic_issue_persistence = {"issues": [], "escalation_required": False, "escalated_issues": []}
    entry.repair_escalation = {"escalation_level": 3, "strategy": "REWRITE_BLOCK",
                               "rewrite_block": True, "directive": "d"}
    data = entry.to_dict()
    loaded = RegressionLogEntry.from_dict(data)
    assert loaded.semantic_issue_persistence == entry.semantic_issue_persistence
    assert loaded.repair_escalation == entry.repair_escalation

    # Back-compat: old logs without the new keys
    for key in ("semantic_issue_persistence", "repair_escalation"):
        data.pop(key)
    loaded_old = RegressionLogEntry.from_dict(data)
    assert loaded_old.semantic_issue_persistence is None
    assert loaded_old.repair_escalation is None
    print("PASS: regression-log entry round-trip with new fields")


def test_prompt_wiring():
    """New placeholders/sections must render without missing-variable errors."""
    from src.utils.prompt_manager import PromptManager

    pm = PromptManager()

    # GenerateSyntaxRepairInstruction + RefineSyntaxRepairInstruction now require pattern_status
    for action in ("GenerateSyntaxRepairInstruction", "RefineSyntaxRepairInstruction"):
        rendered = pm.render_prompt(
            agent_name="Evaluator",
            action_name=action,
            code_snippet="fun leq { ... }",
            error_message="line 75: type mismatch",
            alloy_model="sig A {}",
            lessons="No previous lessons.",
            previous_failed_attempts="None - this is the first attempt.",
            failed_fix_history="None",
            user_guidance="try a helper function",
            pattern_status="ESCALATION LEVEL: 3\nSTRATEGY: REWRITE_BLOCK",
        )
        assert "ESCALATION LEVEL: 3" in rendered
        assert "{{pattern_status}}" not in rendered
        if action == "RefineSyntaxRepairInstruction":
            # User guidance must be binding, with a per-element compliance map
            assert "BINDING RULES FOR USER GUIDANCE" in rendered
            assert "[USER GUIDANCE COMPLIANCE]" in rendered
            assert "FORBIDDEN when referring to the user's approach" in rendered
        if action == "GenerateSyntaxRepairInstruction":
            # Full escalation ladder rules must be present
            assert "- REGENERATE_BLOCK:" in rendered
            assert "- REQUIREMENTS_DIAGNOSIS:" in rendered
            assert "=== REQUIREMENT UPDATES ===" in rendered

    # PersistentIssueEscalation section exists and carries the placeholder
    section = pm.get_section("Evaluator", "PersistentIssueEscalation")
    assert "{{persistence_status}}" in section
    assert "escalate to requirement clarification" in section
    filled = section.replace("{{persistence_status}}", "ISSUE X persisted")
    assert "ISSUE X persisted" in filled

    # RE UpdateAlloyModel base section carries escalation_directive
    base = pm.get_section("RE", "UpdateAlloyModel_Base")
    assert "{{escalation_directive}}" in base
    mode1 = pm.get_section("RE", "UpdateAlloyModel_Mode1_SyntaxRepair")
    assert "REWRITE_BLOCK" in mode1
    # User-directed fixes take precedence over the minimal-change constraint
    assert "USER GUIDANCE COMPLIANCE" in mode1
    assert "precedence over the minimal-change constraint" in mode1
    # Ladder rungs must be actionable on the RE side too
    assert "REGENERATE_BLOCK" in mode1 and "LATEST REQUIREMENTS" in mode1
    assert "REQUIREMENTS_DIAGNOSIS" in mode1 and "INTERIM repair" in mode1
    mode2 = pm.get_section("RE", "UpdateAlloyModel_Mode2_SemanticRepair")
    assert "Cross-Iteration Escalation Status" in mode2
    print("PASS: prompt wiring (placeholders and sections render)")


if __name__ == "__main__":
    test_semantic_persistence_0618()
    test_semantic_no_early_escalation()
    test_syntax_plateau_rewrite_block()
    test_syntax_alternating_loop()
    test_escalation_ladder_climbs()
    test_entry_round_trip()
    test_prompt_wiring()
    print("\nAll escalation-chain tests passed.")
