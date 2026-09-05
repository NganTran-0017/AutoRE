"""
Unit tests for RE Mode 3, Phase 4 (mark the entry, un-poison the ladder) and
Phase 5 (readback and retirement), plus TODO T1/T2/T4.

The invariant under test: a diagnostic iteration is evidence, so nothing in the
system may read it as a failed repair - and a probe that never ran must never be
mistaken for one that ran and returned UNSAT.

Run: python test/test_diagnostic_readback.py   (from the repo root)
"""

import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.regression_log import (
    ImpactAnalysis,
    RegressionLogEntry,
    VerificationResult,
    derive_outcome_classification,
    format_probe_verdicts,
)
from src.utils.repair_plateau_detector import (
    build_probe_verdict_block,
    collect_failed_fixes,
    read_back_probe_verdicts,
)
from src.utils.semantic_diagnostics import is_probe_name
from src.utils.semantic_issue_tracker import SemanticIssueTracker


PLAN = [
    {"construct": "CredentialUpdatePerfomedSeq",
     "hypothesis": "the flag reset timing blocks the scenario",
     "level": "predicate",
     "reading": "SAT => timing is the blocker; UNSAT => it is exonerated"},
    {"construct": "AdminEligibleForEmergencyTrigger",
     "hypothesis": "eligibility must persist across the whole trace",
     "level": "predicate",
     "reading": "SAT => persistence is the blocker; UNSAT => it is not"},
]


def _result(syntax="OK", sat=(), unsat=(), ce=()):
    return VerificationResult(
        syntax=syntax,
        satisfied_predicates=list(sat),
        unsatisfied_predicates=list(unsat),
        counterexamples=list(ce),
        no_counterexample=[],
    )


def _entry(iteration, kind="repair", fix_intent="Narrow the guard", result=None, plan=None):
    return RegressionLogEntry(
        iteration_id=iteration,
        model_file_location=f"AlloyModel__{iteration}.als",
        fix_intent=fix_intent,
        source_ref="ref",
        current_result=result or _result(),
        previous_result=None,
        updated_lines="",
        expected_impact=ImpactAnalysis(),
        kind=kind,
        diagnostic_plan=plan,
    )


# --------------------------------------------------------- probe naming #

def test_probe_names_are_recognised():
    assert is_probe_name("probe1_ScenarioMultiEmgA")
    assert is_probe_name("probe12_X")
    for other in ("probe_X", "probeX_1", "Scenario_MultiEmg_A", "R1R2", "", None):
        assert not is_probe_name(other), other
    print("PASS test_probe_names_are_recognised")


# ------------------------------------- Phase 4: the ladder is un-poisoned #

def test_a_diagnostic_entry_is_not_an_attempted_fix():
    """
    Consequence 1. Listing the experiment here forbids the RE from ever applying
    the repair that experiment was run to validate.
    """
    entries = [
        _entry(66, fix_intent="Relax the flag reset guard"),
        _entry(67, kind="diagnostic",
               fix_intent="DIAGNOSTIC EXECUTION: probe1_X executed yes"),
        _entry(68, fix_intent="Widen the eligibility window"),
    ]
    fixes = collect_failed_fixes([66, 67], entries)

    assert any("Widen the eligibility window" in f for f in fixes)
    assert not any("DIAGNOSTIC EXECUTION" in f for f in fixes)
    print("PASS test_a_diagnostic_entry_is_not_an_attempted_fix")


def test_a_diagnostic_iteration_does_not_advance_persistence():
    tracker = SemanticIssueTracker()
    prior = [_entry(i, result=_result(unsat=["R1R2"])) for i in (64, 65, 66)]

    repair = tracker.run(67, _result(unsat=["R1R2"]), prior)
    assert repair["issues"][0]["consecutive"] == 4

    diagnostic = tracker.run(67, _result(unsat=["R1R2"]), prior, current_is_diagnostic=True)
    assert diagnostic["issues"] == []
    assert diagnostic["escalation_required"] is False
    print("PASS test_a_diagnostic_iteration_does_not_advance_persistence")


