"""Test full syntax error extraction flow with code snippets."""

from pathlib import Path
from src.utils.alloy_executor import AlloyExecutor

def test_full_execution_with_syntax_error():
    """Test that syntax errors include code snippets when executing Alloy."""

    # Initialize executor
    executor = AlloyExecutor()

    # Use the model file with known syntax error
    model_file = Path("Output/AlloyModels/AlloyModel__0.als")
    output_dir = Path("Output/test_syntax_error_output")

    if not model_file.exists():
        print(f"Model file not found: {model_file}")
        return False

    print(f"Testing full execution with: {model_file}")
    print("="*80)

    # Execute Alloy (expecting syntax errors)
    results = executor.execute(model_file, output_dir)

    # Check results
    if not results.get('success'):
        print("ERROR: Execution failed")
        print(results.get('error', 'Unknown error'))
        return False

    # Extract analysis
    analysis = results.get('analysis', {})

    # Check for syntax errors
    if not analysis.get('has_syntax_errors'):
        print("WARNING: No syntax errors found (expected syntax errors)")
        return False

    print(f"✓ Found syntax errors as expected")

    # Get syntax errors
    syntax_errors = analysis.get('syntax_errors', [])
    print(f"✓ Found {len(syntax_errors)} syntax error(s)")

    # Check first error
    if syntax_errors:
        error = syntax_errors[0]
        print(f"\nFirst Error Details:")
        print(f"  Line: {error.get('line')}")
        print(f"  Column: {error.get('column')}")
        print(f"  Message: {error.get('message')}")

        # Check for code snippet
        code_snippet = error.get('code_snippet', '')
        if code_snippet:
            print(f"\n✓ Code snippet is present!")
            print("\nCode Snippet:")
            print("-" * 80)
            print(code_snippet)
            print("-" * 80)

            # Verify content
            assert "CODE CONTEXT" in code_snippet, "Should have header"
            assert f"{error.get('line')}:" in code_snippet, "Should show error line"
            assert f"ERROR at column {error.get('column')}" in code_snippet, "Should show error marker"

            print("\n✓✓✓ All checks passed! Code snippet extraction integrated successfully!")
            return True
        else:
            print("\n✗ ERROR: Code snippet is missing!")
            return False
    else:
        print("\n✗ ERROR: No syntax errors in list")
        return False

if __name__ == "__main__":
    success = test_full_execution_with_syntax_error()
    exit(0 if success else 1)
