"""
Tests for workflow regression helper functions (_create_verification_snapshot, _calculate_actual_impact)
and Evaluator's _parse_outcome_classification.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.regression_log import VerificationResult, ImpactAnalysis
from src.workflow import AutoREWorkflow
from src.actions.evaluation_actions import InterpretResults


class TestCreateVerificationSnapshot:
    """Test _create_verification_snapshot helper method."""

    def setup_method(self):
        """Set up test workflow instance."""
        # Mock the context and dependencies
        self.mock_context = Mock()
        self.mock_context.project_name = "test_project"
        self.mock_context.file_manager = Mock()
        self.mock_context.iteration = Mock()
        self.mock_context.iteration.current = 1

        # We need to create a minimal workflow instance
        # Since initialization is complex, we'll test the method directly

    def test_snapshot_all_satisfied(self):
        """Test creating snapshot when all predicates satisfied, no counterexamples."""
        from src.workflow import AutoREWorkflow

        # Create minimal mock context
        mock_context = Mock()
        workflow = Mock(spec=AutoREWorkflow)
        workflow.context = mock_context

        analyzer_results = {
            "analysis": {
                "has_syntax_errors": False,
                "instances": [
                    {"command_name": "baseline"},
                    {"command_name": "R1"},
                    {"command_name": "R2"}
                ],
                "unsat_run_commands": [],
                "counterexamples": [],
                "unsat_check_commands": [
                    {"name": "assertA"},
                    {"name": "assertB"}
                ]
            }
        }

        # Call the actual method
        from src.workflow import AutoREWorkflow
        result = AutoREWorkflow._create_verification_snapshot(workflow, analyzer_results)

        assert result.syntax == "OK"
        assert result.satisfied_predicates == ["baseline", "R1", "R2"]
        assert result.unsatisfied_predicates == []
        assert result.counterexamples == []
        assert result.no_counterexample == ["assertA", "assertB"]

    def test_snapshot_with_syntax_errors(self):
        """Test creating snapshot when syntax errors exist."""
        workflow = Mock()

        analyzer_results = {
            "analysis": {
                "has_syntax_errors": True,
                "instances": [],
                "unsat_run_commands": [],
                "counterexamples": [],
                "unsat_check_commands": []
            }
        }

        from src.workflow import AutoREWorkflow
        result = AutoREWorkflow._create_verification_snapshot(workflow, analyzer_results)

        assert result.syntax == "Error"
        assert result.satisfied_predicates == []

    def test_snapshot_with_unsat_predicates(self):
        """Test creating snapshot with unsatisfiable predicates."""
        workflow = Mock()

        analyzer_results = {
            "analysis": {
                "has_syntax_errors": False,
                "instances": [
                    {"command_name": "baseline"}
                ],
                "unsat_run_commands": [
                    {"name": "R1"},
                    {"name": "R2"}
                ],
                "counterexamples": [],
                "unsat_check_commands": []
            }
        }

        from src.workflow import AutoREWorkflow
        result = AutoREWorkflow._create_verification_snapshot(workflow, analyzer_results)

        assert result.syntax == "OK"
        assert result.satisfied_predicates == ["baseline"]
        assert result.unsatisfied_predicates == ["R1", "R2"]

    def test_snapshot_with_counterexamples(self):
        """Test creating snapshot with counterexamples."""
        workflow = Mock()

        analyzer_results = {
            "analysis": {
                "has_syntax_errors": False,
                "instances": [
                    {"command_name": "baseline"},
                    {"command_name": "R1"}
                ],
                "unsat_run_commands": [],
                "counterexamples": [
                    {"command_name": "assertA"}
                ],
                "unsat_check_commands": [
                    {"name": "assertB"}
                ]
            }
        }

        from src.workflow import AutoREWorkflow
        result = AutoREWorkflow._create_verification_snapshot(workflow, analyzer_results)

        assert result.counterexamples == ["assertA"]
        assert result.no_counterexample == ["assertB"]


class TestCalculateActualImpact:
    """Test _calculate_actual_impact helper method."""

    def test_no_changes(self):
        """Test when there are no changes between iterations."""
        workflow = Mock()

        current_results = {
            "analysis": {
                "instances": [
                    {"command_name": "baseline"},
                    {"command_name": "R1"}
                ],
                "unsat_run_commands": [],
                "counterexamples": [],
                "unsat_check_commands": [
                    {"name": "assertA"}
                ]
            }
        }

        previous_results = {
            "analysis": {
                "instances": [
                    {"command_name": "baseline"},
                    {"command_name": "R1"}
                ],
                "unsat_run_commands": [],
                "counterexamples": [],
                "unsat_check_commands": [
                    {"name": "assertA"}
                ]
            }
        }

        from src.workflow import AutoREWorkflow
        impact = AutoREWorkflow._calculate_actual_impact(workflow, current_results, previous_results)

        assert impact.sat_to_unsat == []
        assert impact.unsat_to_sat == []
        assert impact.pass_to_fail == []
        assert impact.fail_to_pass == []

    def test_unsat_to_sat(self):
        """Test predicate going from UNSAT to SAT."""
        workflow = Mock()

        current_results = {
            "analysis": {
                "instances": [
                    {"command_name": "baseline"},
                    {"command_name": "R1"}
                ],
                "unsat_run_commands": [],
                "counterexamples": [],
                "unsat_check_commands": []
            }
        }

        previous_results = {
            "analysis": {
                "instances": [
                    {"command_name": "baseline"}
                ],
                "unsat_run_commands": [
                    {"name": "R1"}
                ],
                "counterexamples": [],
                "unsat_check_commands": []
            }
        }

        from src.workflow import AutoREWorkflow
        impact = AutoREWorkflow._calculate_actual_impact(workflow, current_results, previous_results)

        assert impact.unsat_to_sat == ["R1"]
        assert impact.sat_to_unsat == []

    def test_sat_to_unsat(self):
        """Test predicate going from SAT to UNSAT."""
        workflow = Mock()

        current_results = {
            "analysis": {
                "instances": [
                    {"command_name": "baseline"}
                ],
                "unsat_run_commands": [
                    {"name": "R1"}
                ],
                "counterexamples": [],
                "unsat_check_commands": []
            }
        }

        previous_results = {
            "analysis": {
                "instances": [
                    {"command_name": "baseline"},
                    {"command_name": "R1"}
                ],
                "unsat_run_commands": [],
                "counterexamples": [],
                "unsat_check_commands": []
            }
        }

        from src.workflow import AutoREWorkflow
        impact = AutoREWorkflow._calculate_actual_impact(workflow, current_results, previous_results)

        assert impact.sat_to_unsat == ["R1"]
        assert impact.unsat_to_sat == []

    def test_fail_to_pass(self):
        """Test assertion going from FAIL to PASS."""
        workflow = Mock()

        current_results = {
            "analysis": {
                "instances": [],
                "unsat_run_commands": [],
                "counterexamples": [],
                "unsat_check_commands": [
                    {"name": "assertA"}
                ]
            }
        }

        previous_results = {
            "analysis": {
                "instances": [],
                "unsat_run_commands": [],
                "counterexamples": [
                    {"command_name": "assertA"}
                ],
                "unsat_check_commands": []
            }
        }

        from src.workflow import AutoREWorkflow
        impact = AutoREWorkflow._calculate_actual_impact(workflow, current_results, previous_results)

        assert impact.fail_to_pass == ["assertA"]
        assert impact.pass_to_fail == []

    def test_pass_to_fail(self):
        """Test assertion going from PASS to FAIL."""
        workflow = Mock()

        current_results = {
            "analysis": {
                "instances": [],
                "unsat_run_commands": [],
                "counterexamples": [
                    {"command_name": "assertA"}
                ],
                "unsat_check_commands": []
            }
        }

        previous_results = {
            "analysis": {
                "instances": [],
                "unsat_run_commands": [],
                "counterexamples": [],
                "unsat_check_commands": [
                    {"name": "assertA"}
                ]
            }
        }

        from src.workflow import AutoREWorkflow
        impact = AutoREWorkflow._calculate_actual_impact(workflow, current_results, previous_results)

        assert impact.pass_to_fail == ["assertA"]
        assert impact.fail_to_pass == []

    def test_multiple_changes(self):
        """Test multiple simultaneous changes."""
        workflow = Mock()

        current_results = {
            "analysis": {
                "instances": [
                    {"command_name": "baseline"},
                    {"command_name": "R2"}
                ],
                "unsat_run_commands": [
                    {"name": "R1"}
                ],
                "counterexamples": [
                    {"command_name": "assertB"}
                ],
                "unsat_check_commands": [
                    {"name": "assertA"}
                ]
            }
        }

        previous_results = {
            "analysis": {
                "instances": [
                    {"command_name": "baseline"},
                    {"command_name": "R1"}
                ],
                "unsat_run_commands": [
                    {"name": "R2"}
                ],
                "counterexamples": [
                    {"command_name": "assertA"}
                ],
                "unsat_check_commands": [
                    {"name": "assertB"}
                ]
            }
        }

        from src.workflow import AutoREWorkflow
        impact = AutoREWorkflow._calculate_actual_impact(workflow, current_results, previous_results)

        assert impact.sat_to_unsat == ["R1"]
        assert impact.unsat_to_sat == ["R2"]
        assert impact.pass_to_fail == ["assertB"]
        assert impact.fail_to_pass == ["assertA"]


class TestParseOutcomeClassification:
    """Test InterpretResults._parse_outcome_classification method."""

    def test_parse_expected_improvement(self):
        """Test parsing expected_improvement classification."""
        interpretation = """
