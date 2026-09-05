"""
Two discipline rules over the ownership audit.

Rule 1 - a `fact` may only encode an existing-system requirement (E#) or a
promoted assumption. A fact declaring a prospective requirement (R#) is wrong by
construction, live owner or not: R# is modelled as a predicate/assertion.

Rule 2 - a fact that declares nothing AND provably blocks an UNSAT predicate has
no defensible status. Neither signal alone is actionable (a dozen facts block any
scenario; a dozen declare nothing); the intersection is.
"""

from unittest.mock import Mock

import pytest

from src.utils.traceability_store import (
    audit_ownership,
    find_unowned_blockers,
    format_ownership_for_prompt,
    format_unowned_blockers,
)
from src.workflow import AutoREWorkflow


MODEL = """
fact E1_ClearanceAssignment { all u: User | one u.clearance }
fact R4_EmergencyAccess { all s: State | s.mode = EmergencyMode implies some s.responders }
fact EmergencyUnique { all disj s1, s2: State | s1.mode != EmergencyMode }
fact UniqueTimePerState { all disj s1, s2: State | s1.t != s2.t } //@req none:frame
pred Scenario_SecondEmergency[s: State] { some s }
run Scenario_SecondEmergency for 4
"""


def _audit(live=('E1', 'R4')):
    return audit_ownership(MODEL, set(live))


# --------------------------------------------- Rule 1: R# must not be a fact #

def test_fact_declaring_a_prospective_requirement_is_a_violation():
    audit = _audit()
    assert audit['discipline_violations'] == {'R4_EmergencyAccess': ['R4']}


def test_violation_holds_even_though_the_requirement_is_live():
    # R4 IS in the live set - the fact is still wrong, because the defect is the
    # construct KIND, not a dead owner. This is what ownership alone cannot see.
    audit = _audit()
    assert 'R4_EmergencyAccess' in audit['declared']
    assert 'R4_EmergencyAccess' in audit['discipline_violations']


def test_existing_system_fact_is_not_a_violation():
    assert 'E1_ClearanceAssignment' not in _audit()['discipline_violations']


def test_assertion_declaring_a_prospective_requirement_is_fine():
    # R# belongs in predicates and assertions - only `fact` is restricted.
    audit = audit_ownership(
        "assert assertR4Safety { all s: State | some s }\ncheck assertR4Safety for 4\n",
        {'R4'},
    )
    assert audit['discipline_violations'] == {}


def test_violations_are_excluded_from_the_total_sum_invariant():
    s = _audit()['summary']
    assert s['total'] == sum(
        s[k] for k in ('declared', 'derived', 'ownerless', 'orphan', 'dead',
                       'unclassified', 'undeclared_checks')
    )
    assert s['discipline_violations'] == 1


def test_report_tells_the_agent_to_convert_not_delete():
    from src.utils.traceability_store import format_ownership_report
    report = format_ownership_report(_audit())
    assert "DISCIPLINE VIOLATION" in report
    assert "convert to pred/assert" in report


# ------------------------------------- Rule 2: undeclared AND proven blocking #

DIAGNOSTICS = {
    "Scenario_SecondEmergency": {"localization": {
        "verdict": "localized",
        "blocking_facts": ["EmergencyUnique", "E1_ClearanceAssignment", "UniqueTimePerState"],
    }},
}


def test_join_keeps_only_facts_that_are_both_undeclared_and_blocking():
    blockers = find_unowned_blockers(_audit(), DIAGNOSTICS)
    assert list(blockers) == ["EmergencyUnique"]
    # declared E# fact: blocking is legitimate, it encodes a real constraint
    assert "E1_ClearanceAssignment" not in blockers
    # declared none:frame: blocking is legitimate and intentional
    assert "UniqueTimePerState" not in blockers


def test_undeclared_fact_that_blocks_nothing_is_not_flagged():
    audit = _audit()
    assert "EmergencyUnique" in audit['unclassified']
    assert find_unowned_blockers(audit, {"Other": {"localization": {"blocking_facts": []}}}) == {}


