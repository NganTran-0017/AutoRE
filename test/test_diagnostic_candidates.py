"""
Unit tests for RE Mode 3, Phase 0 - the verbatim InterpretResults experiments are
carried into final feedback as their own DIAGNOSTIC CANDIDATES section instead of
being spliced into REPAIR INSTRUCTIONS.

The guarantee that must survive: the text is never lost. What must change: the RE
no longer reads unadopted candidates as a work order, and REPAIR INSTRUCTIONS
carries only what the Evaluator adopted, in the Evaluator's own words.

Run: python test/test_diagnostic_candidates.py   (from the repo root)
"""

import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.workflow import AutoREWorkflow, DIAGNOSTIC_CANDIDATES_HEADER


FEEDBACK = """=== VERIFICATION SUMMARY ===
Predicate Scenario_MultiEmg_A remains UNSAT.

=== REPAIR INSTRUCTIONS ===
1. Relax CredentialUpdatePerfomedSeq so the flag may reset in the first Normal state.
2. Rerun Scenario_MultiEmg_A.

=== REQUIREMENT UPDATES ===
R6.1: The credential flag resets in the second Normal state.

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE
"""

DIAGNOSTIC_TEXT = """1. Disable EmergencyUnique and rerun Scenario_MultiEmg_A.
2. Relax AdminEligibleForEmergencyTrigger and rerun.
3. Widen the trace scope to 12 and rerun."""


def _make_workflow():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.logger = Mock()
    return wf


def _section(text, header):
    """Content of `header` up to the next ===/##/**/--- section header."""
    import re
    lines = text.split('\n')
    start = next(i for i, l in enumerate(lines) if l.strip() == header)
    out = []
    for line in lines[start + 1:]:
        if re.match(r'^(===|##|\*\*|---)\s', line):
            break
        out.append(line)
    return '\n'.join(out)


def test_repair_instructions_are_untouched():
    """The whole point: adopted work is not diluted by unadopted candidates."""
    wf = _make_workflow()
    out = wf._inject_diagnostic_experiments(FEEDBACK, DIAGNOSTIC_TEXT)

    before = _section(FEEDBACK, "=== REPAIR INSTRUCTIONS ===")
    after = _section(out, "=== REPAIR INSTRUCTIONS ===")
    assert before == after, "REPAIR INSTRUCTIONS must be byte-identical"
    assert "Disable EmergencyUnique" not in after
    assert "Widen the trace scope" not in after
    print("PASS test_repair_instructions_are_untouched")


def test_the_text_still_survives_verbatim():
    """The safety net keeps its guarantee - nothing InterpretResults proposed is lost."""
    wf = _make_workflow()
    out = wf._inject_diagnostic_experiments(FEEDBACK, DIAGNOSTIC_TEXT)

    assert DIAGNOSTIC_CANDIDATES_HEADER in out
    assert DIAGNOSTIC_TEXT in out
    candidates = _section(out, DIAGNOSTIC_CANDIDATES_HEADER)
    for line in DIAGNOSTIC_TEXT.split('\n'):
        assert line in candidates
    print("PASS test_the_text_still_survives_verbatim")


def test_the_section_says_it_is_not_a_work_order():
    """
    Phase 0 ships without prompt changes, so the block itself has to carry the
    instruction. Without this line the move only relocates the hazard.
    """
    wf = _make_workflow()
    out = wf._inject_diagnostic_experiments(FEEDBACK, DIAGNOSTIC_TEXT)
    candidates = _section(out, DIAGNOSTIC_CANDIDATES_HEADER)

    assert "NOT adopted" in DIAGNOSTIC_CANDIDATES_HEADER
    assert "not a work order" in candidates
    assert "Do NOT apply them as model edits." in candidates
    assert "REPAIR INSTRUCTIONS section" in candidates  # points at the real work
    # No line inside the block may start like a section header, or _extract_section
    # would cut the block in half and lose the experiments it exists to preserve.
    for line in candidates.split('\n'):
        assert not line.startswith("==="), line
    print("PASS test_the_section_says_it_is_not_a_work_order")


def test_neighbouring_sections_still_parse():
    """
    The new header must terminate the preceding section for _extract_section, or
    REQUIREMENT UPDATES would swallow the candidates and Step 7 would patch them
    into the requirements document.
    """
    wf = _make_workflow()
    # Candidates land after CONVERGENCE_RECOMMENDATION, but assert the general rule
    # by moving REQUIREMENT UPDATES last.
    trailing = FEEDBACK.split("=== CONVERGENCE_RECOMMENDATION ===")[0]
    out = wf._inject_diagnostic_experiments(trailing, DIAGNOSTIC_TEXT)

    updates = _section(out, "=== REQUIREMENT UPDATES ===")
    assert "R6.1" in updates
    assert "Disable EmergencyUnique" not in updates

    wf2 = _make_workflow()
    out2 = wf2._inject_diagnostic_experiments(FEEDBACK, DIAGNOSTIC_TEXT)
    convergence = _section(out2, "=== CONVERGENCE_RECOMMENDATION ===")
    assert "Status: FALSE" in convergence
    assert "Disable EmergencyUnique" not in convergence
    print("PASS test_neighbouring_sections_still_parse")


def test_no_diagnostics_is_a_no_op():
    wf = _make_workflow()
    assert wf._inject_diagnostic_experiments(FEEDBACK, None) == FEEDBACK
    assert wf._inject_diagnostic_experiments(FEEDBACK, "") == FEEDBACK
    print("PASS test_no_diagnostics_is_a_no_op")


def test_injection_is_idempotent():
    """
    Both call sites are mutually exclusive today, but a second pass over the same
    feedback must not duplicate the block - duplication is the failure mode this
    whole phase exists to remove.
    """
    wf = _make_workflow()
    once = wf._inject_diagnostic_experiments(FEEDBACK, DIAGNOSTIC_TEXT)
    twice = wf._inject_diagnostic_experiments(once, DIAGNOSTIC_TEXT)

    assert once == twice
    assert twice.count(DIAGNOSTIC_CANDIDATES_HEADER) == 1
    print("PASS test_injection_is_idempotent")


def test_missing_repair_instructions_no_longer_a_special_case():
    """
    The old implementation had a separate fallback path when REPAIR INSTRUCTIONS
    was absent. Placement no longer depends on that section existing at all.
    """
    wf = _make_workflow()
    no_repair = "=== VERIFICATION SUMMARY ===\nAll predicates SAT.\n"
    out = wf._inject_diagnostic_experiments(no_repair, DIAGNOSTIC_TEXT)

    assert out.startswith("=== VERIFICATION SUMMARY ===")
    assert DIAGNOSTIC_TEXT in out
    assert out.count(DIAGNOSTIC_CANDIDATES_HEADER) == 1
    print("PASS test_missing_repair_instructions_no_longer_a_special_case")


if __name__ == "__main__":
    test_repair_instructions_are_untouched()
    test_the_text_still_survives_verbatim()
    test_the_section_says_it_is_not_a_work_order()
    test_neighbouring_sections_still_parse()
    test_no_diagnostics_is_a_no_op()
    test_injection_is_idempotent()
    test_missing_repair_instructions_no_longer_a_special_case()
    print("\nAll diagnostic-candidate tests passed.")
