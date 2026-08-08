"""
Contest resolution: undoing a requirement update the solver implicated.

Two halves. The user's answer is parsed into revert/keep (silence decides
nothing), and a revert then has to move BOTH the document and the model - a
document-only revert leaves constructs encoding text that is no longer there.

Also covers the conflict-acknowledgement path, which is reached from the
conflict answer rather than from the requirement gate: active mode withholds the
updates section, so the gate never fires on an iteration that raises a conflict.
"""

from unittest.mock import Mock

from src.utils.repair_plateau_detector import (
    REVERT_REQUIREMENT,
    build_requirement_revert,
)
from src.utils.requirement_patch_log import (
    RequirementPatchLog,
    RequirementPatchLogEntry,
)
from src.utils.requirement_status_store import (
    ACTIVE,
    CONTESTED,
    PENDING_REMOVAL,
    RequirementStatusStore,
    format_contest_questions,
    parse_contest_resolution,
)
from src.utils.requirements_store import replace_item
from src.workflow import AutoREWorkflow


DOC = """```
SYSTEM OVERVIEW
===============
An access-control platform.

EXISTING-SYSTEM REQUIREMENTS AND CONSTRAINTS
============================================
- E1: Recordings are immutable.

PROSPECTIVE FUNCTIONAL REQUIREMENTS
====================================
R1: Access Logging
The system shall log every access.

R2: Session Expiry
Sessions expire after 30 minutes.
```"""


# --------------------------------------------------------------------------- #
# Parsing the answer
# --------------------------------------------------------------------------- #

def test_bare_verb_applies_to_every_contested_item():
    assert parse_contest_resolution("revert", ["R1", "R2"]) == {
        "revert": ["R1", "R2"], "keep": []}


def test_per_id_directives_beat_a_blanket_verb():
    result = parse_contest_resolution("revert R1, keep R2", ["R1", "R2"])
    assert result == {"revert": ["R1"], "keep": ["R2"]}


def test_named_ids_are_matched_on_word_boundaries():
    """'R7' must not claim R70 - reverting the wrong requirement is the one
    outcome worse than not deciding."""
    result = parse_contest_resolution("revert R7", ["R7", "R70"])
    assert result["revert"] == ["R7"]


def test_silence_decides_nothing():
    """An unanswered contest must stay contested. Restoring on silence would
    make it indistinguishable from a requirement that passed verification."""
    for answer in ("", "   ", None, "hmm, not sure yet"):
        assert parse_contest_resolution(answer, ["R1"]) == {"revert": [], "keep": []}


def test_a_negated_clause_decides_nothing():
    result = parse_contest_resolution("do not revert, keep it", ["R1"])
    assert result == {"revert": [], "keep": ["R1"]}


def test_a_clause_naming_both_verbs_decides_nothing():
    assert parse_contest_resolution("revert or keep?", ["R1"]) == {
        "revert": [], "keep": []}


def test_question_names_the_operation_specific_undo():
    add, modify = format_contest_questions([
        {"req_id": "R1", "op": "ADD", "text": "log every access", "reason": "unsat"},
        {"req_id": "R2", "op": "MODIFY", "text": "expire", "reason": "unsat"},
    ])
    assert "delete it from the document again" in add
    assert "restore its previous wording" in modify


# --------------------------------------------------------------------------- #
# Reverting the document
# --------------------------------------------------------------------------- #

def test_replace_item_restores_prior_wording():
    result = replace_item(
        DOC, "R2", "R2: Session Expiry\nSessions expire after 15 minutes.\n\n")
    assert result["replaced"]
    assert "15 minutes" in result["text"]
    assert "30 minutes" not in result["text"]
    # Everything else is untouched.
    assert "The system shall log every access." in result["text"]
    assert "E1: Recordings are immutable." in result["text"]


def test_replace_item_supplies_the_structural_newline():
    """render() concatenates raw blocks with no separator, so a replacement
    without a trailing newline would weld two requirements together."""
    result = replace_item(DOC, "R1", "R1: Nothing is logged.")
    assert "R1: Nothing is logged.\nR2:" in result["text"]


def test_replace_item_refuses_to_blank_an_item():
    for blank in ("", "   ", "\n"):
        result = replace_item(DOC, "R1", blank)
        assert not result["replaced"]
        assert result["text"] == DOC


def test_replace_item_leaves_the_document_alone_for_an_unknown_id():
    result = replace_item(DOC, "R99", "R99: whatever")
    assert not result["replaced"]
    assert result["text"] == DOC


# --------------------------------------------------------------------------- #
# Realigning the model
# --------------------------------------------------------------------------- #