def test_blocked_predicates_are_listed_per_fact():
    diag = dict(DIAGNOSTICS)
    diag["Scenario_Recovery"] = {"localization": {"blocking_facts": ["EmergencyUnique"]}}
    assert find_unowned_blockers(_audit(), diag)["EmergencyUnique"] == [
        "Scenario_SecondEmergency", "Scenario_Recovery"
    ]


def test_most_implicated_fact_is_ranked_first():
    audit = audit_ownership(
        "fact AAA_Undeclared { some s: State | some s }\n"
        "fact ZZZ_Undeclared { some s: State | some s }\n", set()
    )
    diag = {
        "P1": {"localization": {"blocking_facts": ["AAA_Undeclared", "ZZZ_Undeclared"]}},
        "P2": {"localization": {"blocking_facts": ["ZZZ_Undeclared"]}},
    }
    # ZZZ blocks 2, AAA blocks 1 - ranking beats alphabetical order.
    assert list(find_unowned_blockers(audit, diag)) == ["ZZZ_Undeclared", "AAA_Undeclared"]


def test_join_is_empty_without_either_input():
    assert find_unowned_blockers(None, DIAGNOSTICS) == {}
    assert find_unowned_blockers(_audit(), None) == {}


# ------------------------------------------------------------- rendering #

def _section(name):
    from src.utils.prompt_manager import PromptManager
    return PromptManager().get_section("Evaluator", name)


def _fresh_finding(blockers, streaks=None):
    """What the FEEDBACK step sees: the measured data plus the rules that the
    Evaluator prompt now owns. The rules used to be built in Python; they moved
    to `[SECTION: UnownedBlockingFacts]` so they can be edited in the prompt."""
    return (format_unowned_blockers(blockers, streaks)
            + "\n\n" + _section("UnownedBlockingFacts"))


def _interpretation_prompt_section():
    """How the interpretation is told to read the finding - it is part of the
    InterpretResults procedure now, not a separate appended section."""
    return _section("InterpretResults")


def test_finding_states_the_four_valid_resolutions():
    text = _fresh_finding(find_unowned_blockers(_audit(), DIAGNOSTICS))
    assert "EmergencyUnique blocks Scenario_SecondEmergency" in text
    # Classifications, NOT the RE's annotation syntax - how a construct is
    # declared or moved is the RE's decision, not the Evaluator's.
    for resolution in ("existing-system requirement", "structural well-formedness",
                       "scope/universe setup", "does not belong in a fact", "delete"):
        assert resolution in text
    assert "never weaken it" in text


def test_finding_leads_the_ownership_block():
    # It is the highest-signal line available; a flat bucket list below it is
    # what the Evaluator previously had to guess from.
    block = format_ownership_for_prompt(
        _audit(), blockers=find_unowned_blockers(_audit(), DIAGNOSTICS))
    assert block.index("UNOWNED BLOCKING FACTS") < block.index("OWNERSHIP AUDIT:")


def test_block_is_unchanged_when_nothing_is_flagged():
    assert "UNOWNED BLOCKING" not in format_ownership_for_prompt(_audit(), blockers={})


# -------------------------------------------------------- workflow wiring #

def test_workflow_appends_the_finding_to_the_escalation_directive():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.ownership_audit = _audit()
    wf.logger = Mock()
    wf.context.prompt_manager.get_section.return_value = "<rules>"
    escalation = {"directive": "existing directive text"}

    wf._flag_unowned_blockers(escalation, DIAGNOSTICS, MODEL)

    assert "existing directive text" in escalation["directive"]
    assert "EmergencyUnique" in escalation["directive"]
    assert escalation["unowned_blockers"] == {"EmergencyUnique": ["Scenario_SecondEmergency"]}


def test_workflow_recomputes_the_audit_when_absent():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.ownership_audit = None          # true after a resume
    wf.context.artifacts.get_latest_requirements.return_value = "E1: clearance"
    wf.logger = Mock()
    wf.context.prompt_manager.get_section.return_value = "<rules>"
    escalation = {"directive": ""}

    wf._flag_unowned_blockers(escalation, DIAGNOSTICS, MODEL)
    assert "EmergencyUnique" in escalation["directive"]


