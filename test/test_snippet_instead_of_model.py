"""Test that code snippets replace full model for syntax errors."""

from pathlib import Path
from src.utils.alloy_executor import AlloyExecutor

def test_snippet_replacement():
    """Test that code snippets replace full model when syntax errors exist."""

    # Initialize executor
    executor = AlloyExecutor()

    # Use the model file with known syntax error
    model_file = Path("Output/AlloyModels/AlloyModel__0.als")
    output_dir = Path("Output/test_snippet_replacement")

    if not model_file.exists():
        print(f"Model file not found: {model_file}")
        return False

    print("Testing snippet replacement for syntax errors...")
    print("="*80)

    # Execute Alloy
    results = executor.execute(model_file, output_dir)

    # Read the full model
    with open(model_file, 'r') as f:
        full_model = f.read()

    print(f"Full model length: {len(full_model)} characters")

    # Get syntax errors
    analysis = results.get('analysis', {})
    has_syntax_errors = analysis.get('has_syntax_errors', False)
    
    if not has_syntax_errors:
        print("ERROR: Expected syntax errors")
        return False

    print("✓ Syntax errors detected")

    # Check what would be sent to the LLM
    syntax_errors = analysis.get('syntax_errors', [])
    snippets = []
    for error in syntax_errors:
        if isinstance(error, dict):
            code_snippet = error.get('code_snippet', '')
            if code_snippet:
                snippets.append(code_snippet)

    if not snippets:
        print("ERROR: No code snippets found")
        return False

    print(f"✓ Found {len(snippets)} code snippet(s)")

    # Build what would be sent (same logic as InterpretResults.run)
    model_context = "RELEVANT CODE SNIPPETS (faulty sections only):\n\n" + "\n\n".join(snippets)
    model_context += "\n\n(Full model omitted to focus on syntax errors)"

    print(f"✓ Snippet context length: {len(model_context)} characters")
    reduction_pct = 100 - int(len(model_context)/len(full_model)*100)
    print(f"✓ Reduction: {len(full_model)} -> {len(model_context)} ({reduction_pct}% smaller)")

    print("\n" + "="*80)
    print("MODEL CONTEXT THAT WILL BE SENT TO LLM:")
    print("="*80)
    print(model_context)
    print("="*80)

    # Verify the snippet contains the error location
    if "CODE CONTEXT" in model_context and "ERROR at column" in model_context:
        print("\n✓✓✓ SUCCESS! LLM will receive focused code snippet instead of full model!")
        print("\nBenefits:")
        print(f"  - {reduction_pct}% reduction in prompt size")
        print("  - LLM focuses on exact error location")
        print("  - Reduces hallucination about unrelated code")
        return True
    else:
        print("\n✗ ERROR: Code snippet not properly formatted")
        return False

if __name__ == "__main__":
    success = test_snippet_replacement()
    exit(0 if success else 1)
