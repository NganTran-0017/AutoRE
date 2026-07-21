"""
Unit tests for rung 5 of the semantic escalation ladder - the requirement-change
decision gate and targeted regeneration (repair_plateau_detector helpers).

Run: python test/test_requirement_gate.py   (from the repo root)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.repair_plateau_detector import (
    classify_gate_decision,
    remove_requirement_updates,
    build_regeneration_escalation,
    REGENERATE_PREDICATES,
)


FEEDBACK = """=== VERIFICATION SUMMARY ===
Predicate R1R2_Conflict remains UNSAT.

=== POTENTIAL REQUIREMENT ISSUES ===
R1 and R2 conflict when any job exists.

=== REQUIREMENT UPDATES ===
R2: Jobs may be pending at initialization unless explicitly cleared.

=== UPDATED USER QUESTIONS ===
1. Confirm the R2 rewording above?

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE
"""


def test_classify_gate_decision():
    # Bare approvals / rejections (case, whitespace, punctuation tolerated)
    for text in ["accept", "  Accept ", "YES", "ok", "approve.", "y"]:
        assert classify_gate_decision(text) == "accepted", text
    for text in ["reject", "No", " n ", "declined!", "REJECTED"]:
        assert classify_gate_decision(text) == "rejected", text
    # Timeout / empty -> provisional
    assert classify_gate_decision(None) == "provisional"
    assert classify_gate_decision("") == "provisional"
    assert classify_gate_decision("   \n") == "provisional"
    # Substantive text -> edited
    assert classify_gate_decision("R2 should instead say jobs start empty") == "edited"
    assert classify_gate_decision("no, but change R3 too") == "edited"
    print("PASS test_classify_gate_decision")


def test_remove_requirement_updates():
    stripped = remove_requirement_updates(FEEDBACK)
    assert "=== REQUIREMENT UPDATES ===" not in stripped
    assert "Jobs may be pending at initialization" not in stripped
    # Neighboring sections intact
    assert "=== POTENTIAL REQUIREMENT ISSUES ===" in stripped
    assert "=== UPDATED USER QUESTIONS ===" in stripped
    assert "Status: FALSE" in stripped

    # Section as the LAST section -> removed to EOF
    tail_only = FEEDBACK.split("=== UPDATED USER QUESTIONS ===")[0]
    stripped = remove_requirement_updates(tail_only)
    assert "REQUIREMENT UPDATES" not in stripped
    assert "=== POTENTIAL REQUIREMENT ISSUES ===" in stripped

    # Absent section -> unchanged
    no_section = "=== REPAIR INSTRUCTIONS ===\nfix things\n"
    assert remove_requirement_updates(no_section) == no_section

    # Singular header variant
    singular = FEEDBACK.replace("REQUIREMENT UPDATES", "REQUIREMENTS UPDATE")
    assert "REQUIREMENTS UPDATE" not in remove_requirement_updates(singular)
    print("PASS test_remove_requirement_updates")


def make_semantic_escalation(with_diagnostics=True):
    esc = {
        "escalation_level": 3,
        "strategy": "REQUIREMENTS_DIAGNOSIS",
        "escalated_issues": ["R1R2_Conflict"],
        "directive": "ESCALATION LEVEL: 3 ...",
    }
    if with_diagnostics:
        esc["diagnostics"] = {
            "R1R2_Conflict": {
                "scope_sweep": {"performed": True, "sat_at_larger_scope": False},
                "localization": {
                    "verdict": "localized",
                    "blocking_facts": ["R1_AllJobsPending", "R2_NoPending"],
                    "implicated_requirements": ["R1", "R2"],
                },
            }
        }
    return esc


def test_build_regeneration_escalation_with_diagnostics():
    regen = build_regeneration_escalation(
        current_iteration=21,
        semantic_escalation=make_semantic_escalation(),
        user_decision="accepted",
        proposed_updates="R2: Jobs may be pending at initialization.",
    )
    assert regen["escalation_level"] == 5
    assert regen["strategy"] == REGENERATE_PREDICATES
    assert regen["user_decision"] == "accepted"
    # Targets = escalated predicate + proven blocking facts, no duplicates
    assert regen["regenerate_targets"] == [
        "R1R2_Conflict", "R1_AllJobsPending", "R2_NoPending"]
    d = regen["directive"]
    assert "STRATEGY: REGENERATE_PREDICATES" in d
    assert "ACCEPTED by the user" in d
    assert "- R2_NoPending" in d
    assert "IMPLICATED REQUIREMENTS" in d and "R1, R2" in d
    assert "APPROVED REQUIREMENT UPDATES:" in d
    assert "Jobs may be pending at initialization" in d
    print("PASS test_build_regeneration_escalation_with_diagnostics")


def test_build_regeneration_escalation_without_diagnostics():
    regen = build_regeneration_escalation(
        current_iteration=21,
        semantic_escalation=make_semantic_escalation(with_diagnostics=False),
        user_decision="provisional",
        proposed_updates=None,
    )
    assert regen["regenerate_targets"] == ["R1R2_Conflict"]
    assert "PROVISIONAL" in regen["directive"]
    assert "provisional assumption" in regen["directive"]
    assert "IMPLICATED REQUIREMENTS" not in regen["directive"]
    assert "APPROVED REQUIREMENT UPDATES:" not in regen["directive"]
    print("PASS test_build_regeneration_escalation_without_diagnostics")


def test_build_regeneration_escalation_edited():
    regen = build_regeneration_escalation(
        current_iteration=21,
        semantic_escalation=make_semantic_escalation(),
        user_decision="edited",
        proposed_updates="R2: original proposal text.",
    )
    assert "WITH EDITS" in regen["directive"]
    print("PASS test_build_regeneration_escalation_edited")


if __name__ == "__main__":
    test_classify_gate_decision()
    test_remove_requirement_updates()
    test_build_regeneration_escalation_with_diagnostics()
    test_build_regeneration_escalation_without_diagnostics()
    test_build_regeneration_escalation_edited()
    print("\nAll requirement-gate tests passed.")
