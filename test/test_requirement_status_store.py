"""
Requirement standing: what each applied patch operation lands in, and what
survives a reconcile / resume.

The store is the primitive the whole probation mechanism rests on: if an op
lands in the wrong status, or a streak survives a resume that re-runs the
iterations that earned it, an unverified requirement is promoted on evidence
the run does not have.
"""
import json

import pytest

from src.utils import requirements_store as rs
from src.utils.requirement_status_store import (
    ACTIVE,
    CONTESTED,
    PENDING_REMOVAL,
    PROBATION_ITERATIONS,
    PROVISIONAL,
    STALLED,
    SUPERSEDED,
    RequirementStatusStore,
    format_marker,
    format_outstanding,
)


@pytest.fixture
def store(tmp_path):
    return RequirementStatusStore(log_path=tmp_path / "requirement_status.json")


DOC = """SYSTEM OVERVIEW
===============
A door system.

EXISTING-SYSTEM ASSUMPTIONS AND CONSTRAINTS
============================================
- Every door has one controller.
- Clearance is assigned per user.

PROSPECTIVE FUNCTIONAL REQUIREMENTS
====================================
R1: Unlock
The door shall unlock for an authorized user.

R2: Log
The system shall record every unlock attempt.
"""


# --------------------------------------------------------------- recording #

@pytest.mark.parametrize("op,expected", [
    ("ADD", PROVISIONAL),
    ("MODIFY", PROVISIONAL),
    ("MODIFY-SECTION", PROVISIONAL),
    ("REMOVE", PENDING_REMOVAL),
])
def test_every_operation_lands_on_probation(store, op, expected):
    entry = store.record_change("R1", op, iteration=5)
    assert entry.status == expected
    assert store.status_of("R1") == expected


def test_user_confirmation_does_not_exempt_an_update(store):
    """Confirming wording is not confirming consistency - the whole premise."""
    for decision in ("accepted", "edited", "provisional", "rejected"):
        store.record_change(f"R{decision[0]}", "ADD", iteration=1,
                            provenance=decision)
    assert all(e.status == PROVISIONAL for e in store.statuses.values())


def test_unknown_operation_is_not_recorded(store):
    assert store.record_change("R1", "NO-CHANGE", iteration=1) is None
    assert store.statuses == {}


def test_record_changes_reads_an_apply_patch_report(store):
    report = rs.apply_patch(
        DOC,
        "=== REQUIREMENT PATCH ===\n[MODIFY] R1\nNew text:\nR1: Unlock\nfaster.\n",
        protected_ids=set(),
    )
    recorded = store.record_changes(report["changes"], iteration=9)
    assert [e.req_id for e in recorded] == ["R1"]
    assert store.get("R1").prior_text.startswith("R1: Unlock")


def test_an_item_with_no_record_reads_as_active(store):
    """Original-source requirements are ground truth, never on probation."""
    assert store.status_of("R9") == ACTIVE


def test_touching_a_probationary_item_restarts_its_clock(store):
    store.record_change("R1", "ADD", iteration=1)
    store.register_clean("R1")
    store.register_clean("R1")
    assert store.get("R1").clean_streak == 2

    store.record_change("R1", "MODIFY", iteration=4, prior_text="new prior")
    assert store.get("R1").clean_streak == 0
    assert store.get("R1").since_iteration == 4


def test_a_second_modify_keeps_the_original_revert_target(store):
    """Reverting must undo the whole probation, not land on a midpoint."""
    store.record_change("R1", "MODIFY", iteration=1, prior_text="ORIGINAL")
    store.record_change("R1", "MODIFY", iteration=3, prior_text="INTERMEDIATE")
    assert store.get("R1").prior_text == "ORIGINAL"


# --------------------------------------------------------------- probation #

def test_confirmation_needs_exactly_three_clean_iterations(store):
    store.record_change("R1", "ADD", iteration=1)
    assert PROBATION_ITERATIONS == 3
    assert store.register_clean("R1") is False
    assert store.register_clean("R1") is False
    assert store.register_clean("R1") is True


def test_implication_contests_and_resets(store):
    store.record_change("R1", "ADD", iteration=1)
    store.register_clean("R1")
    store.register_implicated("R1", "pred R1 is UNSAT")
    entry = store.get("R1")
    assert entry.status == CONTESTED
    assert entry.clean_streak == 0
    assert "UNSAT" in entry.reason


def test_a_contested_item_stops_accruing(store):
    store.record_change("R1", "ADD", iteration=1)
    store.register_implicated("R1", "why")
    assert store.register_clean("R1") is False
    assert store.get("R1").clean_streak == 0


