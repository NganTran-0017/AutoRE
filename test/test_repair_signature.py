"""
Tests for normalize_repair - the fix-side analogue of the error signature.

Motivating case (070726.log, iteration 12): the same repair kept being
re-prescribed in different words; fuzzy text similarity (threshold 0.85)
missed rephrased repeats. The normalized repair signature classifies the
prescribed operation into stable families anchored to the repaired block, so
"remove the : Bool return type" and "omit the return type from fun leq" get
the SAME signature and the retry loop can reject the repeat deterministically.

Run: python test/test_repair_signature.py   (from the repo root)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.repair_plateau_detector import (
    normalize_repair, build_syntax_escalation, REWRITE_BLOCK,
)
from src.utils.regression_log import RegressionLogEntry, VerificationResult, ImpactAnalysis
from src.utils.issue_pattern_tracker import IssuePatternTracker


ERR_SIG = {
    "normalized_signature": "syntax_error:invalid_operator:fun:leq:function_body:type_mismatch",
    "root_error_family": "type_mismatch",
    "affected_construct": "fun",
    "affected_symbol": "leq",
    "model_region": "function_body",
}


def fb(intent, steps):
    return f"[FIX INTENT]:\n{intent}\n\n[REPAIR INSTRUCTIONS]:\n{steps}\n\n[RATIONALE]:\nr"


def test_operation_classification():
    # The 0707 iteration-12 fix: remove the return type
    sig = normalize_repair(
        fb("Remove the explicit return type Bool from the leq function",
           "- Step 1: Remove the : Bool return type so the declaration reads fun leq[t1, t2: Time]"),
        error_signature=ERR_SIG)
    assert "remove_return_type" in sig["operation_families"], sig
    assert sig["target"] == "fun leq"
    assert sig["normalized_signature"].startswith("repair:")

    # The user-directed fix: fun -> pred + util/ordering
    sig2 = normalize_repair(
        fb("Replace the fun leq helper with a pred and use the built-in ordering",
           "- Step 1: use pred instead of fun for leq\n- Step 2: add open util/ordering[Time] as TO"),
        error_signature=ERR_SIG)
    assert "construct_conversion" in sig2["operation_families"], sig2
    assert "add_open_import" in sig2["operation_families"], sig2
    assert sig2["normalized_signature"] != sig["normalized_signature"]
    print("PASS: operation-family classification")


def test_rephrased_repeat_same_signature():
    a = normalize_repair(
        fb("Remove the explicit return type Bool from leq",
           "- Step 1: Remove the : Bool return type"),
        error_signature=ERR_SIG)
    b = normalize_repair(
        fb("Let Alloy infer the result of leq",
           "- Step 1: omit the return type from fun leq so Alloy infers PrimitiveBoolean"),
        error_signature=ERR_SIG)
    assert a["normalized_signature"] == b["normalized_signature"], (a, b)
    print("PASS: rephrased identical repair -> same signature")


def test_no_change_and_fallback():
    sig = normalize_repair(fb("Keep the model as-is", "- Step 1: no model changes"),
                           error_signature=ERR_SIG)
    assert sig["operation_families"][0] == "no_change", sig
    sig = normalize_repair(fb("Tweak something unusual", "- Step 1: do the thing"),
                           error_signature=None)
    assert sig["operation_families"] == ["other_edit"] and sig["target"] == "unknown"
    print("PASS: no_change and fallback classification")


def test_directive_lists_attempted_operations():
    """build_syntax_escalation must surface prior repair signatures for the
    matched iterations so the Evaluator sees the tried-strategy history."""
    def make_entry(iteration):
        return RegressionLogEntry(
            iteration_id=iteration,
            model_file_location=f"Output/AlloyModels/AlloyModel__{iteration}.als",
            fix_intent="applied fix",
            source_ref="test",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            error_signature=ERR_SIG,
        )

    entries = [make_entry(i) for i in (12, 13, 14, 15)]
    entries[0].repair_signature = {"normalized_signature": "repair:remove_return_type:fun leq"}
    entries[1].repair_signature = {"normalized_signature": "repair:quantifier_change:fun leq"}

    pattern = IssuePatternTracker().run(15, ERR_SIG, entries)
    escalation = build_syntax_escalation(15, pattern, ERR_SIG, entries)
    assert escalation["strategy"] == REWRITE_BLOCK
    d = escalation["directive"]
    assert "REPAIR OPERATIONS ALREADY ATTEMPTED" in d, d
    assert "repair:remove_return_type:fun leq" in d
    assert "repair:quantifier_change:fun leq" in d
    print("PASS: escalation directive lists attempted repair operations")


def test_entry_round_trip():
    entry = RegressionLogEntry(
        iteration_id=1, model_file_location="m.als", fix_intent="f", source_ref="s",
        current_result=VerificationResult(syntax="OK"), previous_result=None,
        updated_lines="", expected_impact=ImpactAnalysis(),
    )
    entry.repair_signature = normalize_repair(
        fb("Remove return type", "- Step 1: Remove the : Bool return type"),
        error_signature=ERR_SIG, strategy="FORBID_PRIOR_FIXES")
    data = entry.to_dict()
    loaded = RegressionLogEntry.from_dict(data)
    assert loaded.repair_signature == entry.repair_signature
    assert loaded.repair_signature["strategy"] == "FORBID_PRIOR_FIXES"
    data.pop("repair_signature")
    assert RegressionLogEntry.from_dict(data).repair_signature is None  # old logs
    print("PASS: repair_signature round-trip incl. old logs")


if __name__ == "__main__":
    test_operation_classification()
    test_rephrased_repeat_same_signature()
    test_no_change_and_fallback()
    test_directive_lists_attempted_operations()
    test_entry_round_trip()
    print("\nAll repair-signature tests passed.")
