"""
Contradicting lessons must not be reconciled by similarity or by recency.

Similarity is not agreement - "always X" and "never X" embed close together, so
a contradiction lands in the merge band and the old merge folded it into one
sentence, arbitrarily picking a side and then re-injecting it every iteration.

The rule these tests pin: on a contradiction, keep BOTH rows, stop injecting the
older one, and let the run's outcome decide which survives. A new lesson never
wins for being newer; an old lesson is never deleted on suspicion.
"""

from unittest.mock import Mock

import pytest

from src.actions.memory_assistant_action import MemoryAssistant


# ------------------------------------------------------- verdict parsing #

def test_parses_a_contradiction_verdict():
    verdict, merged = MemoryAssistant.parse_lesson_merge(
        "VERDICT: CONTRADICTORY\nMERGED: NONE"
    )
    assert verdict == "CONTRADICTORY"
    assert merged == ""


def test_parses_a_merge_verdict_and_text():
    verdict, merged = MemoryAssistant.parse_lesson_merge(
        "VERDICT: COMPLEMENTARY\nMERGED: Check syntax and multiplicities first"
    )
    assert verdict == "COMPLEMENTARY"
    assert merged == "Check syntax and multiplicities first"


def test_tolerates_decoration_and_case():
    verdict, merged = MemoryAssistant.parse_lesson_merge(
        "**verdict**: `Same`\n**merged**: One sentence."
    )
    assert verdict == "SAME"
    assert merged == "One sentence."


def test_a_reply_without_a_verdict_changes_nothing():
    """A parse miss must not merge, and must not suspend, on no evidence.

    Merging is the destructive branch - it rewrites the surviving row - so
    defaulting a missing verdict to COMPLEMENTARY meant a malformed reply could
    fold a binding convention into the rule that replaced it. UNPARSED is not a
    verdict; it routes to storing the new item on its own row, which loses
    nothing and stays visible for the next comparison.
    """
    verdict, merged = MemoryAssistant.parse_lesson_merge(
        "Always check syntax before running the analyzer"
    )
    assert verdict == MemoryAssistant.UNPARSED
    assert merged == "Always check syntax before running the analyzer"


def test_an_unrecognised_verdict_is_not_treated_as_a_contradiction():
    verdict, _ = MemoryAssistant.parse_lesson_merge("VERDICT: MAYBE\nMERGED: x")
    assert verdict == MemoryAssistant.UNPARSED
    assert verdict != "CONTRADICTORY"


def test_an_empty_reply_changes_nothing():
    assert MemoryAssistant.parse_lesson_merge("") == (MemoryAssistant.UNPARSED, "")


# ----------------------------------------------------------- lifecycle #

_COUNTER = iter(range(1, 10_000))


@pytest.fixture(scope="module")
def _store_root(tmp_path_factory):
    """One chdir for the module.

    ChromaDB's PersistentClient caches by resolved path; chdir-ing per test made
    the same relative path resolve to different (already-deleted) directories
    and the cached client blew up on a missing table.
    """
    import os

    root = tmp_path_factory.mktemp("lesson_conflicts")
    previous = os.getcwd()
    os.chdir(root)
    yield root
    os.chdir(previous)


@pytest.fixture
def memory(_store_root):
    """A SemanticMemorySystem on a fresh store, with the LLM merge stubbed."""
    pytest.importorskip("chromadb")
    from src.utils.semantic_memory import SemanticMemorySystem

    # A distinct project per test - collections are persistent, so a shared name
    # would leak lessons between tests.
    return SemanticMemorySystem(
        f"conflict_{next(_COUNTER)}",
        enable_dedup=True,
        dedup_config={
            "merge_threshold": 0.5,
            "drop_threshold": 0.999,  # never drop; everything reaches the merge band
            "merge_similar_lessons": True,
        },
    )


def _stub_merge(mem, verdict, merged=""):
    assistant = Mock()

    async def _classified(existing, new):
        return verdict, merged

    assistant.merge_lessons_classified = _classified
    mem._memory_assistant = assistant


def _statuses(mem):
    rows = mem.lessons_collection.get()
    return {
        doc: (rows['metadatas'][i] or {}).get('status')
        for i, doc in enumerate(rows['documents'])
    }


OLD = "Model emergency duration with a State signature, not a time index"
NEW = "Model emergency duration with a time index rather than a State signature"


def test_a_contradiction_keeps_both_rows(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)

    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    statuses = _statuses(memory)
    assert OLD in statuses and NEW in statuses, "neither lesson may be deleted"


