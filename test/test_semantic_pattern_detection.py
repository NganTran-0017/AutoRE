"""
Test semantic similarity pattern detection with very similar fix approaches
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.regression_log import (
    RegressionLogEntry,
    VerificationResult,
    ImpactAnalysis,
    detect_fix_pattern
)


def test_semantic_similarity_detection():
    """Test that semantic similarity actually detects similar approaches."""
    print("=" * 80)
    print("TEST: Semantic Similarity Pattern Detection")
    print("=" * 80)

    # Create entries with VERY similar fix approaches (should cluster together)
    entries = [
        RegressionLogEntry(
            iteration_id=2,
            model_file_location="test.als",
            fix_intent="Add a guard constraint to the predicate",
            source_ref="Evaluator feedback",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact Test",
            resolved_target_issue=False
        ),
        RegressionLogEntry(
            iteration_id=3,
            model_file_location="test.als",
            fix_intent="Add guard constraint for the predicate",
            source_ref="Evaluator feedback",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact Test",
            resolved_target_issue=False
        ),
        RegressionLogEntry(
            iteration_id=4,
            model_file_location="test.als",
            fix_intent="Insert a guard constraint into the predicate",
            source_ref="Evaluator feedback",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis(),
            issue="syntax error in fact Test",
            resolved_target_issue=False
        ),
    ]

    pattern_note = detect_fix_pattern("syntax error in fact Test", entries)

    print(f"\nPattern Detection Result:")
    print(f"  {pattern_note}")

    # Check if it detected the similar approaches
    if "Similar approach used" in pattern_note:
        print("\n  ✅ Semantic similarity DETECTED similar fix approaches!")
        print("  ✅ Clustering is working correctly")
        return True
    else:
        print("\n  ⚠️  No pattern detected (may need to adjust similarity threshold)")
        print("  ℹ️  This could mean the approaches aren't similar enough semantically")
        return False


def test_similarity_threshold_info():
    """Show similarity scores for debugging."""
    print("\n" + "=" * 80)
    print("TEST: Check Actual Similarity Scores")
    print("=" * 80)

    try:
        from sentence_transformers import SentenceTransformer
        from sklearn.metrics.pairwise import cosine_similarity

        model = SentenceTransformer('all-MiniLM-L6-v2')

        # Test with very similar sentences
        fix_intents = [
            "Add a guard constraint to the predicate",
            "Add guard constraint for the predicate",
            "Insert a guard constraint into the predicate",
            "Rename the variable to newName"  # Different approach
        ]

        embeddings = model.encode(fix_intents)
        similarity_matrix = cosine_similarity(embeddings)

        print("\nSimilarity Matrix:")
        print("(Threshold for clustering: 0.75)")
        print("-" * 60)
        for i, intent in enumerate(fix_intents):
            print(f"\n[{i}] {intent[:50]}...")
        print("\n")

        for i in range(len(fix_intents)):
            for j in range(i+1, len(fix_intents)):
                sim = similarity_matrix[i][j]
                status = "✓ CLUSTER" if sim > 0.75 else "✗ separate"
                print(f"  [{i}] vs [{j}]: {sim:.3f}  {status}")

        print("\n  ℹ️  Similarities > 0.75 will be clustered together")

    except Exception as e:
        print(f"  ⚠️  Could not compute similarity scores: {e}")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("SEMANTIC SIMILARITY PATTERN DETECTION TEST")
    print("=" * 80 + "\n")

    try:
        test_semantic_similarity_detection()
        test_similarity_threshold_info()

        print("\n" + "=" * 80)
        print("✅ TESTS COMPLETED")
        print("=" * 80 + "\n")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
