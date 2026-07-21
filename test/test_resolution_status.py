"""
Tests for provisional resolution tracking (update_resolution_statuses):
a temporarily-absent issue must not be permanently recorded as resolved -
it is marked 'temporarily_absent', confirmed only after several observable
iterations, and REVERTED (resolved_target_issue flipped back to False) if it
recurs, as in oscillating A,B,A,B error loops.

Run: python test/test_resolution_status.py   (from the repo root)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.regression_log import (
    RegressionLogEntry, VerificationResult, ImpactAnalysis,
    update_resolution_statuses, issues_match, check_issue_resolved,
)

SIG_A = "syntax_error:invalid_operator:fun:leq:function_body:type_mismatch"
SIG_B = "syntax_error:missing_brace:pred:precedes:predicate_body:delimiter"
ISSUE_A = "syntax error at line 75 in fun leq"
ISSUE_B = "syntax error at line 120 in pred precedes"


def make_entry(iteration, syntax="OK", issue=None, signature=None,
               resolved=None, resolution_status=None, outcome="pending"):
    return RegressionLogEntry(
        iteration_id=iteration,
        model_file_location=f"Output/AlloyModels/AlloyModel__{iteration}.als",
        fix_intent="test fix",
        source_ref="test",
        current_result=VerificationResult(syntax=syntax),
        previous_result=None,
        updated_lines="",
        expected_impact=ImpactAnalysis(),
        issue=issue,
        error_signature={"normalized_signature": signature} if signature else None,
        resolved_target_issue=resolved,
        resolution_status=resolution_status,
        outcome_classification=outcome,
    )


def absent(target_issue, target_signature):
    return {'status': 'temporarily_absent',
            'target_issue': target_issue, 'target_signature': target_signature}


def test_oscillation_reverts_resolution():
    """A at 10, absent at 11 (marked temporarily_absent), A back at 12
    -> the iteration-11 'resolution' is reverted, not left as solved."""
    entries = [
        make_entry(10, syntax="Error", issue=ISSUE_A, signature=SIG_A, resolved=False),
        make_entry(11, syntax="Error", issue=ISSUE_B, signature=SIG_B, resolved=True,
                   resolution_status=absent(ISSUE_A, SIG_A),
                   outcome="provisional_improvement: target issue absent (confirmation pending)"),
        make_entry(12, syntax="Error", issue=ISSUE_A, signature=SIG_A, resolved=False),
    ]
    result = update_resolution_statuses(entries, current_iteration=12)
    e11 = entries[1]
    assert result['reverted'] == [11] and not result['confirmed']
    assert e11.resolution_status['status'] == 'resolution_reverted'
    assert e11.resolution_status['recurred_at'] == 12
    assert e11.resolved_target_issue is False, "must no longer be marked solved"
    assert e11.outcome_classification.startswith("no_improvement:")
    print("PASS: oscillating error reverts the provisional resolution")


def test_confirmed_after_clean_iterations():
    """Absent at 11 and stays away through 13 -> confirmed at 13 (3 clean)."""
    entries = [
        make_entry(10, syntax="Error", issue=ISSUE_A, signature=SIG_A, resolved=False),
        make_entry(11, resolved=True, resolution_status=absent(ISSUE_A, SIG_A),
                   outcome="provisional_improvement: target issue absent (confirmation pending)"),
        make_entry(12),
        make_entry(13),
    ]
    # Not yet at iteration 12 (only 2 clean iterations: 11, 12)
    result = update_resolution_statuses(entries[:3], current_iteration=12)
    assert not result['confirmed'] and not result['reverted']
    assert entries[1].resolution_status['status'] == 'temporarily_absent'

    result = update_resolution_statuses(entries, current_iteration=13)
    e11 = entries[1]
    assert result['confirmed'] == [11]
    assert e11.resolution_status['status'] == 'resolved_confirmed'
    assert e11.resolved_target_issue is True
    assert e11.outcome_classification.startswith("expected_improvement:"), \
        "provisional classification must be upgraded on confirmation"
    print("PASS: resolution confirmed after required clean iterations")


def test_semantic_target_needs_observable_iterations():
    """A semantic (unsat) resolution can't be confirmed by syntax-broken
    iterations - they neither advance nor break the confirmation count."""
    target = "unsat predicate: EmergencyBypassFIFOScenario"
    entries = [
        make_entry(20, issue=target, resolved=False),
        make_entry(21, resolved=True, resolution_status=absent(target, None)),
        make_entry(22, syntax="Error", issue=ISSUE_B, signature=SIG_B),
        make_entry(23, syntax="Error", issue=ISSUE_B, signature=SIG_B),
    ]
    result = update_resolution_statuses(entries, current_iteration=23)
    assert not result['confirmed'] and not result['reverted']
    assert entries[1].resolution_status['status'] == 'temporarily_absent'

    # Two more measurable clean iterations complete confirmation (21, 24, 25)
    entries.append(make_entry(24))
    entries.append(make_entry(25))
    result = update_resolution_statuses(entries, current_iteration=25)
    assert result['confirmed'] == [21]
    print("PASS: semantic resolution only confirmed on measurable iterations")


def test_semantic_recurrence_reverts():
    """The same predicate going UNSAT again reverts the provisional resolution."""
    target = "unsat predicate: R1R2"
    entries = [
        make_entry(30, issue=target, resolved=False),
        make_entry(31, resolved=True, resolution_status=absent(target, None)),
        make_entry(32, issue="unsat predicate: R1R2, R3; counterexample: assertX"),
    ]
    result = update_resolution_statuses(entries, current_iteration=32)
    assert result['reverted'] == [31]
    assert entries[1].resolved_target_issue is False
    print("PASS: semantic recurrence reverts the provisional resolution")


def test_issues_match_helper():
    assert issues_match(ISSUE_A, SIG_A, "syntax error at line 90 in fun leq", SIG_A)
    assert issues_match(ISSUE_A, None, "syntax error at line 90 in fun leq", None)  # same block
    assert not issues_match(ISSUE_A, SIG_A, ISSUE_B, SIG_B)
    # Regression guard: SAME block but DIFFERENT normalized signatures must NOT
    # match. A predicate under repair throws a sequence of distinct errors
    # (arity -> delimiter -> ...) in the same block; block-overlap alone used to
    # wrongly treat each as a recurrence. With both signatures known, signature
    # equality is authoritative.
    assert not issues_match(
        "syntax error at line 169 in fun leq", SIG_A,
        "syntax error at line 170 in fun leq", SIG_B,
    )
    assert issues_match("unsat predicate: P1", None, "unsat predicate: P1, P2", None)
    assert not issues_match("unsat predicate: P1", None, "unsat predicate: P2", None)
    print("PASS: issues_match helper")


# Signatures for the 18->19->20 scenario from the RBAC run: distinct errors that
# all live in the same block `pred R1R2` (arity, then a delimiter error twice).
SIG_ARITY = "type_error:arity_or_join_error:pred:R1R2:predicate_body:relation_arity_or_join_error"
SIG_DELIM = "syntax_error:unexpected_token:pred:R1R2:predicate_body:delimiter_or_block_structure_error"
ISSUE_18 = "syntax error at line 169 in pred R1R2"
ISSUE_19 = "syntax error at line 170 in pred R1R2"
ISSUE_20 = "syntax error at line 171 in pred R1R2"


def test_distinct_errors_same_block_not_reverted():
    """Iteration 19 fixes 18's arity error (a different delimiter error appears).
    18's arity signature never recurs, so 19's resolution of 18 must NOT be
    reverted just because both errors are in `pred R1R2`."""
    entries = [
        make_entry(18, syntax="Error", issue=ISSUE_18, signature=SIG_ARITY, resolved=False),
        make_entry(19, syntax="Error", issue=ISSUE_19, signature=SIG_DELIM, resolved=True,
                   resolution_status=absent(ISSUE_18, SIG_ARITY),
                   outcome="provisional_improvement: target issue absent (confirmation pending)"),
        make_entry(20, syntax="Error", issue=ISSUE_20, signature=SIG_DELIM, resolved=False),
    ]
    result = update_resolution_statuses(entries, current_iteration=20)
    assert 19 not in result['reverted'], "arity fix must not be reverted by a new delimiter error"
    assert entries[1].resolution_status['status'] != 'resolution_reverted'
    assert entries[1].resolved_target_issue is True
    print("PASS: distinct errors in the same block do not revert the resolution")


def test_check_issue_resolved_signature_short_circuit():
    """check_issue_resolved prefers the normalized signature: a different
    signature (same block, adjacent line) => resolved; same signature => not."""
    def analysis(line):
        return {'syntax_errors': [{'line': line, 'context': ''}]}

    prev = make_entry(18, syntax="Error", issue=ISSUE_18, signature=SIG_ARITY)
    # Different signature -> the arity target was resolved (a new error appeared).
    curr_diff = make_entry(19, syntax="Error", issue=ISSUE_19, signature=SIG_DELIM)
    assert check_issue_resolved(analysis(170), analysis(169), curr_diff, prev) is True
    # Same signature -> the same error persists.
    curr_same = make_entry(19, syntax="Error", issue=ISSUE_19, signature=SIG_ARITY)
    assert check_issue_resolved(analysis(170), analysis(169), curr_same, prev) is False
    print("PASS: check_issue_resolved uses normalized signature for syntax errors")


if __name__ == "__main__":
    test_oscillation_reverts_resolution()
    test_confirmed_after_clean_iterations()
    test_semantic_target_needs_observable_iterations()
    test_semantic_recurrence_reverts()
    test_issues_match_helper()
    test_distinct_errors_same_block_not_reverted()
    test_check_issue_resolved_signature_short_circuit()
    print("\nAll resolution-status tests passed.")
