"""Test code snippet extraction for syntax errors."""

from pathlib import Path
from src.utils.alloy_executor import AlloyExecutor

def test_code_snippet_extraction():
    """Test that code snippets are extracted and formatted correctly."""

    # Initialize executor
    executor = AlloyExecutor()

    # Test the _extract_code_snippet method directly
    test_file = Path("Output/AlloyModels/AlloyModel__0.als")

    if not test_file.exists():
        print(f"Test file not found: {test_file}")
        print("Looking for alternative test files...")
        test_file = Path("Output/AlloyModels/050126_12PM/AlloyModel__0.als")

    if test_file.exists():
        print(f"Testing with file: {test_file}")
        print("\n" + "="*80)

        # Test extracting snippet at line 40, column 3 (the known error location)
        snippet = executor._extract_code_snippet(str(test_file), 40, 3)

        print("Extracted Code Snippet:")
        print("-" * 80)
        print(snippet)
        print("-" * 80)

        # Verify the snippet contains expected elements
        assert "CODE CONTEXT" in snippet, "Should have header"
        assert "40:" in snippet, "Should show line 40"
        assert "ERROR at column 3" in snippet, "Should show error marker"

        print("\n✓ Code snippet extraction working correctly!")

    else:
        print(f"ERROR: Could not find test file: {test_file}")
        return False

    return True

if __name__ == "__main__":
    test_code_snippet_extraction()
