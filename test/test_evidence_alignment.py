"""
Evidence gate (apply_evidence_alignment) over a level-3 semantic escalation.

The InterpretResults causal analysis decides: requirements diagnosis is
mandated whenever it attributes the failure to the requirements, and the
escalation is redirected to MODEL_OVERCONSTRAINT_REPAIR whenever it does not
(cause `model`, `mixed`, or `unknown`).

The deterministic diagnostics corroborate but do not veto. Their `modeling`
verdicts establish WHERE the contradiction sits - inside a predicate body, or
below the bounds - which is not the same question as whether the requirement
that body transcribes is sound.
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

# Iteration-68 diagnostics: internal contradiction (modeling) + single-requirement
# localization (now REQUIREMENT evidence: a requirement can be self-inconsistent).
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

# Purely modeling diagnostics (no requirement evidence) - for the veto test.
MODELING_ONLY_DIAGNOSTICS = {
    "All_Requirements": {
        "scope_sweep": {"performed": True, "sat_at_larger_scope": False},
        "localization": {"verdict": "internal_contradiction", "runs": 1},
    },
}

# A single internally-inconsistent requirement (localized to exactly one R#).
SINGLE_REQ_DIAGNOSTICS = {
    "R1": {
        "scope_sweep": {"performed": True, "sat_at_larger_scope": False},
        "localization": {
            "verdict": "localized",
            "blocking_facts": ["R1_Structure"],
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
    # internal_contradiction is modeling; single_requirement is now REQUIREMENT
    # evidence (a requirement can be internally inconsistent), so both are present.
    assert summary["modeling_evidence"] is True
    assert summary["requirement_evidence"] is True

    # A lone single-requirement localization is requirement evidence, not modeling.
    single = summarize_diagnostics_evidence(SINGLE_REQ_DIAGNOSTICS)
    assert single["per_issue"]["R1"] == "single_requirement"
    assert single["requirement_evidence"] is True
    assert single["modeling_evidence"] is False

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


def test_requirement_interpretation_survives_modeling_diagnostics():
    """The sources disagree, and the interpretation wins.

    `internal_contradiction` means the predicate is UNSAT with every fact
    disabled - it establishes that the contradiction sits inside the predicate
    body, not that the requirement that body transcribes is sound. A predicate
    faithfully encoding a self-contradictory requirement measures exactly this
    way, so reading it as a refutation buried the requirement defect the
    interpretation was reporting. The two remaining risks are handled in the
    prompt, not here: a scope artifact is overridden per issue by the
    DETERMINISTIC DIAGNOSIS block, and a genuinely over-strong encoding is
    routed out by the `model overconstraint` exception in rule 2.
    """
    escalation = make_escalation(MODELING_ONLY_DIAGNOSTICS)
    result = apply_evidence_alignment(escalation, REQ_INTERPRETATION)
    assert result["strategy"] == REQUIREMENTS_DIAGNOSIS
    assert "not whether the requirement" in result["reason"]
    assert "requirements diagnosis AUTHORIZED" in escalation["directive"]


def test_only_the_interpretation_can_redirect_to_model_repair():
    """The gate is now one-sided: no diagnostics verdict produces model repair
    while the interpretation reads requirement-level. Pin that, so a future
    verdict added to the `modeling` set cannot silently restore the veto."""
    for diagnostics in (
        MODELING_ONLY_DIAGNOSTICS, SINGLE_REQ_DIAGNOSTICS,
        MULTI_REQ_DIAGNOSTICS, ITER68_DIAGNOSTICS, None,
    ):
        escalation = make_escalation(diagnostics)
        result = apply_evidence_alignment(escalation, REQ_INTERPRETATION)
        assert result["strategy"] == REQUIREMENTS_DIAGNOSIS, diagnostics


def test_a_scope_artifact_still_reaches_the_evaluator_as_measured():
    """Requirements diagnosis no longer suppresses it, so the prompt's per-issue
    override is the only thing standing between a bounded-search artifact and a
    requirement rewrite. The verdict must therefore survive into the directive."""
    escalation = make_escalation({
        "R1": {
            "scope_sweep": {"performed": True, "sat_at_larger_scope": True,
                            "swept_command": "run R1 for 12"},
            "localization": {},
        },
    })
    result = apply_evidence_alignment(escalation, REQ_INTERPRETATION)
    assert result["strategy"] == REQUIREMENTS_DIAGNOSIS
    assert result["diagnostics_per_issue"]["R1"] == "scope_artifact"
    assert "SAT at enlarged bounds" in escalation["directive"]


def test_single_requirement_is_requirement_evidence():
    """A single internally-inconsistent requirement authorizes requirements diagnosis."""
    escalation = make_escalation(SINGLE_REQ_DIAGNOSTICS)
    result = apply_evidence_alignment(escalation, REQ_INTERPRETATION)
    assert result["strategy"] == REQUIREMENTS_DIAGNOSIS


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