def test_a_diagnostic_iteration_in_the_window_is_not_measurable():
    """
    The streak must survive a diagnostic detour without being *extended* by it:
    the measurement is neither progress nor failure.
    """
    tracker = SemanticIssueTracker()
    entries = [
        _entry(64, result=_result(unsat=["R1R2"])),
        _entry(65, result=_result(unsat=["R1R2"])),
        _entry(66, kind="diagnostic", result=_result(unsat=["R1R2", "probe1_X"])),
    ]
    out = tracker.run(67, _result(unsat=["R1R2"]), entries)

    assert out["issues"][0]["consecutive"] == 3  # 64, 65, current - not the probe iteration
    print("PASS test_a_diagnostic_iteration_in_the_window_is_not_measurable")


def test_probe_unsat_is_not_a_tracked_issue():
    """T2: a probe UNSAT is a completed experiment, not a stuck requirement."""
    tracker = SemanticIssueTracker()
    out = tracker.run(67, _result(unsat=["probe1_X", "probe2_Y"]), [])

    assert out["issues"] == []
    print("PASS test_probe_unsat_is_not_a_tracked_issue")


def test_outcome_classification_says_nothing_was_attempted():
    out = derive_outcome_classification(
        has_syntax_errors=False, resolved_target_issue=None,
        has_previous_iteration=True, current_issue="unsat: R1R2", kind="diagnostic",
    )
    assert out.startswith("diagnostic_measurement:")
    assert "no fix attempted" in out

    # A repair iteration is untouched
    repair = derive_outcome_classification(
        has_syntax_errors=False, resolved_target_issue=False, has_previous_iteration=True,
    )
    assert repair.startswith("no_improvement:")
    print("PASS test_outcome_classification_says_nothing_was_attempted")


# --------------------------------------------------- Phase 5: the readback #

def test_verdicts_join_back_onto_the_plan():
    readback = read_back_probe_verdicts(
        PLAN,
        satisfied=["probe1_ScenarioMultiEmgA", "R1"],
        unsatisfied=["probe2_ScenarioMultiEmgA", "Scenario_MultiEmg_A"],
    )
    statuses = [r["status"] for r in readback["results"]]

    assert statuses == ["confirmed", "refuted"]
    assert readback["probes"] == ["probe1_ScenarioMultiEmgA", "probe2_ScenarioMultiEmgA"]
    assert readback["not_run"] == []
    assert readback["all_refuted"] is False
    print("PASS test_verdicts_join_back_onto_the_plan")


def test_a_probe_that_never_ran_is_not_refuted():
    """
    The failure this whole phase exists to prevent. The RE writes probe 1 only;
    it returns UNSAT. Reading the missing probe 2 as UNSAT too would satisfy the
    plan's own "both refuted => requirement-level defect" and produce a
    requirement-level conclusion from one experiment.
    """
    readback = read_back_probe_verdicts(
        PLAN, satisfied=[], unsatisfied=["probe1_ScenarioMultiEmgA"],
    )

    assert [r["status"] for r in readback["results"]] == ["refuted", "not_run"]
    assert readback["not_run"] == ["AdminEligibleForEmergencyTrigger"]
    assert readback["all_refuted"] is False  # NOT all refuted - one never ran

    block = build_probe_verdict_block(readback)
    assert "NOT RUN - no probe reported" in block
    assert "UNMEASURED, not refuted" in block
    # The requirement-level note must not fire (the word also appears inside the
    # declared reading, so pin the note's own wording)
    assert "every hypothesis was refuted" not in block
    assert "requirement level" not in block
    print("PASS test_a_probe_that_never_ran_is_not_refuted")


