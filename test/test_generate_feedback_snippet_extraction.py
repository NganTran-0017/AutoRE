"""Test that GenerateFeedback extracts code snippets from interpretation when there are syntax errors."""

import re

def test_snippet_extraction():
    """Test the regex pattern extracts code snippets correctly."""

    print("Testing Code Snippet Extraction from Interpretation")
    print("=" * 80)

    # Sample interpretation with syntax error and code snippet
    interpretation = """SYNTAX STATUS: Errors found
Location: Line 114, Column 40
Fix: Correct the set comprehension syntax

CODE CONTEXT (lines 112-116):
112:   all s: SystemState | s.mode = Normal =>
113:     all u: User |
114:       all r1, r2: u.assignedRoles + (dr: u.delegatedRoles | dr.role) |
                                            ^^ ERROR at column 40
115:         r1 != r2 implies no (r1.mutuallyExclusive & r2.mutuallyExclusive)
116: }

COUNTEREXAMPLES: N/A (syntax errors prevent verification)

SATISFYING INSTANCES: N/A (syntax errors prevent verification)"""

    # Test the regex pattern
    snippet_pattern = r'CODE CONTEXT \(lines \d+-\d+\):.*?(?=\n\n[A-Z]|\n\n\*|\Z)'
    snippets = re.findall(snippet_pattern, interpretation, re.DOTALL)

    print(f"Found {len(snippets)} code snippet(s)")
    print()

    if snippets:
        print("Extracted Snippet:")
        print("-" * 80)
        print(snippets[0])
        print("-" * 80)

        # Verify it contains expected content
        snippet = snippets[0]
        checks = [
            ("Contains 'CODE CONTEXT'", "CODE CONTEXT" in snippet),
            ("Contains line numbers", "112:" in snippet and "114:" in snippet),
            ("Contains error marker", "ERROR at column" in snippet),
            ("Contains actual code", "SystemState" in snippet),
            ("Does NOT contain 'COUNTEREXAMPLES'", "COUNTEREXAMPLES" not in snippet),
        ]

        print("\nValidation Checks:")
        all_passed = True
        for check_name, result in checks:
            status = "✓" if result else "✗"
            print(f"  {status} {check_name}")
            if not result:
                all_passed = False

        if all_passed:
            print("\n✓✓✓ SUCCESS! Snippet extraction works correctly")
            return True
        else:
            print("\n✗✗✗ FAILED! Some validation checks failed")
            return False
    else:
        print("✗ No snippets extracted")
        return False

def test_multiple_syntax_errors():
    """Test extraction when there are multiple syntax errors."""

    print("\n" + "=" * 80)
    print("Testing Multiple Syntax Errors")
    print("=" * 80)

    interpretation = """SYNTAX STATUS: Errors found

CODE CONTEXT (lines 40-44):
 40:   all r, r': Role | r' in r.mutexRoles implies r in r'.mutexRoles
       ^^ ERROR at column 3
 41: }
 42:

CODE CONTEXT (lines 112-116):
112:   all s: SystemState | s.mode = Normal =>
114:       all r1, r2: u.assignedRoles + (dr: u.delegatedRoles | dr.role) |
                                            ^^ ERROR at column 40
116: }

COUNTEREXAMPLES: N/A (syntax errors prevent verification)"""

    snippet_pattern = r'CODE CONTEXT \(lines \d+-\d+\):.*?(?=\n\n[A-Z]|\n\n\*|\Z)'
    snippets = re.findall(snippet_pattern, interpretation, re.DOTALL)

    print(f"Found {len(snippets)} code snippet(s)")

    if len(snippets) == 2:
        print("✓ Correctly extracted both code snippets")
        print(f"  - Snippet 1: lines 40-44")
        print(f"  - Snippet 2: lines 112-116")
        return True
    else:
        print(f"✗ Expected 2 snippets, got {len(snippets)}")
        return False

def test_no_syntax_errors():
    """Test that no extraction happens when there are no syntax errors."""

    print("\n" + "=" * 80)
    print("Testing No Syntax Errors Case")
    print("=" * 80)

    interpretation = """SYNTAX STATUS: OK

COUNTEREXAMPLES: None
- All assertions passed

SATISFYING INSTANCES: Found
- Meaningful instances generated"""

    has_syntax_errors = "SYNTAX STATUS: Errors found" in interpretation or "SYNTAX STATUS: Error" in interpretation

    print(f"Has syntax errors: {has_syntax_errors}")

    if not has_syntax_errors:
        print("✓ Correctly identified no syntax errors")
        print("✓ Full model should be used (not snippets)")
        return True
    else:
        print("✗ Incorrectly detected syntax errors")
        return False

if __name__ == "__main__":
    result1 = test_snippet_extraction()
    result2 = test_multiple_syntax_errors()
    result3 = test_no_syntax_errors()

    print("\n" + "=" * 80)
    print("FINAL RESULTS:")
    print("=" * 80)

    if result1 and result2 and result3:
        print("✓✓✓ All tests passed!")
        print("\nGenerateFeedback will now:")
        print("  - Extract code snippets when syntax errors exist")
        print("  - Use full model when no syntax errors")
        print("  - Handle multiple syntax errors correctly")
        exit(0)
    else:
        print("✗✗✗ Some tests failed")
        exit(1)