def test_flagging_failure_never_breaks_diagnostics():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.ownership_audit = "not-an-audit"
    wf.logger = Mock()
    wf.context.prompt_manager.get_section.return_value = "<rules>"
    escalation = {"directive": "untouched"}

    wf._flag_unowned_blockers(escalation, DIAGNOSTICS, MODEL)   # must not raise
    assert escalation["directive"] == "untouched"


# ----------------------------------------- persistence: guidance with teeth #
#
# The finding says "resolve every one before proposing any other repair". Said
# once, that is an instruction with no compliance check - which is how the stale
# fact survived being flagged the first time and got weakened instead. Three
# mechanisms close that: a streak that distinguishes "not seen yet" from "seen
# and declined", a required output block, and a parse that reads back what the
# agent actually decided.

from src.utils.traceability_store import (          # noqa: E402
    BLOCKER_DECISION_HEADING,
    missing_blocker_decisions,
    parse_blocker_decisions,
    track_blocker_persistence,
)


def test_first_sighting_has_a_streak_of_one():
    assert track_blocker_persistence({"EmergencyUnique": ["P1"]}, []) == {"EmergencyUnique": 1}


def test_streak_counts_consecutive_prior_flaggings():
    history = [{"EmergencyUnique": ["P1"]}, {"EmergencyUnique": ["P1"]}]
    assert track_blocker_persistence({"EmergencyUnique": ["P1"]}, history) == {
        "EmergencyUnique": 3
    }


def test_a_gap_resets_the_streak():
    # The intervening iteration did NOT flag it, so the agent demonstrably acted;
    # a later regression is a fresh problem, not a second refusal.
    history = [{"EmergencyUnique": ["P1"]}, {"Other": ["P2"]}, {"EmergencyUnique": ["P1"]}]
    assert track_blocker_persistence({"EmergencyUnique": ["P1"]}, history) == {
        "EmergencyUnique": 2
    }


def test_first_sighting_gets_no_escalation_language():
    text = format_unowned_blockers({"EmergencyUnique": ["P1"]}, {"EmergencyUnique": 1})
    assert "UNRESOLVED" not in text
    assert "ESCALATION" not in text


def test_persistent_blocker_is_told_not_to_repeat_the_failed_instruction():
    text = _fresh_finding({"EmergencyUnique": ["P1"]}, {"EmergencyUnique": 2})
    assert "UNRESOLVED for 2 consecutive iterations" in text
    assert "ESCALATION: EmergencyUnique" in text
    assert "do not repeat it" in text.lower()
    assert "different resolution" in text.lower()


def test_finding_supplies_criteria_for_choosing_among_the_four_resolutions():
    # Four options with no way to choose between them is not guidance.
    text = _fresh_finding({"EmergencyUnique": ["P1"]})
    for cue in ("EXISTING system already guarantees", "well-formedness",
                "scope or universe setup", "PROSPECTIVE component"):
        assert cue in text


def test_finding_names_the_section_the_decision_must_be_recorded_in():
    text = _fresh_finding({"EmergencyUnique": ["P1"]})
    assert BLOCKER_DECISION_HEADING in text


# ------------------------------------------------ reading back what was decided #

FEEDBACK = f"""
=== NEXT ACTION DECISION ===
Decision: refine/narrow fix

{BLOCKER_DECISION_HEADING}
- Fact: EmergencyUnique
- Resolution: delete
- Requirement: none
- Rationale: it encodes a superseded original requirement.
- Fact: UniqueTimePerState
- Resolution: declare none:frame
- Requirement: none
- Rationale: structural well-formedness of the time ordering.

=== REPAIR INSTRUCTIONS ===
- Fact: NotADecision
"""


def test_decisions_are_parsed_with_their_resolutions():
    assert parse_blocker_decisions(FEEDBACK) == {
        "EmergencyUnique": "delete",
        "UniqueTimePerState": "declare none:frame",
    }


def test_parsing_stops_at_the_next_section_heading():
    # A `Fact:` line in REPAIR INSTRUCTIONS must not count as a decision.
    assert "NotADecision" not in parse_blocker_decisions(FEEDBACK)


