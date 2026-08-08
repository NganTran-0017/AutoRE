"""
Unit tests for RE Mode 3, Phase 2 (guard-rail the plan in code) and TODO T5
(the signal survives RefineFeedback).

The Evaluator judges WHETHER to diagnose; code decides WHAT survives. A dropped
item is never silent and never merely refused - it is reported back with whatever
the deterministic diagnosis already measured about it.

Run: python test/test_diagnostic_guardrails.py   (from the repo root)
"""

import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.workflow import AutoREWorkflow
from src.utils.repair_plateau_detector import (
    DIAGNOSTIC_DECISION,
    DROPPED_ITEMS_HEADING,
    build_diagnostic_status_block,
    filter_diagnostic_plan,
    parse_diagnostic_plan,
    parse_next_action_decision,
    preserve_diagnostic_signal,
    should_run_diagnostic_iteration,
)


MODEL = """sig State {}
one sig Config {}
pred CredentialUpdatePerfomedSeq { some State }
pred Scenario_MultiEmg_A { some State }
fact EmergencyUnique { no State }
assert assertR6Safety { some State }
run Scenario_MultiEmg_A for 6
"""

# Iteration-67-shaped diagnostics: the sweep ran on the failing scenario and the
# localizer proved EmergencyUnique blocks it.
DIAGNOSTICS = {
    "Scenario_MultiEmg_A": {
        "scope_sweep": {
            "performed": True,
            "sat_at_larger_scope": False,
            "swept_command": "run Scenario_MultiEmg_A for 12",
        },
        "localization": {
            "verdict": "localized",
            "blocking_facts": ["EmergencyUnique"],
        },
    },
}


def _item(construct, level="predicate"):
    return {
        "construct": construct,
        "hypothesis": f"{construct} blocks the scenario",
        "level": level,
        "reading": "SAT => blocker; UNSAT => exonerated",
    }


def _feedback(items_text, decision=DIAGNOSTIC_DECISION):
    return (
        "=== NEXT ACTION DECISION ===\n"
        f"Decision: {decision}\n\n"
        "=== DIAGNOSTIC PLAN ===\n"
        f"{items_text}\n"
        "=== REPAIR INSTRUCTIONS ===\n"
        "None\n"
    )


def _plan_text(construct, level="predicate"):
    return (f"- Construct: {construct}\n"
            f"- Hypothesis: {construct} blocks the scenario\n"
            f"- Level: {level}\n"
            "- Reading: SAT => blocker; UNSAT => exonerated\n")


# ------------------------------------------------------------ guard rails #

def test_fact_level_items_are_dropped():
    """
    The EmergencyUnique case. A fact constrains the probe too, so a predicate-level
    probe returns UNSAT whether or not the hypothesis was right - the experiment
    cannot discriminate, and the localizer has already answered it.
    """
    out = filter_diagnostic_plan([_item("EmergencyUnique", "fact")], MODEL, DIAGNOSTICS)
    assert out["items"] == []
    assert "fact-level hypothesis" in out["dropped"][0]["reason"]
    print("PASS test_fact_level_items_are_dropped")


def test_scope_items_drop_only_when_the_sweep_ran():
    swept = filter_diagnostic_plan([_item("Scenario_MultiEmg_A", "scope")], MODEL, DIAGNOSTICS)
    assert swept["items"] == []
    assert "already measured by the scope sweep" in swept["dropped"][0]["reason"]

    # A construct the sweep never touched keeps its item: a larger-scope probe is
    # a new run command, so it stays additive and is still worth running.
    unswept = filter_diagnostic_plan(
        [_item("CredentialUpdatePerfomedSeq", "scope")], MODEL, DIAGNOSTICS
    )
    assert [i["construct"] for i in unswept["items"]] == ["CredentialUpdatePerfomedSeq"]
    assert unswept["dropped"] == []
    print("PASS test_scope_items_drop_only_when_the_sweep_ran")


def test_unknown_constructs_are_dropped():
    out = filter_diagnostic_plan([_item("NoSuchPredicate")], MODEL, DIAGNOSTICS)
    assert out["items"] == []
    assert "does not appear in the model" in out["dropped"][0]["reason"]
    print("PASS test_unknown_constructs_are_dropped")


def test_declared_constructs_of_every_kind_survive():
    names = ["CredentialUpdatePerfomedSeq", "assertR6Safety", "State", "Config"]
    out = filter_diagnostic_plan([_item(n) for n in names], MODEL, DIAGNOSTICS)
    assert [i["construct"] for i in out["items"]] == names
    assert out["dropped"] == []
    print("PASS test_declared_constructs_of_every_kind_survive")


