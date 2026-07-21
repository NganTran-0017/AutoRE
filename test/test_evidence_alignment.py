"""
Two-key evidence gate (apply_evidence_alignment): requirements diagnosis is
only mandated when BOTH the InterpretResults causal analysis and the
deterministic diagnostics support a requirement-level cause; otherwise the
level-3 escalation is redirected to MODEL_OVERCONSTRAINT_REPAIR.
"""

import copy

from src.utils.repair_plateau_detector import (
    MODEL_OVERCONSTRAINT_REPAIR,
    REQUIREMENTS_DIAGNOSIS,
    apply_evidence_alignment,
    summarize_diagnostics_evidence,
    summarize_interpretation_cause,
)


# ---------------------------------------------------------------- fixtures #

# Condensed from the real iteration-68 InterpretResults response (071626.log):
# the interpretation attributes the UNSAT collapse to the modeling.
ITER68_INTERPRETATION = """
=== RESULT INTERPRETATION ===
- What: All major predicates are UNSAT.
- Expected vs. Actual: Unexpected regression.
- Likely Cause: Model issue (likely overconstraint or contradiction introduced in facts), with possible requirement issue (latent requirement inconsistency or missing scenario), but primarily a modeling overconstraint.

=== OUTCOME CLASSIFICATION ===
Classification: unintended_regression
Rationale: All run predicates are now UNSAT, indicating a modeling overconstraint.
"""

REQ_INTERPRETATION = """
=== RESULT INTERPRETATION ===
- What: R3 stays UNSAT while everything else is SAT.
- Likely Cause: Requirement issue - a requirement inconsistency between the delegation and revocation rules.

=== OUTCOME CLASSIFICATION ===
Classification: expected_failure
"""

# Iteration-68 diagnostics: internal contradiction + single-requirement
# localization - both modeling evidence.
ITER68_DIAGNOSTICS = {
    "All_Requirements": {
        "scope_sweep": {"performed": True, "sat_at_larger_scope": False},
        "localization": {"verdict": "internal_contradiction", "runs": 1},
    },
    "R1": {
        "scope_sweep": {"performed": True, "sat_at_larger_scope": False},
        "localization": {
            "verdict": "localized",
            "blocking_facts": ["EmergencyTriggerStructure", "DelegationValidity"],
            "implicated_requirements": ["R1"],
        },
    },
}

MULTI_REQ_DIAGNOSTICS = {
    "R3": {
        "scope_sweep": {"performed": True, "sat_at_larger_scope": False},
        "localization": {
            "verdict": "localized",
            "blocking_facts": ["R2R4_DelegationRules"],
            "implicated_requirements": ["R2", "R3", "R4"],
        },
    },
}


def make_escalation(diagnostics=None):
    escalation = {
        "escalation_level": 3,
        "strategy": REQUIREMENTS_DIAGNOSIS,
        "escalated_issues": ["R1", "All_Requirements"],
        "directive": (
            "ESCALATION LEVEL: 3\n"
            f"STRATEGY: {REQUIREMENTS_DIAGNOSIS}\n"
            "PERSISTENT SEMANTIC ISSUES (survived repeated repair attempts):\n"
            "  - unsatisfiable predicate 'R1': present in 3 consecutive iterations"
        ),
    }
    if diagnostics is not None:
        escalation["diagnostics"] = diagnostics
    return escalation


# ------------------------------------------------- interpretation parsing #

def test_interpretation_model_cause():
    summary = summarize_interpretation_cause(ITER68_INTERPRETATION)
    # "Model issue ... possible requirement issue" mentions both -> mixed,
    # which the gate treats as NOT supporting a requirements diagnosis.
    assert summary["cause"] == "mixed"
    assert summary["classification"] == "unintended_regression"
    assert "Model issue" in summary["likely_cause_text"]


def test_interpretation_requirement_cause():
    summary = summarize_interpretation_cause(REQ_INTERPRETATION)
    assert summary["cause"] == "requirement"


def test_interpretation_unknown_and_regression_fallback():
    assert summarize_interpretation_cause("")["cause"] == "unknown"
    assert summarize_interpretation_cause(None)["cause"] == "unknown"
    # No Likely Cause line, but an unintended_regression classification is
    # itself modeling evidence.
    text = "=== OUTCOME CLASSIFICATION ===\nClassification: unintended_regression"
    assert summarize_interpretation_cause(text)["cause"] == "model"


# --------------------------------------------------- diagnostics verdicts #