def test_omitted_fact_is_reported_as_undecided():
    blockers = {"EmergencyUnique": ["P1"], "AtLeastTwoAdmins": ["P1"], "UniqueTimePerState": ["P2"]}
    assert missing_blocker_decisions(blockers, FEEDBACK) == ["AtLeastTwoAdmins"]


def test_nothing_is_missing_when_every_fact_was_decided():
    blockers = {"EmergencyUnique": ["P1"], "UniqueTimePerState": ["P2"]}
    assert missing_blocker_decisions(blockers, FEEDBACK) == []


def test_feedback_without_the_section_leaves_every_fact_undecided():
    assert missing_blocker_decisions({"EmergencyUnique": ["P1"]}, "=== REPAIR INSTRUCTIONS ===\nnone") == [
        "EmergencyUnique"
    ]


# --------------------------------------------------- workflow wiring (items 1+3) #

def _entry(iteration_id, blockers):
    entry = Mock()
    entry.iteration_id = iteration_id
    entry.repair_escalation = {"unowned_blockers": blockers} if blockers is not None else None
    return entry


def test_history_comes_from_the_regression_log_most_recent_first():
    # Persisted and resume-trimmed already, so a streak cannot count iterations
    # that a rewind discarded.
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.iteration.current = 5
    wf.context.regression_log.entries = [
        _entry(3, {"A": ["P"]}), _entry(4, {"B": ["P"]}), _entry(5, {"C": ["P"]}),
    ]
    assert wf._collect_blocker_history() == [{"B": ["P"]}, {"A": ["P"]}]


def test_history_tolerates_entries_without_an_escalation():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.iteration.current = 3
    wf.context.regression_log.entries = [_entry(1, None), _entry(2, {"A": ["P"]})]
    assert wf._collect_blocker_history() == [{"A": ["P"]}, {}]


def test_workflow_records_the_streak_on_the_escalation():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.ownership_audit = _audit()
    wf.context.iteration.current = 4
    wf.context.regression_log.entries = [_entry(3, {"EmergencyUnique": ["P"]})]
    wf.logger = Mock()
    wf.context.prompt_manager.get_section.return_value = "<rules>"
    escalation = {"directive": ""}

    wf._flag_unowned_blockers(escalation, DIAGNOSTICS, MODEL)

    assert escalation["unowned_blocker_streaks"] == {"EmergencyUnique": 2}
    assert "UNRESOLVED for 2 consecutive iterations" in escalation["directive"]


def test_workflow_does_not_touch_the_escalation_level():
    # This path is only reachable from the already-escalated branch, so the
    # level is > 0 by construction; raising it here would be a silent no-op that
    # implies a gate this method does not control.
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.ownership_audit = _audit()
    wf.context.iteration.current = 1
    wf.context.regression_log.entries = []
    wf.logger = Mock()
    wf.context.prompt_manager.get_section.return_value = "<rules>"
    escalation = {"directive": "", "escalation_level": 3}

    wf._flag_unowned_blockers(escalation, DIAGNOSTICS, MODEL)
    assert escalation["escalation_level"] == 3


def test_undecided_blockers_are_reported_after_feedback():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.unowned_blockers = {"EmergencyUnique": ["P1"], "AtLeastTwoAdmins": ["P1"]}
    wf.context.unowned_blockers_iteration = 7
    wf.context.iteration.current = 7
    wf.logger = Mock()

    wf._check_blocker_decisions(FEEDBACK)

    logged = " ".join(str(c) for c in wf.logger.log.call_args_list)
    assert "AtLeastTwoAdmins" in logged
    assert "no decision recorded" in logged


def test_decision_check_is_silent_when_nothing_was_flagged():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.unowned_blockers = {}
    wf.logger = Mock()

    wf._check_blocker_decisions(FEEDBACK)
    wf.logger.log.assert_not_called()


# ------------------------------------------------------ prompt delivery (item 2) #

def _evaluator_prompt():
    from pathlib import Path
    return Path("prompts/Evaluator_prompt.txt").read_text()