def test_the_older_lesson_stops_being_injected(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    injected = memory.get_lessons(agent="RE", action="UpdateAlloyModel", limit=10)
    assert NEW in injected
    assert OLD not in injected


def test_an_unverified_lesson_only_suspends_pending_an_outcome(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2, verified=False)

    assert _statuses(memory)[OLD] == "pending_withdrawn"
    assert len(memory.pending_lesson_conflicts) == 1


def test_a_verified_lesson_retires_the_one_it_contradicts(memory):
    """Probation already confirmed the change held - that is what settles it."""
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2, verified=True)

    assert _statuses(memory)[OLD] == "superseded"
    assert memory.pending_lesson_conflicts == []


def test_an_unheld_fix_puts_the_older_lesson_back(memory):
    """The new lesson loses: it was never verified, and its change failed."""
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    settled = memory.resolve_lesson_conflicts(resolved=False, iteration=3)

    assert settled == 1
    statuses = _statuses(memory)
    assert statuses[OLD] == "active"
    assert statuses[NEW] == "superseded"
    injected = memory.get_lessons(agent="RE", action="UpdateAlloyModel", limit=10)
    assert OLD in injected and NEW not in injected


def test_a_held_fix_retires_the_older_lesson(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    memory.resolve_lesson_conflicts(resolved=True, iteration=3)

    statuses = _statuses(memory)
    assert statuses[OLD] == "superseded"
    assert statuses[NEW] == "active"


def test_resolution_can_be_scoped_to_one_source_iteration(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    assert memory.resolve_lesson_conflicts(True, 5, source_iteration=99) == 0
    assert len(memory.pending_lesson_conflicts) == 1
    assert memory.resolve_lesson_conflicts(True, 5, source_iteration=2) == 1


# ----------------------------------------- a conflict belongs to a lesson #

def test_settlement_is_scoped_to_the_lesson_that_raised_the_conflict(memory):
    """An iteration is not an identity.

    Two lessons written in the same iteration have unrelated fates. Keying on
    the iteration let an unrelated lesson's failure settle this conflict - in
    the direction "restore the old, retire the new" - on evidence that was never
    about it.
    """
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    # Same iteration, different lesson - must not settle this one.
    assert memory.resolve_lesson_conflicts(
        False, 5, lesson_texts=["Some unrelated lesson from iteration 2"]) == 0
    assert len(memory.pending_lesson_conflicts) == 1

    assert memory.resolve_lesson_conflicts(False, 5, lesson_texts=[NEW]) == 1


def test_the_lesson_key_tolerates_whitespace_and_case(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    assert memory.resolve_lesson_conflicts(
        True, 5, lesson_texts=["  " + NEW.upper() + " "]) == 1


# ------------------------------------------------------ the bounded wait #

def test_a_suspension_expires_and_puts_the_older_lesson_back(memory):
    """A suspension nobody lifts is a permanent deletion wearing the word
    "provisional" - and it survives restarts, because the queue is rebuilt from
    the row."""
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    assert memory.expire_stale_lesson_conflicts(current_iteration=7, max_wait=5) == 1

    statuses = _statuses(memory)
    assert statuses[OLD] == "active"
    # Nothing was shown about either, so both are injected and the
    # contradiction is at least visible rather than resolved by silence.
    assert statuses[NEW] == "active"
    assert memory.pending_lesson_conflicts == []


def test_a_suspension_inside_the_window_is_left_alone(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    assert memory.expire_stale_lesson_conflicts(current_iteration=5, max_wait=5) == 0
    assert _statuses(memory)[OLD] == "pending_withdrawn"


def test_the_window_must_outlast_the_probation_that_could_settle_it(memory):
    """Default 5 against a 3-iteration probation window.

    An outcome arriving at +3 must still find the suspension there, or the sweep
    pre-empts the very answer it is waiting for.
    """
    assert memory.dedup_config.get("lesson_conflict_max_wait", 5) > 3


def test_a_suspension_with_no_recorded_iteration_expires(memory):
    """Every row this lifecycle writes carries retract_pending_iteration, so a
    missing one is an old row - the likeliest to have sat unsettled longest."""
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)
    memory.pending_lesson_conflicts[0]['iteration'] = None

    assert memory.expire_stale_lesson_conflicts(current_iteration=2) == 1
    assert _statuses(memory)[OLD] == "active"


def test_expiry_survives_a_restart(memory):
    """The suspension is rebuilt from the row, so the clock must be too."""
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    memory.pending_lesson_conflicts = []
    assert memory.load_pending_lesson_conflicts() == 1
    assert memory.expire_stale_lesson_conflicts(current_iteration=9, max_wait=5) == 1
    assert _statuses(memory)[OLD] == "active"


# -------------------------------------------------- the decision record #

def _decisions(root):
    import json

    log = root / "Output" / "LessonDedup" / "decisions.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def test_every_decision_records_both_lessons_and_which_way_it_went(memory, _store_root):
    """This is the only path that takes guidance the run was already following
    OUT of circulation, and the row keeps just a 120-char excerpt of its
    accuser - so without this there is no record of what was weighed."""
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    suspended = _decisions(_store_root)[-1]
    assert suspended['decision'] == "suspended"
    assert suspended['new_item'] == NEW
    assert suspended['old_item'] == OLD
    assert suspended['item_type'] == "lesson"
    assert suspended['similarity'] is not None
    assert suspended['reason']

    memory.resolve_lesson_conflicts(resolved=False, iteration=4, lesson_texts=[NEW])

    restored = _decisions(_store_root)[-1]
    assert restored['decision'] == "restored"
    assert restored['new_item'] == NEW
    assert restored['old_item'] == OLD


def test_an_expiry_says_so_and_says_why(memory, _store_root):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)
    memory.expire_stale_lesson_conflicts(current_iteration=9, max_wait=5)

    expired = _decisions(_store_root)[-1]
    assert expired['decision'] == "expired"
    assert expired['old_item'] == OLD
    assert expired['new_item'] == NEW
    assert "no outcome arrived" in expired['reason']


def test_a_verified_retirement_is_recorded_too(memory, _store_root):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2, verified=True)

    retired = _decisions(_store_root)[-1]
    assert retired['decision'] == "retired_on_verified"
    assert retired['old_item'] == OLD


def test_a_compatible_pair_still_merges_into_one_row(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "COMPLEMENTARY", "Merged guidance about emergency duration")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    docs = memory.lessons_collection.get()['documents']
    assert docs == ["Merged guidance about emergency duration"]
    assert memory.pending_lesson_conflicts == []


def test_a_lesson_stored_before_the_lifecycle_existed_is_still_injected(memory):
    """Legacy rows carry no status - absence must read as active, or the whole
    pre-existing lesson store goes dark."""
    memory.lessons_collection.add(
        documents=["A lesson from before the status field"],
        metadatas=[{"agent": "RE", "action": "UpdateAlloyModel", "iteration": 0}],
        ids=["legacy_1"],
    )
    injected = memory.get_lessons(agent="RE", action="UpdateAlloyModel", limit=10)
    assert "A lesson from before the status field" in injected


def test_suppressed_lessons_do_not_return_through_semantic_search(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(memory, "CONTRADICTORY")
    memory.store(NEW, "lesson", "RE", "UpdateAlloyModel", 2)

    hits = memory.retrieve_similar("emergency duration", item_type="lesson", limit=10)
    contents = [h['content'] for h in hits]
    assert NEW in contents
    assert OLD not in contents


# ------------------------------------------------------- learning system #

def test_learning_system_is_a_no_op_on_a_backend_without_the_lifecycle():
    """The traditional (non-semantic) store has no conflict machinery."""
    from src.utils.learning_system import LearningSystem

    plain = Mock(spec=[])  # no resolve_lesson_conflicts attribute
    assert LearningSystem(plain).resolve_lesson_conflicts(True, 1) == 0


def test_learning_system_forwards_the_outcome():
    from src.utils.learning_system import LearningSystem

    mem = Mock()
    mem.resolve_lesson_conflicts.return_value = 2
    assert LearningSystem(mem).resolve_lesson_conflicts(
        False, 7, 4, lesson_texts=["a lesson"]) == 2
    mem.resolve_lesson_conflicts.assert_called_once_with(False, 7, 4, ["a lesson"])


def test_learning_system_falls_back_for_a_backend_on_the_old_signature():
    """The per-lesson key was added after some backends; forwarding must not
    break the ones that only take an iteration."""
    from src.utils.learning_system import LearningSystem

    mem = Mock()
    calls = []

    def _resolve(*args):
        calls.append(args)
        if len(args) > 3:
            raise TypeError("takes 4 positional arguments but 5 were given")
        return 1

    mem.resolve_lesson_conflicts = _resolve
    assert LearningSystem(mem).resolve_lesson_conflicts(
        False, 7, 4, lesson_texts=["a lesson"]) == 1
    assert calls[-1] == (False, 7, 4)


def test_learning_system_expiry_is_a_no_op_without_the_lifecycle():
    from src.utils.learning_system import LearningSystem

    plain = Mock(spec=[])
    assert LearningSystem(plain).expire_lesson_conflicts(9) == 0


def test_record_lesson_passes_verification_through():
    from src.utils.learning_system import LearningSystem

    mem = Mock()
    LearningSystem(mem).record_lesson("l", "RE", "A", 3, verified=True)
    assert mem.store.call_args.kwargs["verified"] is True


# ------------------------------------------ surviving a restart / resume #

def _reopen(mem):
    """Rebuild the memory system from disk, as a restart or resume would."""
    from src.utils.semantic_memory import SemanticMemorySystem

    return SemanticMemorySystem(
        mem.project_name, enable_dedup=True, dedup_config=dict(mem.dedup_config)
    )


def _suspend(mem, iteration=2):
    _stub_merge(mem, "SAME", "merged")
    mem.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    _stub_merge(mem, "CONTRADICTORY")
    mem.store(NEW, "lesson", "RE", "UpdateAlloyModel", iteration)


def test_a_suspension_is_recovered_after_a_restart(memory):
    """Otherwise the row stays pending_withdrawn with nothing left to restore
    it - and the unverified newer lesson wins by default."""
    _suspend(memory)
    assert len(memory.pending_lesson_conflicts) == 1

    reopened = _reopen(memory)

    assert len(reopened.pending_lesson_conflicts) == 1
    conflict = reopened.pending_lesson_conflicts[0]
    assert conflict["existing_content"] == OLD
    assert conflict["iteration"] == 2
    assert conflict["new_id"]


def test_a_recovered_suspension_can_still_be_resolved(memory):
    _suspend(memory)
    reopened = _reopen(memory)

    reopened.resolve_lesson_conflicts(resolved=False, iteration=9)

    statuses = _statuses(reopened)
    assert statuses[OLD] == "active"
    assert statuses[NEW] == "superseded"


def test_nothing_is_recovered_when_there_are_no_suspensions(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    assert _reopen(memory).pending_lesson_conflicts == []


def test_a_settled_conflict_is_not_recovered(memory):
    """finalize/restore flip the status, so a rebuild cannot re-collect it."""
    _suspend(memory)
    memory.resolve_lesson_conflicts(resolved=True, iteration=5)
    assert _reopen(memory).pending_lesson_conflicts == []


def test_a_suspension_from_a_discarded_iteration_is_undone(memory):
    """Resuming to 45 rewrites iteration 47 - its verdict goes with it."""
    _suspend(memory, iteration=47)
    reopened = _reopen(memory)

    restored = reopened.discard_lesson_conflicts_from(45)

    assert restored == 1
    assert _statuses(reopened)[OLD] == "active"
    assert reopened.pending_lesson_conflicts == []


def test_a_suspension_before_the_resume_point_is_kept(memory):
    _suspend(memory, iteration=40)
    reopened = _reopen(memory)

    assert reopened.discard_lesson_conflicts_from(45) == 0
    assert _statuses(reopened)[OLD] == "pending_withdrawn"
    assert len(reopened.pending_lesson_conflicts) == 1


# --------------------------------------------------------- fresh start #

def test_clear_all_empties_every_collection(memory):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)
    memory.store("a convention", "convention", "RE", "UpdateAlloyModel", 1)

    memory.clear_all(snapshot=False)

    assert memory.get_stats()["total"] == 0
    assert memory.pending_lesson_conflicts == []


def test_clear_all_keeps_the_configured_dedup_settings(memory):
    """Re-running __init__ with the project name alone reverted merge/drop
    thresholds to defaults, so a cleared run stopped honouring config.yaml."""
    before = dict(memory.dedup_config)
    memory.clear_all(snapshot=False)

    assert memory.dedup_config["drop_threshold"] == before["drop_threshold"]
    assert memory.dedup_config["merge_threshold"] == before["merge_threshold"]
    assert memory.enable_dedup is True


def test_clear_all_snapshots_before_wiping(memory, tmp_path):
    _stub_merge(memory, "SAME", "merged")
    memory.store(OLD, "lesson", "RE", "UpdateAlloyModel", 1)

    out = memory.save_copy_to_output(tmp_path / "snap")

    import json
    saved = json.loads(out.read_text())
    assert [row["content"] for row in saved["lesson"]] == [OLD]


def test_workflow_clears_semantic_memory_on_a_fresh_start():
    from src.workflow import AutoREWorkflow

    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.logger = Mock()
    wf.context.memory.get_stats.return_value = {"total": 7}

    wf._clear_semantic_memory_for_fresh_start()

    wf.context.memory.clear_all.assert_called_once()


def test_fresh_start_clear_never_aborts_the_run():
    from src.workflow import AutoREWorkflow

    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.logger = Mock()
    wf.context.memory.clear_all.side_effect = RuntimeError("store unavailable")

    wf._clear_semantic_memory_for_fresh_start()  # must not raise


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