def test_diagnostics_verdicts():
    summary = summarize_diagnostics_evidence(ITER68_DIAGNOSTICS)
    assert summary["ran"] is True
    assert summary["per_issue"]["All_Requirements"] == "internal_contradiction"
    assert summary["per_issue"]["R1"] == "single_requirement"
    assert summary["modeling_evidence"] is True
    assert summary["requirement_evidence"] is False

    multi = summarize_diagnostics_evidence(MULTI_REQ_DIAGNOSTICS)
    assert multi["per_issue"]["R3"] == "requirement_conflict"
    assert multi["requirement_evidence"] is True

    scope = summarize_diagnostics_evidence({
        "P": {"scope_sweep": {"performed": True, "sat_at_larger_scope": True}}
    })
    assert scope["per_issue"]["P"] == "scope_artifact"
    assert scope["modeling_evidence"] is True

    empty = summarize_diagnostics_evidence(None)
    assert empty["ran"] is False


# --------------------------------------------------------- the gate itself #

def test_iter68_replay_redirects_to_model_repair():
    """The exact iteration-68 scenario must no longer force requirements diagnosis."""
    escalation = make_escalation(ITER68_DIAGNOSTICS)
    result = apply_evidence_alignment(escalation, ITER68_INTERPRETATION)

    assert result["applied"] is True
    assert result["strategy"] == MODEL_OVERCONSTRAINT_REPAIR
    assert escalation["strategy"] == MODEL_OVERCONSTRAINT_REPAIR
    assert f"STRATEGY: {MODEL_OVERCONSTRAINT_REPAIR}" in escalation["directive"]
    assert f"STRATEGY: {REQUIREMENTS_DIAGNOSIS}" not in escalation["directive"]
    assert "EVIDENCE ALIGNMENT" in escalation["directive"]
    assert "MODEL REPAIR REQUIRED" in escalation["directive"]
    # Original persistence evidence must be preserved.
    assert "PERSISTENT SEMANTIC ISSUES" in escalation["directive"]
    assert escalation["evidence_alignment"]["strategy"] == MODEL_OVERCONSTRAINT_REPAIR


def test_both_sources_agree_keeps_requirements_diagnosis():
    escalation = make_escalation(MULTI_REQ_DIAGNOSTICS)
    result = apply_evidence_alignment(escalation, REQ_INTERPRETATION)

    assert result["strategy"] == REQUIREMENTS_DIAGNOSIS
    assert escalation["strategy"] == REQUIREMENTS_DIAGNOSIS
    assert f"STRATEGY: {REQUIREMENTS_DIAGNOSIS}" in escalation["directive"]
    assert "requirements diagnosis AUTHORIZED" in escalation["directive"]


def test_requirement_interpretation_but_modeling_diagnostics():
    """Diagnostics veto: interpretation says requirements, measurements say modeling."""
    escalation = make_escalation(ITER68_DIAGNOSTICS)
    result = apply_evidence_alignment(escalation, REQ_INTERPRETATION)
    assert result["strategy"] == MODEL_OVERCONSTRAINT_REPAIR


def test_no_diagnostics_falls_back_to_interpretation():
    """Counterexample-style escalation: no diagnostics -> interpretation decides."""
    escalation = make_escalation(diagnostics=None)
    result = apply_evidence_alignment(escalation, REQ_INTERPRETATION)
    assert result["strategy"] == REQUIREMENTS_DIAGNOSIS
    assert "unavailable/inconclusive" in escalation["directive"]

    escalation = make_escalation(diagnostics=None)
    result = apply_evidence_alignment(escalation, ITER68_INTERPRETATION)
    assert result["strategy"] == MODEL_OVERCONSTRAINT_REPAIR


def test_unknown_interpretation_means_model_repair():
    escalation = make_escalation(MULTI_REQ_DIAGNOSTICS)
    result = apply_evidence_alignment(escalation, "no structured sections here")
    assert result["strategy"] == MODEL_OVERCONSTRAINT_REPAIR


def test_not_escalated_is_untouched():
    escalation = {"escalation_level": 0, "strategy": "STANDARD_REPAIR", "directive": ""}
    before = copy.deepcopy(escalation)
    result = apply_evidence_alignment(escalation, REQ_INTERPRETATION)
    assert result["applied"] is False
    assert escalation == before


def test_best_effort_on_malformed_input():
    # A broken escalation object must not raise.
    result = apply_evidence_alignment(None, REQ_INTERPRETATION)
    assert result["applied"] is False
    result = apply_evidence_alignment({"escalation_level": "bad"}, None)
    assert result["applied"] is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All evidence-alignment tests passed.")
