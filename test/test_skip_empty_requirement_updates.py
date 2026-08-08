"""
Test that UpdateRequirements action is skipped when feedback has no REQUIREMENT_UPDATES.
"""
import pytest
from src.workflow import AutoREWorkflow


def test_extract_requirement_updates_with_content():
    """Test extraction when REQUIREMENT_UPDATES has meaningful content."""
    workflow = AutoREWorkflow.__new__(AutoREWorkflow)

    feedback = """
=== VERIFICATION STATUS ===
Model verified successfully.

=== ALLOY_MODEL_IMPROVEMENTS ===
Consider adding more assertions.

=== REQUIREMENT UPDATES ===
- Affected Requirement/Assumption/Constraint: R2
- Classification: requirement
- Target kind & placement: sub-requirement R2.1 under R2
- Coverage check: checked R1-R3; none specify a timeout value
- Issue Type: ambiguity
- Recommended Update: specify an exact login timeout value

=== UPDATED USER QUESTIONS ===
None
"""

    result = workflow._extract_requirement_updates(feedback)
    assert result is not None
    assert "specify an exact login timeout value" in result


def test_extract_requirement_updates_empty():
    """Test extraction when REQUIREMENT_UPDATES is empty."""
    workflow = AutoREWorkflow.__new__(AutoREWorkflow)

    feedback = """
=== VERIFICATION STATUS ===
Model verified successfully.

=== ALLOY_MODEL_IMPROVEMENTS ===
Consider adding more assertions.

=== REQUIREMENT UPDATES ===

=== USER QUESTIONS ===
None
"""

    result = workflow._extract_requirement_updates(feedback)
    assert result is None


def test_extract_requirement_updates_none():
    """Test extraction when REQUIREMENT_UPDATES says 'None'."""
    workflow = AutoREWorkflow.__new__(AutoREWorkflow)

    feedback = """
=== VERIFICATION STATUS ===
Model verified successfully.

=== ALLOY_MODEL_IMPROVEMENTS ===
Consider adding more assertions.

=== REQUIREMENT UPDATES ===
None

=== USER QUESTIONS ===
None
"""

    result = workflow._extract_requirement_updates(feedback)
    assert result is None


def test_extract_requirement_updates_placeholder():
    """Test extraction when REQUIREMENT_UPDATES has only placeholder text."""
    workflow = AutoREWorkflow.__new__(AutoREWorkflow)

    feedback = """
=== VERIFICATION STATUS ===
Model verified successfully.

=== REQUIREMENT UPDATES ===
[Ambiguities/inconsistencies/missing items]

=== USER QUESTIONS ===
None
"""

    result = workflow._extract_requirement_updates(feedback)
    assert result is None


def test_extract_requirement_updates_not_applicable():
    """Test extraction when REQUIREMENT_UPDATES says 'N/A'."""
    workflow = AutoREWorkflow.__new__(AutoREWorkflow)

    feedback = """
=== VERIFICATION STATUS ===
Model verified successfully.

=== REQUIREMENT UPDATES ===
N/A

=== USER QUESTIONS ===
None
"""

    result = workflow._extract_requirement_updates(feedback)
    assert result is None


def test_extract_requirement_updates_missing_section():
    """Test extraction when REQUIREMENT_UPDATES section is missing."""
    workflow = AutoREWorkflow.__new__(AutoREWorkflow)

    feedback = """
=== VERIFICATION STATUS ===
Model verified successfully.

=== ALLOY_MODEL_IMPROVEMENTS ===
Consider adding more assertions.

=== USER QUESTIONS ===
None
"""

    result = workflow._extract_requirement_updates(feedback)
    assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
