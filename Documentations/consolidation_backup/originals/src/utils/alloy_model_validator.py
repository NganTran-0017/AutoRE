"""
Alloy Model Completeness Validator

This module provides validation functions to verify that an Alloy model is complete
and not just a snippet or partial update.
"""

import re
from typing import Tuple, List, Dict, Any


def _strip_comments(code: str) -> str:
    """
    Strip both single-line (//) and block (/* */) comments from Alloy code.
    This prevents false positives when checking for snippet indicators in comments.
    
    Args:
        code: The Alloy code
        
    Returns:
        Code with comments removed
    """
    # Remove block comments /* ... */
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    
    # Remove single-line comments //
    lines = code.split('\n')
    stripped_lines = []
    for line in lines:
        # Find // and remove everything after it
        comment_pos = line.find('//')
        if comment_pos != -1:
            line = line[:comment_pos]
        stripped_lines.append(line)
    
    return '\n'.join(stripped_lines)


def validate_alloy_model_completeness(
    model_code: str,
    check_structure: bool = True,
    check_snippets: bool = True
) -> Tuple[bool, List[str]]:
    """
    Validate that an Alloy model is complete and not a snippet.
    
    Note: This function focuses on structural/snippet validation only.
    Length-based validation (empty check, min lines, size comparison) should be 
    done separately before calling this function to avoid redundancy.

    Args:
        model_code: The Alloy model code to validate
        check_structure: Whether to check for essential structural elements
        check_snippets: Whether to check for snippet indicators

    Returns:
        Tuple of (is_valid: bool, issues: List[str])
        - is_valid: True if model is complete, False if snippet/incomplete
        - issues: List of validation issues found (empty if valid)
    """
    issues = []

    # Extract code from markdown fences if present
    alloy_block_pattern = r'```alloy\s*\n(.*?)```'
    match = re.search(alloy_block_pattern, model_code, re.DOTALL)

    if match:
        clean_code = match.group(1).strip()
    else:
        clean_code = model_code.strip()

    # Check 1: Snippet indicators
    if check_snippets:
        # Strip comments before checking for snippet indicators
        # This prevents false positives from comments like "// ..."
        code_without_comments = _strip_comments(clean_code)
        
        snippet_indicators = [
            r'\(rest\s+(?:of\s+)?(?:the\s+)?model\s+unchanged\)',
            r'\.\.\.',  # Three dots (but now checked in code without comments)
            r'unchanged',
            r'same\s+as\s+before',
            r'rest\s+remains',
            r'other\s+parts?\s+unchanged'
        ]

        for pattern in snippet_indicators:
            if re.search(pattern, code_without_comments, re.IGNORECASE):
                issues.append(f"Snippet indicator found: '{pattern}'")

    # Check 3: Essential structural elements (if enabled)
    if check_structure:
        required_elements = {
            'signature': r'\bsig\s+\w+',
            'fact': r'\bfact\s+\w+',
            'predicate': r'\bpred\s+\w+',
            'run_command': r'\brun\s+\w+',
            'check_command': r'\bcheck\s+\w+'
        }

        for element_name, pattern in required_elements.items():
            if not re.search(pattern, clean_code):
                issues.append(f"Missing essential element: {element_name}")

    # Check 4: Specific required predicates/commands
    expected_predicates = ['baseline', 'All_Requirements']
    for pred in expected_predicates:
        if not re.search(rf'\bpred\s+{pred}\b', clean_code):
            issues.append(f"Missing required predicate: {pred}")

    # Check 5: Run command order (baseline should come before All_Requirements)
    run_baseline = re.search(r'\brun\s+baseline\b', clean_code)
    run_all = re.search(r'\brun\s+All_Requirements\b', clean_code)

    if run_baseline and run_all:
        if run_baseline.start() > run_all.start():
            issues.append("Run command order incorrect: 'run baseline' should come before 'run All_Requirements'")

    is_valid = len(issues) == 0
    return is_valid, issues


