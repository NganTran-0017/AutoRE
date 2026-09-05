"""
The Mode 3 control check.

A diagnostic iteration is additive-only, and the meaning of a SAT/UNSAT verdict
rests entirely on that. Rolling the model back afterwards protects the MODEL from
an illegal edit; it does not protect the EVIDENCE, because the analyzer has
already run on the altered model and the verdict is already in the log. So the
control is checked, and its answer travels with the verdicts.

Run: python test/test_diagnostic_control.py   (from the repo root)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.repair_plateau_detector import (
    build_probe_verdict_block,
    diff_diagnostic_control,
    extract_probe_bodies,
    read_back_probe_verdicts,
    strip_probes,
)

BASELINE = """open util/ordering[State]

sig State { emg: lone Bool }

fact EmergencyUnique { one s: State | s.emg = True }  //@req R6

pred Scenario_MultiEmg_A { some s: State | s.emg = True }
run Scenario_MultiEmg_A for 6
"""

PROBED = BASELINE + """
pred probe1_ScenarioMultiEmgA { some disj a, b: State | a.emg = True and b.emg = True }  //@req none:probe
run probe1_ScenarioMultiEmgA for 6
"""


# ----------------------------------------------------------------- stripping #

def test_stripping_probes_recovers_the_baseline():
    assert strip_probes(PROBED).strip() == BASELINE.strip()
    print("PASS test_stripping_probes_recovers_the_baseline")


def test_a_probe_run_command_is_removed_by_name_not_position():
    """The probe's run may sit anywhere among the others; only its own goes."""
    shuffled = PROBED.replace(
        "run Scenario_MultiEmg_A for 6",
        "run probe1_ScenarioMultiEmgA for 6\nrun Scenario_MultiEmg_A for 6",
    ).replace("\nrun probe1_ScenarioMultiEmgA for 6\n", "\n", 1)

    out = strip_probes(shuffled)
    assert "run Scenario_MultiEmg_A for 6" in out
    assert "probe1_" not in out
    print("PASS test_a_probe_run_command_is_removed_by_name_not_position")


def test_probe_bodies_are_extracted_whole():
    bodies = extract_probe_bodies(PROBED)
    assert list(bodies) == ["probe1_ScenarioMultiEmgA"]
    assert "some disj a, b: State" in bodies["probe1_ScenarioMultiEmgA"]
    assert extract_probe_bodies(BASELINE) == {}
    print("PASS test_probe_bodies_are_extracted_whole")


# ------------------------------------------------------------- the verdict #

def test_an_additive_iteration_is_unmodified():
    control = diff_diagnostic_control(PROBED, BASELINE)
    assert control["modified"] is False
    assert control["probes"] == ["probe1_ScenarioMultiEmgA"]
    assert "UNMODIFIED" in control["status"]
    print("PASS test_an_additive_iteration_is_unmodified")


def test_reformatting_is_not_an_edit():
    """Blank lines and trailing space are not a changed control."""
    noisy = PROBED.replace("\n\n", "\n\n\n").replace("sig State", "sig State  ")
    assert diff_diagnostic_control(noisy, BASELINE)["modified"] is False
    print("PASS test_reformatting_is_not_an_edit")


def test_a_relaxed_fact_is_caught():
    """
    The failure this exists for: the RE relaxes `EmergencyUnique` to make its own
    probe pass. probe1 comes back SAT, the Evaluator reads "hypothesis confirmed",
    and repairs against a measurement that was never made.
    """
    edited = PROBED.replace("one s: State", "some s: State")
    control = diff_diagnostic_control(edited, BASELINE)

    assert control["modified"] is True
    assert control["changed"] == ["EmergencyUnique"]
    assert "UNANSWERED" in control["status"]
    print("PASS test_a_relaxed_fact_is_caught")


def test_a_deleted_construct_is_caught():
    edited = PROBED.replace(
        "fact EmergencyUnique { one s: State | s.emg = True }  //@req R6\n", "")
    control = diff_diagnostic_control(edited, BASELINE)

    assert control["modified"] is True
    assert control["removed"] == ["EmergencyUnique"]
    assert "deleted EmergencyUnique" in control["status"]
    print("PASS test_a_deleted_construct_is_caught")


def test_a_smuggled_repair_is_caught_as_an_addition():
    """A new non-probe construct is a repair, not a measurement."""
    edited = PROBED + "\npred HelperFix { some State }  //@req R6\n"
    control = diff_diagnostic_control(edited, BASELINE)

    assert control["modified"] is True
    assert control["added"] == ["HelperFix"]
    print("PASS test_a_smuggled_repair_is_caught_as_an_addition")


def test_a_changed_scope_is_caught_outside_any_block():
    """Every named block matches, so the change must be reported another way."""
    edited = PROBED.replace("run Scenario_MultiEmg_A for 6", "run Scenario_MultiEmg_A for 12")
    control = diff_diagnostic_control(edited, BASELINE)

    assert control["modified"] is True
    assert control["changed"] == [] and control["removed"] == []
    assert "outside any named block" in control["status"]
    print("PASS test_a_changed_scope_is_caught_outside_any_block")


def test_a_missing_baseline_refuses_to_guess():
    """
    Same refuse-when-unsure rule as the guard rails: a false MODIFIED discards a
    sound measurement, which is the more expensive mistake.
    """
    assert diff_diagnostic_control(PROBED, "")["modified"] is False
    assert diff_diagnostic_control("", BASELINE)["modified"] is False
    print("PASS test_a_missing_baseline_refuses_to_guess")


