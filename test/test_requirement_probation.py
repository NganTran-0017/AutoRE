"""
Probation resolution, the anti-stall ladder, and contradiction triage.

The rules under test are the ones that decide whether an unverified requirement
becomes official, gets contested, or is escalated to the user - and each of them
is deliberately biased. Verdicts must be earned (three analyzed iterations, not
three iterations), a failure that implicates several items identifies none of
them, and a contradiction the Evaluator cannot point at is not acted on.
"""
import json

import pytest

from src.utils.repair_plateau_detector import (
    ENCODE_PROVISIONAL,
    build_encode_provisional,
)
from src.utils.requirement_status_store import (
    ACTIVE,
    CONTESTED,
    PENDING_REMOVAL,
    PROVISIONAL,
    STALLED,
    RequirementStatusStore,
    evaluate_probation,
    format_conflict_notices,
    log_conflict_shadow,
    parse_conflict_declarations,
    validate_conflicts,
)
from src.utils.traceability_store import TraceabilityStore


MODEL = """
pred R1_Unlock { some d: Door | d.open }
run R1_Unlock for 3

fact EmergencyUnique { }  //@req E2

pred R7_Audit { }         //@req R7
run R7_Audit for 3
"""


@pytest.fixture
def store(tmp_path):
    return RequirementStatusStore(log_path=tmp_path / "status.json")


@pytest.fixture
def trace():
    t = TraceabilityStore()
    t.rebuild(MODEL)
    return t


def _run(store, trace, **kwargs):
    params = dict(iteration=10, model_analyzed=True)
    params.update(kwargs)
    return evaluate_probation(store, trace, **params)


# --------------------------------------------------------- the clean path #

def test_an_encoded_requirement_confirms_after_three_analyzed_iterations(store, trace):
    store.record_change("R1", "ADD", iteration=9)
    assert _run(store, trace)['confirmed'] == []
    assert _run(store, trace)['confirmed'] == []
    assert _run(store, trace)['confirmed'] == ["R1"]


def test_a_syntax_error_iteration_yields_no_verdict(store, trace):
    """A model Alloy could not compile is evidence about syntax, not about
    whether a requirement is consistent."""
    store.record_change("R1", "ADD", iteration=9)
    outcome = _run(store, trace, model_analyzed=False)
    assert outcome['skipped'] is True
    assert store.get("R1").clean_streak == 0


def test_a_syntax_error_iteration_does_not_debit_either(store, trace):
    store.record_change("R1", "ADD", iteration=9)
    _run(store, trace)
    _run(store, trace, model_analyzed=False)
    assert store.get("R1").clean_streak == 1


def test_nothing_happens_when_no_item_is_on_probation(store, trace):
    outcome = _run(store, trace)
    assert outcome == {'confirmed': [], 'contested': [], 'stalled': [], 'held': [],
                       'unencoded': [], 'unannotated': [], 'skipped': False}


# ------------------------------------------------------------- implicated #

def test_an_unsat_predicate_contests_its_requirement(store, trace):
    store.record_change("R1", "ADD", iteration=9)
    outcome = _run(store, trace, unsatisfied_predicates=["R1_Unlock"])
    assert outcome['contested'] and outcome['contested'][0][0] == "R1"
    assert store.status_of("R1") == CONTESTED


def test_a_counterexample_contests_its_requirement(store, trace):
    store.record_change("R7", "MODIFY", iteration=9)
    outcome = _run(store, trace, counterexamples=["R7_Audit"])
    assert [c[0] for c in outcome['contested']] == ["R7"]


def test_a_blocking_fact_contests_the_requirement_it_encodes(store, trace):
    store.record_change("E2", "MODIFY", iteration=9)
    outcome = _run(store, trace, blocking_facts={"EmergencyUnique"})
    assert [c[0] for c in outcome['contested']] == ["E2"]


def test_baseline_unsat_contests_an_existing_system_item(store, trace):
    """An inconsistent E# fact shows up as baseline UNSAT, not as its own pred."""
    store.record_change("E2", "MODIFY", iteration=9)
    outcome = _run(store, trace, unsatisfied_predicates=["baseline"])
    assert [c[0] for c in outcome['contested']] == ["E2"]


def test_baseline_unsat_does_not_contest_a_prospective_item(store, trace):
    store.record_change("R1", "ADD", iteration=9)
    outcome = _run(store, trace, unsatisfied_predicates=["baseline"])
    assert outcome['contested'] == []
    assert outcome['confirmed'] == []      # credited normally
    assert store.get("R1").clean_streak == 1