def test_all_refuted_is_reported_as_a_requirement_level_signal():
    readback = read_back_probe_verdicts(
        PLAN, unsatisfied=["probe1_A", "probe2_B"],
    )
    assert readback["all_refuted"] is True

    block = build_probe_verdict_block(readback)
    assert "every hypothesis was refuted" in block
    assert "requirement level" in block
    print("PASS test_all_refuted_is_reported_as_a_requirement_level_signal")


def test_the_block_carries_hypothesis_and_declared_reading():
    """T4: bare SAT/UNSAT is not a measurement without what it was declared to mean."""
    block = build_probe_verdict_block(
        read_back_probe_verdicts(PLAN, satisfied=["probe1_A"], unsatisfied=["probe2_B"])
    )
    assert "the flag reset timing blocks the scenario" in block
    assert "SAT => timing is the blocker" in block
    assert "CONFIRMED (SAT)" in block and "REFUTED (UNSAT)" in block
    print("PASS test_the_block_carries_hypothesis_and_declared_reading")


def test_an_empty_plan_renders_nothing():
    assert build_probe_verdict_block(read_back_probe_verdicts([], satisfied=["probe1_A"])) == ""
    assert build_probe_verdict_block({}) == ""
    print("PASS test_an_empty_plan_renders_nothing")


def test_the_entry_renders_its_own_verdicts():
    entry = _entry(
        67, kind="diagnostic", plan=PLAN,
        result=_result(sat=["probe1_A"], unsat=["probe2_B", "Scenario_MultiEmg_A"]),
    )
    out = format_probe_verdicts(entry)

    assert "CONFIRMED (SAT)" in out and "REFUTED (UNSAT)" in out
    # A repair entry, or a diagnostic one with no manifest, renders nothing
    assert format_probe_verdicts(_entry(67)) == ""
    assert format_probe_verdicts(_entry(67, kind="diagnostic")) == ""
    print("PASS test_the_entry_renders_its_own_verdicts")


# -------------------------------------------- Phase 5: rollback + control #

BASELINE = """pred Scenario_MultiEmg_A { some State }
fact EmergencyUnique { one s: State | s.emg }
"""

MODEL_WITH_PROBES = BASELINE + """pred probe1_ScenarioMultiEmgA { some State } //@req none:probe
run probe1_ScenarioMultiEmgA for 6
"""


def _make_workflow(model, baseline=BASELINE):
    from src.workflow import AutoREWorkflow

    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.logger = Mock()
    wf.context = Mock()
    wf.context.iteration.current = 68
    wf.context.artifacts.get_latest_alloy_model.return_value = model
    wf.context.artifacts.alloy_models = {67: baseline} if baseline else {}
    wf.context.file_manager = Mock()
    return wf


def test_the_model_rolls_back_and_the_probes_are_kept_as_evidence():
    """
    The probes are spent once read. Rather than asking the RE to prune them, the
    lineage reverts - so an illegal edit cannot survive and no pruning has to
    succeed. Their source is kept because the declared reading is only a claim
    about what a probe altered.
    """
    wf = _make_workflow(MODEL_WITH_PROBES)
    entry = _entry(68, kind="diagnostic", plan=PLAN)

    wf._finalize_diagnostic_model(entry)

    wf.context.artifacts.store_alloy_model.assert_called_once_with(68, BASELINE)
    wf.context.file_manager.save_alloy_model.assert_called_once_with(BASELINE, 68)
    wf.context.file_manager.archive_diagnostic_model.assert_called_once()
    assert "probe1_ScenarioMultiEmgA" in entry.diagnostic_probe_bodies
    assert "Control: UNMODIFIED" in entry.diagnostic_control
    print("PASS test_the_model_rolls_back_and_the_probes_are_kept_as_evidence")


