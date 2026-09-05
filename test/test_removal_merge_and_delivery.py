"""
Five wiring fixes found by auditing the localization reorder (A-E).

A: staged removals merge instead of overwriting each other.
B: the measurement is taken before requirement probation reads it.
C: unowned blocking facts reach the interpretation, not only the repair step.
D: guard-railed-away plan items are recorded even when the plan is emptied.
E: the RE's execution report is rendered beside the measured verdicts.

Run: python test/test_removal_merge_and_delivery.py   (from the repo root)
"""

import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.workflow import AutoREWorkflow
from src.utils.regression_log import (
    ImpactAnalysis,
    RegressionLogEntry,
    VerificationResult,
)
from src.utils.repair_plateau_detector import (
    build_stale_construct_removal,
    merge_stale_removals,
)


def _removal(iteration, names, kind="fact", reason="orphan"):
    return build_stale_construct_removal(
        current_iteration=iteration,
        audit={"orphan": {n: reason for n in names}, "dead": [],
               "kinds": {n: kind for n in names}},
        closure={"remove": list(names), "cascaded": [], "blocked": {}},
    )


# ------------------------------------------------------------------ A #

def test_two_removals_merge_into_one():
    """
    The failure: iteration 68 retires a spent probe in step 4; step 7 stages the
    constructs of a requirement the user removed. Assignment dropped the probe,
    and nothing retries it - retirement only fires when the PREVIOUS entry was
    diagnostic, which iteration 69's is not.
    """
    probes = _removal(68, ["probe1_ScenarioMultiEmgA"], kind="pred",
                      reason="spent diagnostic probe")
    req = _removal(68, ["R4Pred", "R4Helper"])

    merged = merge_stale_removals(68, probes, req)

    assert sorted(merged["remove_targets"]) == [
        "R4Helper", "R4Pred", "probe1_ScenarioMultiEmgA"
    ]
    for name in ("probe1_ScenarioMultiEmgA", "R4Pred", "R4Helper"):
        assert name in merged["directive"], name
    # each construct still says why it is going
    assert "spent diagnostic probe" in merged["directive"]
    print("PASS test_two_removals_merge_into_one")


def test_merging_with_nothing_returns_the_other():
    req = _removal(68, ["R4Pred"])
    assert merge_stale_removals(68, None, req) is req
    assert merge_stale_removals(68, req, None) is req
    assert merge_stale_removals(68, {"remove_targets": []}, req) is req
    print("PASS test_merging_with_nothing_returns_the_other")


def test_the_workflow_merges_rather_than_replaces():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.logger = Mock()
    wf.context = Mock()
    wf.context.iteration.current = 68
    wf.context.pending_stale_removal = None

    wf._merge_pending_removal(_removal(68, ["probe1_X"], kind="pred"))
    wf._merge_pending_removal(_removal(68, ["R4Pred"]))

    staged = wf.context.pending_stale_removal
    assert sorted(staged["remove_targets"]) == ["R4Pred", "probe1_X"]
    print("PASS test_the_workflow_merges_rather_than_replaces")


# ------------------------------------------------------------------ B #

def test_the_measurement_precedes_probation():
    """
    Probation asks whether a provisional requirement's construct is implicated.
    Reading a measurement taken on the PREVIOUS model marked R6 implicated by a
    fact the RE had already deleted, costing it a clean iteration it had earned.
    """
    source = Path("src/workflow.py").read_text()
    prepare = source.index("diagnosis_text = self._prepare_semantic_escalation(")
    probation = source.index("self._advance_requirement_probation(entry)")
    interpret = source.index("interpretation = await self.interpret_results.run(")

    assert prepare < probation < interpret
    print("PASS test_the_measurement_precedes_probation")


# ------------------------------------------------------------------ C #