def test_evaluator_does_not_prescribe_the_res_annotation_syntax():
    # Encoding a requirement is the RE's job. The Evaluator classifies what a
    # fact IS; it must not hand the RE `//@req` tokens to write, and it must not
    # be taught that syntax as a standing instruction.
    rules = _section("UnownedBlockingFacts")
    for token in ("//@req", "none:frame", "none:harness", "none:probe"):
        assert token not in rules, f"{token} leaked into the Evaluator's decision rules"
    fmt = _evaluator_prompt().split("[SECTION: ResponseFormatFeedback]", 1)[1]
    resolution = [l for l in fmt.splitlines() if l.startswith("- Resolution:")][0]
    assert "//@req" not in resolution and "none:frame" not in resolution


def test_response_format_requires_a_decision_per_flagged_fact():
    prompt = _evaluator_prompt()
    assert BLOCKER_DECISION_HEADING in prompt
    assert "One entry for EACH fact listed under UNOWNED BLOCKING FACTS" in prompt


def test_decisions_are_requested_before_repair_instructions():
    prompt = _evaluator_prompt()
    fmt = prompt.split("[SECTION: ResponseFormatFeedback]", 1)[1]
    assert fmt.index(BLOCKER_DECISION_HEADING) < fmt.index("=== REPAIR INSTRUCTIONS ===")


# --------------------------------------------- the interpretation's copy is a prior #

BLOCKERS = {"EmergencyUnique": ["Scenario_MultiEmg_4_trace"]}


def test_the_interpretation_is_told_how_to_read_the_finding():
    """The read-rules live in the InterpretResults procedure (step 1), so no
    separate 'prior' section is appended - and nothing labels the list stale."""
    section = _interpretation_prompt_section()
    assert "UNOWNED BLOCKING FACTS" in section
    assert "PROVEN to block" in section
    assert "structural well-formedness" in section
    assert "scope setup" in section


def test_no_stale_variant_survives():
    """Localization runs BEFORE InterpretResults, so a list rendered for it was
    measured against the model it is shown with. There is nothing to label."""
    import inspect
    from src.utils import traceability_store
    assert "stale" not in inspect.signature(
        traceability_store.format_unowned_blockers).parameters
    prompt = _evaluator_prompt()
    assert "UnownedBlockingFactsPrior" not in prompt
    assert "PRIOR" not in format_unowned_blockers(BLOCKERS)


def test_the_finding_still_forbids_weakening():
    text = _fresh_finding(BLOCKERS)
    assert "never weaken it" in text


def test_the_fresh_copy_is_unchanged():
    text = _fresh_finding(BLOCKERS)
    assert BLOCKER_DECISION_HEADING in text
    assert "before any other repair instruction" in text


def test_both_copies_still_name_the_fact_and_what_it_blocks():
    text = format_unowned_blockers(BLOCKERS)
    assert "EmergencyUnique" in text
    assert "Scenario_MultiEmg_4_trace" in text


def test_the_streak_marker_survives_in_the_stale_copy():
    text = format_unowned_blockers(BLOCKERS, {"EmergencyUnique": 3})
    assert "UNRESOLVED for 3 consecutive iterations" in text


def test_the_ownership_block_presents_the_finding_as_current_evidence():
    """format_ownership_for_prompt feeds the interpretation prompts. The caller
    only passes blockers measured THIS iteration, so nothing is labelled stale -
    and the interpretation is still given no section to record decisions in."""
    block = format_ownership_for_prompt(None, blockers=BLOCKERS)
    assert "PRIOR" not in block
    assert "EmergencyUnique" in block
    assert BLOCKER_DECISION_HEADING not in block


def test_a_stale_list_is_withheld_from_the_decision_check():
    """Localization only runs on escalated iterations, so the context can hold a
    list measured several model rewrites ago. The feedback was never shown it, so
    it cannot be faulted for not deciding it."""
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.unowned_blockers = {"EmergencyUnique": ["P1"], "AtLeastTwoAdmins": ["P1"]}
    wf.context.unowned_blockers_iteration = 4      # measured 3 iterations ago
    wf.context.iteration.current = 7
    wf.logger = Mock()

    wf._check_blocker_decisions(FEEDBACK)

    logged = " ".join(str(c) for c in wf.logger.log.call_args_list)
    assert "no decision recorded" not in logged


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