def test_an_edited_control_voids_the_verdicts():
    """
    Rollback protects the MODEL; it cannot protect the EVIDENCE, because the
    analyzer already ran on the edited model and the verdict is already recorded.
    """
    edited = MODEL_WITH_PROBES.replace("one s: State | s.emg", "some s: State | s.emg")
    wf = _make_workflow(edited)
    entry = _entry(68, kind="diagnostic", plan=PLAN)

    wf._finalize_diagnostic_model(entry)

    assert "Control: MODIFIED" in entry.diagnostic_control
    assert "EmergencyUnique" in entry.diagnostic_control
    assert "UNANSWERED" in entry.diagnostic_control
    # still rolled back - the edit does not survive either
    wf.context.artifacts.store_alloy_model.assert_called_once_with(68, BASELINE)
    print("PASS test_an_edited_control_voids_the_verdicts")


def test_rollback_leaves_ordinary_iterations_alone():
    wf = _make_workflow(MODEL_WITH_PROBES)
    wf._finalize_diagnostic_model(_entry(68))  # kind="repair"
    wf.context.artifacts.store_alloy_model.assert_not_called()

    # With no baseline to revert to, the diagnostic model stays as the head
    # rather than the lineage being blanked.
    wf2 = _make_workflow(MODEL_WITH_PROBES, baseline=None)
    wf2._finalize_diagnostic_model(_entry(68, kind="diagnostic", plan=PLAN))
    wf2.context.artifacts.store_alloy_model.assert_not_called()
    print("PASS test_rollback_leaves_ordinary_iterations_alone")


def test_the_verdict_block_carries_the_control_and_the_probe_source():
    entry = _entry(68, kind="diagnostic", plan=PLAN, result=_result(sat=["probe1_A"]))
    entry.diagnostic_control = "Control: UNMODIFIED (identical outside the probes)"
    entry.diagnostic_probe_bodies = {"probe1_A": "pred probe1_A { some State }"}

    block = format_probe_verdicts(entry)

    assert "Control: UNMODIFIED" in block
    assert "Probe source (as executed):" in block
    assert "pred probe1_A { some State }" in block
    print("PASS test_the_verdict_block_carries_the_control_and_the_probe_source")


# ------------------------------------------------------------ persistence #

def test_the_new_fields_round_trip():
    entry = _entry(67, kind="diagnostic", plan=PLAN, result=_result(unsat=["probe1_A"]))
    entry.diagnostic_execution = "- Experiment: X\n- Executed: yes"

    restored = RegressionLogEntry.from_dict(entry.to_dict())

    assert restored.kind == "diagnostic"
    assert restored.diagnostic_plan == PLAN
    assert restored.diagnostic_execution.startswith("- Experiment:")
    # An entry written before Mode 3 existed defaults to a repair
    legacy = entry.to_dict()
    for field in ("kind", "diagnostic_plan", "diagnostic_execution"):
        legacy.pop(field)
    assert RegressionLogEntry.from_dict(legacy).kind == "repair"
    print("PASS test_the_new_fields_round_trip")


if __name__ == "__main__":
    test_probe_names_are_recognised()
    test_a_diagnostic_entry_is_not_an_attempted_fix()
    test_a_diagnostic_iteration_does_not_advance_persistence()
    test_a_diagnostic_iteration_in_the_window_is_not_measurable()
    test_probe_unsat_is_not_a_tracked_issue()
    test_outcome_classification_says_nothing_was_attempted()
    test_verdicts_join_back_onto_the_plan()
    test_a_probe_that_never_ran_is_not_refuted()
    test_all_refuted_is_reported_as_a_requirement_level_signal()
    test_the_block_carries_hypothesis_and_declared_reading()
    test_an_empty_plan_renders_nothing()
    test_the_entry_renders_its_own_verdicts()
    test_the_model_rolls_back_and_the_probes_are_kept_as_evidence()
    test_an_edited_control_voids_the_verdicts()
    test_rollback_leaves_ordinary_iterations_alone()
    test_the_verdict_block_carries_the_control_and_the_probe_source()
    test_the_new_fields_round_trip()
    print("\nAll Phase 4/5 diagnostic readback tests passed.")