def test_stall_escalates_to_stalled_after_three(store):
    store.record_change("R1", "ADD", iteration=1)
    store.register_stall("R1", "unencoded")
    store.register_stall("R1", "unencoded")
    assert store.get("R1").status == PROVISIONAL
    store.register_stall("R1", "unencoded")
    assert store.get("R1").status == STALLED


def test_stall_causes_are_counted_apart_but_escalate_together(store):
    """Alternating between unbuilt and unlabelled is still stuck."""
    store.record_change("R1", "ADD", iteration=1)
    store.register_stall("R1", "unencoded")
    store.register_stall("R1", "unannotated")
    store.register_stall("R1", "unencoded")
    entry = store.get("R1")
    assert entry.unencoded_streak == 2
    assert entry.unannotated_streak == 1
    assert entry.status == STALLED


def test_a_clean_iteration_clears_the_stall_counters(store):
    store.record_change("R1", "ADD", iteration=1)
    store.register_stall("R1", "unencoded")
    store.register_stall("R1", "unencoded")
    store.register_clean("R1")
    assert store.get("R1").stall_streak == 0


def test_reset_streak_withholds_credit_without_contesting(store):
    store.record_change("R1", "ADD", iteration=1)
    store.register_clean("R1")
    store.reset_streak("R1", "implicated together with R2")
    entry = store.get("R1")
    assert entry.status == PROVISIONAL
    assert entry.clean_streak == 0


# ------------------------------------------------------------ reconcile #

def test_reconcile_drops_and_reports_a_vanished_id(store):
    store.record_change("R1", "ADD", iteration=1)
    store.record_change("R2", "ADD", iteration=1)
    dropped = store.reconcile({"R1"})
    assert dropped == ["R2"]
    assert "R2" not in store.statuses


def test_reconcile_keeps_a_pending_removal(store):
    """Its whole point is that the id is still in the document."""
    store.record_change("R1", "REMOVE", iteration=1)
    assert store.reconcile({"R1"}) == []
    assert store.status_of("R1") == PENDING_REMOVAL


def test_reconcile_keeps_a_superseded_record(store):
    store.record_change("R1", "REMOVE", iteration=1)
    store.supersede("R1")
    assert store.reconcile(set()) == []
    assert store.status_of("R1") == SUPERSEDED


# ---------------------------------------------------------------- resume #

def test_trim_drops_records_from_discarded_iterations(store):
    store.record_change("R1", "ADD", iteration=10)
    store.record_change("R2", "ADD", iteration=25)
    dropped = store.trim_to_iteration(20)
    assert dropped == ["R2"]
    assert "R1" in store.statuses


def test_trim_resets_surviving_streaks(store):
    """The iterations that earned the streak are about to be re-run."""
    store.record_change("R1", "ADD", iteration=5)
    store.register_clean("R1")
    store.register_clean("R1")
    store.trim_to_iteration(20)
    assert store.get("R1").clean_streak == 0
    assert store.get("R1").status == PROVISIONAL


def test_trim_cannot_promote_an_update(store):
    store.record_change("R1", "ADD", iteration=5)
    store.register_clean("R1")
    store.register_clean("R1")
    store.trim_to_iteration(20)
    assert store.register_clean("R1") is False   # 1/3, not 3/3


def test_state_survives_a_restart(tmp_path):
    path = tmp_path / "requirement_status.json"
    first = RequirementStatusStore(log_path=path)
    first.record_change("R1", "REMOVE", iteration=7)
    first.register_clean("R1")

    second = RequirementStatusStore(log_path=path)
    assert second.status_of("R1") == PENDING_REMOVAL
    assert second.get("R1").clean_streak == 1


def test_a_corrupt_file_starts_fresh_rather_than_raising(tmp_path):
    path = tmp_path / "requirement_status.json"
    path.write_text("{not json", encoding="utf-8")
    assert RequirementStatusStore(log_path=path).statuses == {}


def test_clear_removes_the_file(store):
    store.record_change("R1", "ADD", iteration=1)
    assert store.log_path.exists()
    store.clear()
    assert store.statuses == {}
    assert not store.log_path.exists()


# --------------------------------------------------------------- queries #

def test_outstanding_puts_the_worst_first(store):
    store.record_change("R1", "ADD", iteration=1)
    store.record_change("R2", "ADD", iteration=1)
    store.record_change("R3", "REMOVE", iteration=1)
    store.register_implicated("R2", "why")
    for _ in range(3):
        store.register_stall("R1", "unencoded")

    order = [e.req_id for e in store.outstanding_items()]
    assert order[:2] == ["R1", "R2"]     # stalled, then contested
    assert "R3" in order