def test_an_implicated_iteration_resets_the_streak(store, trace):
    store.record_change("R1", "ADD", iteration=9)
    _run(store, trace)
    _run(store, trace, unsatisfied_predicates=["R1_Unlock"])
    assert store.get("R1").clean_streak == 0


def test_two_implicated_items_contest_neither(store, trace):
    """One failure implicating several candidates identifies none of them."""
    store.record_change("R1", "ADD", iteration=9)
    store.record_change("R7", "ADD", iteration=9)
    outcome = _run(store, trace,
                   unsatisfied_predicates=["R1_Unlock", "R7_Audit"])
    assert outcome['contested'] == []
    assert sorted(outcome['held']) == ["R1", "R7"]
    assert store.status_of("R1") == PROVISIONAL
    assert store.status_of("R7") == PROVISIONAL


def test_two_implicated_items_still_withhold_credit(store, trace):
    store.record_change("R1", "ADD", iteration=9)
    store.record_change("R7", "ADD", iteration=9)
    _run(store, trace)
    _run(store, trace, unsatisfied_predicates=["R1_Unlock", "R7_Audit"])
    assert store.get("R1").clean_streak == 0
    assert "implicated together with R7" in store.get("R1").reason


def test_an_unrelated_failure_does_not_contest(store, trace):
    store.record_change("R1", "ADD", iteration=9)
    outcome = _run(store, trace, unsatisfied_predicates=["R7_Audit"])
    assert outcome['contested'] == []
    assert store.get("R1").clean_streak == 1


# ---------------------------------------------------------- the stalls #

def test_an_unencoded_requirement_stalls_rather_than_waiting(store, trace):
    store.record_change("R9", "ADD", iteration=9)
    for _ in range(2):
        outcome = _run(store, trace)
        assert outcome['unencoded'] == ["R9"]
        assert outcome['stalled'] == []
    assert _run(store, trace)['stalled'] == ["R9"]
    assert store.status_of("R9") == STALLED


def test_an_unowned_construct_makes_it_a_labelling_stall(store, trace):
    """Opposite remedy: annotate the construct, do not build a second one."""
    store.record_change("R9", "ADD", iteration=9)
    outcome = _run(store, trace, unowned_constructs=["MysteryFact"])
    assert outcome['unannotated'] == ["R9"]
    assert outcome['unencoded'] == []


def test_an_unencoded_requirement_never_confirms_silently(store, trace):
    store.record_change("R9", "ADD", iteration=9)
    for _ in range(5):
        outcome = _run(store, trace)
        assert outcome['confirmed'] == []


def test_a_section_modification_can_never_stall(store, trace):
    """A section blob has no ID to trace, so there is no encoding to demand."""
    store.record_change("SYSTEM OVERVIEW", "MODIFY-SECTION", iteration=9)
    for _ in range(2):
        _run(store, trace)
    assert _run(store, trace)['confirmed'] == ["SYSTEM OVERVIEW"]


# -------------------------------------------------------- pending removal #

def test_a_removal_confirms_once_its_encoding_is_gone(store, trace):
    store.record_change("R5", "REMOVE", iteration=9)     # nothing encodes R5
    for _ in range(2):
        _run(store, trace)
    assert _run(store, trace)['confirmed'] == ["R5"]


def test_a_removal_whose_construct_survives_is_not_credited(store, trace):
    store.record_change("R1", "REMOVE", iteration=9)     # R1_Unlock still there
    for _ in range(4):
        outcome = _run(store, trace)
        assert outcome['confirmed'] == []
    assert store.status_of("R1") == STALLED


def test_a_blocked_prune_is_not_credited_as_a_verified_removal(store, trace):
    """A prune the pruner refused means the removal was never tested."""
    store.record_change("R5", "REMOVE", iteration=9)
    outcome = _run(store, trace, removal_blocked={"R5"})
    assert outcome['confirmed'] == []
    assert outcome['held'] == ["R5"]


def test_a_verified_removal_stays_pending_until_the_caller_deletes(store, trace):
    """evaluate_probation reports; the document change is the caller's."""
    store.record_change("R5", "REMOVE", iteration=9)
    for _ in range(3):
        _run(store, trace)
    assert store.status_of("R5") == PENDING_REMOVAL


# ------------------------------------------------------- encode directive #

