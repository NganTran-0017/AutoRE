"""
The ownership audit must actually REACH the Evaluator.

Three prompt edits ask it to name the requirement a fact encodes, to map an
UNSAT blocker to a requirement, and to treat a pruned construct as deliberate.
All three are inert unless the audit and the removal log are in the prompt -
and a section carrying {{ownership_audit}} without the variable being supplied
raises ValueError, taking the whole interpretation down.
"""

from unittest.mock import Mock

import pytest

from src.utils.construct_removal_log import ConstructRemovalEntry, ConstructRemovalLog
from src.utils.prompt_manager import PromptManager
from src.utils.traceability_store import (
    audit_model,
    format_ownership_for_prompt,
    format_ownership_report,
)


MODEL = """
fact R1_ModeExclusive { all s: State | one s.mode }
fact E5_RequestProcessorAudit { all r: Request | some r.audit }
fact UndeclaredFact { all s: State | one s.t }
assert assertUnlabelled { all s: State | some s.mode }
check assertUnlabelled for 4
"""

REQUIREMENTS = """
PROSPECTIVE FUNCTIONAL REQUIREMENTS
R1: The system shall have exactly one mode per state.
EXISTING-SYSTEM REQUIREMENTS AND CONSTRAINTS
E1: Users hold a clearance.
"""


def _audit():
    # E5 is absent from the requirements -> its fact is an orphan.
    return audit_model(MODEL, REQUIREMENTS)


# ------------------------------------------------------ the composed block #

def test_block_names_the_orphan_and_its_dead_requirement():
    block = format_ownership_for_prompt(_audit())
    assert "E5_RequestProcessorAudit" in block
    assert "declared E5" in block


def test_block_tells_the_evaluator_to_remove_not_weaken():
    block = format_ownership_for_prompt(_audit())
    assert "NOT over-restrictive constraints to weaken" in block


def test_block_says_undeclared_checks_are_not_defects():
    # The assertion correction: an exploratory check may encode no requirement.
    block = format_ownership_for_prompt(_audit())
    assert "not a defect" in block


def test_block_omits_check_names_to_save_tokens():
    # The count stays in the summary line; the names are the largest and least
    # actionable bucket, so they are dropped from the prompt rendering.
    audit = _audit()
    assert "assertUnlabelled" in format_ownership_report(audit)
    assert "assertUnlabelled" not in format_ownership_for_prompt(audit)


def test_block_is_honest_when_the_audit_is_missing():
    block = format_ownership_for_prompt(None)
    assert "unavailable" in block
    # It must not silently look like a clean audit.
    assert "ORPHAN" not in block


def test_removals_are_appended_to_the_block(tmp_path):
    log = ConstructRemovalLog(log_path=tmp_path / "r.json")
    log.add_entry(ConstructRemovalEntry(
        iteration_id=65,
        removed=["E5_RequestProcessorAudit"],
        kinds={"E5_RequestProcessorAudit": "fact"},
        orphan_owners={"E5_RequestProcessorAudit": ["E5"]},
    ))
    block = format_ownership_for_prompt(_audit(), removals=log.format_for_prompt())
    assert "DELETED DELIBERATELY" in block


# ------------------------------------------------ prompts actually render #

def test_interpret_results_prompt_renders_with_the_audit():
    # Guards the ValueError path: the section declares {{ownership_audit}}, so
    # every caller must supply it.
    pm = PromptManager()
    prompt = pm.render_prompt(
        agent_name="Evaluator",
        action_name="InterpretResults",
        analyzer_results="", requirements_document=REQUIREMENTS,
        alloy_model=MODEL, regression_log="",
        ownership_audit=format_ownership_for_prompt(_audit()),
        user_preferences="",
    )
    assert "E5_RequestProcessorAudit" in prompt
    # and the relocated clause landed in the section that diagnoses regressions
    assert "deleted deliberately" in prompt.lower()


def test_vacuity_section_renders_with_the_audit():
    pm = PromptManager()
    section = pm.get_section("Evaluator", "VacuityAnalysis")
    assert "{{ownership_audit}}" in section
    rendered = pm._substitute_variables(section, {
        "analyzer_results": "", "alloy_model": MODEL,
        "requirements_document": REQUIREMENTS,
        "ownership_audit": format_ownership_for_prompt(_audit()),
    })
    assert "E5_RequestProcessorAudit" in rendered
    # the Encodes field the audit exists to make answerable
    assert "Encodes:" in rendered


def test_unsat_section_defers_to_the_base_prompt_block():
    # Appended to the base prompt, which already carries the block - it must
    # reference it, not re-declare the variable and duplicate it per request.
    section = PromptManager().get_section("Evaluator", "InterpretUNSATPred")
    assert "{{ownership_audit}}" not in section
    assert "Construct Ownership section above" in section


def test_semantic_feedback_section_does_not_carry_the_block():
    # It consumes {{interpretation}} and is told not to re-diagnose; the
    # ownership conclusion reaches it through the interpretation instead.
    section = PromptManager().get_section("Evaluator", "GenerateSemanticFeedback")
    assert "{{ownership_audit}}" not in section


# -------------------------------------------------------- action plumbing #

def _action():
    from src.actions.evaluation_actions import InterpretResults

    action = InterpretResults.__new__(InterpretResults)
    ctx = Mock()
    ctx.ownership_audit = None
    ctx.construct_removal_log = None
    object.__setattr__(action, "_ctx", ctx)
    return action, ctx


def test_action_recomputes_the_audit_when_the_context_has_none(monkeypatch):
    # True on the first iteration and after every resume, when step 8 has not
    # yet run to populate context.ownership_audit.
    action, ctx = _action()
    monkeypatch.setattr(type(action), "context", property(lambda self: self._ctx))
    monkeypatch.setattr(type(action), "_debug", lambda self, m: None)

    block = action._format_ownership_context(MODEL, REQUIREMENTS)
    assert "E5_RequestProcessorAudit" in block


def test_action_never_breaks_the_interpretation(monkeypatch):
    action, ctx = _action()
    ctx.ownership_audit = "not-an-audit"      # forces a failure downstream
    monkeypatch.setattr(type(action), "context", property(lambda self: self._ctx))
    monkeypatch.setattr(type(action), "_debug", lambda self, m: None)

    block = action._format_ownership_context(MODEL, REQUIREMENTS)
    assert "unavailable" in block


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