def test_a_confirmed_item_is_not_outstanding(store):
    store.record_change("R1", "ADD", iteration=1)
    store.confirm("R1")
    assert store.outstanding_items() == []


# -------------------------------------------------------------- markers #

def test_marker_shows_progress_and_origin(store):
    store.record_change("R1", "ADD", iteration=23)
    store.register_clean("R1")
    assert format_marker(store.get("R1")) == "[PROVISIONAL since it.23, 1/3]"


def test_pending_removal_marker_is_distinct(store):
    store.record_change("R6", "REMOVE", iteration=21)
    assert format_marker(store.get("R6")).startswith("[PENDING REMOVAL since it.21")


def test_a_verified_item_carries_no_marker(store):
    store.record_change("R1", "ADD", iteration=1)
    store.confirm("R1")
    assert format_marker(store.get("R1")) == ""


def test_annotate_for_prompt_attaches_the_marker_to_the_id_line(store):
    store.record_change("R2", "ADD", iteration=4)
    doc = rs.parse_requirements_document(DOC)
    rendered = rs.annotate_for_prompt(doc, store)
    marked = [l for l in rendered.splitlines() if l.startswith("R2:")]
    assert marked and "[PROVISIONAL since it.4, 0/3]" in marked[0]
    # The description line below it stays untouched.
    assert "The system shall record every unlock attempt." in rendered


def test_annotation_never_reaches_the_stored_document(store):
    """render() is byte-for-byte; a marker in `raw` would become requirement text."""
    store.record_change("R1", "ADD", iteration=4)
    doc = rs.parse_requirements_document(DOC)
    rs.annotate_for_prompt(doc, store)
    assert doc.render() == DOC
    assert "PROVISIONAL" not in doc.render()


def test_annotate_without_statuses_is_unchanged(store):
    doc = rs.parse_requirements_document(DOC)
    assert rs.annotate_for_prompt(doc) == rs.annotate_for_prompt(doc, None)


def test_e_markers_and_status_markers_coexist(store):
    store.record_change("E1", "MODIFY", iteration=8)
    doc = rs.parse_requirements_document(DOC)
    rendered = rs.annotate_for_prompt(doc, store)
    line = next(l for l in rendered.splitlines() if l.startswith("[E1]"))
    assert "PROVISIONAL since it.8" in line


def test_format_outstanding_names_every_item(store):
    store.record_change("R1", "ADD", iteration=1)
    store.record_change("R2", "REMOVE", iteration=2)
    report = format_outstanding(store.outstanding_items())
    assert "R1" in report and "R2" in report
    assert "2 item(s)" in report


def test_format_outstanding_is_empty_when_nothing_is_pending():
    assert format_outstanding([]) == ""


# ------------------------------------------------------- deferred removal #

def test_deferred_removal_leaves_the_document_intact():
    report = rs.apply_patch(
        DOC,
        "=== REQUIREMENT PATCH ===\n[REMOVE] R2\n",
        protected_ids=set(),
        defer_removals=True,
    )
    assert report["deferred"] == ["REMOVE R2"]
    assert report["applied"] == ["REMOVE R2"]      # still stages the un-encoding
    assert report["changed"] is False
    assert report["text"] == DOC
    assert "R2: Log" in report["text"]


def test_deferred_removal_still_records_the_text_for_revert():
    report = rs.apply_patch(
        DOC, "=== REQUIREMENT PATCH ===\n[REMOVE] R2\n",
        protected_ids=set(), defer_removals=True,
    )
    change = report["changes"][0]
    assert change["op"] == "REMOVE"
    assert change["before"].startswith("R2: Log")
    assert change["after"] == ""


def test_deferring_does_not_bypass_the_protected_set():
    report = rs.apply_patch(
        DOC, "=== REQUIREMENT PATCH ===\n[REMOVE] R1\n",
        protected_ids={"R1"}, defer_removals=True,
    )
    assert report["blocked"] and not report["deferred"]
    assert "R1: Unlock" in report["text"]


def test_a_deferred_removal_of_an_absent_item_errors():
    report = rs.apply_patch(
        DOC, "=== REQUIREMENT PATCH ===\n[REMOVE] R9\n",
        protected_ids=set(), defer_removals=True,
    )
    assert any("no such item" in e for e in report["errors"])


def test_defer_off_removes_immediately():
    report = rs.apply_patch(
        DOC, "=== REQUIREMENT PATCH ===\n[REMOVE] R2\n", protected_ids=set())
    assert report["changed"] is True
    assert "R2: Log" not in report["text"]


