"""Test that GenerateSemanticFeedback retrieves and uses code snippets from analyzer_results."""

import asyncio
from src.utils.runtime_context import SharedRuntimeContext
from src.actions.evaluation_actions import GenerateSemanticFeedback

async def _impl_with_syntax_errors():
    """Test that GenerateSemanticFeedback retrieves code snippets from stored analyzer_results."""

    print("Testing GenerateSemanticFeedback Code Snippet Retrieval")
    print("=" * 80)

    # Create context
    context = SharedRuntimeContext()

    # Set current iteration
    context.iteration.set(0)

    # Create mock analyzer results with syntax errors and code snippets
    mock_analyzer_results = {
        "analysis": {
            "has_syntax_errors": True,
            "syntax_errors": [
                {
                    "file": "/path/to/model.als",
                    "line": 87,
                    "column": 3,
                    "message": "Syntax error at line 87, column 3",
                    "code_snippet": """CODE CONTEXT (lines 85-89):
 85: fact RoleExclusivitySymmetry {
 86:   all r: Role | r !in r.mutuallyExclusive
 87:   all r, r': Role | (r in r'.mutuallyExclusive) iff (r' in r.mutuallyExclusive)
       ^^ ERROR at column 3
 88: }
 89: """
                }
            ]
        }
    }

    # Store analyzer results
    context.artifacts.store_analyzer_results(0, mock_analyzer_results)

    # Create interpretation with syntax errors (no CODE CONTEXT in interpretation)
    interpretation = """SYNTAX STATUS: Errors found
Location: Line 87, Column 3
Fix: Add semicolon after line 86

COUNTEREXAMPLES: N/A (syntax errors prevent verification)

SATISFYING INSTANCES: N/A (syntax errors prevent verification)"""

    # Create mock requirements and model
    requirements = "Test requirements"
    full_model = "// Full Alloy model\n" + "sig Test {}\n" * 100  # Large model

    # Create GenerateSemanticFeedback action
    action = GenerateSemanticFeedback(context, agent_name="Evaluator")

    # Mock the _aask method to avoid actual LLM call
    async def mock_aask(prompt):
        # Check if prompt contains code snippet or full model
        if "RELEVANT CODE SNIPPETS" in prompt:
            return "Feedback with snippets"
        else:
            return "Feedback with full model"

    action._aask = mock_aask

    # Run the action
    print("\nRunning GenerateSemanticFeedback...")
    result = await action.run(
        interpretation=interpretation,
        requirements_document=requirements,
        alloy_model=full_model
    )

    print(f"\nResult: {result}")

    # Verify the result
    if result == "Feedback with snippets":
        print("\n✓✓✓ SUCCESS! GenerateSemanticFeedback correctly retrieved and used code snippets")
        print("✓ Full model was replaced with focused code snippets")
        return True
    else:
        print("\n✗✗✗ FAILED! GenerateSemanticFeedback did not use code snippets")
        print("✗ Full model was used instead of snippets")
        return False

async def _impl_without_syntax_errors():
    """Test that GenerateSemanticFeedback uses full model when there are no syntax errors."""

    print("\n" + "=" * 80)
    print("Testing GenerateSemanticFeedback Without Syntax Errors")
    print("=" * 80)

    # Create context
    context = SharedRuntimeContext()
    context.iteration.set(1)

    # Create mock analyzer results without syntax errors
    mock_analyzer_results = {
        "analysis": {
            "has_syntax_errors": False,
            "syntax_errors": []
        }
    }

    # Store analyzer results
    context.artifacts.store_analyzer_results(1, mock_analyzer_results)

    # Create interpretation without syntax errors
    interpretation = """SYNTAX STATUS: OK

COUNTEREXAMPLES: None

SATISFYING INSTANCES: Found meaningful instances"""

    requirements = "Test requirements"
    full_model = "// Full Alloy model\nsig Test {}\n"

    # Create action
    action = GenerateSemanticFeedback(context, agent_name="Evaluator")

    # Mock the _aask method
    async def mock_aask(prompt):
        if "RELEVANT CODE SNIPPETS" in prompt:
            return "Feedback with snippets"
        else:
            return "Feedback with full model"

    action._aask = mock_aask

    # Run the action
    print("\nRunning GenerateSemanticFeedback...")
    result = await action.run(
        interpretation=interpretation,
        requirements_document=requirements,
        alloy_model=full_model
    )

    print(f"\nResult: {result}")

    # Verify the result
    if result == "Feedback with full model":
        print("\n✓✓✓ SUCCESS! GenerateSemanticFeedback correctly used full model")
        print("✓ No snippets extracted when no syntax errors")
        return True
    else:
        print("\n✗✗✗ FAILED! GenerateSemanticFeedback unexpectedly used snippets")
        return False

def test_generate_feedback_with_syntax_errors():
    """Sync pytest entrypoint (repo convention: asyncio.run inside a sync test)."""
    assert asyncio.run(_impl_with_syntax_errors())


def test_generate_feedback_without_syntax_errors():
    """Sync pytest entrypoint (repo convention: asyncio.run inside a sync test)."""
    assert asyncio.run(_impl_without_syntax_errors())


if __name__ == "__main__":
    result1 = asyncio.run(_impl_with_syntax_errors())
    result2 = asyncio.run(_impl_without_syntax_errors())

    print("\n" + "=" * 80)
    print("FINAL RESULTS:")
    print("=" * 80)

    if result1 and result2:
        print("✓✓✓ All tests passed!")
        print("\nGenerateSemanticFeedback now correctly:")
        print("  - Retrieves analyzer_results from artifact store")
        print("  - Extracts code snippets when syntax errors exist")
        print("  - Uses full model when no syntax errors")
        exit(0)
    else:
        print("✗✗✗ Some tests failed")
        exit(1)
