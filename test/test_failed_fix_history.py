"""
Test Failed Fix History and Pattern Detection
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.regression_log import (
    RegressionLogEntry,
    VerificationResult,
    ImpactAnalysis,
    detect_fix_pattern,
    get_same_issue_failed_fixes,
    format_failed_fix_history
)


def test_pattern_detection():
    """Test semantic similarity pattern detection."""
    print("=" * 80)
    print("TEST 1: Pattern Detection with Semantic Similarity")
    print("=" * 80)

    # Create mock regression log entries with similar fix approaches
    entries = [
        RegressionLogEntry(
            iteration_id=2,
            model_file_location="Output/AlloyModels/AlloyModel__2.als",
            fix_intent="Add guard constraint to prevent null values in the fact ExistingSystem",
            source_ref="Evaluator feedback: syntax error on line 87",
            current_result=VerificationResult(syntax="Error"),
            previous_result=VerificationResult(syntax="Error"),
            updated_lines="diff...",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact ExistingSystem",
            resolved_target_issue=False
        ),
        RegressionLogEntry(
            iteration_id=4,
            model_file_location="Output/AlloyModels/AlloyModel__4.als",
            fix_intent="Add conditional check to ensure all values are properly defined",
            source_ref="Evaluator feedback: same error at line 87",
            current_result=VerificationResult(syntax="Error"),
            previous_result=VerificationResult(syntax="Error"),
            updated_lines="diff...",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact ExistingSystem",
            resolved_target_issue=False
        ),
        RegressionLogEntry(
            iteration_id=5,
            model_file_location="Output/AlloyModels/AlloyModel__5.als",
            fix_intent="Insert guard to handle edge case for empty sets",
            source_ref="Evaluator feedback: error persists at line 87",
            current_result=VerificationResult(syntax="Error"),
            previous_result=VerificationResult(syntax="Error"),
            updated_lines="diff...",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact ExistingSystem",
            resolved_target_issue=False
        ),
        RegressionLogEntry(
            iteration_id=7,
            model_file_location="Output/AlloyModels/AlloyModel__7.als",
            fix_intent="Rename the fact to ExistingSystemConstraints",
            source_ref="Evaluator feedback: try different approach",
            current_result=VerificationResult(syntax="Error"),
            previous_result=VerificationResult(syntax="Error"),
            updated_lines="diff...",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact ExistingSystem",
            resolved_target_issue=False
        ),
        RegressionLogEntry(
            iteration_id=9,
            model_file_location="Output/AlloyModels/AlloyModel__9.als",
            fix_intent="Reorder constraints in the fact body to fix precedence",
            source_ref="Evaluator feedback: previous fix didn't work",
            current_result=VerificationResult(syntax="Error"),
            previous_result=VerificationResult(syntax="Error"),
            updated_lines="diff...",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact ExistingSystem",
            resolved_target_issue=False
        )
    ]

    current_issue = "syntax error in fact ExistingSystem"

    # Test detect_fix_pattern
    pattern_note = detect_fix_pattern(current_issue, entries)
    print("\nPattern Detection Result:")
    print(f"  {pattern_note}")

    # Verify it detected the pattern
    assert "total fix attempts" in pattern_note.lower(), "Should mention total attempts"
    print("  ✓ Pattern detection working correctly")

    return entries, current_issue


def test_same_issue_failed_fixes():
    """Test extraction of same-issue failed fixes."""
    print("\n" + "=" * 80)
    print("TEST 2: Extract Same-Issue Failed Fixes")
    print("=" * 80)

    entries = [
        # Same issue - should be included
        RegressionLogEntry(
            iteration_id=2,
            model_file_location="test.als",
            fix_intent="Fix 1",
            source_ref="Source 1",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact ExistingSystem",
            resolved_target_issue=False
        ),
        # Different block - should NOT be included
        RegressionLogEntry(
            iteration_id=3,
            model_file_location="test.als",
            fix_intent="Fix 2",
            source_ref="Source 2",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in pred R1",
            resolved_target_issue=False
        ),
        # Same issue - should be included
        RegressionLogEntry(
            iteration_id=4,
            model_file_location="test.als",
            fix_intent="Fix 3",
            source_ref="Source 3",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact ExistingSystem",
            resolved_target_issue=False
        ),
        # Same block but resolved - should NOT be included
        RegressionLogEntry(
            iteration_id=5,
            model_file_location="test.als",
            fix_intent="Fix 4",
            source_ref="Source 4",
            current_result=VerificationResult(syntax="OK"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact ExistingSystem",
            resolved_target_issue=True  # Resolved!
        ),
    ]

    current_issue = "syntax error in fact ExistingSystem"
    failed_fixes = get_same_issue_failed_fixes(current_issue, entries)

    print(f"\nCurrent Issue: {current_issue}")
    print(f"Total Entries: {len(entries)}")
    print(f"Matching Failed Fixes Found: {len(failed_fixes)}")
    print("\nMatching Iterations:")
    for entry in failed_fixes:
        print(f"  - Iteration {entry.iteration_id}: {entry.issue}")

    # Verify correct filtering
    assert len(failed_fixes) == 2, f"Should find 2 matching failed fixes, found {len(failed_fixes)}"
    assert all(e.iteration_id in [2, 4] for e in failed_fixes), "Should only include iterations 2 and 4"
    print("\n  ✓ Same-issue filtering working correctly")


def test_format_failed_fix_history(entries, current_issue):
    """Test formatting of failed fix history for prompt."""
    print("\n" + "=" * 80)
    print("TEST 3: Format Failed Fix History for Prompt")
    print("=" * 80)

    formatted = format_failed_fix_history(current_issue, entries)

    print("\nFormatted Output:")
    print("-" * 80)
    print(formatted)
    print("-" * 80)

    # Verify key elements
    assert "Previous failed attempts" in formatted, "Should mention previous attempts"
    assert current_issue in formatted, "Should include the issue description"
    assert "Fix Intent:" in formatted, "Should include fix intents"
    assert "Source Ref:" in formatted, "Should include source references"
    assert formatted.count("Issue:") == 1, "Issue should appear only once"
    assert formatted.count("Attempt") == 5, "Should show all 5 attempts"

    print("\n  ✓ Formatting working correctly")
    print("  ✓ Issue appears only once")
    print("  ✓ All attempts listed")


def test_unsat_predicate_matching():
    """Test matching for unsat predicates."""
    print("\n" + "=" * 80)
    print("TEST 4: Same-Issue Matching for Unsat Predicates")
    print("=" * 80)

    entries = [
        RegressionLogEntry(
            iteration_id=2,
            model_file_location="test.als",
            fix_intent="Fix unsat R1R2",
            source_ref="Source",
            current_result=VerificationResult(syntax="OK", unsatisfied_predicates=["R1R2"]),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="unsat predicate: R1R2",
            resolved_target_issue=False
        ),
        RegressionLogEntry(
            iteration_id=3,
            model_file_location="test.als",
            fix_intent="Fix unsat R1R2R3",
            source_ref="Source",
            current_result=VerificationResult(syntax="OK", unsatisfied_predicates=["R1R2R3"]),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="unsat predicate: R1R2R3",
            resolved_target_issue=False
        ),
        RegressionLogEntry(
            iteration_id=4,
            model_file_location="test.als",
            fix_intent="Another try at R1R2",
            source_ref="Source",
            current_result=VerificationResult(syntax="OK", unsatisfied_predicates=["R1R2"]),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="unsat predicate: R1R2",
            resolved_target_issue=False
        ),
    ]

    current_issue = "unsat predicate: R1R2"
    failed_fixes = get_same_issue_failed_fixes(current_issue, entries)

    print(f"\nCurrent Issue: {current_issue}")
    print(f"Matching Failed Fixes Found: {len(failed_fixes)}")
    for entry in failed_fixes:
        print(f"  - Iteration {entry.iteration_id}: {entry.issue}")

    assert len(failed_fixes) == 2, f"Should find 2 matching (R1R2), found {len(failed_fixes)}"
    assert all(e.iteration_id in [2, 4] for e in failed_fixes), "Should match iterations 2 and 4 (both R1R2)"
    print("\n  ✓ Unsat predicate matching working correctly")


def test_first_attempt():
    """Test behavior with no previous failed fixes."""
    print("\n" + "=" * 80)
    print("TEST 5: First Attempt (No History)")
    print("=" * 80)

    entries = []
    current_issue = "syntax error in fact NewFact"

    pattern_note = detect_fix_pattern(current_issue, entries)
    formatted = format_failed_fix_history(current_issue, entries)

    print(f"\nPattern Note: {pattern_note}")
    print(f"Formatted History:\n{formatted}")

    assert pattern_note == "First attempt at fixing this issue", "Should indicate first attempt"
    assert "first attempt" in formatted.lower(), "Should mention first attempt in formatted output"
    print("\n  ✓ First attempt handling working correctly")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("TESTING FAILED FIX HISTORY AND PATTERN DETECTION")
    print("=" * 80 + "\n")

    try:
        # Run tests
        entries, current_issue = test_pattern_detection()
        test_same_issue_failed_fixes()
        test_format_failed_fix_history(entries, current_issue)
        test_unsat_predicate_matching()
        test_first_attempt()

        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED!")
        print("=" * 80 + "\n")

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 80 + "\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