=== RESULT INTERPRETATION ===
All changes as expected

=== REGRESSION DIAGNOSIS ===
Discrepancies: None - changes match expected impact

=== OUTCOME CLASSIFICATION ===
Classification: expected_improvement
Rationale: Fix worked as intended, R1 now satisfiable

=== BLOCKING QUESTIONS ===
None
"""

        # Create a mock InterpretResults instance
        mock_context = Mock()
        interpret_results = InterpretResults(mock_context, agent_name="Evaluator")

        result = interpret_results._parse_outcome_classification(interpretation)

        assert result == "expected_improvement"

    def test_parse_unintended_regression(self):
        """Test parsing unintended_regression classification."""
        interpretation = """
=== OUTCOME CLASSIFICATION ===
Classification: unintended_regression
Rationale: R1 became SAT but R2 unexpectedly became UNSAT
"""

        mock_context = Mock()
        interpret_results = InterpretResults(mock_context, agent_name="Evaluator")

        result = interpret_results._parse_outcome_classification(interpretation)

        assert result == "unintended_regression"

    def test_parse_spec_clarification(self):
        """Test parsing spec_clarification classification."""
        interpretation = """
=== OUTCOME CLASSIFICATION ===
Classification: spec_clarification: unclear cardinality constraint
Rationale: Issue reveals ambiguity about whether Users can have zero or multiple Roles
"""

        mock_context = Mock()
        interpret_results = InterpretResults(mock_context, agent_name="Evaluator")

        result = interpret_results._parse_outcome_classification(interpretation)

        assert result == "spec_clarification: unclear cardinality constraint"

    def test_parse_spec_clarification_simple(self):
        """Test parsing spec_clarification without detailed rationale."""
        interpretation = """