def test_encode_directive_separates_build_from_label():
    directive = build_encode_provisional(
        current_iteration=12,
        unencoded=[{"req_id": "R9", "text": "R9: Alarm the operator."}],
        unannotated=[{"req_id": "R8", "text": "R8: Audit.",
                      "candidates": ["MysteryFact"]}],
    )
    text = directive["directive"]
    assert directive["strategy"] == ENCODE_PROVISIONAL
    assert "BUILD" in text and "R9: Alarm the operator." in text
    assert "LABEL ONLY" in text and "MysteryFact" in text
    assert "Do NOT build a second construct" in text


def test_encode_directive_says_it_is_not_a_repair():
    directive = build_encode_provisional(
        current_iteration=1,
        unencoded=[{"req_id": "R9", "text": "R9: Alarm."}],
    )
    assert "not a repair" in directive["directive"].lower()


def test_encode_directive_names_a_repeat_as_a_repeat():
    directive = build_encode_provisional(
        current_iteration=13,
        unencoded=[{"req_id": "R9", "text": "R9: Alarm."}],
        previous_targets=["R9"],
    )
    assert directive["repeated"] == ["R9"]
    assert "did not land" in directive["directive"]


def test_encode_directive_is_empty_when_nothing_stalled():
    directive = build_encode_provisional(current_iteration=1)
    assert directive["directive"] == ""
    assert directive["encode_targets"] == []


# --------------------------------------------------- contradiction triage #

FEEDBACK = """
=== REQUIREMENT UPDATES ===
- Affected Requirement/Assumption/Constraint: concurrent emergencies
- Classification: requirement
- Target kind & placement: new R#
- Coverage check: checked R1, R6 - none cover it
- Conflicts with: R6 - R6 allows one emergency per session, this allows many
- Recommended Update: The system shall permit concurrent emergencies.

- Affected Requirement/Assumption/Constraint: audit retention
- Classification: requirement
- Target kind & placement: new R#
- Coverage check: checked R2
- Conflicts with: none
- Recommended Update: Audit records shall be retained for one year.

=== UPDATED USER QUESTIONS ===
1. Anything else?
"""


def test_only_the_entry_that_declared_a_conflict_is_returned():
    declared = parse_conflict_declarations(FEEDBACK)
    assert len(declared) == 1
    assert declared[0]["conflicts_with"] == ["R6"]
    assert "concurrent emergencies" in declared[0]["affected"]
    assert "permit concurrent emergencies" in declared[0]["recommended"]


def test_a_declaration_is_attributed_to_its_own_entry():
    """Fields are read per entry, not to whichever candidate parsed last."""
    declared = parse_conflict_declarations(FEEDBACK)
    assert "audit retention" not in declared[0]["affected"]


@pytest.mark.parametrize("value", ["none", "None", "N/A", "-", "  none. "])
def test_no_conflict_spellings_declare_nothing(value):
    feedback = f"=== REQUIREMENT UPDATES ===\n- Affected: x\n- Conflicts with: {value}\n"
    assert parse_conflict_declarations(feedback) == []


def test_nothing_is_parsed_outside_the_updates_section():
    feedback = ("=== REPAIR INSTRUCTIONS ===\n- Affected: x\n"
                "- Conflicts with: R6\n")
    assert parse_conflict_declarations(feedback) == []


def test_missing_section_parses_to_nothing():
    assert parse_conflict_declarations("no sections here") == []
    assert parse_conflict_declarations("") == []


def test_an_uncitable_conflict_is_downgraded_not_acted_on():
    """The semantic judgment cannot be checked; that the ID exists can."""
    declared = [{"affected": "x", "recommended": "y",
                 "conflicts_with": ["R99"], "why": "because"}]
    split = validate_conflicts(declared, live_ids={"R1", "R6"})
    assert split["accepted"] == []
    assert "R99" in split["downgraded"][0]["downgrade_reason"]


def test_a_conflict_naming_no_id_is_downgraded():
    declared = [{"affected": "x", "recommended": "y",
                 "conflicts_with": [], "why": "they just clash"}]
    split = validate_conflicts(declared, live_ids={"R1"})
    assert split["accepted"] == []
    assert "no ID given" in split["downgraded"][0]["downgrade_reason"]


def test_validation_keeps_only_the_ids_that_exist():
    declared = [{"affected": "x", "recommended": "y",
                 "conflicts_with": ["R6", "R99"], "why": "w"}]
    split = validate_conflicts(declared, live_ids={"R6"})
    assert split["accepted"][0]["conflicts_with"] == ["R6"]


