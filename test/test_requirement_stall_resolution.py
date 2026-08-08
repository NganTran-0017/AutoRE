"""
Stall resolution: the way out of the one status a run could not leave.

Three iterations of encoding directives producing nothing traceable is
evidence about the REQUIREMENT, not only about the model - so the question is
about rewording it, and until this existed there was no question at all.
"""

from unittest.mock import Mock

from src.utils.repair_plateau_detector import (
    REQUIREMENTS_DIAGNOSIS,
    build_unmodelable_requirement_diagnosis,
)
from src.utils.requirement_status_store import (
    PENDING_REMOVAL,
    PROVISIONAL,
    STALLED,
    RequirementStatusStore,
    format_stall_questions,
    parse_stall_resolution,
)
from src.workflow import AutoREWorkflow


DOC = """```
PROSPECTIVE FUNCTIONAL REQUIREMENTS
====================================
R7: Emergency Session
An operator session stays open for the duration of an active emergency.
```"""


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def test_the_three_verbs_are_recognised():
    assert parse_stall_resolution("reword R7", ["R7"])["reword"] == ["R7"]
    assert parse_stall_resolution("drop R7", ["R7"])["drop"] == ["R7"]
    assert parse_stall_resolution("wait", ["R7"])["wait"] == ["R7"]


def test_per_id_directives_beat_a_blanket_verb():
    result = parse_stall_resolution("drop R7, wait R8", ["R7", "R8"])
    assert result == {"reword": [], "drop": ["R7"], "wait": ["R8"]}


def test_silence_decides_nothing():
    for answer in ("", "   ", None, "not sure"):
        assert parse_stall_resolution(answer, ["R7"]) == {
            "reword": [], "drop": [], "wait": []}


def test_a_clause_naming_two_verbs_decides_nothing():
    assert parse_stall_resolution("reword or drop?", ["R7"]) == {
        "reword": [], "drop": [], "wait": []}


def test_the_contest_vocabulary_is_unaffected_by_the_shared_parser():
    from src.utils.requirement_status_store import parse_contest_resolution
    assert parse_contest_resolution("revert R7", ["R7"]) == {
        "revert": ["R7"], "keep": []}


def test_the_question_offers_all_three_and_names_the_claim():
    question = format_stall_questions([
        {"req_id": "R7", "reason": "no verifiable encoding after 3 iterations",
         "text": "sessions stay open", "conflicts_with": ["R2"]},
    ])[0]
    assert "[STALLED]" in question
    assert "reword R7" in question and "drop R7" in question and "wait R7" in question
    assert "contradicting R2" in question


# --------------------------------------------------------------------------- #
# Workflow wiring
# --------------------------------------------------------------------------- #

def _stalled_workflow(tmp_path, answer="", op="ADD"):
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    store.record_change("R7", op, iteration=20)
    for _ in range(3):
        store.register_stall("R7", "unencoded")
    assert store.status_of("R7") == STALLED

    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.logger = Mock()
    wf.cli = Mock()
    wf.cli.request_input.return_value = answer
    ctx = Mock()
    ctx.requirement_status = store
    ctx.pending_requirement_stalls = []
    ctx.pending_requirement_contests = []
    ctx.pending_deferred_removals = []
    ctx.pending_requirement_diagnosis = []
    ctx.iteration.current = 23
    ctx.artifacts.get_latest_requirements.return_value = DOC
    wf.context = ctx
    return wf, store


def test_a_stalled_item_is_raised_from_the_store(tmp_path):
    """It left the probation pool at iteration 23, so nothing else would ever
    mention it again - and a restart loses the in-memory queue."""
    wf, store = _stalled_workflow(tmp_path)

    queued = wf._pending_stalls(store)

    assert [e["req_id"] for e in queued] == ["R7"]
    assert "R7: Emergency Session" in queued[0]["text"]


def test_waiting_grants_another_window(tmp_path):
    wf, store = _stalled_workflow(tmp_path, answer="wait R7")

    wf._resolve_requirement_stalls()

    assert store.status_of("R7") == PROVISIONAL
    assert store.get("R7").unencoded_streak == 0
    assert wf.context.pending_requirement_stalls == []


def test_waiting_on_a_stalled_removal_returns_it_to_pending_removal(tmp_path):
    wf, store = _stalled_workflow(tmp_path, answer="wait", op="REMOVE")

    wf._resolve_requirement_stalls()

    assert store.status_of("R7") == PENDING_REMOVAL


def test_dropping_stages_a_deferred_removal(tmp_path):
    """Not a special deletion - the same reviewable, revertible path every
    other removal takes."""
    wf, store = _stalled_workflow(tmp_path, answer="drop R7")

    wf._resolve_requirement_stalls()

    assert wf.context.pending_deferred_removals == [
        {"req_id": "R7",
         "because": "dropped after three iterations with no encoding",
         "by": ""}]


def test_rewording_queues_a_diagnosis_and_resumes_probation(tmp_path):
    """The item goes back on probation: the Evaluator is being asked to fix the
    wording, and leaving it stalled would block convergence while it does."""
    wf, store = _stalled_workflow(tmp_path, answer="reword R7")

    wf._resolve_requirement_stalls()

    assert [e["req_id"] for e in wf.context.pending_requirement_diagnosis] == ["R7"]
    assert store.status_of("R7") == PROVISIONAL


def test_an_undecided_stall_is_held_for_the_next_iteration(tmp_path):
    wf, store = _stalled_workflow(tmp_path, answer="")

    wf._resolve_requirement_stalls()

    assert store.status_of("R7") == STALLED
    assert [e["req_id"] for e in wf.context.pending_requirement_stalls] == ["R7"]


# --------------------------------------------------------------------------- #
# Delivering the diagnosis
# --------------------------------------------------------------------------- #

def test_the_diagnosis_states_the_evidence_and_forbids_model_repair():
    directive = build_unmodelable_requirement_diagnosis(
        current_iteration=23,
        items=[{"req_id": "R7", "text": "sessions stay open",
                "reason": "no verifiable encoding after 3 iterations",
                "conflicts_with": ["R2"]}],
    )
    assert REQUIREMENTS_DIAGNOSIS in directive
    assert "R7" in directive and "sessions stay open" in directive
    assert "do not propose model repairs" in directive
    assert "contradict R2" in directive


def test_no_diagnosis_when_nothing_was_reworded():
    assert build_unmodelable_requirement_diagnosis(current_iteration=23) == ""


def test_the_diagnosis_joins_the_escalation_directive_once(tmp_path):
    wf, store = _stalled_workflow(tmp_path)
    wf.context.pending_requirement_diagnosis = [
        {"req_id": "R7", "text": "sessions stay open", "reason": "never encoded"}]
    escalation = {"escalation_level": 0, "directive": "EXISTING EVIDENCE"}

    wf._stage_stall_diagnosis(escalation)

    assert "EXISTING EVIDENCE" in escalation["directive"]
    assert "R7" in escalation["directive"]
    assert escalation["escalation_level"] == 3
    assert wf.context.pending_requirement_diagnosis == []

    # Delivered once: repeating it would re-diagnose wording already answered.
    second = {"escalation_level": 0, "directive": ""}
    wf._stage_stall_diagnosis(second)
    assert second["directive"] == ""
