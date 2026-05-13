"""
Test convergence scenarios with hybrid approach (Hard Metrics + Agent Assessment).

Tests cover all branches:
1. Syntax errors (hard metrics fail)
2. Counterexamples (hard metrics fail)
3. Incomplete positive runs (hard metrics fail)
4. Hard metrics pass with weak instances (agent recommends FALSE)
5. Hard metrics pass with good instances (agent recommends TRUE)
6. User requests more tests (agent refines to FALSE)
7. User satisfaction (agent confirms TRUE)
"""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from src.workflow import AutoREWorkflow


@pytest.fixture
def mock_workflow():
    """Create a mock workflow with necessary components."""
    workflow = AutoREWorkflow.__new__(AutoREWorkflow)

    # Mock context and components
    workflow.context = Mock()
    workflow.context.artifacts = Mock()
    workflow.context.iteration = Mock()
    workflow.context.iteration.current = 5
    workflow.context.file_manager = Mock()
    workflow.context.user_preferences = Mock()
    workflow.logger = Mock()
    workflow.cli = Mock()

    # Mock actions - need to set return_value explicitly
    workflow.run_analyzer = Mock()
    workflow.interpret_results = Mock()
    workflow.generate_feedback = Mock()
    workflow.refine_feedback = Mock()

    # Make them awaitable
    workflow.run_analyzer.run = AsyncMock()
    workflow.interpret_results.run = AsyncMock()
    workflow.generate_feedback.run = AsyncMock()
    workflow.refine_feedback.run = AsyncMock()

    return workflow


# ============================================================================
# Scenario 1: Syntax Errors (Hard Metrics Fail)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario1_syntax_errors(mock_workflow):
    """Test convergence with syntax errors - hard metrics fail."""

    # Mock analyzer results with syntax errors
    analyzer_results = {
        'analysis': {
            'has_syntax_errors': True,
            'has_counterexamples': False,
            'positive_run_commands': 5,
            'satisfied_positive_runs': 5,
            'syntax_errors': [
                {'line': 42, 'message': 'Unexpected token'}
            ]
        }
    }

    mock_workflow.run_analyzer.run.return_value = analyzer_results
    mock_workflow.interpret_results.run.return_value = "SYNTAX STATUS: Errors found"
    mock_workflow.context.artifacts.get_latest_requirements.return_value = "Requirements"
    mock_workflow.context.artifacts.get_latest_alloy_model.return_value = "Model"

    # Mock model file exists
    mock_model_path = Mock()
    mock_model_path.exists.return_value = True
    mock_workflow.context.file_manager.get_alloy_model_path.return_value = mock_model_path

    # Run Step 4
    result = await mock_workflow._step4_evaluate_model()

    # Assertions
    assert result is False, "Hard metrics should fail due to syntax errors"


# ============================================================================
# Scenario 2: Counterexamples (Hard Metrics Fail)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario2_counterexamples(mock_workflow):
    """Test convergence with counterexamples - hard metrics fail."""

    # Mock analyzer results with counterexamples
    analyzer_results = {
        'analysis': {
            'has_syntax_errors': False,
            'has_counterexamples': True,
            'positive_run_commands': 5,
            'satisfied_positive_runs': 5,
            'counterexamples': [
                {'command_name': 'assertNoMutexViolation', 'file': 'counterexample.json'}
            ]
        }
    }

    mock_workflow.run_analyzer.run.return_value = analyzer_results
    mock_workflow.interpret_results.run.return_value = "COUNTEREXAMPLES: Found"
    mock_workflow.context.artifacts.get_latest_requirements.return_value = "Requirements"
    mock_workflow.context.artifacts.get_latest_alloy_model.return_value = "Model"

    # Mock model file exists
    mock_model_path = Mock()
    mock_model_path.exists.return_value = True
    mock_workflow.context.file_manager.get_alloy_model_path.return_value = mock_model_path

    # Run Step 4
    result = await mock_workflow._step4_evaluate_model()

    # Assertions
    assert result is False, "Hard metrics should fail due to counterexamples"


