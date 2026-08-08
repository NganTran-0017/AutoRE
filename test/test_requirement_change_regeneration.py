"""
Stale-construct-after-requirement-change fixes:
  Fix A - build_requirement_change_regeneration routes a changed requirement's
          constructs into the REGENERATE_PREDICATES path.
  Fix B - a stale-encoding internal_contradiction is attributed to the
          requirement (not model overconstraint) via the traceability map.
"""

from src.utils.repair_plateau_detector import (
    MODEL_OVERCONSTRAINT_REPAIR,
    REGENERATE_PREDICATES,
    REQUIREMENTS_DIAGNOSIS,
    apply_evidence_alignment,
    build_requirement_change_regeneration,
    summarize_diagnostics_evidence,
)
from src.utils.traceability_store import TraceabilityStore


REQ_INTERPRETATION = (
    "=== RESULT INTERPRETATION ===\n"
    "- Likely Cause: Requirement issue - requirement R6 is inconsistent as stated.\n"
)


# ------------------------------------------------------------- Fix A: builder #

def test_builder_emits_regenerate_directive():
    d = build_requirement_change_regeneration(
        current_iteration=3,
        changed_requirement_ids=["R6"],
        regenerate_targets=["assertR6", "EmergencyUnique"],
        updated_requirements="R6: only triggering admins update credentials.",
    )
    assert d["strategy"] == REGENERATE_PREDICATES
    assert d["regenerate_targets"] == ["assertR6", "EmergencyUnique"]
    assert "CHANGED REQUIREMENTS: R6" in d["directive"]
    assert "REGENERATE" in d["directive"]
    assert "assertR6" in d["directive"] and "EmergencyUnique" in d["directive"]
    assert "UPDATED REQUIREMENTS:" in d["directive"]


def test_builder_no_targets_is_noop():
    d = build_requirement_change_regeneration(3, ["R6"], [])
    assert d["directive"] == ""
    assert d["regenerate_targets"] == []


def test_builder_targets_come_from_traceability():
    ts = TraceabilityStore()
    ts.rebuild(
        "fact R1R2_policy { some x }\nassert assertR6 { no x }\nfact EmergencyUnique { one e }",
        annotations={"EmergencyUnique": ["R6"]},
    )
    targets = ts.constructs_for(["R6"])
    d = build_requirement_change_regeneration(3, ["R6"], targets)
    # R6's constructs (prefixed + annotated) are regenerated; R1/R2 untouched.
    assert set(d["regenerate_targets"]) == {"assertR6", "EmergencyUnique"}
    assert "R1R2_policy" not in d["regenerate_targets"]


# ------------------------------------------------ Fix B: stale-encoding verdict #

def _stale_diag():
    return {
        "R6pred": {
            "scope_sweep": {"performed": True, "sat_at_larger_scope": False},
            "localization": {"verdict": "internal_contradiction", "runs": 1},
        }
    }


def test_internal_contradiction_stays_modeling_without_change_signal():
    summary = summarize_diagnostics_evidence(_stale_diag())
    assert summary["per_issue"]["R6pred"] == "internal_contradiction"
    assert summary["requirement_evidence"] is False
    assert summary["modeling_evidence"] is True


def test_internal_contradiction_becomes_stale_when_requirement_changed():
    ts = TraceabilityStore()
    ts.rebuild("pred R6pred[s: State] { some s }", annotations={})
    summary = summarize_diagnostics_evidence(
        _stale_diag(), traceability=ts, recently_changed=["R6"]
    )
    assert summary["per_issue"]["R6pred"] == "stale_requirement_encoding"
    assert summary["requirement_evidence"] is True
    assert summary["modeling_evidence"] is False


