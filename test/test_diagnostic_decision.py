"""
Unit tests for RE Mode 3, Phase 1 - the Evaluator's next-action decision is the
diagnostic signal, and the plan behind it is parsed deterministically.

Two conditions gate Mode 3: the decision is `run diagnostic experiments` AND at
least one plan item survives parsing. Everything else falls back to Mode 2, which
is the same deterministic downgrade the rest of repair_plateau_detector uses.

Run: python test/test_diagnostic_decision.py   (from the repo root)
"""

import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.workflow import AutoREWorkflow
from src.utils.repair_plateau_detector import (
    DIAGNOSTIC_DECISION,
    NEXT_ACTION_DECISIONS,
    parse_diagnostic_plan,
    parse_next_action_decision,
    should_run_diagnostic_iteration,
)


PLAN = """=== DIAGNOSTIC PLAN ===
- Construct: CredentialUpdatePerfomedSeq
- Hypothesis: it forces the flag to reset in the second Normal state, blocking Scenario_MultiEmg_A.
- Level: predicate
- Reading: SAT => this construct is the blocker; UNSAT => it is exonerated.
- Construct: AdminEligibleForEmergencyTrigger
- Hypothesis: it requires eligibility to persist across the whole trace.
- Level: predicate
- Reading: SAT => the persistence requirement is the blocker; UNSAT => it is not.
"""


def _feedback(decision, plan=PLAN, repair="None"):
    return (
        "=== NEXT ACTION DECISION ===\n"
        f"Decision: {decision}\n"
        "Rationale: the failing scenario has two candidate blockers.\n\n"
        f"{plan}\n"
        "=== REPAIR INSTRUCTIONS ===\n"
        f"{repair}\n\n"
        "=== CONVERGENCE_RECOMMENDATION ===\n"
        "Status: FALSE\n"
    )


# ------------------------------------------------------- decision parsing #

def test_every_canonical_decision_parses():
    for decision in NEXT_ACTION_DECISIONS:
        assert parse_next_action_decision(_feedback(decision)) == decision, decision
    print("PASS test_every_canonical_decision_parses")


def test_decision_parsing_tolerates_llm_formatting():
    variants = {
        "**run diagnostic experiments**": DIAGNOSTIC_DECISION,
        "`run diagnostic experiments`": DIAGNOSTIC_DECISION,
        "  Run Diagnostic Experiments  ": DIAGNOSTIC_DECISION,
        "run diagnostic experiments.": DIAGNOSTIC_DECISION,
        "run diagnostic experiments (predicate level only)": DIAGNOSTIC_DECISION,
        "keep fix": "keep fix",
    }
    for written, expected in variants.items():
        assert parse_next_action_decision(_feedback(written)) == expected, written
    # The label itself may be emphasised or bulleted
    assert parse_next_action_decision(
        "=== NEXT ACTION DECISION ===\n- **Decision**: keep fix\n"
    ) == "keep fix"
    print("PASS test_decision_parsing_tolerates_llm_formatting")


def test_decision_parsing_refuses_when_unsure():
    # Echoed template - several decisions on one line names none of them
    echoed = _feedback("keep fix / refine/narrow fix / run diagnostic experiments")
    assert parse_next_action_decision(echoed) is None
    # Unfilled placeholder
    assert parse_next_action_decision(_feedback("[decide here]")) is None
    # Wording outside the enum
    assert parse_next_action_decision(_feedback("rewrite the whole model")) is None
    # Missing section / missing line / empty input
    assert parse_next_action_decision("=== REPAIR INSTRUCTIONS ===\nfix it\n") is None
    assert parse_next_action_decision("=== NEXT ACTION DECISION ===\nRationale: none\n") is None
    assert parse_next_action_decision("") is None
    assert parse_next_action_decision(None) is None
    print("PASS test_decision_parsing_refuses_when_unsure")


def test_decision_is_read_from_its_own_section():
    """A decision phrase quoted inside REPAIR INSTRUCTIONS must not be picked up."""
    text = (
        "=== NEXT ACTION DECISION ===\n"
        "Decision: keep fix\n\n"
        "=== REPAIR INSTRUCTIONS ===\n"
        "Decision: run diagnostic experiments\n"
    )
    assert parse_next_action_decision(text) == "keep fix"
    print("PASS test_decision_is_read_from_its_own_section")


# ----------------------------------------------------------- plan parsing #

def test_plan_items_parse():
    plan = parse_diagnostic_plan(_feedback(DIAGNOSTIC_DECISION))
    assert plan["dropped"] == []
    assert [i["construct"] for i in plan["items"]] == [
        "CredentialUpdatePerfomedSeq",
        "AdminEligibleForEmergencyTrigger",
    ]
    first = plan["items"][0]
    assert first["level"] == "predicate"
    assert "second Normal state" in first["hypothesis"]
    assert "UNSAT => it is exonerated" in first["reading"]
    print("PASS test_plan_items_parse")