def test_missing_evidence_never_discards_a_plan():
    """
    No model text and no diagnostics means no basis to drop anything. Refusing to
    filter is the safe outcome; dropping on absent evidence would convert a
    diagnostic iteration into a repair one for a reason that does not exist.
    """
    items = [_item("Whatever"), _item("Another", "scope")]
    out = filter_diagnostic_plan(items)
    assert out["items"] == items
    assert out["dropped"] == []
    print("PASS test_missing_evidence_never_discards_a_plan")


def test_filtering_can_empty_the_plan_and_fall_back_to_mode_2():
    feedback = _feedback(_plan_text("EmergencyUnique", "fact"))
    signal = should_run_diagnostic_iteration(feedback, MODEL, DIAGNOSTICS)
    assert signal["diagnostic"] is False
    assert "no usable plan item" in signal["reason"]
    assert signal["dropped"][0]["construct"] == "EmergencyUnique"
    print("PASS test_filtering_can_empty_the_plan_and_fall_back_to_mode_2")


def test_a_mixed_plan_keeps_what_survives():
    feedback = _feedback(
        _plan_text("EmergencyUnique", "fact") + _plan_text("CredentialUpdatePerfomedSeq")
    )
    signal = should_run_diagnostic_iteration(feedback, MODEL, DIAGNOSTICS)
    assert signal["diagnostic"] is True
    assert [i["construct"] for i in signal["items"]] == ["CredentialUpdatePerfomedSeq"]
    assert len(signal["dropped"]) == 1
    print("PASS test_a_mixed_plan_keeps_what_survives")


# ------------------------------------- dropped items report their status #

def test_dropped_facts_carry_the_localizer_verdict():
    """
    The Evaluator asked a question; code refused to re-ask it because the answer
    is already measured. Carrying that answer is what makes the refusal useful.
    """
    dropped = filter_diagnostic_plan(
        [_item("EmergencyUnique", "fact")], MODEL, DIAGNOSTICS
    )["dropped"]
    block = build_diagnostic_status_block(dropped, DIAGNOSTICS)

    assert DROPPED_ITEMS_HEADING in block
    assert "EmergencyUnique" in block
    assert "Not run:" in block
    assert "proven to block Scenario_MultiEmg_A" in block
    print("PASS test_dropped_facts_carry_the_localizer_verdict")


def test_dropped_scope_items_carry_the_sweep_verdict():
    dropped = filter_diagnostic_plan(
        [_item("Scenario_MultiEmg_A", "scope")], MODEL, DIAGNOSTICS
    )["dropped"]
    block = build_diagnostic_status_block(dropped, DIAGNOSTICS)

    assert "still UNSAT at larger scope" in block
    assert "run Scenario_MultiEmg_A for 12" in block
    assert "localizer verdict: localized" in block
    print("PASS test_dropped_scope_items_carry_the_sweep_verdict")


def test_a_drop_with_no_measurement_says_so():
    """
    An unknown construct was not answered, it was untestable. The block must not
    let the two read alike - "already measured" and "unanswerable" lead the
    Evaluator to opposite next steps.
    """
    dropped = filter_diagnostic_plan([_item("NoSuchPredicate")], MODEL, DIAGNOSTICS)["dropped"]
    block = build_diagnostic_status_block(dropped, DIAGNOSTICS)

    assert "no deterministic result for this construct" in block
    assert "untestable as written, not as already answered" in block
    print("PASS test_a_drop_with_no_measurement_says_so")


def test_status_block_rides_on_the_signal():
    feedback = _feedback(
        _plan_text("EmergencyUnique", "fact") + _plan_text("CredentialUpdatePerfomedSeq")
    )
    signal = should_run_diagnostic_iteration(feedback, MODEL, DIAGNOSTICS)
    assert "EmergencyUnique" in signal["status_block"]
    assert "CredentialUpdatePerfomedSeq" not in signal["status_block"]  # it survived

    # Nothing dropped -> nothing to report
    clean = should_run_diagnostic_iteration(
        _feedback(_plan_text("CredentialUpdatePerfomedSeq")), MODEL, DIAGNOSTICS
    )
    assert clean["status_block"] == ""
    print("PASS test_status_block_rides_on_the_signal")


# ------------------------------------------ T5: surviving RefineFeedback #

DRAFT = _feedback(_plan_text("CredentialUpdatePerfomedSeq"))


