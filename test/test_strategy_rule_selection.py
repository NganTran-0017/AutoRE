"""The escalation section ships one rulebook, not two.

`[SECTION: PersistentIssueEscalation]` carries a binding-rules block for
REQUIREMENTS_DIAGNOSIS and one for MODEL_OVERCONSTRAINT_REPAIR, and they
contradict each other on every point: one MANDATES the `REQUIREMENT UPDATES`
entries the other FORBIDS. Which applies was already decided deterministically
by `apply_evidence_alignment` before the prompt is built, so sending both hands
the model an opposed pair plus a pointer - a resolution step it can get wrong,
on every escalated iteration.

These tests pin the selection and, more importantly, the cases where it must
refuse to select: an unchanged section is the pre-existing behaviour, so the
fallback is never worse than not selecting at all.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.prompt_manager import PromptManager
from src.utils.repair_plateau_detector import (
    MODEL_OVERCONSTRAINT_REPAIR,
    REGENERATE_PREDICATES,
    REQUIREMENTS_DIAGNOSIS,
    select_binding_rules,
    strategy_from_directive,
)

REQ_HEADER = "**BINDING RULES when STRATEGY is REQUIREMENTS_DIAGNOSIS"
MODEL_HEADER = "**BINDING RULES when STRATEGY is MODEL_OVERCONSTRAINT_REPAIR"
POINTER = "Read ONLY the block matching the STRATEGY line above"


def _section() -> str:
    return PromptManager().get_section("Evaluator", "PersistentIssueEscalation")


def _directive(strategy: str) -> str:
    return (
        "ESCALATION LEVEL: 3\n"
        f"STRATEGY: {strategy}\n"
        "PERSISTENT SEMANTIC ISSUES (survived repeated repair attempts):\n"
        "  - unsatisfiable predicate 'All_Requirements': present in 3 consecutive"
        " syntactically-valid iterations\n"
    )


# ------------------------------------------------------------------ selection #

def test_the_section_really_does_carry_two_opposed_rulebooks():
    """If this ever stops holding, the selection below is solving nothing."""
    section = _section()
    assert REQ_HEADER in section and MODEL_HEADER in section
    # The contradiction that makes shipping both a defect.
    assert "MUST contain an entry" in section
    assert "Do NOT add entries to `=== POTENTIAL REQUIREMENT ISSUES ===`" in section


def test_a_requirements_diagnosis_sends_only_the_requirements_rulebook():
    out = select_binding_rules(_section(), _directive(REQUIREMENTS_DIAGNOSIS))
    assert REQ_HEADER in out
    assert MODEL_HEADER not in out


def test_a_model_repair_sends_only_the_model_repair_rulebook():
    out = select_binding_rules(_section(), _directive(MODEL_OVERCONSTRAINT_REPAIR))
    assert MODEL_HEADER in out
    assert REQ_HEADER not in out


def test_the_pointer_to_the_other_block_goes_with_it():
    """'Read ONLY the block matching the STRATEGY line' describes a choice that
    no longer exists once one block is left; leaving it invites the model to
    hunt for a second block that is not there."""
    out = select_binding_rules(_section(), _directive(MODEL_OVERCONSTRAINT_REPAIR))
    assert POINTER not in out


def test_selection_actually_removes_tokens():
    section = _section()
    for strategy in (REQUIREMENTS_DIAGNOSIS, MODEL_OVERCONSTRAINT_REPAIR):
        assert len(select_binding_rules(section, _directive(strategy))) < len(section)


# --------------------------------------------------- what survives regardless #

def test_the_shared_rules_and_the_evidence_placeholder_survive():
    """Everything above the two blocks applies under either strategy - the
    evidence itself, the scope note, and the forbidden list hoisted out of both
    rulebooks. Dropping any of it would be a behaviour change, not a saving."""
    for strategy in (REQUIREMENTS_DIAGNOSIS, MODEL_OVERCONSTRAINT_REPAIR):
        out = select_binding_rules(_section(), _directive(strategy))
        assert "{{persistence_status}}" in out          # still substitutable
        assert "**SCOPE OF THE STRATEGY:**" in out
        assert "FORBIDDEN RESPONSES for the escalated issues, under BOTH" in out
        assert "UNOWNED BLOCKING FACTS" in out          # required under every strategy


# -------------------------------------------------------- refusing to select #

def test_a_directive_naming_no_strategy_changes_nothing():
    assert select_binding_rules(_section(), "ESCALATION LEVEL: 3\n") == _section()
    assert select_binding_rules(_section(), "") == _section()
    assert select_binding_rules(_section(), None) == _section()


def test_two_disagreeing_strategies_keep_both_rulebooks():
    """_stage_stall_diagnosis appends its own REQUIREMENTS_DIAGNOSIS block to an
    escalation the evidence gate may have redirected to model repair. Both
    rulebooks then genuinely apply, to different issues - this is a real state
    of the run, not a parse failure, and dropping either would lose rules."""
    directive = (
        _directive(MODEL_OVERCONSTRAINT_REPAIR)
        + "\n\n"
        + _directive(REQUIREMENTS_DIAGNOSIS)
    )
    assert strategy_from_directive(directive) is None
    out = select_binding_rules(_section(), directive)
    assert REQ_HEADER in out and MODEL_HEADER in out


def test_a_strategy_with_no_rulebook_changes_nothing():
    """The syntax-ladder strategies ride the same STRATEGY: line but no block in
    this section is written for them, so there is nothing to select between."""
    out = select_binding_rules(_section(), _directive(REGENERATE_PREDICATES))
    assert out == _section()


def test_a_repeated_agreeing_strategy_still_selects():
    directive = _directive(REQUIREMENTS_DIAGNOSIS) + _directive(REQUIREMENTS_DIAGNOSIS)
    assert strategy_from_directive(directive) == REQUIREMENTS_DIAGNOSIS
    assert MODEL_HEADER not in select_binding_rules(_section(), directive)


def test_a_strategy_named_mid_line_is_not_read_as_the_verdict():
    """Fix intents quote strategy names in prose ("REGENERATE_PREDICATES strategy
    triggered by..."). Only a line that IS the STRATEGY declaration counts."""
    directive = (
        _directive(REQUIREMENTS_DIAGNOSIS)
        + "      - Fix Intent: STRATEGY: MODEL_OVERCONSTRAINT_REPAIR was tried\n"
    )
    # The prose line is indented, so it strips to a STRATEGY: declaration and
    # disagrees - the safe answer is to send both, never to pick the prose one.
    assert strategy_from_directive(directive) != MODEL_OVERCONSTRAINT_REPAIR


def test_a_section_without_two_blocks_is_returned_untouched():
    assert select_binding_rules("no rulebooks here", _directive(REQUIREMENTS_DIAGNOSIS)) \
        == "no rulebooks here"
    assert select_binding_rules("", _directive(REQUIREMENTS_DIAGNOSIS)) == ""


# ------------------------------------------------------------ delivered shape #

def test_the_selected_section_still_reads_as_one_document():
    out = select_binding_rules(_section(), _directive(MODEL_OVERCONSTRAINT_REPAIR))
    assert "\n\n\n" not in out          # no hole where the dropped block was
    assert out.endswith("\n")
    assert out.index("{{persistence_status}}") < out.index(MODEL_HEADER)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All strategy-rule-selection tests passed.")