def test_revert_directive_separates_delete_from_regenerate():
    """Opposite remedies: a reverted ADD has no requirement left to rebuild
    from, a reverted MODIFY has one that reads differently."""
    directive = build_requirement_revert(
        current_iteration=9,
        deleted=[{"req_id": "R1", "text": "", "constructs": ["AccessLogged"]}],
        restored=[{"req_id": "R2", "text": "expire after 15 minutes",
                   "constructs": ["SessionExpiry"]}],
    )
    assert directive["strategy"] == REVERT_REQUIREMENT
    assert directive["remove_targets"] == ["AccessLogged"]
    assert directive["regenerate_targets"] == ["SessionExpiry"]
    body = directive["directive"]
    assert "DELETE" in body and "AccessLogged" in body
    assert "REGENERATE" in body and "expire after 15 minutes" in body
    # The RE must not treat this as licence to re-argue the requirement.
    assert "already been changed back" in body


def test_revert_directive_is_empty_when_nothing_was_reverted():
    directive = build_requirement_revert(current_iteration=9)
    assert directive["directive"] == ""
    assert directive["reverted_ids"] == []


# --------------------------------------------------------------------------- #
# Workflow wiring
# --------------------------------------------------------------------------- #

def _workflow(store, doc=DOC, answer=""):
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.logger = Mock()
    wf.cli = Mock()
    wf.cli.request_input.return_value = answer
    ctx = Mock()
    ctx.requirement_status = store
    ctx.pending_requirement_contests = []
    ctx.pending_requirement_reverts = []
    ctx.pending_revert_directive = None
    ctx.iteration.current = 9
    ctx.traceability.constructs_for.return_value = ["AccessLogged"]
    ctx.artifacts.get_latest_requirements.return_value = doc
    wf.context = ctx
    return wf


def _contested_store(tmp_path, req_id="R1", op="ADD", prior=""):
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    store.record_change(req_id, op, iteration=5, prior_text=prior)
    store.register_implicated(req_id, "encoding implicated: AccessLogged")
    assert store.status_of(req_id) == CONTESTED
    return store


def test_keeping_clears_the_contest_without_touching_the_document(tmp_path):
    store = _contested_store(tmp_path)
    wf = _workflow(store, answer="keep R1")
    wf.context.pending_requirement_contests = [
        {"req_id": "R1", "op": "ADD", "text": "log", "reason": "unsat"}]

    wf._resolve_requirement_contests()

    assert store.status_of("R1") == ACTIVE
    assert wf.context.pending_requirement_reverts == []
    assert wf.context.pending_requirement_contests == []


def test_an_undecided_contest_is_held_for_the_next_iteration(tmp_path):
    """A contested item has left the probation pool, so nothing else would ever
    raise it again - the queue is the only thing keeping it visible."""
    store = _contested_store(tmp_path)
    queued = [{"req_id": "R1", "op": "ADD", "text": "log", "reason": "unsat"}]
    wf = _workflow(store, answer="")
    wf.context.pending_requirement_contests = list(queued)

    wf._resolve_requirement_contests()

    assert wf.context.pending_requirement_contests == queued
    assert store.status_of("R1") == CONTESTED


def test_the_contest_queue_is_rebuilt_from_the_store_after_a_resume(tmp_path):
    """The status file survives a restart; the in-memory queue does not. A
    contested item has already left the probation pool, so without this rebuild
    nothing would ever ask about it again - and it blocks convergence."""
    store = _contested_store(tmp_path)
    wf = _workflow(store, answer="keep R1")
    wf.context.pending_requirement_contests = []  # as after a fresh process start

    wf._resolve_requirement_contests()

    assert store.status_of("R1") == ACTIVE


def test_reverting_an_add_deletes_the_item_and_stages_construct_deletion(tmp_path):
    store = _contested_store(tmp_path, op="ADD")
    wf = _workflow(store, answer="revert R1")
    wf.context.pending_requirement_reverts = ["R1"]

    text = wf._perform_requirement_reverts(DOC)

    assert "The system shall log every access." not in text
    assert "Sessions expire after 30 minutes." in text
    directive = wf.context.pending_revert_directive
    assert directive["remove_targets"] == ["AccessLogged"]
    assert directive["regenerate_targets"] == []