def test_unowned_blockers_reach_the_interpretation():
    prompt = Path("prompts/Evaluator_prompt.txt").read_text()
    section = prompt[prompt.index("[SECTION: InterpretResults]"):]
    section = section[:section.index("\n[SECTION:", 1)]

    assert "UNOWNED BLOCKING FACTS" in section
    assert "PROVEN to block" in section
    # and the stale claim that the localization runs after the interpretation is gone
    source = Path("src/workflow.py").read_text()
    assert "the localization runs AFTER InterpretResults" not in source
    print("PASS test_unowned_blockers_reach_the_interpretation")


# ---------------------------------------------------------------- D + E #

DROPPED = ("=== DIAGNOSTIC ITEMS NOT RUN (already measured) ===\n"
           "- Construct: EmergencyUnique\n"
           "  Not run: fact-level hypothesis\n"
           "  Measured: deterministic localizer: proven to block Scenario_MultiEmg_A")

REPORT = ("- Experiment: AdminEligibleForEmergencyTrigger\n"
          "- Probe: none\n- Executed: no\n"
          "- Reason: cannot be expressed as an additive probe without altering the fact")


def _entry(iteration, kind="repair", dropped=None, report=None, plan=None):
    return RegressionLogEntry(
        iteration_id=iteration,
        model_file_location=f"AlloyModel__{iteration}.als",
        fix_intent="Narrow the guard",
        source_ref="ref",
        current_result=VerificationResult(syntax="OK", satisfied_predicates=[],
                                          unsatisfied_predicates=[], counterexamples=[],
                                          no_counterexample=[]),
        previous_result=None,
        updated_lines="",
        expected_impact=ImpactAnalysis(),
        kind=kind,
        diagnostic_dropped=dropped,
        diagnostic_execution=report,
        diagnostic_plan=plan,
    )


def _render(entry):
    from src.utils.regression_log import RegressionLog
    log = RegressionLog.__new__(RegressionLog)
    log.entries = [entry]
    return log.format_for_prompt(count=1)


def test_dropped_items_are_recorded_on_a_fallback_iteration():
    """
    The plan held one fact-level item; the guard rails dropped it and the
    iteration became an ordinary repair. No RE report exists on that path, so
    without this the measured answer reaches nobody and the Evaluator proposes
    the identical experiment again.
    """
    out = _render(_entry(68, kind="repair", dropped=DROPPED))

    assert "DIAGNOSTIC ITEMS NOT RUN" in out
    assert "proven to block Scenario_MultiEmg_A" in out
    print("PASS test_dropped_items_are_recorded_on_a_fallback_iteration")


def test_the_execution_report_is_rendered():
    """The verdict table can say an item did not run; only the RE says why."""
    out = _render(_entry(68, kind="diagnostic", report=REPORT))

    assert "Diagnostic execution report (from the RE)" in out
    assert "cannot be expressed as an additive probe" in out
    print("PASS test_the_execution_report_is_rendered")


def test_an_ordinary_entry_renders_neither():
    out = _render(_entry(68))
    assert "DIAGNOSTIC ITEMS NOT RUN" not in out
    assert "Diagnostic execution report" not in out
    print("PASS test_an_ordinary_entry_renders_neither")


def test_the_new_field_round_trips():
    entry = _entry(68, kind="diagnostic", dropped=DROPPED, report=REPORT)
    restored = RegressionLogEntry.from_dict(entry.to_dict())
    assert restored.diagnostic_dropped == DROPPED
    assert restored.diagnostic_execution == REPORT
    legacy = entry.to_dict()
    legacy.pop("diagnostic_dropped")
    assert RegressionLogEntry.from_dict(legacy).diagnostic_dropped is None
    print("PASS test_the_new_field_round_trips")


if __name__ == "__main__":
    test_two_removals_merge_into_one()
    test_merging_with_nothing_returns_the_other()
    test_the_workflow_merges_rather_than_replaces()
    test_the_measurement_precedes_probation()
    test_unowned_blockers_reach_the_interpretation()
    test_dropped_items_are_recorded_on_a_fallback_iteration()
    test_the_execution_report_is_rendered()
    test_an_ordinary_entry_renders_neither()
    test_the_new_field_round_trips()
    print("\nAll removal-merge and delivery tests passed.")
