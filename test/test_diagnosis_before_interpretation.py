"""
The deterministic diagnosis runs BEFORE the interpretation is written.

It used to run afterwards, which left the causal analysis guessing at something
the Analyzer had already been asked. Everything the diagnosis needs exists by the
time the analyzer results are in, so it is measured first and handed to the
interpretation; the escalation is then reused downstream rather than re-measured,
because each diagnosis costs a scope sweep plus up to a dozen localization runs.

Run: python test/test_diagnosis_before_interpretation.py   (from the repo root)
"""

import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.workflow import AutoREWorkflow
from src.utils.prompt_manager import PromptManager


MEASURED = (
    "  - 'Scenario_MultiEmg_A' SCOPE VERDICT: still UNSAT at enlarged bounds "
    "(run Scenario_MultiEmg_A for 12) -> genuine over-constraint.\n"
    "  - 'Scenario_MultiEmg_A' BLOCKING FACTS: EmergencyUnique"
)


def _make_workflow(escalated=True):
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.logger = Mock()
    wf.context = Mock()
    wf.context.iteration.current = 68
    wf.context.regression_log.entries = []
    wf.context.pending_semantic_escalation = None

    def fake_diagnostics(escalation, persistence, model_text):
        escalation['directive'] += "\n" + MEASURED
        escalation['diagnostics'] = {"Scenario_MultiEmg_A": {}}

    wf._run_semantic_diagnostics = Mock(side_effect=fake_diagnostics)
    return wf


class _Entry:
    def __init__(self, escalated):
        self.semantic_issue_persistence = {
            "issues": [{"name": "Scenario_MultiEmg_A", "kind": "unsat_predicate",
                        "consecutive": 3, "total": 3, "iterations": [65, 66, 67],
                        "first_seen": 65}],
            "escalated_issues": ["Scenario_MultiEmg_A"] if escalated else [],
            "escalation_required": escalated,
        }


def test_the_measurement_is_taken_before_the_interpretation():
    wf = _make_workflow()

    diagnosis = wf._prepare_semantic_escalation(_Entry(True), "pred p {}")

    wf._run_semantic_diagnostics.assert_called_once()
    # What reaches the interpretation is the MEASURED part only - not the
    # persistence bookkeeping it already has, and not the binding rules, which
    # belong to the feedback step rather than to a diagnosis.
    assert "SCOPE VERDICT" in diagnosis
    assert "BLOCKING FACTS: EmergencyUnique" in diagnosis
    assert "STRATEGY:" not in diagnosis
    assert "ESCALATION LEVEL" not in diagnosis
    print("PASS test_the_measurement_is_taken_before_the_interpretation")


def test_the_escalation_is_carried_forward_for_reuse():
    """Re-running it downstream would double the Alloy cost and could answer
    differently than the answer the interpretation was formed against."""
    wf = _make_workflow()
    wf._prepare_semantic_escalation(_Entry(True), "pred p {}")

    carried = wf.context.pending_semantic_escalation
    assert carried["iteration"] == 68
    assert carried["escalation"]["escalated_issues"] == ["Scenario_MultiEmg_A"]
    assert MEASURED in carried["escalation"]["directive"]
    print("PASS test_the_escalation_is_carried_forward_for_reuse")


def test_nothing_escalated_means_nothing_measured():
    wf = _make_workflow()

    diagnosis = wf._prepare_semantic_escalation(_Entry(False), "pred p {}")

    assert diagnosis == ""
    wf._run_semantic_diagnostics.assert_not_called()
    assert wf.context.pending_semantic_escalation is None
    print("PASS test_nothing_escalated_means_nothing_measured")


def test_preparation_never_breaks_the_iteration():
    """Best-effort, like the diagnosis itself: a failure costs the evidence, not the run."""
    wf = _make_workflow()
    wf.context.regression_log.entries = None  # provokes a failure inside

    def boom(*a, **k):
        raise RuntimeError("alloy unavailable")

    wf._run_semantic_diagnostics = Mock(side_effect=boom)
    assert wf._prepare_semantic_escalation(_Entry(True), "pred p {}") == ""
    assert wf.context.pending_semantic_escalation is None
    print("PASS test_preparation_never_breaks_the_iteration")


def test_the_interpretation_prompt_states_how_to_use_the_measurement():
    pm = PromptManager()
    section = pm.get_section("Evaluator", "InterpretResults")

    assert "{{deterministic_diagnosis}}" in section
    # The rules that make a measurement binding rather than decorative
    assert "never contradict it" in section
    assert "bounded-search artifact" in section
    assert "PROVEN to block" in section
    assert "internal_contradiction" in section
    print("PASS test_the_interpretation_prompt_states_how_to_use_the_measurement")


def test_the_feedback_prompt_no_longer_calls_them_independent():
    prompt = Path("prompts/Evaluator_prompt.txt").read_text()

    assert "measured BEFORE the interpretation was written" in prompt
    assert "not independent opinions to weigh" in prompt
    # The stale two-key phrasing is gone from the model-repair rulebook
    assert "the evidence does not support it from both sources" not in prompt
    assert "when either the result interpretation or the deterministic diagnosis" not in prompt
    print("PASS test_the_feedback_prompt_no_longer_calls_them_independent")


if __name__ == "__main__":
    test_the_measurement_is_taken_before_the_interpretation()
    test_the_escalation_is_carried_forward_for_reuse()
    test_nothing_escalated_means_nothing_measured()
    test_preparation_never_breaks_the_iteration()
    test_the_interpretation_prompt_states_how_to_use_the_measurement()
    test_the_feedback_prompt_no_longer_calls_them_independent()
    print("\nAll diagnosis-ordering tests passed.")