def test_reverting_a_modify_restores_prior_text_and_stages_regeneration(tmp_path):
    prior = "R2: Session Expiry\nSessions expire after 15 minutes.\n\n"
    store = _contested_store(tmp_path, req_id="R2", op="MODIFY", prior=prior)
    wf = _workflow(store, answer="revert R2")
    wf.context.pending_requirement_reverts = ["R2"]
    wf.context.traceability.constructs_for.return_value = ["SessionExpiry"]

    text = wf._perform_requirement_reverts(DOC)

    assert "15 minutes" in text and "30 minutes" not in text
    directive = wf.context.pending_revert_directive
    assert directive["regenerate_targets"] == ["SessionExpiry"]
    assert directive["remove_targets"] == []
    assert store.status_of("R2") == ACTIVE


def test_a_modify_with_no_prior_text_is_not_reverted(tmp_path):
    """Better to leave the contest standing than to blank a requirement."""
    store = _contested_store(tmp_path, req_id="R2", op="MODIFY", prior="")
    wf = _workflow(store)
    wf.context.pending_requirement_reverts = ["R2"]

    text = wf._perform_requirement_reverts(DOC)

    assert text == DOC
    assert wf.context.pending_revert_directive is None


# --------------------------------------------------------------------------- #
# Contradiction claims: reported, then settled by verification
# --------------------------------------------------------------------------- #

CONFLICT_FEEDBACK = (
    "=== REQUIREMENT UPDATES ===\n"
    "Affected requirement: R2\n"
    "Recommended change: sessions never expire\n"
    "Conflicts with: R2\n"
    "Why: cannot both hold\n"
)


def _screening_workflow(store, settled=None, doc=DOC):
    wf = _workflow(store, doc=doc)
    wf.context.requirement_conflict_mode = "active"
    wf.context.acknowledged_conflicts = set() if settled is None else settled
    wf.context.pending_requirement_conflicts = []
    wf.context.pending_deferred_removals = []
    wf.context.requirement_patch_log = RequirementPatchLog(
        log_path=store.log_path.parent / "patchlog.json")
    return wf


def _store(tmp_path):
    return RequirementStatusStore(log_path=tmp_path / "status.json")


def test_a_claim_never_withholds_the_update(tmp_path, monkeypatch):
    """The Evaluator read two requirements and said they clash; nothing checked
    it. Stripping the section would discard a requirement on that alone."""
    monkeypatch.chdir(tmp_path)
    wf = _screening_workflow(_store(tmp_path))

    feedback, notices = wf._screen_requirement_conflicts(CONFLICT_FEEDBACK)

    assert feedback == CONFLICT_FEEDBACK
    assert len(notices) == 1
    assert "No answer is needed now." in notices[0]


def test_observe_mode_shows_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wf = _screening_workflow(_store(tmp_path))
    wf.context.requirement_conflict_mode = "observe"

    feedback, notices = wf._screen_requirement_conflicts(CONFLICT_FEEDBACK)

    assert (feedback, notices) == (CONFLICT_FEEDBACK, [])


def test_a_settled_conflict_is_not_reported_again(tmp_path, monkeypatch):
    """The detector re-runs every iteration with no memory of the outcome."""
    monkeypatch.chdir(tmp_path)
    wf = _screening_workflow(_store(tmp_path), settled={("R2",)})

    _, notices = wf._screen_requirement_conflicts(CONFLICT_FEEDBACK)

    assert notices == []


def test_a_settlement_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "status.json"
    first = _store(tmp_path)
    first.acknowledge_conflict(["R2"], iteration=8)

    resumed = _screening_workflow(RequirementStatusStore(log_path=path))
    _, notices = resumed._screen_requirement_conflicts(CONFLICT_FEEDBACK)

    assert notices == []


def test_the_claim_is_attached_to_the_update_it_referred_to(tmp_path, monkeypatch):
    """So a later contest can say WHICH requirement this one was said to
    displace, instead of asking the user to remember an iteration ago."""
    monkeypatch.chdir(tmp_path)
    store = _store(tmp_path)
    wf = _screening_workflow(store)
    wf._screen_requirement_conflicts(CONFLICT_FEEDBACK)
    wf.context.requirement_patch_log.add_entry(RequirementPatchLogEntry(
        iteration_id=9, raw_response="", applied=["ADD R7"], changed=True))

    wf._attach_declared_conflicts()

    record = store.get("R7")
    assert record.conflicts_with == ["R2"]
    # Claimed, not confirmed - nothing has verified it yet.
    assert record.conflict_acknowledged is False
    assert store.acknowledged_conflict_keys() == set()


def test_an_ambiguous_iteration_leaves_the_claim_unattached(tmp_path, monkeypatch):
    """Attaching it to the wrong update would later supersede a requirement
    that was never in the conflict."""
    monkeypatch.chdir(tmp_path)
    store = _store(tmp_path)
    wf = _screening_workflow(store)
    wf._screen_requirement_conflicts(CONFLICT_FEEDBACK)
    wf.context.requirement_patch_log.add_entry(RequirementPatchLogEntry(
        iteration_id=9, raw_response="",
        applied=["ADD R7", "ADD R8"], changed=True))

    wf._attach_declared_conflicts()

    assert store.get("R7") is None
    assert store.get("R8") is None


