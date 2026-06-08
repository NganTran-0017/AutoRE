"""
Tests for regression log parsing functions added for regression tracking.
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.regression_log import (
    parse_re_response_for_regression,
    ImpactAnalysis,
    VerificationResult,
    RegressionLog,
    RegressionLogEntry
)


class TestParseREResponse:
    """Test parsing RE agent's response for regression tracking."""

    def test_parse_complete_response(self):
        """Test parsing a complete RE response with all sections."""
        response = """
=== FIX INTENT ===
Fix the missing constraint that allows unauthorized access

=== SOURCE REFERENCE ===
Evaluator feedback: counterexample in assertNoUnauthorizedAccess

=== EXPECTED IMPACT ===
satToUnsat: [None]
unsatToSat: [R1, R2]
passToFail: [None]
failToPass: [assertNoUnauthorizedAccess, assertDelegation]

```alloy
sig User {}
sig Resource {}
// Updated model code here
```
"""
        result = parse_re_response_for_regression(response)

        assert result["fix_intent"] == "Fix the missing constraint that allows unauthorized access"
        assert result["source_ref"] == "Evaluator feedback: counterexample in assertNoUnauthorizedAccess"
        assert result["expected_impact"].sat_to_unsat == []
        assert result["expected_impact"].unsat_to_sat == ["R1", "R2"]
        assert result["expected_impact"].pass_to_fail == []
        assert result["expected_impact"].fail_to_pass == ["assertNoUnauthorizedAccess", "assertDelegation"]

    def test_parse_with_none_values(self):
        """Test parsing when expected impact has 'None' values."""
        response = """
=== FIX INTENT ===
Add baseline predicate

=== SOURCE REFERENCE ===
Initial model creation

=== EXPECTED IMPACT ===
satToUnsat: [None]
unsatToSat: [None]
passToFail: [None]
failToPass: [None]
"""
        result = parse_re_response_for_regression(response)

        assert result["fix_intent"] == "Add baseline predicate"
        assert result["expected_impact"].sat_to_unsat == []
        assert result["expected_impact"].unsat_to_sat == []
        assert result["expected_impact"].pass_to_fail == []
        assert result["expected_impact"].fail_to_pass == []

    def test_parse_missing_sections(self):
        """Test parsing when some sections are missing."""
        response = """
=== FIX INTENT ===
Fix syntax error

=== EXPECTED IMPACT ===
satToUnsat: [None]
unsatToSat: [None]
passToFail: [None]
failToPass: [None]

```alloy
sig User {}
```
"""
        result = parse_re_response_for_regression(response)

        assert result["fix_intent"] == "Fix syntax error"
        assert result["source_ref"] == ""
        assert isinstance(result["expected_impact"], ImpactAnalysis)

    def test_parse_multiline_values(self):
        """Test parsing multiline fix intent."""
        response = """
=== FIX INTENT ===
Fix the constraint issue by:
1. Adding proper bounds
2. Removing overconstraint
3. Testing with larger scope

=== SOURCE REFERENCE ===
User clarification Q3_2

=== EXPECTED IMPACT ===
satToUnsat: [R3]
unsatToSat: [None]
passToFail: [None]
failToPass: [None]
"""
        result = parse_re_response_for_regression(response)

        assert "1. Adding proper bounds" in result["fix_intent"]
        assert "2. Removing overconstraint" in result["fix_intent"]
        assert result["expected_impact"].sat_to_unsat == ["R3"]

    def test_parse_empty_lists(self):
        """Test parsing when lists are empty."""
        response = """
=== EXPECTED IMPACT ===
satToUnsat: []
unsatToSat: []
passToFail: []
failToPass: []
"""
        result = parse_re_response_for_regression(response)

        assert result["expected_impact"].sat_to_unsat == []
        assert result["expected_impact"].unsat_to_sat == []

    def test_parse_single_item_lists(self):
        """Test parsing lists with single items."""
        response = """
=== EXPECTED IMPACT ===
satToUnsat: [R1]
unsatToSat: [baseline]
passToFail: [assertA]
failToPass: [assertB]
"""
        result = parse_re_response_for_regression(response)

        assert result["expected_impact"].sat_to_unsat == ["R1"]
        assert result["expected_impact"].unsat_to_sat == ["baseline"]
        assert result["expected_impact"].pass_to_fail == ["assertA"]
        assert result["expected_impact"].fail_to_pass == ["assertB"]