# ============================================================================
# Scenario 3: Incomplete Positive Runs (Hard Metrics Fail)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario3_incomplete_positive_runs(mock_workflow):
    """Test convergence with incomplete positive runs - hard metrics fail."""

    # Mock analyzer results: 7/8 positive runs satisfied (one negative case UNSAT is OK)
    analyzer_results = {
        'analysis': {
            'has_syntax_errors': False,
            'has_counterexamples': False,
            'positive_run_commands': 8,
            'satisfied_positive_runs': 7,  # One positive run failed
            'total_run_commands': 9,
            'unsat_run_commands': [
                {'name': 'SomePositiveScenario', 'type': 'run'}  # Positive run failed
            ]
        }
    }

    mock_workflow.run_analyzer.run.return_value = analyzer_results
    mock_workflow.interpret_results.run.return_value = "UNSATISFIABLE PREDICATES: Found"
    mock_workflow.context.artifacts.get_latest_requirements.return_value = "Requirements"
    mock_workflow.context.artifacts.get_latest_alloy_model.return_value = "Model"

    # Mock model file exists
    mock_model_path = Mock()
    mock_model_path.exists.return_value = True
    mock_workflow.context.file_manager.get_alloy_model_path.return_value = mock_model_path

    # Run Step 4
    result = await mock_workflow._step4_evaluate_model()

    # Assertions
    assert result is False, "Hard metrics should fail: 7/8 positive runs satisfied"


# ============================================================================
# Scenario 4: Hard Metrics Pass + Weak Instances (Agent Recommends FALSE)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario4_weak_instances_no_user_feedback(mock_workflow):
    """Test convergence: hard metrics pass but weak instances, no user feedback."""

    # Mock analyzer results: all metrics pass
    analyzer_results = {
        'analysis': {
            'has_syntax_errors': False,
            'has_counterexamples': False,
            'positive_run_commands': 7,
            'satisfied_positive_runs': 7,
            'sample_instances': [
                {'command_name': 'All_Requirements', 'file': 'instance.json', 'data': {}}
            ]
        }
    }

    mock_workflow.run_analyzer.run.return_value = analyzer_results
    mock_workflow.interpret_results.run.return_value = "SATISFYING INSTANCES: Weak/trivial"

    # Agent recommends FALSE due to weak instances
    feedback_with_false = """
=== VERIFICATION STATUS ===
- Syntax: OK
- Assertions: Pass
- Predicates: Satisfiable
- Instances: Suspicious (trivial)
- Vacuity: Possible
- Overall: Incomplete

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE
Reasoning: Satisfying instances appear trivial. Model may be under-constrained.

=== ALLOY_MODEL_IMPROVEMENTS ===
Add stronger constraints to ensure meaningful scenarios.
"""

    mock_workflow.generate_feedback.run.return_value = feedback_with_false
    mock_workflow.context.artifacts.get_latest_evaluation.return_value = "Interpretation"
    mock_workflow.context.artifacts.get_latest_requirements.return_value = "Requirements"
    mock_workflow.context.artifacts.get_latest_alloy_model.return_value = "Model"

    # User provides no feedback (timeout)
    mock_workflow.cli.request_input.return_value = None

    # Mock model file exists
    mock_model_path = Mock()
    mock_model_path.exists.return_value = True
    mock_workflow.context.file_manager.get_alloy_model_path.return_value = mock_model_path

    # Run Step 4 + Step 5-6
    hard_metrics = await mock_workflow._step4_evaluate_model()
    feedback_result = await mock_workflow._step5_6_generate_feedback_and_get_user_input()

    # Assertions
    assert hard_metrics is True, "Hard metrics should pass"
    assert feedback_result['final_convergence'] is False, "Agent should recommend FALSE (weak instances)"
    assert feedback_result['user_provided_feedback'] is False, "No user feedback"