def validate_model_structure_details(model_code: str) -> Dict[str, Any]:
    """
    Analyze the structure of an Alloy model in detail.

    Args:
        model_code: The Alloy model code to analyze

    Returns:
        Dictionary with structure details:
        - signature_count: Number of signatures
        - fact_count: Number of facts
        - predicate_count: Number of predicates
        - assertion_count: Number of assertions
        - run_count: Number of run commands
        - check_count: Number of check commands
        - line_count: Total non-empty lines
        - has_baseline: Whether baseline predicate exists
        - has_all_requirements: Whether All_Requirements predicate exists
    """
    # Extract clean code
    alloy_block_pattern = r'```alloy\s*\n(.*?)```'
    match = re.search(alloy_block_pattern, model_code, re.DOTALL)
    clean_code = match.group(1).strip() if match else model_code.strip()

    # Count elements
    structure = {
        'signature_count': len(re.findall(r'\bsig\s+\w+', clean_code)),
        'fact_count': len(re.findall(r'\bfact\s+\w+', clean_code)),
        'predicate_count': len(re.findall(r'\bpred\s+\w+', clean_code)),
        'assertion_count': len(re.findall(r'\bassert\s+\w+', clean_code)),
        'run_count': len(re.findall(r'\brun\s+\w+', clean_code)),
        'check_count': len(re.findall(r'\bcheck\s+\w+', clean_code)),
        'line_count': len([line for line in clean_code.split('\n') if line.strip()]),
        'has_baseline': bool(re.search(r'\bpred\s+baseline\b', clean_code)),
        'has_all_requirements': bool(re.search(r'\bpred\s+All_Requirements\b', clean_code)),
        'has_open_statements': bool(re.search(r'\bopen\s+util/', clean_code))
    }

    return structure


def format_validation_report(is_valid: bool, issues: List[str], structure: Dict[str, Any] = None) -> str:
    """
    Format a validation report for console/log output.

    Args:
        is_valid: Validation result
        issues: List of issues found
        structure: Optional structure details

    Returns:
        Formatted report string
    """
    lines = []

    if is_valid:
        lines.append("✅ Alloy Model Validation: PASSED")
    else:
        lines.append("❌ Alloy Model Validation: FAILED")

    if issues:
        lines.append("\nIssues found:")
        for i, issue in enumerate(issues, 1):
            lines.append(f"  {i}. {issue}")

    if structure:
        lines.append("\nModel Structure:")
        lines.append(f"  Signatures: {structure['signature_count']}")
        lines.append(f"  Facts: {structure['fact_count']}")
        lines.append(f"  Predicates: {structure['predicate_count']}")
        lines.append(f"  Assertions: {structure['assertion_count']}")
        lines.append(f"  Run commands: {structure['run_count']}")
        lines.append(f"  Check commands: {structure['check_count']}")
        lines.append(f"  Total lines: {structure['line_count']}")
        lines.append(f"  Has baseline: {structure['has_baseline']}")
        lines.append(f"  Has All_Requirements: {structure['has_all_requirements']}")

    return "\n".join(lines)


def test_alloy_model_validator():
    """
    Unit tests for the Alloy model validator.
    """
    print("Running Alloy Model Validator Tests...\n")

    # Test 1: Complete model (should pass)
    complete_model = """
sig User {}
sig Role {}

fact ExistingSystem {
    some User
}

pred baseline {}

pred R1 {
    some User
}

pred All_Requirements {
    R1
}

run baseline
run All_Requirements
run R1

assert assertUserExists {
    some User
}

check assertUserExists
"""

    is_valid, issues = validate_alloy_model_completeness(complete_model)
    structure = validate_model_structure_details(complete_model)
    print("Test 1: Complete Model")
    print(format_validation_report(is_valid, issues, structure))
    print(f"Result: {'PASS' if is_valid else 'FAIL'}\n")

    # Test 2: Snippet (should fail)
    snippet_model = """
pred R1 {
    some User
}

// ... (rest of model unchanged)
"""

    is_valid, issues = validate_alloy_model_completeness(snippet_model)
    print("Test 2: Snippet Model")
    print(format_validation_report(is_valid, issues))
    print(f"Result: {'PASS (correctly detected)' if not is_valid else 'FAIL'}\n")

    # Test 3: Missing baseline (should fail)
    no_baseline_model = """
sig User {}
sig Role {}

fact ExistingSystem {
    some User
}

pred R1 {
    some User
}

pred All_Requirements {
    R1
}

run All_Requirements
run R1
check assertUserExists
"""

    is_valid, issues = validate_alloy_model_completeness(no_baseline_model)
    print("Test 3: Missing Baseline")
    print(format_validation_report(is_valid, issues))
    print(f"Result: {'PASS (correctly detected)' if not is_valid else 'FAIL'}\n")

    # Test 4: Wrapped in markdown (should pass)
    markdown_model = f"""```alloy
{complete_model}
```"""

    is_valid, issues = validate_alloy_model_completeness(markdown_model)
    print("Test 4: Markdown-Wrapped Model")
    print(format_validation_report(is_valid, issues))
    print(f"Result: {'PASS' if is_valid else 'FAIL'}\n")

    print("All tests completed!")


if __name__ == "__main__":
    test_alloy_model_validator()