def test_unrelated_change_does_not_reclassify():
    ts = TraceabilityStore()
    ts.rebuild("pred R6pred[s: State] { some s }", annotations={})
    # R1 changed, but the contradiction predicate encodes R6 -> stays modeling.
    summary = summarize_diagnostics_evidence(
        _stale_diag(), traceability=ts, recently_changed=["R1"]
    )
    assert summary["per_issue"]["R6pred"] == "internal_contradiction"


def test_gate_routes_stale_encoding_to_requirements_diagnosis():
    ts = TraceabilityStore()
    ts.rebuild("pred R6pred[s: State] { some s }", annotations={})
    escalation = {
        "escalation_level": 3,
        "strategy": REQUIREMENTS_DIAGNOSIS,
        "escalated_issues": ["R6pred"],
        "diagnostics": _stale_diag(),
        "directive": (
            "ESCALATION LEVEL: 3\n"
            f"STRATEGY: {REQUIREMENTS_DIAGNOSIS}\n"
            "PERSISTENT SEMANTIC ISSUES:\n  - unsatisfiable predicate 'R6pred'"
        ),
    }
    result = apply_evidence_alignment(
        escalation, REQ_INTERPRETATION, traceability=ts, recently_changed=["R6"]
    )
    # Without the stale signal this internal_contradiction would veto to model
    # repair; with it, requirements diagnosis is authorized.
    assert result["strategy"] == REQUIREMENTS_DIAGNOSIS
    assert escalation["strategy"] == REQUIREMENTS_DIAGNOSIS


# ------------------ Fix B (facts): stale blocking-fact from a changed req #
# Reproduces the 072226 EmergencyUnique misdiagnosis: a positive predicate is
# UNSAT because a stale, un-prefixed fact (the old encoding of a just-changed
# requirement) blocks it. The localizer returns 'localized' with that fact in
# the blocking set - it must be attributed to the requirement (stale encoding),
# not to a self-contradictory requirement or an over-restrictive model fact.

def _emergency_localized_diag():
    # 'p_TwoEmergencyPeriods' is SAT once the stale fact is dropped -> localized;
    # the blocking fact 'EmergencyUniqueness' carries no R-prefix, so the
    # localizer implicates no requirement by name.
    return {
        "p_TwoEmergencyPeriods": {
            "scope_sweep": {"performed": True, "sat_at_larger_scope": False},
            "localization": {
                "verdict": "localized",
                "blocking_facts": ["EmergencyUniqueness"],
                "implicated_requirements": [],
                "runs": 4,
            },
        }
    }


def _emergency_traceability():
    # The stale fact is un-prefixed; only the //@req annotation ties it to R3.
    ts = TraceabilityStore()
    ts.rebuild(
        "fact EmergencyUniqueness { all disj s1, s2: State | ... } //@req R3\n"
        "pred p_TwoEmergencyPeriods { some s: State | ... }"
    )
    return ts


def test_stale_blocking_fact_is_requirement_evidence():
    ts = _emergency_traceability()
    assert ts.requirements_for("EmergencyUniqueness") == ["R3"]
    summary = summarize_diagnostics_evidence(
        _emergency_localized_diag(), traceability=ts, recently_changed=["R3"]
    )
    assert summary["per_issue"]["p_TwoEmergencyPeriods"] == "stale_requirement_encoding"
    assert summary["requirement_evidence"] is True
    assert summary["modeling_evidence"] is False


def test_stale_blocking_fact_without_change_stays_single_requirement():
    # Same UNSAT, but no requirement changed recently -> the old classification
    # (an implicated-nothing localized set falls to single_requirement).
    ts = _emergency_traceability()
    summary = summarize_diagnostics_evidence(
        _emergency_localized_diag(), traceability=ts, recently_changed=[]
    )
    assert summary["per_issue"]["p_TwoEmergencyPeriods"] == "single_requirement"