# ============================================================================
# Scenario 5: Hard Metrics Pass + Good Instances (Agent Recommends TRUE)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario5_good_instances_no_user_feedback(mock_workflow):
    """Test convergence: hard metrics pass, good instances, no user feedback."""

    # Mock analyzer results: all metrics pass
    analyzer_results = {
        'analysis': {
            'has_syntax_errors': False,
            'has_counterexamples': False,
            'positive_run_commands': 7,
            'satisfied_positive_runs': 7,
            'sample_instances': [
                {'command_name': 'All_Requirements', 'file': 'instance.json', 'data': {}}
            ]
        }
    }

    mock_workflow.run_analyzer.run.return_value = analyzer_results
    mock_workflow.interpret_results.run.return_value = "SATISFYING INSTANCES: Meaningful"

    # Agent recommends TRUE - instances are good
    feedback_with_true = """
=== VERIFICATION STATUS ===
- Syntax: OK
- Assertions: Pass
- Predicates: Satisfiable
- Instances: Meaningful
- Vacuity: None
- Overall: Provisionally strong

=== CONVERGENCE_RECOMMENDATION ===
Status: TRUE
Reasoning: All requirements verified. Instances are meaningful and cover key scenarios.

=== ALLOY_MODEL_IMPROVEMENTS ===
N/A
"""

    mock_workflow.generate_feedback.run.return_value = feedback_with_true
    mock_workflow.context.artifacts.get_latest_evaluation.return_value = "Interpretation"
    mock_workflow.context.artifacts.get_latest_requirements.return_value = "Requirements"
    mock_workflow.context.artifacts.get_latest_alloy_model.return_value = "Model"

    # User provides no feedback (satisfied)
    mock_workflow.cli.request_input.return_value = ""

    # Mock model file exists
    mock_model_path = Mock()
    mock_model_path.exists.return_value = True
    mock_workflow.context.file_manager.get_alloy_model_path.return_value = mock_model_path

    # Run Step 4 + Step 5-6
    hard_metrics = await mock_workflow._step4_evaluate_model()
    feedback_result = await mock_workflow._step5_6_generate_feedback_and_get_user_input()

    # Assertions
    assert hard_metrics is True, "Hard metrics should pass"
    assert feedback_result['final_convergence'] is True, "Agent should recommend TRUE (good instances)"
    assert feedback_result['user_provided_feedback'] is False, "No user feedback"


# ============================================================================
# Scenario 6: User Requests More Tests (Agent Refines to FALSE)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario6_user_requests_more_tests(mock_workflow):
    """Test convergence: hard metrics pass, but user requests additional tests."""

    # Mock analyzer results: all metrics pass
    analyzer_results = {
        'analysis': {
            'has_syntax_errors': False,
            'has_counterexamples': False,
            'positive_run_commands': 7,
            'satisfied_positive_runs': 7,
            'sample_instances': [
                {'command_name': 'All_Requirements', 'file': 'instance.json', 'data': {}}
            ]
        }
    }

    mock_workflow.run_analyzer.run.return_value = analyzer_results
    mock_workflow.interpret_results.run.return_value = "SATISFYING INSTANCES: Meaningful"

    # Agent initially recommends TRUE
    draft_feedback_with_true = """
=== VERIFICATION STATUS ===
- Syntax: OK
- Assertions: Pass
- Overall: Provisionally strong

=== CONVERGENCE_RECOMMENDATION ===
Status: TRUE
Reasoning: All requirements verified.

=== ALLOY_MODEL_IMPROVEMENTS ===
N/A
"""

    # After user feedback, agent refines to FALSE
    refined_feedback_with_false = """
=== VERIFICATION STATUS ===
- Syntax: OK
- Assertions: Pass
- Overall: Incomplete

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE
Reasoning: User requested additional edge case testing for delegation expiry scenarios.

=== ALLOY_MODEL_IMPROVEMENTS ===
Add test scenarios for delegation expiry edge cases.
"""

    mock_workflow.generate_feedback.run.return_value = draft_feedback_with_true
    mock_workflow.refine_feedback.run.return_value = refined_feedback_with_false
    mock_workflow.context.artifacts.get_latest_evaluation.return_value = "Interpretation"
    mock_workflow.context.artifacts.get_latest_requirements.return_value = "Requirements"
    mock_workflow.context.artifacts.get_latest_alloy_model.return_value = "Model"

    # User provides feedback requesting more tests
    mock_workflow.cli.request_input.return_value = "Please add test scenarios for delegation expiry edge cases"

    # Mock model file exists
    mock_model_path = Mock()
    mock_model_path.exists.return_value = True
    mock_workflow.context.file_manager.get_alloy_model_path.return_value = mock_model_path

    # Run Step 4 + Step 5-6
    hard_metrics = await mock_workflow._step4_evaluate_model()
    feedback_result = await mock_workflow._step5_6_generate_feedback_and_get_user_input()

    # Assertions
    assert hard_metrics is True, "Hard metrics should pass"
    assert feedback_result['final_convergence'] is False, "Agent should refine to FALSE (user requests more)"
    assert feedback_result['user_provided_feedback'] is True, "User provided feedback"