=== OUTCOME CLASSIFICATION ===
Classification: spec_clarification
Rationale: Needs user input on requirement R3
"""

        mock_context = Mock()
        interpret_results = InterpretResults(mock_context, agent_name="Evaluator")

        result = interpret_results._parse_outcome_classification(interpretation)

        # Should return at least "spec_clarification"
        assert "spec_clarification" in result

    def test_parse_missing_section(self):
        """Test parsing when OUTCOME CLASSIFICATION section is missing."""
        interpretation = """
=== RESULT INTERPRETATION ===
Some results

=== BLOCKING QUESTIONS ===
None
"""

        mock_context = Mock()
        interpret_results = InterpretResults(mock_context, agent_name="Evaluator")

        result = interpret_results._parse_outcome_classification(interpretation)

        assert result == "pending"

    def test_parse_missing_classification_line(self):
        """Test parsing when Classification: line is missing."""
        interpretation = """
=== OUTCOME CLASSIFICATION ===
Rationale: Some rationale without classification
"""

        mock_context = Mock()
        interpret_results = InterpretResults(mock_context, agent_name="Evaluator")

        result = interpret_results._parse_outcome_classification(interpretation)

        assert result == "pending"

    def test_parse_case_insensitive(self):
        """Test that parsing is case-insensitive."""
        interpretation = """
=== OUTCOME CLASSIFICATION ===
Classification: EXPECTED_IMPROVEMENT
Rationale: All good
"""

        mock_context = Mock()
        interpret_results = InterpretResults(mock_context, agent_name="Evaluator")

        result = interpret_results._parse_outcome_classification(interpretation)

        assert result == "expected_improvement"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
