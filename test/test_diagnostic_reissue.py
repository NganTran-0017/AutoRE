"""
Unit tests for RE Mode 3, TODO T1's second half - an experiment that was ordered
and produced no probe is asked for exactly once more, then abandoned on the record.

`not_run` is the status that answers nothing: the readback refuses to read it as
refuted, so without a retry the hypothesis stays unmeasured and the plan quietly
shrinks. The bound matters as much as the retry - two failures to express the same
hypothesis say something about the hypothesis, not about the RE's diligence.

Run: python test/test_diagnostic_reissue.py   (from the repo root)
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
    DIAGNOSTIC_DECISION,
    RERUN_DIAGNOSTIC_PROBES,
    build_diagnostic_reissue,
)


PLAN = [
    {"construct": "CredentialUpdatePerfomedSeq",
     "hypothesis": "the flag reset timing blocks the scenario",
     "level": "predicate",
     "reading": "SAT => timing is the blocker"},
    {"construct": "AdminEligibleForEmergencyTrigger",
     "hypothesis": "eligibility must persist across the trace",
     "level": "predicate",
     "reading": "SAT => persistence is the blocker"},
]


def _entry(kind="diagnostic", plan=PLAN, sat=(), unsat=()):
    return RegressionLogEntry(
        iteration_id=68,
        model_file_location="AlloyModel__68.als",
        fix_intent="DIAGNOSTIC EXECUTION: ...",
        source_ref="plan",
        current_result=VerificationResult(
            syntax="OK",
            satisfied_predicates=list(sat),
            unsatisfied_predicates=list(unsat),
            counterexamples=[],
            no_counterexample=[],
        ),
        previous_result=None,
        updated_lines="",
        expected_impact=ImpactAnalysis(),
        kind=kind,
        diagnostic_plan=plan,
    )


def _make_workflow():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.logger = Mock()
    wf.context = Mock()
    wf.context.iteration.current = 69
    wf.context.pending_diagnostic_reissue = None
    return wf


# ------------------------------------------------------------- the builder #

def test_the_directive_names_the_unrun_experiment():
    out = build_diagnostic_reissue(69, items=[{**PLAN[1], "attempt": 1}])

    assert out["strategy"] == RERUN_DIAGNOSTIC_PROBES
    assert out["rerun_targets"] == ["AdminEligibleForEmergencyTrigger"]
    d = out["directive"]
    assert "eligibility must persist across the trace" in d
    assert "SAT => persistence is the blocker" in d
    # It must say WHY it is here - an unrun experiment is not a refuted one
    assert "measured NOTHING" in d
    # And how to number it, since it arrives outside the DIAGNOSTIC PLAN section
    assert "CONTINUING the plan's numbering" in d
    print("PASS test_the_directive_names_the_unrun_experiment")


def test_a_second_ask_is_marked_as_a_repeat():
    out = build_diagnostic_reissue(69, items=[{**PLAN[0], "attempt": 2}])
    assert "already asked for once and produced no probe" in out["directive"]
    print("PASS test_a_second_ask_is_marked_as_a_repeat")


def test_abandoned_items_are_named_not_dropped():
    out = build_diagnostic_reissue(69, abandoned=[{**PLAN[0], "attempt": 2}])

    assert out["abandoned_targets"] == ["CredentialUpdatePerfomedSeq"]
    d = out["directive"]
    assert "NOT RETRIED" in d
    assert "neither confirmed nor refuted" in d
    print("PASS test_abandoned_items_are_named_not_dropped")


def test_nothing_to_say_renders_nothing():
    assert build_diagnostic_reissue(69)["directive"] == ""
    print("PASS test_nothing_to_say_renders_nothing")


# ------------------------------------------------------------- staging #

def test_an_unrun_item_is_staged_for_retry():
    wf = _make_workflow()
    # probe1 ran, probe2 never appeared
    wf._stage_diagnostic_reissue(_entry(sat=["probe1_X"]))

    pending = wf.context.pending_diagnostic_reissue
    assert [i["construct"] for i in pending["items"]] == ["AdminEligibleForEmergencyTrigger"]
    assert pending["attempts"]["AdminEligibleForEmergencyTrigger"] == 1
    assert "RERUN_DIAGNOSTIC_PROBES" in pending["directive"]
    print("PASS test_an_unrun_item_is_staged_for_retry")


def test_a_refuted_item_is_not_retried():
    """UNSAT is an answer. Only silence is re-asked."""
    wf = _make_workflow()
    wf._stage_diagnostic_reissue(_entry(sat=["probe1_X"], unsat=["probe2_Y"]))
    assert wf.context.pending_diagnostic_reissue is None
    print("PASS test_a_refuted_item_is_not_retried")


def test_a_second_miss_abandons_instead_of_looping():
    wf = _make_workflow()
    wf.context.pending_diagnostic_reissue = {
        "items": [{**PLAN[1], "attempt": 1}],
        "attempts": {"AdminEligibleForEmergencyTrigger": 1},
        "directive": "",
    }

    wf._stage_diagnostic_reissue(_entry(sat=["probe1_X"]))

    # Not re-staged - the loop is bounded
    assert wf.context.pending_diagnostic_reissue is None
    logged = " ".join(str(c) for c in wf.logger.log.call_args_list)
    assert "left" in logged and "UNMEASURED" in logged
    assert "AdminEligibleForEmergencyTrigger" in logged
    print("PASS test_a_second_miss_abandons_instead_of_looping")


def test_staging_ignores_repair_iterations_and_missing_manifests():
    for entry in (_entry(kind="repair"), _entry(plan=None)):
        wf = _make_workflow()
        wf._stage_diagnostic_reissue(entry)
        assert wf.context.pending_diagnostic_reissue is None
    print("PASS test_staging_ignores_repair_iterations_and_missing_manifests")


# ------------------------------------------------------------- merging #

def _feedback(decision, constructs):
    plan = "".join(
        f"- Construct: {c}\n- Hypothesis: h\n- Level: predicate\n- Reading: SAT => x\n"
        for c in constructs
    )
    return (
        "=== NEXT ACTION DECISION ===\n"
        f"Decision: {decision}\n\n"
        "=== DIAGNOSTIC PLAN ===\n"
        f"{plan}"
        "=== REPAIR INSTRUCTIONS ===\nNone\n"
    )


MODEL = "pred NewHypothesis {}\npred AdminEligibleForEmergencyTrigger {}\n"


def test_the_retry_is_merged_into_the_next_plan():
    wf = _make_workflow()
    wf.context.pending_diagnostic_reissue = {
        "items": [{**PLAN[1], "attempt": 1}],
        "attempts": {"AdminEligibleForEmergencyTrigger": 1},
        "directive": "d",
    }

    signal = wf._evaluate_diagnostic_signal(
        _feedback(DIAGNOSTIC_DECISION, ["NewHypothesis"]), model_text=MODEL
    )

    # Appended AFTER the new plan, so probe numbering continues rather than shifts
    assert [i["construct"] for i in signal["items"]] == [
        "NewHypothesis", "AdminEligibleForEmergencyTrigger"
    ]
    assert "attempt" not in signal["items"][1]  # the manifest holds plan fields only
    print("PASS test_the_retry_is_merged_into_the_next_plan")


def test_a_retry_already_replanned_is_not_duplicated():
    wf = _make_workflow()
    wf.context.pending_diagnostic_reissue = {
        "items": [{**PLAN[1], "attempt": 1}],
        "attempts": {"AdminEligibleForEmergencyTrigger": 1},
        "directive": "d",
    }

    signal = wf._evaluate_diagnostic_signal(
        _feedback(DIAGNOSTIC_DECISION, ["AdminEligibleForEmergencyTrigger"]),
        model_text=MODEL,
    )

    assert [i["construct"] for i in signal["items"]] == ["AdminEligibleForEmergencyTrigger"]
    print("PASS test_a_retry_already_replanned_is_not_duplicated")


def test_a_fresh_decision_outranks_an_outstanding_retry():
    """
    The Evaluator saw NOT RUN and chose to move on. Carrying the retry past that
    would let a stale experiment survive a change of direction indefinitely.
    """
    wf = _make_workflow()
    wf.context.pending_diagnostic_reissue = {
        "items": [{**PLAN[1], "attempt": 1}],
        "attempts": {"AdminEligibleForEmergencyTrigger": 1},
        "directive": "d",
    }

    signal = wf._evaluate_diagnostic_signal(
        _feedback("refine/narrow fix", ["AdminEligibleForEmergencyTrigger"]),
        model_text=MODEL,
    )

    assert signal["diagnostic"] is False
    assert wf.context.pending_diagnostic_reissue is None
    logged = " ".join(str(c) for c in wf.logger.log.call_args_list)
    assert "outstanding re-issue dropped" in logged
    print("PASS test_a_fresh_decision_outranks_an_outstanding_retry")


# ------------------------------------- T6: a diagnostic entry that was lost #

MODEL_WITH_PROBES = (
    "pred Scenario_MultiEmg_A { some State }\n"
    "pred probe1_ScenarioMultiEmgA { some State } //@req none:probe\n"
    "run probe1_ScenarioMultiEmgA for 6\n"
)


def _placeholder():
    return RegressionLogEntry(
        iteration_id=68,
        model_file_location="AlloyModel__68.als",
        fix_intent="Model update",
        source_ref="RE Agent",
        current_result=VerificationResult(syntax="Pending"),
        previous_result=None,
        updated_lines="",
        expected_impact=ImpactAnalysis(),
    )


def test_probes_without_an_entry_are_recognised_as_diagnostic():
    """
    A crash between save_alloy_model and add_entry leaves probes on disk with no
    entry. The placeholder would call it a repair - so retirement never fires and
    the probes survive, while their verdicts read as ordinary predicate results.
    """
    wf = _make_workflow()
    wf.context.artifacts.get_latest_alloy_model.return_value = MODEL_WITH_PROBES
    entry = _placeholder()

    wf._recover_diagnostic_placeholder(entry)

    assert entry.kind == "diagnostic"          # retirement keys on this
    assert "probe1_ScenarioMultiEmgA" in entry.fix_intent
    # The plan is gone and must be said to be gone, not quietly absent
    assert "MANIFEST LOST" in entry.diagnostic_execution
    assert "must not be read as evidence" in entry.diagnostic_execution
    print("PASS test_probes_without_an_entry_are_recognised_as_diagnostic")


def test_an_ordinary_placeholder_is_untouched():
    wf = _make_workflow()
    wf.context.artifacts.get_latest_alloy_model.return_value = "pred R1 { some State }\n"
    entry = _placeholder()

    wf._recover_diagnostic_placeholder(entry)

    assert entry.kind == "repair"
    assert entry.fix_intent == "Model update"
    assert entry.diagnostic_execution is None
    print("PASS test_an_ordinary_placeholder_is_untouched")


if __name__ == "__main__":
    test_the_directive_names_the_unrun_experiment()
    test_a_second_ask_is_marked_as_a_repeat()
    test_abandoned_items_are_named_not_dropped()
    test_nothing_to_say_renders_nothing()
    test_an_unrun_item_is_staged_for_retry()
    test_a_refuted_item_is_not_retried()
    test_a_second_miss_abandons_instead_of_looping()
    test_staging_ignores_repair_iterations_and_missing_manifests()
    test_the_retry_is_merged_into_the_next_plan()
    test_a_retry_already_replanned_is_not_duplicated()
    test_a_fresh_decision_outranks_an_outstanding_retry()
    test_probes_without_an_entry_are_recognised_as_diagnostic()
    test_an_ordinary_placeholder_is_untouched()
    print("\nAll diagnostic re-issue tests passed.")