def test_a_claim_naming_its_update_is_attached_even_when_ambiguous(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = _store(tmp_path)
    wf = _screening_workflow(store)
    wf._screen_requirement_conflicts(CONFLICT_FEEDBACK.replace(
        "Recommended change: sessions never expire",
        "Recommended change: R8 replaces the expiry rule"))
    wf.context.requirement_patch_log.add_entry(RequirementPatchLogEntry(
        iteration_id=9, raw_response="",
        applied=["ADD R7", "ADD R8"], changed=True))

    wf._attach_declared_conflicts()

    assert store.get("R8").conflicts_with == ["R2"]
    assert store.get("R7") is None


# --------------------------------------------------------------------------- #
# Settling the claim: keep supersedes, revert restores
# --------------------------------------------------------------------------- #

def test_keeping_a_contested_update_supersedes_what_it_contradicted(tmp_path):
    """Two independent things now agree: the Evaluator claimed they cannot
    coexist, and the solver produced a failure consistent with that."""
    store = _store(tmp_path)
    store.record_change("R1", "ADD", iteration=5)
    store.note_conflict("R1", ["R2"], acknowledged=False, iteration=5)
    store.register_implicated("R1", "encoding implicated")
    wf = _screening_workflow(store)
    wf.cli.request_input.return_value = "keep R1"
    wf.context.pending_requirement_contests = [
        {"req_id": "R1", "op": "ADD", "text": "log", "reason": "unsat"}]

    wf._resolve_requirement_contests()

    assert store.status_of("R1") == ACTIVE
    assert wf.context.pending_deferred_removals == [
        {"req_id": "R2", "because": "R1 was kept over it after verification",
         "by": "R1"}]
    # Settled, so the claim stops being reported.
    assert ("R2",) in wf.context.acknowledged_conflicts


def test_keeping_an_update_with_no_claim_supersedes_nothing(tmp_path):
    store = _store(tmp_path)
    store.record_change("R1", "ADD", iteration=5)
    store.register_implicated("R1", "encoding implicated")
    wf = _screening_workflow(store)
    wf.cli.request_input.return_value = "keep R1"
    wf.context.pending_requirement_contests = [
        {"req_id": "R1", "op": "ADD", "text": "log", "reason": "unsat"}]

    wf._resolve_requirement_contests()

    assert wf.context.pending_deferred_removals == []


def test_the_contest_question_warns_that_keeping_supersedes(tmp_path):
    store = _store(tmp_path)
    store.record_change("R1", "ADD", iteration=5)
    store.note_conflict("R1", ["R2"], acknowledged=False, iteration=5)
    wf = _screening_workflow(store)

    reason = wf._contest_reason(store, "R1", "encoding implicated")

    assert "contradicting R2" in reason
    assert "pending removal" in reason


def test_the_supersession_is_linked_to_the_update_that_survived(tmp_path):
    store = _store(tmp_path)
    wf = _screening_workflow(store)
    wf.context.pending_deferred_removals = [
        {"req_id": "R2", "because": "R1 was kept over it", "by": "R1"}]

    assert wf._perform_staged_removals(DOC) == ["R2"]
    assert store.get("R2").superseded_by == "R1"
    assert [e.req_id for e in store.displaced_by("R1")] == ["R2"]


def _supersession_workflow(store, doc=DOC):
    wf = _workflow(store, doc=doc)
    wf.context.requirement_patch_log = RequirementPatchLog(
        log_path=store.log_path.parent / "patchlog.json")
    wf.context.pending_deferred_removals = []
    wf.context.withheld_conflict_feedback = None
    wf.context.pending_requirement_conflicts = []
    wf.context.acknowledged_conflicts = set()
    return wf


def test_a_superseded_item_becomes_a_deferred_removal(tmp_path):
    """Text stays in the document, encoding goes - the same shape as any other
    REMOVE, which is what makes the supersession reviewable and revertible."""
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    wf = _supersession_workflow(store)
    wf.context.pending_deferred_removals = [
        {"req_id": "R2", "because": "sessions never expire"}]

    superseded = wf._perform_staged_removals(DOC)

    assert superseded == ["R2"]
    record = store.get("R2")
    assert record.status == PENDING_REMOVAL
    assert record.provenance == "conflict-supersession"
    assert "sessions never expire" in record.reason
    # The revert target: the text as it stood when it was superseded.
    assert "30 minutes" in record.prior_text
    assert wf.context.pending_deferred_removals == []


def test_the_supersession_is_logged_as_a_patch_operation(tmp_path):
    """Not cosmetic: changed_requirement_ids reads the patch log, and that is
    what stages deletion of the constructs in step 8."""
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    wf = _supersession_workflow(store)
    wf.context.pending_deferred_removals = [{"req_id": "R2", "because": ""}]

    wf._perform_staged_removals(DOC)

    log = wf.context.requirement_patch_log
    assert log.changed_requirement_ids(9, ops=("REMOVE",)) == ["R2"]
    assert log.entries[0].changes[0]["before"].startswith("R2: Session Expiry")


def test_superseding_an_item_that_is_not_in_the_document_is_skipped(tmp_path):
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    wf = _supersession_workflow(store)
    wf.context.pending_deferred_removals = [{"req_id": "R9", "because": ""}]

    assert wf._perform_staged_removals(DOC) == []
    assert store.get("R9") is None


# --------------------------------------------------------------------------- #
# Reverting a supersession
# --------------------------------------------------------------------------- #

def test_reverting_a_pending_removal_rebuilds_the_encoding(tmp_path):
    """A deferred removal never took the text out, so the revert is entirely
    model-side: the item stands, its constructs have to come back."""
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    store.record_change("R2", "REMOVE", iteration=5, prior_text="R2: Session Expiry\n")
    wf = _supersession_workflow(store)
    wf.context.pending_requirement_reverts = ["R2"]

    text = wf._perform_requirement_reverts(DOC)

    assert store.status_of("R2") == ACTIVE
    assert "R2: Session Expiry" in text          # never left
    directive = wf.context.pending_revert_directive
    assert directive["strategy"] == REVERT_REQUIREMENT
    assert directive["remove_targets"] == []     # nothing to delete
    assert directive["regenerate_targets"] == ["AccessLogged"]


def test_reverting_the_superseding_update_restores_what_it_displaced(tmp_path):
    """Undoing the update while leaving R2 removed would enact half a decision
    whose other half was just withdrawn - the document would keep neither."""
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    store.record_change("R1", "ADD", iteration=5)
    store.register_implicated("R1", "encoding implicated")
    store.record_change("R2", "REMOVE", iteration=5, prior_text="R2: Session Expiry\n")
    store.link_supersession("R2", "R1")
    wf = _supersession_workflow(store)
    wf.context.pending_requirement_reverts = ["R1"]

    text = wf._perform_requirement_reverts(DOC)

    assert "R1: Access Logging" not in text      # the update is gone
    assert "R2: Session Expiry" in text          # the item it displaced stands
    assert store.status_of("R2") == ACTIVE
    assert "R2" in wf.context.pending_revert_directive["directive"]


def test_a_revert_does_not_restore_an_unrelated_pending_removal(tmp_path):
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    store.record_change("R1", "ADD", iteration=5)
    store.record_change("R2", "REMOVE", iteration=5, prior_text="R2: Session Expiry\n")
    wf = _supersession_workflow(store)
    wf.context.pending_requirement_reverts = ["R1"]

    wf._perform_requirement_reverts(DOC)

    assert store.status_of("R2") == PENDING_REMOVAL


def test_the_contest_question_says_what_else_a_revert_brings_back(tmp_path):
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    store.record_change("R2", "REMOVE", iteration=5, prior_text="x")
    store.link_supersession("R2", "R1")
    wf = _supersession_workflow(store)

    reason = wf._contest_reason(store, "R1", "encoding implicated")

    assert "also restores R2" in reason


def test_a_deletion_scheduled_this_iteration_is_cancelled_by_the_revert(tmp_path):
    """Step 4 can verify R2's removal in the same iteration whose step 5-6
    revokes its cause, and step 7 deletes before it reverts - so the restore
    would otherwise be undone a moment after it happened."""
    store = RequirementStatusStore(log_path=tmp_path / "status.json")
    store.record_change("R1", "ADD", iteration=5)
    store.register_implicated("R1", "encoding implicated")
    store.record_change("R2", "REMOVE", iteration=5, prior_text="R2: Session Expiry\n")
    store.link_supersession("R2", "R1")
    wf = _supersession_workflow(store)
    wf.context.pending_requirement_reverts = ["R1"]
    wf.context.pending_requirement_deletions = ["R2"]

    wf._perform_requirement_reverts(DOC)

    assert wf.context.pending_requirement_deletions == []
    assert store.status_of("R2") == ACTIVE


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            if "tmp_path" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"  ✓ {name}")
    print("All requirement-contest tests passed.")