def test_plan_stops_at_the_next_section():
    plan = parse_diagnostic_plan(_feedback(DIAGNOSTIC_DECISION, repair="Delete EmergencyUnique"))
    assert len(plan["items"]) == 2
    assert all("EmergencyUnique" not in i["hypothesis"] for i in plan["items"])
    print("PASS test_plan_stops_at_the_next_section")


def test_wrapped_field_values_are_joined():
    wrapped = (
        "=== DIAGNOSTIC PLAN ===\n"
        "- Construct: R6pred\n"
        "- Hypothesis: the flag reset timing in R6pred is what forbids\n"
        "  a second emergency in the same trace.\n"
        "- Level: predicate\n"
        "- Reading: SAT => timing is the blocker;\n"
        "  UNSAT => it is not.\n"
    )
    item = parse_diagnostic_plan(wrapped)["items"][0]
    assert item["hypothesis"].endswith("in the same trace.")
    assert "UNSAT => it is not." in item["reading"]
    print("PASS test_wrapped_field_values_are_joined")


def test_incomplete_items_are_dropped_with_a_reason():
    cases = [
        ("- Construct: X\n- Level: predicate\n- Reading: SAT => blocker\n",
         "no hypothesis stated"),
        ("- Construct: X\n- Hypothesis: h\n- Level: predicate\n",
         "no reading declared before the run"),
        ("- Construct: X\n- Hypothesis: h\n- Level: signature\n- Reading: SAT => blocker\n",
         "is not one of"),
        ("- Construct: [exact name]\n- Hypothesis: h\n- Level: predicate\n- Reading: SAT => x\n",
         "no construct named"),
    ]
    for body, expected_reason in cases:
        plan = parse_diagnostic_plan("=== DIAGNOSTIC PLAN ===\n" + body)
        assert plan["items"] == [], body
        assert len(plan["dropped"]) == 1, body
        assert expected_reason in plan["dropped"][0]["reason"], body
    print("PASS test_incomplete_items_are_dropped_with_a_reason")


def test_fact_and_scope_levels_parse_so_phase_2_can_drop_them():
    """Phase 1 parses all three levels; the filtering is Phase 2's job."""
    body = ("=== DIAGNOSTIC PLAN ===\n"
            "- Construct: EmergencyUnique\n- Hypothesis: it blocks E->N->N->E\n"
            "- Level: fact\n- Reading: SAT => blocker\n")
    plan = parse_diagnostic_plan(body)
    assert plan["items"][0]["level"] == "fact"
    assert plan["dropped"] == []
    print("PASS test_fact_and_scope_levels_parse_so_phase_2_can_drop_them")


def test_absent_or_none_plan_yields_nothing():
    for text in ["", None, "=== REPAIR INSTRUCTIONS ===\nfix it\n",
                 "=== DIAGNOSTIC PLAN ===\nNone\n"]:
        plan = parse_diagnostic_plan(text)
        assert plan == {"items": [], "dropped": []}, text
    print("PASS test_absent_or_none_plan_yields_nothing")


# --------------------------------------------------------- the Mode 3 gate #

def test_both_conditions_select_a_diagnostic_iteration():
    signal = should_run_diagnostic_iteration(_feedback(DIAGNOSTIC_DECISION))
    assert signal["diagnostic"] is True
    assert signal["decision"] == DIAGNOSTIC_DECISION
    assert len(signal["items"]) == 2
    print("PASS test_both_conditions_select_a_diagnostic_iteration")


def test_a_plan_without_the_decision_is_not_diagnostic():
    """
    The decision selects the mode, never the presence of experiment text - the
    injected DIAGNOSTIC CANDIDATES fire on nearly every UNSAT iteration.
    """
    signal = should_run_diagnostic_iteration(_feedback("refine/narrow fix"))
    assert signal["diagnostic"] is False
    assert signal["items"] == []
    assert "refine/narrow fix" in signal["reason"]
    print("PASS test_a_plan_without_the_decision_is_not_diagnostic")


def test_decision_without_a_usable_plan_falls_back_to_mode_2():
    empty = should_run_diagnostic_iteration(_feedback(DIAGNOSTIC_DECISION, plan=""))
    assert empty["diagnostic"] is False
    assert "no usable plan item" in empty["reason"]

    unusable = should_run_diagnostic_iteration(_feedback(
        DIAGNOSTIC_DECISION,
        plan="=== DIAGNOSTIC PLAN ===\n- Construct: X\n- Hypothesis: h\n- Level: predicate\n",
    ))
    assert unusable["diagnostic"] is False
    # The drop is reported, not swallowed
    assert unusable["dropped"][0]["construct"] == "X"
    print("PASS test_decision_without_a_usable_plan_falls_back_to_mode_2")