# ============================================================================
# Scenario 7: User Satisfaction (Agent Confirms TRUE)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario7_user_satisfaction(mock_workflow):
    """Test convergence: hard metrics pass, user indicates satisfaction."""

    # Mock analyzer results: all metrics pass
    analyzer_results = {
        'analysis': {
            'has_syntax_errors': False,
            'has_counterexamples': False,
            'positive_run_commands': 7,
            'satisfied_positive_runs': 7,
            'sample_instances': [
                {'command_name': 'All_Requirements', 'file': 'instance.json', 'data': {}}
            ]
        }
    }

    mock_workflow.run_analyzer.run.return_value = analyzer_results
    mock_workflow.interpret_results.run.return_value = "SATISFYING INSTANCES: Meaningful"

    # Agent initially recommends TRUE
    draft_feedback_with_true = """
=== VERIFICATION STATUS ===
- Syntax: OK
- Assertions: Pass
- Overall: Provisionally strong

=== CONVERGENCE_RECOMMENDATION ===
Status: TRUE
Reasoning: All requirements verified.

=== ALLOY_MODEL_IMPROVEMENTS ===
N/A
"""

    # After user satisfaction, agent confirms TRUE
    refined_feedback_confirmed_true = """
=== VERIFICATION STATUS ===
- Syntax: OK
- Assertions: Pass
- Overall: Provisionally strong

=== CONVERGENCE_RECOMMENDATION ===
Status: TRUE
Reasoning: User confirmed satisfaction. All requirements adequately verified.

=== ALLOY_MODEL_IMPROVEMENTS ===
N/A
"""

    mock_workflow.generate_feedback.run.return_value = draft_feedback_with_true
    mock_workflow.refine_feedback.run.return_value = refined_feedback_confirmed_true
    mock_workflow.context.artifacts.get_latest_evaluation.return_value = "Interpretation"
    mock_workflow.context.artifacts.get_latest_requirements.return_value = "Requirements"
    mock_workflow.context.artifacts.get_latest_alloy_model.return_value = "Model"

    # User indicates satisfaction
    mock_workflow.cli.request_input.return_value = "Looks good! Everything is verified."

    # Mock model file exists
    mock_model_path = Mock()
    mock_model_path.exists.return_value = True
    mock_workflow.context.file_manager.get_alloy_model_path.return_value = mock_model_path

    # Run Step 4 + Step 5-6
    hard_metrics = await mock_workflow._step4_evaluate_model()
    feedback_result = await mock_workflow._step5_6_generate_feedback_and_get_user_input()

    # Assertions
    assert hard_metrics is True, "Hard metrics should pass"
    assert feedback_result['final_convergence'] is True, "Agent should confirm TRUE (user satisfied)"
    assert feedback_result['user_provided_feedback'] is True, "User provided feedback"


# ============================================================================
# Scenario 8: Negative Test Cases Excluded from Positive Run Count
# ============================================================================

@pytest.mark.asyncio
async def test_scenario8_negative_cases_excluded(mock_workflow):
    """Test that negative test cases don't count toward positive run requirements."""

    # Mock analyzer results: 7/7 positive runs + 1 negative UNSAT
    analyzer_results = {
        'analysis': {
            'has_syntax_errors': False,
            'has_counterexamples': False,
            'positive_run_commands': 7,      # Excludes negative cases
            'satisfied_positive_runs': 7,    # All positive satisfied
            'total_run_commands': 8,         # Total includes 1 negative
            'unsat_run_commands': [
                {'name': 'EmergencyScenario_Negative', 'type': 'run'}  # Negative case UNSAT is OK
            ],
            'sample_instances': [
                {'command_name': 'All_Requirements', 'file': 'instance.json', 'data': {}}
            ]
        }
    }

    mock_workflow.run_analyzer.run.return_value = analyzer_results
    mock_workflow.interpret_results.run.return_value = "SATISFYING INSTANCES: Meaningful"
    mock_workflow.context.artifacts.get_latest_requirements.return_value = "Requirements"
    mock_workflow.context.artifacts.get_latest_alloy_model.return_value = "Model"

    # Mock model file exists
    mock_model_path = Mock()
    mock_model_path.exists.return_value = True
    mock_workflow.context.file_manager.get_alloy_model_path.return_value = mock_model_path

    # Run Step 4
    result = await mock_workflow._step4_evaluate_model()

    # Assertions
    assert result is True, "Hard metrics should pass: negative case excluded from count"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