def test_a_rewrite_that_dropped_the_signal_is_repaired():
    refined = ("=== NEXT ACTION DECISION ===\n"
               "Rationale: the user asked for more detail.\n\n"
               "=== REPAIR INSTRUCTIONS ===\n"
               "None\n")
    out = preserve_diagnostic_signal(DRAFT, refined)

    assert out["action"] == "restored"
    assert set(out["restored"]) == {"decision", "plan"}
    assert parse_next_action_decision(out["text"]) == DIAGNOSTIC_DECISION
    assert [i["construct"] for i in parse_diagnostic_plan(out["text"])["items"]] == [
        "CredentialUpdatePerfomedSeq"
    ]
    print("PASS test_a_rewrite_that_dropped_the_signal_is_repaired")


def test_only_the_plan_is_restored_when_only_the_plan_is_missing():
    refined = ("=== NEXT ACTION DECISION ===\n"
               f"Decision: {DIAGNOSTIC_DECISION}\n\n"
               "=== REPAIR INSTRUCTIONS ===\n"
               "None\n")
    out = preserve_diagnostic_signal(DRAFT, refined)

    assert out["restored"] == ["plan"]
    # Restored where the schema puts it, before REPAIR INSTRUCTIONS
    assert out["text"].index("=== DIAGNOSTIC PLAN ===") < out["text"].index("=== REPAIR INSTRUCTIONS ===")
    print("PASS test_only_the_plan_is_restored_when_only_the_plan_is_missing")


def test_a_user_override_is_left_alone():
    """
    "Stop experimenting, just fix it" is a legitimate outcome of the review. Only
    a decision that vanished is restored; one that CHANGED is the user's.
    """
    refined = ("=== NEXT ACTION DECISION ===\n"
               "Decision: refine/narrow fix\n\n"
               "=== REPAIR INSTRUCTIONS ===\n"
               "Narrow the guard in CredentialUpdatePerfomedSeq.\n")
    out = preserve_diagnostic_signal(DRAFT, refined)

    assert out["action"] == "overridden"
    assert out["text"] == refined
    assert parse_next_action_decision(out["text"]) == "refine/narrow fix"
    print("PASS test_a_user_override_is_left_alone")


def test_an_intact_rewrite_is_untouched():
    out = preserve_diagnostic_signal(DRAFT, DRAFT)
    assert out["action"] == "intact"
    assert out["text"] == DRAFT

    # And a draft that never chose to diagnose is not this function's business
    plain = _feedback(_plan_text("X"), decision="keep fix")
    assert preserve_diagnostic_signal(plain, "anything")["action"] == "not_applicable"
    print("PASS test_an_intact_rewrite_is_untouched")


# ------------------------------------------------------- workflow wiring #

def _make_workflow():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.logger = Mock()
    wf.context = Mock()
    return wf


def test_workflow_logs_the_dropped_status_block():
    wf = _make_workflow()
    feedback = _feedback(
        _plan_text("EmergencyUnique", "fact") + _plan_text("CredentialUpdatePerfomedSeq")
    )

    signal = wf._evaluate_diagnostic_signal(feedback, MODEL, DIAGNOSTICS)

    assert signal["diagnostic"] is True
    logged = " ".join(str(c) for c in wf.logger.log.call_args_list)
    assert "MODE3_DROPPED" in logged
    assert "proven to block Scenario_MultiEmg_A" in logged
    print("PASS test_workflow_logs_the_dropped_status_block")


def test_workflow_restores_the_signal_after_refine():
    wf = _make_workflow()
    stripped = "=== REPAIR INSTRUCTIONS ===\nNone\n"

    out = wf._preserve_diagnostic_signal(DRAFT, stripped)

    assert parse_next_action_decision(out) == DIAGNOSTIC_DECISION
    assert parse_diagnostic_plan(out)["items"]
    logged = " ".join(str(c) for c in wf.logger.log.call_args_list)
    assert "restored after refine" in logged
    print("PASS test_workflow_restores_the_signal_after_refine")


if __name__ == "__main__":
    test_fact_level_items_are_dropped()
    test_scope_items_drop_only_when_the_sweep_ran()
    test_unknown_constructs_are_dropped()
    test_declared_constructs_of_every_kind_survive()
    test_missing_evidence_never_discards_a_plan()
    test_filtering_can_empty_the_plan_and_fall_back_to_mode_2()
    test_a_mixed_plan_keeps_what_survives()
    test_dropped_facts_carry_the_localizer_verdict()
    test_dropped_scope_items_carry_the_sweep_verdict()
    test_a_drop_with_no_measurement_says_so()
    test_status_block_rides_on_the_signal()
    test_a_rewrite_that_dropped_the_signal_is_repaired()
    test_only_the_plan_is_restored_when_only_the_plan_is_missing()
    test_a_user_override_is_left_alone()
    test_an_intact_rewrite_is_untouched()
    test_workflow_logs_the_dropped_status_block()
    test_workflow_restores_the_signal_after_refine()
    print("\nAll diagnostic guard-rail tests passed.")