def test_unparseable_decision_falls_back_to_mode_2():
    signal = should_run_diagnostic_iteration(_feedback("[decide here]"))
    assert signal["diagnostic"] is False
    assert signal["decision"] is None
    assert "unparseable" in signal["reason"]
    print("PASS test_unparseable_decision_falls_back_to_mode_2")


# ------------------------------------------------------- workflow wiring #

def _make_workflow():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.logger = Mock()
    wf.context = Mock()
    return wf


def test_workflow_stores_the_signal_and_logs_every_drop():
    wf = _make_workflow()
    feedback = _feedback(
        DIAGNOSTIC_DECISION,
        plan=PLAN + "- Construct: Orphan\n- Hypothesis: h\n- Level: predicate\n",
    )

    signal = wf._evaluate_diagnostic_signal(feedback)

    assert signal["diagnostic"] is True
    assert wf.context.diagnostic_signal is signal
    logged = " ".join(str(c) for c in wf.logger.log.call_args_list)
    assert "Orphan" in logged and "no reading declared" in logged
    assert "MODE3" in logged
    print("PASS test_workflow_stores_the_signal_and_logs_every_drop")


def test_workflow_signal_is_observation_only():
    """Phase 1 changes no behaviour: the workflow still selects semantic (Mode 2)."""
    wf = _make_workflow()
    signal = wf._evaluate_diagnostic_signal(_feedback("keep fix"))
    assert signal["diagnostic"] is False
    assert wf.context.diagnostic_signal["decision"] == "keep fix"
    print("PASS test_workflow_signal_is_observation_only")


def test_every_non_diagnostic_outcome_is_logged():
    """
    Including the one with no decision at all - a plan RefineFeedback rewrote away
    leaves no other trace, and an unlogged downgrade reads like a proposal that was
    never made.
    """
    for decision in ("keep fix", "[decide here]", DIAGNOSTIC_DECISION):
        wf = _make_workflow()
        wf._evaluate_diagnostic_signal(_feedback(decision, plan=""))
        logged = " ".join(str(c) for c in wf.logger.log.call_args_list)
        assert "MODE3" in logged, decision
        assert "not a diagnostic iteration" in logged, decision
    print("PASS test_every_non_diagnostic_outcome_is_logged")


# ------------------------------------------------------------- the prompt #

def test_prompt_carries_the_sixth_value_and_the_plan_schema():
    prompt = Path("prompts/Evaluator_prompt.txt").read_text()

    # The enum the parser matches against, in both the task list and the schema
    assert prompt.count(DIAGNOSTIC_DECISION) >= 3
    assert "=== DIAGNOSTIC PLAN ===" in prompt
    for field in ("- Construct:", "- Hypothesis:", "- Level:", "- Reading:"):
        assert field in prompt, field
    # Repair XOR measurement - the rule that stops an iteration being both
    assert "EITHER a repair OR a measurement" in prompt
    # Experiments no longer route into REPAIR INSTRUCTIONS
    assert "experiment you adopt -> `=== DIAGNOSTIC PLAN ===`" in prompt
    assert "diagnostic experiment routed here by task 8" not in prompt
    # RefineFeedback rewrites the whole blob and does not carry the response
    # format, so the decision and plan need an explicit preservation rule or the
    # signal is lost between the draft and the feedback the RE actually acts on.
    refine = prompt[prompt.index("[SECTION: RefineFeedback]"):]
    refine = refine[:refine.index("\n[SECTION:", 1)]
    assert "=== DIAGNOSTIC PLAN ===" in refine
    assert "`Decision:` line" in refine
    print("PASS test_prompt_carries_the_sixth_value_and_the_plan_schema")


if __name__ == "__main__":
    test_every_canonical_decision_parses()
    test_decision_parsing_tolerates_llm_formatting()
    test_decision_parsing_refuses_when_unsure()
    test_decision_is_read_from_its_own_section()
    test_plan_items_parse()
    test_plan_stops_at_the_next_section()
    test_wrapped_field_values_are_joined()
    test_incomplete_items_are_dropped_with_a_reason()
    test_fact_and_scope_levels_parse_so_phase_2_can_drop_them()
    test_absent_or_none_plan_yields_nothing()
    test_both_conditions_select_a_diagnostic_iteration()
    test_a_plan_without_the_decision_is_not_diagnostic()
    test_decision_without_a_usable_plan_falls_back_to_mode_2()
    test_unparseable_decision_falls_back_to_mode_2()
    test_workflow_stores_the_signal_and_logs_every_drop()
    test_workflow_signal_is_observation_only()
    test_every_non_diagnostic_outcome_is_logged()
    test_prompt_carries_the_sixth_value_and_the_plan_schema()
    print("\nAll diagnostic-decision tests passed.")
