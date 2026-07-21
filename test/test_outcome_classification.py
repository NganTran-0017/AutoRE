"""
Tests for derive_outcome_classification - the deterministic fallback that
guarantees regression-log entries never stay at outcome_classification="pending".

Motivating case: the 0706 run's regression log had every entry stuck at
"pending" because all iterations had syntax errors, and InterpretResults (the
only writer of outcome_classification) is skipped on syntax-error iterations.

Run: python test/test_outcome_classification.py   (from the repo root)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.regression_log import derive_outcome_classification


def test_initial_iteration():
    # Iteration 0 with a syntax error (exactly the 0706 log's first entry)
    c = derive_outcome_classification(
        has_syntax_errors=True, resolved_target_issue=None,
        has_previous_iteration=False, current_issue="syntax error at line 159 in pred R1R2")
    assert c.startswith("initial_verification:"), c
    assert "does not parse" in c

    # Iteration 0, clean model
    c = derive_outcome_classification(
        has_syntax_errors=False, resolved_target_issue=None,
        has_previous_iteration=False)
    assert c.startswith("initial_verification:"), c
    print("PASS: initial iteration classifications")


def test_syntax_error_iterations():
    # Same syntax error persisted after a repair attempt (0706 iterations 1+)
    c = derive_outcome_classification(
        has_syntax_errors=True, resolved_target_issue=False,
        has_previous_iteration=True, current_issue="syntax error at line 159 in pred R1R2")
    assert c.startswith("no_improvement:"), c

    # Previous issue fixed but a new syntax error introduced
    c = derive_outcome_classification(
        has_syntax_errors=True, resolved_target_issue=True,
        has_previous_iteration=True)
    assert c.startswith("unintended_regression:"), c

    # Resolution undeterminable (e.g. previous entry had no recorded issue)
    c = derive_outcome_classification(
        has_syntax_errors=True, resolved_target_issue=None,
        has_previous_iteration=True)
    assert c.startswith("syntax_error_blocked:"), c
    print("PASS: syntax-error iteration classifications")


def test_semantic_iterations():
    # Target issue absent, other issues remain - provisional until the absence
    # is confirmed over several iterations (oscillating errors come back)
    c = derive_outcome_classification(
        has_syntax_errors=False, resolved_target_issue=True,
        has_previous_iteration=True, current_issue="unsat predicate: R1R2")
    assert c.startswith("provisional_improvement:") and "unsat predicate: R1R2" in c, c

    # Target issue absent, nothing outstanding - still provisional
    c = derive_outcome_classification(
        has_syntax_errors=False, resolved_target_issue=True,
        has_previous_iteration=True, current_issue=None)
    assert c.startswith("provisional_improvement:") and "no outstanding" in c, c

    # Target issue persists
    c = derive_outcome_classification(
        has_syntax_errors=False, resolved_target_issue=False,
        has_previous_iteration=True, current_issue="unsat predicate: R1R2")
    assert c.startswith("no_improvement:"), c

    # No comparison possible but issues exist
    c = derive_outcome_classification(
        has_syntax_errors=False, resolved_target_issue=None,
        has_previous_iteration=True, current_issue="counterexample: assertX")
    assert c.startswith("unclassified:"), c

    # No comparison possible, clean
    c = derive_outcome_classification(
        has_syntax_errors=False, resolved_target_issue=None,
        has_previous_iteration=True, current_issue=None)
    assert c.startswith("expected_improvement:"), c
    print("PASS: semantic iteration classifications")


def test_never_pending():
    """Exhaustive: no input combination may yield 'pending'."""
    for syntax in (True, False):
        for resolved in (True, False, None):
            for prev in (True, False):
                for issue in (None, "unsat predicate: X"):
                    c = derive_outcome_classification(syntax, resolved, prev, issue)
                    assert c and c != "pending", (syntax, resolved, prev, issue)
    print("PASS: no input combination yields 'pending'")


if __name__ == "__main__":
    test_initial_iteration()
    test_syntax_error_iterations()
    test_semantic_iterations()
    test_never_pending()
    print("\nAll outcome-classification tests passed.")