def test_stale_blocking_fact_needs_the_map_not_just_the_name():
    # Without traceability the un-prefixed fact can't be tied to R3, so even a
    # recent change can't reclassify it - the map is what closes the gap.
    summary = summarize_diagnostics_evidence(
        _emergency_localized_diag(), traceability=None, recently_changed=["R3"]
    )
    assert summary["per_issue"]["p_TwoEmergencyPeriods"] == "single_requirement"


def test_unrelated_blocking_fact_change_does_not_reclassify():
    # The blocking fact encodes R3, but R1 changed -> stays as it was.
    ts = _emergency_traceability()
    summary = summarize_diagnostics_evidence(
        _emergency_localized_diag(), traceability=ts, recently_changed=["R1"]
    )
    assert summary["per_issue"]["p_TwoEmergencyPeriods"] == "single_requirement"


def test_gate_routes_stale_blocking_fact_to_requirements_diagnosis():
    ts = _emergency_traceability()
    escalation = {
        "escalation_level": 3,
        "strategy": REQUIREMENTS_DIAGNOSIS,
        "escalated_issues": ["p_TwoEmergencyPeriods"],
        "diagnostics": _emergency_localized_diag(),
        "directive": (
            "ESCALATION LEVEL: 3\n"
            f"STRATEGY: {REQUIREMENTS_DIAGNOSIS}\n"
            "PERSISTENT SEMANTIC ISSUES:\n  - unsatisfiable predicate 'p_TwoEmergencyPeriods'"
        ),
    }
    interpretation = (
        "=== RESULT INTERPRETATION ===\n"
        "- Likely Cause: Requirement issue - the Emergency-uniqueness requirement "
        "was relaxed to allow multiple sequential Emergency periods.\n"
    )
    result = apply_evidence_alignment(
        escalation, interpretation, traceability=ts, recently_changed=["R3"]
    )
    assert result["strategy"] == REQUIREMENTS_DIAGNOSIS
    assert escalation["strategy"] == REQUIREMENTS_DIAGNOSIS


def test_gate_without_signal_keeps_requirements_diagnosis_but_not_the_stale_verdict():
    """Without a recent-change signal the verdict stays `internal_contradiction`,
    so Fix A's regeneration route is NOT taken - that distinction is what this
    file exists to pin, and it still holds.

    The strategy no longer differs, though: the interpretation decides the cause,
    and `internal_contradiction` locates the contradiction inside the predicate
    body without establishing that the requirement body transcribes is sound.
    The `model overconstraint` exception in the REQUIREMENTS_DIAGNOSIS rulebook
    is what routes a genuinely over-strong encoding back to repair.
    """
    escalation = {
        "escalation_level": 3,
        "strategy": REQUIREMENTS_DIAGNOSIS,
        "escalated_issues": ["R6pred"],
        "diagnostics": _stale_diag(),
        "directive": f"ESCALATION LEVEL: 3\nSTRATEGY: {REQUIREMENTS_DIAGNOSIS}\n",
    }
    result = apply_evidence_alignment(escalation, REQ_INTERPRETATION)
    assert result["strategy"] == REQUIREMENTS_DIAGNOSIS
    assert result["diagnostics_per_issue"]["R6pred"] == "internal_contradiction"


def test_gate_still_redirects_when_the_interpretation_does_not_blame_requirements():
    """The one path to model repair that survives: the interpretation itself."""
    escalation = {
        "escalation_level": 3,
        "strategy": REQUIREMENTS_DIAGNOSIS,
        "escalated_issues": ["R6pred"],
        "diagnostics": _stale_diag(),
        "directive": f"ESCALATION LEVEL: 3\nSTRATEGY: {REQUIREMENTS_DIAGNOSIS}\n",
    }
    result = apply_evidence_alignment(
        escalation,
        "=== RESULT INTERPRETATION ===\n"
        "- Likely Cause: Model issue - an overconstraint introduced in the facts.\n",
    )
    assert result["strategy"] == MODEL_OVERCONSTRAINT_REPAIR


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All requirement-change-regeneration tests passed.")