# ------------------------------------------------------- probe attribution #

PLAN = [
    {"construct": "CredentialUpdatePerfomedSeq", "hypothesis": "h1", "reading": "SAT => timing"},
    {"construct": "AdminEligibleForEmergencyTrigger", "hypothesis": "h2", "reading": "SAT => eligibility"},
]


def test_probes_in_plan_order_still_match():
    rb = read_back_probe_verdicts(
        PLAN,
        satisfied=["probe1_CredentialUpdatePerfomedSeq"],
        unsatisfied=["probe2_AdminEligibleForEmergencyTrigger"],
    )
    assert [r["status"] for r in rb["results"]] == ["confirmed", "refuted"]
    assert rb["misnumbered"] == []
    print("PASS test_probes_in_plan_order_still_match")


def test_a_misnumbered_probe_lands_on_its_own_hypothesis():
    """
    The failure: the RE probes the item it found easiest and calls it `probe1_`.
    Positional matching reported "timing CONFIRMED" from an experiment about
    eligibility - confidently, since the table still comes out full and plausible.
    """
    rb = read_back_probe_verdicts(
        PLAN, satisfied=["probe1_AdminEligibleForEmergencyTrigger"], unsatisfied=[])

    assert rb["results"][0]["status"] == "not_run"      # timing was never probed
    assert rb["results"][1]["status"] == "confirmed"    # eligibility was
    assert rb["results"][1]["probe"] == "probe1_AdminEligibleForEmergencyTrigger"
    assert rb["misnumbered"] == ["probe1_AdminEligibleForEmergencyTrigger answers plan item 2"]
    # and the false "everything was refuted" signal cannot fire off one experiment
    assert rb["all_refuted"] is False
    print("PASS test_a_misnumbered_probe_lands_on_its_own_hypothesis")


def test_the_suffix_is_matched_without_separators_or_case():
    rb = read_back_probe_verdicts(
        PLAN, satisfied=["probe2_credential_update_perfomed_seq"], unsatisfied=[])
    assert rb["results"][0]["probe"] == "probe2_credential_update_perfomed_seq"
    assert rb["results"][1]["status"] == "not_run"
    print("PASS test_the_suffix_is_matched_without_separators_or_case")


def test_a_truncated_suffix_still_lands():
    rb = read_back_probe_verdicts(PLAN, satisfied=["probe1_AdminEligible"], unsatisfied=[])
    assert rb["results"][1]["status"] == "confirmed"
    print("PASS test_a_truncated_suffix_still_lands")


def test_an_unrecognisable_suffix_falls_back_to_position():
    rb = read_back_probe_verdicts(PLAN, satisfied=["probe1_X", "probe2_Y"], unsatisfied=[])
    assert [r["probe"] for r in rb["results"]] == ["probe1_X", "probe2_Y"]
    assert rb["misnumbered"] == []
    print("PASS test_an_unrecognisable_suffix_falls_back_to_position")


def test_a_probe_nobody_ordered_is_reported_not_absorbed():
    rb = read_back_probe_verdicts(
        PLAN,
        satisfied=["probe1_CredentialUpdatePerfomedSeq", "probe3_SomethingElse"],
        unsatisfied=["probe2_AdminEligibleForEmergencyTrigger"],
    )
    assert rb["unmatched_probes"] == ["probe3_SomethingElse"]
    assert [r["status"] for r in rb["results"]] == ["confirmed", "refuted"]
    print("PASS test_a_probe_nobody_ordered_is_reported_not_absorbed")


def test_each_probe_is_claimed_only_once():
    """Two items naming the same construct must not both harvest one verdict."""
    plan = [dict(PLAN[0]), dict(PLAN[0])]
    rb = read_back_probe_verdicts(
        plan, satisfied=["probe1_CredentialUpdatePerfomedSeq"], unsatisfied=[])
    assert [r["status"] for r in rb["results"]] == ["confirmed", "not_run"]
    print("PASS test_each_probe_is_claimed_only_once")


def test_the_block_reports_the_misnumbering_rather_than_hiding_it():
    rb = read_back_probe_verdicts(
        PLAN, satisfied=["probe1_AdminEligibleForEmergencyTrigger"], unsatisfied=[])
    block = build_probe_verdict_block(rb)

    assert "probe numbering did not follow the plan order" in block
    assert "matched by construct name" in block
    print("PASS test_the_block_reports_the_misnumbering_rather_than_hiding_it")


if __name__ == "__main__":
    test_stripping_probes_recovers_the_baseline()
    test_a_probe_run_command_is_removed_by_name_not_position()
    test_probe_bodies_are_extracted_whole()
    test_an_additive_iteration_is_unmodified()
    test_reformatting_is_not_an_edit()
    test_a_relaxed_fact_is_caught()
    test_a_deleted_construct_is_caught()
    test_a_smuggled_repair_is_caught_as_an_addition()
    test_a_changed_scope_is_caught_outside_any_block()
    test_a_missing_baseline_refuses_to_guess()
    test_probes_in_plan_order_still_match()
    test_a_misnumbered_probe_lands_on_its_own_hypothesis()
    test_the_suffix_is_matched_without_separators_or_case()
    test_a_truncated_suffix_still_lands()
    test_an_unrecognisable_suffix_falls_back_to_position()
    test_a_probe_nobody_ordered_is_reported_not_absorbed()
    test_each_probe_is_claimed_only_once()
    test_the_block_reports_the_misnumbering_rather_than_hiding_it()
    print("\nAll Mode 3 control-check and attribution tests passed.")
