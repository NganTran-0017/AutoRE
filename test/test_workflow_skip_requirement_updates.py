"""
Test workflow behavior when REQUIREMENT_UPDATES is empty - verify requirements file is still created.
"""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from src.workflow import AutoREWorkflow


def test_step7_with_no_requirement_updates():
    """Test that Step 7 creates a copy of requirements when no updates needed."""

    # Create a minimal workflow instance without full initialization
    workflow = AutoREWorkflow.__new__(AutoREWorkflow)

    # Mock the context and its components
    workflow.context = Mock()
    workflow.context.artifacts = Mock()
    workflow.context.iteration = Mock()
    workflow.context.iteration.current = 2
    workflow.context.file_manager = Mock()
    workflow.context.user_preferences = Mock()

    # Set up mock return values
    current_requirements = "Original requirements document"
    feedback_no_updates = """
=== VERIFICATION STATUS ===
Model verified successfully.

=== ALLOY_MODEL_IMPROVEMENTS ===
Consider adding more assertions.

=== REQUIREMENT UPDATES ===
None

=== USER QUESTIONS ===
None
"""

    workflow.context.artifacts.get_latest_feedback.return_value = feedback_no_updates
    workflow.context.artifacts.get_latest_requirements.return_value = current_requirements
    workflow.context.file_manager.get_latest_requirements_file.return_value = Path("Output/ReqsDoc/requirements_iter_1.md")

    # Mock the update_requirements action (should not be called)
    workflow.update_requirements = AsyncMock()

    # Run Step 7
    asyncio.run(workflow._step7_update_requirements())

    # Verify that update_requirements was NOT called
    workflow.update_requirements.run.assert_not_called()

    # Current behavior: when there are no updates, Step 7 reuses the existing
    # requirements file and does NOT re-save.
    workflow.context.file_manager.save_requirements.assert_not_called()
    workflow.context.file_manager.get_latest_requirements_file.assert_called_once()


def test_step7_with_requirement_updates():
    """Test that Step 7 updates requirements when updates are present."""

    # Create a minimal workflow instance without full initialization
    workflow = AutoREWorkflow.__new__(AutoREWorkflow)

    # Mock the context and its components
    workflow.context = Mock()
    workflow.context.artifacts = Mock()
    workflow.context.iteration = Mock()
    workflow.context.iteration.current = 2
    workflow.context.file_manager = Mock()
    workflow.context.user_preferences = Mock()

    # Set up mock return values
    current_requirements = "Original requirements document"
    feedback_with_updates = """
=== VERIFICATION STATUS ===
Model has issues.

=== ALLOY_MODEL_IMPROVEMENTS ===
Consider adding more assertions.

=== REQUIREMENT UPDATES ===
- Affected Requirement/Assumption/Constraint: R2
- Classification: requirement
- Target kind & placement: sub-requirement R2.1 under R2
- Coverage check: checked R1-R3; none specify a timeout value
- Issue Type: ambiguity
- Evidence: counterexample shows unbounded session duration
- Recommended Update: specify an exact login timeout value

=== UPDATED USER QUESTIONS ===
What should the timeout value be?
"""

    updated_requirements = "Updated requirements document with timeout clarification"

    workflow.context.artifacts.get_latest_feedback.return_value = feedback_with_updates
    workflow.context.artifacts.get_latest_requirements.return_value = current_requirements
    workflow.context.user_preferences.format_for_prompt.return_value = ""
    workflow.context.file_manager.save_requirements.return_value = Path("Output/ReqsDoc/requirements_iter_2.md")

    # Mock the update_requirements action
    workflow.update_requirements = AsyncMock()
    workflow.update_requirements.run.return_value = updated_requirements

    # Run Step 7
    asyncio.run(workflow._step7_update_requirements())

    # Verify that update_requirements WAS called
    workflow.update_requirements.run.assert_called_once()

    # Verify that save_requirements WAS called with the updated requirements
    workflow.context.file_manager.save_requirements.assert_called_once_with(
        updated_requirements,
        iteration=2
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
