"""
Tests for LessonProbation - lessons are stored only after their target issue
stays resolved for several consecutive iterations, and are discarded if the
issue recurs (oscillating A,B,A,B errors previously confirmed lessons at the
first B iteration even though A came right back).

Run: python test/test_lesson_probation.py   (from the repo root)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.learning_system import LessonProbation


def make_pending(iteration=10):
    return {
        'lessons': ['[LESSON] use next[t] instead of t.next for ordering'],
        'agent_name': 'Evaluator',
        'action_name': 'GenerateSyntaxRepairInstruction',
        'source_iteration': iteration,
    }


SIG_A = "syntax_error:invalid_operator:fun:leq:function_body:type_mismatch"
SIG_B = "syntax_error:missing_brace:pred:precedes:predicate_body:delimiter"


def test_confirm_after_clean_run():
    """Issue resolved at 11 and stays away through 12, 13 -> confirmed at 13."""
    p = LessonProbation(required_clean_iterations=3)
    p.add(make_pending(10), 'syntax error at line 75 in fun leq', SIG_A, resolved_at_iteration=11)

    confirmed, discarded = p.evaluate(12, None, None, syntax_ok=True)
    assert not confirmed and not discarded and len(p.items) == 1

    confirmed, discarded = p.evaluate(13, None, None, syntax_ok=True)
    assert len(confirmed) == 1 and not discarded and not p.items
    assert confirmed[0]['pending']['source_iteration'] == 10
    print("PASS: confirmed after required clean iterations")


def test_oscillation_discards():
    """A resolved at 11 (B present), A recurs at 12 -> lesson discarded, not stored."""
    p = LessonProbation(required_clean_iterations=3)
    p.add(make_pending(10), 'syntax error at line 75 in fun leq', SIG_A, resolved_at_iteration=11)

    # Iteration 12: error A is back (same normalized signature, line moved)
    confirmed, discarded = p.evaluate(
        12, 'syntax error at line 78 in fun leq', SIG_A, syntax_ok=False)
    assert not confirmed and len(discarded) == 1 and not p.items
    print("PASS: oscillating error discards the lesson")


def test_recurrence_by_issue_components():
    """Semantic recurrence detected via issue-string overlap (no signature)."""
    p = LessonProbation(required_clean_iterations=3)
    p.add(make_pending(20), 'unsat predicate: EmergencyBypassFIFOScenario', None,
          resolved_at_iteration=21)

    # Different surrounding issues but the same predicate is UNSAT again
    confirmed, discarded = p.evaluate(
        22, 'unsat predicate: EmergencyBypassFIFOScenario, R1R2', None, syntax_ok=True)
    assert len(discarded) == 1 and not confirmed
    print("PASS: semantic recurrence detected via issue components")


def test_semantic_not_advanced_by_syntax_iterations():
    """Syntax-error iterations can't show a semantic issue is gone - they
    neither advance nor break a semantic lesson's probation."""
    p = LessonProbation(required_clean_iterations=3)
    p.add(make_pending(20), 'unsat predicate: R1R2', None, resolved_at_iteration=21)

    # Two syntax-broken iterations: no progress
    p.evaluate(22, 'syntax error at line 5 in sig Delegation', SIG_B, syntax_ok=False)
    p.evaluate(23, 'syntax error at line 9 in sig Request', SIG_B, syntax_ok=False)
    assert len(p.items) == 1 and p.items[0]['clean_count'] == 1

    # Two measurable clean iterations complete the probation
    p.evaluate(24, None, None, syntax_ok=True)
    confirmed, _ = p.evaluate(25, None, None, syntax_ok=True)
    assert len(confirmed) == 1 and not p.items
    print("PASS: semantic probation only advances on measurable iterations")


def test_flush_on_convergence():
    p = LessonProbation(required_clean_iterations=3)
    p.add(make_pending(30), 'unsat predicate: R3', None, resolved_at_iteration=31)
    items = p.flush()
    assert len(items) == 1 and not p.items
    print("PASS: flush returns remaining items for convergence confirmation")


if __name__ == "__main__":
    test_confirm_after_clean_run()
    test_oscillation_discards()
    test_recurrence_by_issue_components()
    test_semantic_not_advanced_by_syntax_iterations()
    test_flush_on_convergence()
    print("\nAll lesson-probation tests passed.")