def test_a_mixed_patch_reports_changed(store):
    """A real edit alongside a deferred removal is still a document change."""
    report = rs.apply_patch(
        DOC,
        "=== REQUIREMENT PATCH ===\n[REMOVE] R2\n\n"
        "[MODIFY] R1\nNew text:\nR1: Unlock\nrewritten.\n",
        protected_ids=set(), defer_removals=True,
    )
    assert report["changed"] is True
    assert "R2: Log" in report["text"]
    assert "rewritten." in report["text"]


def test_remove_item_performs_the_deferred_deletion():
    result = rs.remove_item(DOC, "R2")
    assert result["removed"] is True
    assert "R2: Log" not in result["text"]
    assert result["before"].startswith("R2: Log")


def test_remove_item_is_a_no_op_for_an_unknown_id():
    result = rs.remove_item(DOC, "R9")
    assert result["removed"] is False
    assert result["text"] == DOC


def test_snapshot_writes_a_readable_copy(store, tmp_path):
    store.record_change("R1", "ADD", iteration=3)
    store.save_copy_to_output(output_dir=tmp_path / "snap")
    written = list((tmp_path / "snap").glob("reqstatus_*.log"))
    assert written
    assert json.loads(written[0].read_text(encoding="utf-8"))[0]["req_id"] == "R1"


# --------------------------------------------------------------------------- #
# Durable conflict acknowledgement
# --------------------------------------------------------------------------- #

def test_note_conflict_records_an_item_that_had_no_status(store):
    """The losing side of a conflict is usually an original-source requirement,
    which carries no record at all - the common case, not an edge one."""
    store.note_conflict("R2", ["R2"], acknowledged=True, iteration=7)

    entry = store.get("R2")
    assert entry is not None
    assert entry.status == ACTIVE          # carries the conflict, marks nothing
    assert entry.conflicts_with == ["R2"]
    assert entry.conflict_acknowledged is True
    assert format_marker(entry) == ""
    assert entry not in store.outstanding_items()


def test_note_conflict_leaves_an_existing_probation_alone(store):
    store.record_change("R2", "ADD", iteration=3)
    store.note_conflict("R2", ["R2", "R5"], acknowledged=True, iteration=7)

    entry = store.get("R2")
    assert entry.status == PROVISIONAL     # still on trial
    assert entry.since_iteration == 3
    assert entry.conflict_iteration == 7


def test_an_acknowledged_conflict_survives_a_reload(store, tmp_path):
    store.acknowledge_conflict(["R2", "R5"], iteration=7)

    reloaded = RequirementStatusStore(log_path=tmp_path / "requirement_status.json")
    assert reloaded.acknowledged_conflict_keys() == {("R2", "R5")}


def test_the_key_ignores_the_order_the_evaluator_wrote_the_ids_in(store):
    """Keying on write order would re-raise "R5, R2" as a conflict already
    answered as "R2, R5"."""
    key = store.acknowledge_conflict(["R5", "R2"], iteration=7)
    assert key == ("R2", "R5")
    assert store.acknowledged_conflict_keys() == {("R2", "R5")}


def test_the_acknowledgement_is_written_to_every_member_of_the_set(store):
    """So a reconcile that drops one ID cannot resurrect a decided conflict."""
    store.acknowledge_conflict(["R2", "R5"], iteration=7)
    del store.statuses["R2"]

    assert store.acknowledged_conflict_keys() == {("R2", "R5")}


def test_an_unacknowledged_conflict_is_not_a_suppression_key(store):
    store.note_conflict("R2", ["R2"], acknowledged=False, iteration=7)
    assert store.acknowledged_conflict_keys() == set()


def test_a_resume_forgets_an_acknowledgement_given_after_the_resume_point(store):
    store.record_change("R2", "ADD", iteration=3)
    store.acknowledge_conflict(["R2"], iteration=9)

    store.trim_to_iteration(5)

    assert store.get("R2") is not None      # the item predates the resume
    assert store.acknowledged_conflict_keys() == set()


def test_a_resume_keeps_an_acknowledgement_given_before_the_resume_point(store):
    store.record_change("R2", "ADD", iteration=3)
    store.acknowledge_conflict(["R2"], iteration=4)

    store.trim_to_iteration(5)

    assert store.acknowledged_conflict_keys() == {("R2",)}


def test_re_touching_an_item_keeps_its_acknowledgement(store):
    """Probation restarts on a new op; the user's conflict decision does not."""
    store.acknowledge_conflict(["R2"], iteration=4)
    store.record_change("R2", "MODIFY", iteration=8)

    assert store.get("R2").conflict_acknowledged is True
    assert store.get("R2").conflict_iteration == 4