class TestVerificationResult:
    """Test VerificationResult dataclass with new structure."""

    def test_create_verification_result(self):
        """Test creating VerificationResult with new fields."""
        result = VerificationResult(
            syntax="OK",
            satisfied_predicates=["baseline", "R1", "R2"],
            unsatisfied_predicates=["R3"],
            counterexamples=["assertA"],
            no_counterexample=["assertB", "assertC"]
        )

        assert result.syntax == "OK"
        assert len(result.satisfied_predicates) == 3
        assert len(result.unsatisfied_predicates) == 1
        assert len(result.counterexamples) == 1
        assert len(result.no_counterexample) == 2

    def test_to_dict(self):
        """Test VerificationResult serialization."""
        result = VerificationResult(
            syntax="Error",
            satisfied_predicates=["baseline"],
            unsatisfied_predicates=[],
            counterexamples=[],
            no_counterexample=[]
        )

        data = result.to_dict()

        assert data["syntax"] == "Error"
        assert data["satisfied_predicates"] == ["baseline"]
        assert isinstance(data, dict)

    def test_from_dict(self):
        """Test VerificationResult deserialization."""
        data = {
            "syntax": "OK",
            "satisfied_predicates": ["R1", "R2"],
            "unsatisfied_predicates": [],
            "counterexamples": ["assertA"],
            "no_counterexample": ["assertB"]
        }

        result = VerificationResult.from_dict(data)

        assert result.syntax == "OK"
        assert result.satisfied_predicates == ["R1", "R2"]
        assert result.counterexamples == ["assertA"]

    def test_empty_lists(self):
        """Test VerificationResult with empty lists."""
        result = VerificationResult(
            syntax="Pending",
            satisfied_predicates=[],
            unsatisfied_predicates=[],
            counterexamples=[],
            no_counterexample=[]
        )

        assert result.satisfied_predicates == []
        assert result.unsatisfied_predicates == []


class TestRegressionLogFormatting:
    """Test RegressionLog formatting functions."""

    def test_format_for_prompt_single_entry(self, tmp_path):
        """Test formatting a single regression log entry."""
        log_file = tmp_path / "test_regression.json"
        regression_log = RegressionLog(log_path=log_file)

        entry = RegressionLogEntry(
            iteration_id=1,
            model_file_location="/path/to/model.als",
            fix_intent="Fix syntax error",
            source_ref="Initial creation",
            current_result=VerificationResult(
                syntax="OK",
                satisfied_predicates=["baseline"],
                unsatisfied_predicates=[],
                counterexamples=[],
                no_counterexample=["assertA"]
            ),
            previous_result=None,
            updated_lines="+ sig User {}",
            expected_impact=ImpactAnalysis()
        )

        regression_log.add_entry(entry)
        formatted = regression_log.format_for_prompt(count=1)

        assert "Iteration 1" in formatted
        assert "Fix syntax error" in formatted
        assert "Initial creation" in formatted
        assert "baseline" in formatted

    def test_format_for_prompt_empty(self, tmp_path):
        """Test formatting when no entries exist."""
        log_file = tmp_path / "empty_regression.json"
        regression_log = RegressionLog(log_path=log_file)

        formatted = regression_log.format_for_prompt()

        assert "No regression log entries available" in formatted

    def test_format_for_prompt_with_impact(self, tmp_path):
        """Test formatting with actual impact."""
        log_file = tmp_path / "test_regression.json"
        regression_log = RegressionLog(log_path=log_file)

        impact = ImpactAnalysis(
            unsat_to_sat=["R1"],
            sat_to_unsat=[],
            fail_to_pass=["assertA"],
            pass_to_fail=[]
        )

        entry = RegressionLogEntry(
            iteration_id=2,
            model_file_location="/path/to/model.als",
            fix_intent="Make R1 satisfiable",
            source_ref="Evaluator feedback",
            current_result=VerificationResult(
                syntax="OK",
                satisfied_predicates=["baseline", "R1"],
                unsatisfied_predicates=[],
                counterexamples=[],
                no_counterexample=["assertA"]
            ),
            previous_result=VerificationResult(
                syntax="OK",
                satisfied_predicates=["baseline"],
                unsatisfied_predicates=["R1"],
                counterexamples=["assertA"],
                no_counterexample=[]
            ),
            updated_lines="+ fact { ... }",
            expected_impact=impact,
            actual_impact=impact,
            outcome_classification="expected_improvement"
        )

        regression_log.add_entry(entry)
        formatted = regression_log.format_for_prompt(count=1)

        assert "UNSAT→SAT: R1" in formatted
        assert "FAIL→PASS: assertA" in formatted
        assert "expected_improvement" in formatted

    def test_compute_diff(self, tmp_path):
        """Test computing diff between models."""
        log_file = tmp_path / "test_regression.json"
        regression_log = RegressionLog(log_path=log_file)

        current_model = """sig User {}
sig Resource {}
fact { all u: User | some r: Resource }"""

        previous_model = """sig User {}
sig Resource {}"""

        diff = regression_log.compute_diff(current_model, previous_model)

        assert "+ fact { all u: User | some r: Resource }" in diff or "fact" in diff


class TestImpactAnalysis:
    """Test ImpactAnalysis dataclass."""

    def test_empty_impact(self):
        """Test creating empty impact analysis."""
        impact = ImpactAnalysis()

        assert impact.sat_to_unsat == []
        assert impact.unsat_to_sat == []
        assert impact.pass_to_fail == []
        assert impact.fail_to_pass == []

    def test_impact_with_values(self):
        """Test creating impact analysis with values."""
        impact = ImpactAnalysis(
            sat_to_unsat=["R1"],
            unsat_to_sat=["R2", "R3"],
            pass_to_fail=["assertA"],
            fail_to_pass=[]
        )

        assert len(impact.sat_to_unsat) == 1
        assert len(impact.unsat_to_sat) == 2
        assert impact.pass_to_fail == ["assertA"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