def test_the_notice_states_the_claim_and_asks_for_nothing():
    """A CONTRADICTS verdict is the Evaluator reading two pieces of English.
    Demanding a decision on it would spend the user's attention before
    anything had checked whether the conflict is real."""
    accepted = validate_conflicts(
        parse_conflict_declarations(FEEDBACK), live_ids={"R6"})["accepted"]
    notice = format_conflict_notices(accepted)[0]
    assert "[CONFLICT CLAIMED]" in notice
    assert "R6" in notice
    assert "permit concurrent emergencies" in notice
    assert "No answer is needed now." in notice


def test_the_shadow_log_records_the_verdict_without_acting(tmp_path):
    accepted = validate_conflicts(
        parse_conflict_declarations(FEEDBACK), live_ids={"R6"})["accepted"]
    log_conflict_shadow(accepted, "observe", 12, "contradicts", output_dir=tmp_path)
    record = json.loads((tmp_path / "shadow.jsonl").read_text().strip())
    assert record["mode"] == "observe"
    assert record["verdict"] == "contradicts"
    assert record["conflicts_with"] == ["R6"]
    assert record["iteration"] == 12


def test_the_shadow_log_appends_across_rounds(tmp_path):
    entry = [{"affected": "a", "conflicts_with": ["R1"]}]
    log_conflict_shadow(entry, "observe", 1, "contradicts", output_dir=tmp_path)
    log_conflict_shadow(entry, "observe", 2, "downgraded", output_dir=tmp_path)
    lines = (tmp_path / "shadow.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


def test_shadow_logging_cannot_break_the_feedback_path(tmp_path):
    """A measurement must never be able to take the run down with it."""
    log_conflict_shadow([{"affected": object()}], "observe", 1, "contradicts",
                        output_dir=tmp_path)
    log_conflict_shadow([], "observe", 1, "contradicts", output_dir=tmp_path)


# --------------------------------------------------- prompt-side delivery #

def test_the_re_is_told_how_to_answer_an_encoding_obligation():
    """The directive is inert unless the RE prompt says what to do with it."""
    from src.utils.prompt_manager import PromptManager

    section = PromptManager().get_section("RE", "UpdateAlloyModel_Mode2_SemanticRepair")
    assert ENCODE_PROVISIONAL in section
    assert "TRACEABILITY obligation" in section
    assert "do NOT build a second construct" in section.replace("Do NOT", "do NOT")


def test_the_legend_forbids_reading_provisional_as_deprioritised():
    """The stall this closes is the RE quietly skipping a provisional item -
    which leaves probation with nothing to decide on, forever."""
    from src.utils.requirement_status_store import STATUS_LEGEND

    assert "not its priority" in STATUS_LEGEND
    assert "PENDING REMOVAL" in STATUS_LEGEND
    assert "do not re-add a construct" in STATUS_LEGEND


def test_the_legend_is_attached_only_when_something_is_outstanding(tmp_path):
    from unittest.mock import Mock

    from src.actions.lesson_aware_action import LessonAwareAction

    action = LessonAwareAction.__new__(LessonAwareAction)
    action.context = Mock()
    action.context.requirement_status = RequirementStatusStore(
        log_path=tmp_path / "s.json")

    doc = ("PROSPECTIVE FUNCTIONAL REQUIREMENTS\n"
           "====================================\n"
           "R1: Unlock\nThe door shall unlock.\n")
    assert "REQUIREMENT STANDING" not in action.annotate_requirements(doc)

    action.context.requirement_status.record_change("R1", "ADD", iteration=3)
    annotated = action.annotate_requirements(doc)
    assert "REQUIREMENT STANDING" in annotated
    assert "[PROVISIONAL since it.3, 0/3]" in annotated


def test_annotation_falls_back_to_the_plain_document_on_error():
    """A rendering aid must never cost the agent its requirements."""
    from unittest.mock import Mock

    from src.actions.lesson_aware_action import LessonAwareAction

    action = LessonAwareAction.__new__(LessonAwareAction)
    action.context = Mock()
    action.context.requirement_status = object()   # no .get / .outstanding_items
    assert action.annotate_requirements("R1: Unlock\n") == "R1: Unlock\n"


# --------------------------------------------------------------------------- #
# A contradiction claim steers verification (items 1 and 2)
# --------------------------------------------------------------------------- #

class _Trace:
    """Traceability stub: requirement id -> constructs."""

    def __init__(self, mapping):
        self.mapping = mapping

    def constructs_for(self, ids):
        out = []
        for rid in ids:
            out.extend(self.mapping.get(rid, []))
        return out


def test_a_failure_on_the_claimed_side_contests_the_claimant(tmp_path):
    """R7 is encoded as a fact, so its own constructs never appear in a failure
    - the clash surfaces on R2's assertion. Without the claim R7 accrues three
    clean iterations and an unresolved contradiction is promoted."""
    store = RequirementStatusStore(log_path=tmp_path / "s.json")
    store.record_change("R7", "ADD", iteration=20)
    store.note_conflict("R7", ["R2"], acknowledged=False, iteration=20)
    trace = _Trace({"R7": ["R7_EmergencySession"],
                    "R2": ["R2_SessionTimeout", "R2_SessionsAlwaysExpire"]})

    outcome = evaluate_probation(
        store, trace, iteration=21, model_analyzed=True,
        counterexamples=["R2_SessionsAlwaysExpire"],
    )

    assert [rid for rid, _ in outcome['contested']] == ["R7"]
    assert store.status_of("R7") == CONTESTED
    reason = outcome['contested'][0][1]
    assert "R2_SessionsAlwaysExpire" in reason
    assert "declared to contradict R2" in reason


def test_a_settled_claim_stops_steering_verification(tmp_path):
    """Once the user has decided it, the claim is no longer a hypothesis worth
    widening the evidence test with."""
    store = RequirementStatusStore(log_path=tmp_path / "s.json")
    store.record_change("R7", "ADD", iteration=20)
    store.note_conflict("R7", ["R2"], acknowledged=True, iteration=20)
    trace = _Trace({"R7": ["R7_EmergencySession"], "R2": ["R2_SessionsAlwaysExpire"]})

    outcome = evaluate_probation(
        store, trace, iteration=21, model_analyzed=True,
        counterexamples=["R2_SessionsAlwaysExpire"],
    )

    assert outcome['contested'] == []
    assert store.get("R7").clean_streak == 1


def test_an_unrelated_failure_does_not_reach_through_the_claim(tmp_path):
    store = RequirementStatusStore(log_path=tmp_path / "s.json")
    store.record_change("R7", "ADD", iteration=20)
    store.note_conflict("R7", ["R2"], acknowledged=False, iteration=20)
    trace = _Trace({"R7": ["R7_EmergencySession"], "R2": ["R2_SessionTimeout"]})

    outcome = evaluate_probation(
        store, trace, iteration=21, model_analyzed=True,
        unsatisfied_predicates=["R5_Interlock"],
    )

    assert outcome['contested'] == []
    assert outcome['confirmed'] == []
    assert store.get("R7").clean_streak == 1


def test_the_claim_breaks_the_unique_culprit_tie(tmp_path):
    """Two provisional items implicated together used to contest neither, so
    the same failure repeated every iteration with no question asked."""
    store = RequirementStatusStore(log_path=tmp_path / "s.json")
    store.record_change("R7", "ADD", iteration=20)
    store.note_conflict("R7", ["R2"], acknowledged=False, iteration=20)
    store.record_change("R5", "MODIFY", iteration=20)
    trace = _Trace({"R7": ["R7_EmergencySession"], "R5": ["R5_Interlock"]})

    outcome = evaluate_probation(
        store, trace, iteration=21, model_analyzed=True,
        blocking_facts={"R7_EmergencySession", "R5_Interlock"},
    )

    assert [rid for rid, _ in outcome['contested']] == ["R7"]
    assert outcome['held'] == ["R5"]
    # The one that was not contested keeps its place, credited with nothing.
    assert store.status_of("R5") == PROVISIONAL
    assert store.get("R5").clean_streak == 0


def test_two_claimants_still_contest_neither(tmp_path):
    """The tie-break needs a unique suspect too - otherwise it just moves the
    guess one level up."""
    store = RequirementStatusStore(log_path=tmp_path / "s.json")
    for rid, construct in (("R7", "R7_EmergencySession"), ("R5", "R5_Interlock")):
        store.record_change(rid, "ADD", iteration=20)
        store.note_conflict(rid, ["R2"], acknowledged=False, iteration=20)
    trace = _Trace({"R7": ["R7_EmergencySession"], "R5": ["R5_Interlock"]})

    outcome = evaluate_probation(
        store, trace, iteration=21, model_analyzed=True,
        blocking_facts={"R7_EmergencySession", "R5_Interlock"},
    )

    assert outcome['contested'] == []
    assert sorted(outcome['held']) == ["R5", "R7"]
