"""
Conventions are deduplicated by the same banded mechanism as lessons, and for a
sharper reason: a convention is BINDING on the model builder, and the item it
sits closest to in embedding space is usually the convention that REPLACES it -
both describe the same corner of the model. Folding those two into one row hands
the builder a rule and its own replacement at once.

So the merge band is not a merge band any more. It is a CLASSIFY band:

    sim >= drop      -> the new one adds nothing, drop it
    merge <= sim     -> ask the MemoryAssistant: one rule, or opposing rules?
                        SAME/COMPLEMENTARY -> one row, pre-merge text kept
                        CONTRADICTORY      -> both rows, older one suspended
                        no answer          -> change nothing
    sim < merge      -> unrelated enough to leave alone

The floor is 0.78 rather than the lessons' 0.7, calibrated on a real run's
shadow log: below it, every observed pair was the same TOPIC under a different
RULE (an eligibility condition against an encoding style), which must not be
fused.

Nothing here is decided by recency. What a fix's outcome decides, it decides in
both directions: a merge that did not hold goes back to its pre-merge wording,
and a suspension that did not hold puts the older convention back.
"""

from unittest.mock import Mock

import pytest

from src.utils.learning_system import LearningSystem


# ------------------------------------------------- the exact-text guard #

def test_normalization_folds_case_whitespace_and_trailing_punctuation():
    """The shadow log's only near-identical pair differed by ONE period.

    It cost a full semantic comparison to catch at 0.9869, having slipped past a
    guard that is deterministic and free.
    """
    norm = LearningSystem._normalize_convention
    assert norm("Use StateOrder directly.") == norm("use stateorder  directly")
    assert norm("Keep requirements in predicates;") == norm("Keep requirements in predicates")


def test_an_exact_repeat_never_reaches_the_classifier():
    memory = Mock()
    memory.get_conventions.return_value = ["Use StateOrder/indexOf directly"]
    learning = LearningSystem(memory)

    stored, decision = learning._store_convention_if_new(
        "use stateorder/indexof directly.", "RE", "UpdateAlloyModel", 5
    )

    assert stored is False
    assert decision is None
    memory.store.assert_not_called()


# ------------------------------------------------------------ fixtures #

_COUNTER = iter(range(1, 10_000))


@pytest.fixture(scope="module")
def _store_root(tmp_path_factory):
    """One chdir for the module - ChromaDB caches PersistentClient by path."""
    import os

    root = tmp_path_factory.mktemp("convention_dedup")
    previous = os.getcwd()
    os.chdir(root)
    yield root
    os.chdir(previous)


@pytest.fixture
def memory(_store_root):
    pytest.importorskip("chromadb")
    from src.utils.semantic_memory import SemanticMemorySystem

    return SemanticMemorySystem(
        f"conv_{next(_COUNTER)}",
        enable_dedup=True,
        dedup_config={
            "convention_merge_threshold": 0.5,   # everything lands in the band
            "convention_drop_threshold": 0.999,  # nothing is dropped outright
            "merge_similar_lessons": True,
            "convention_mode": "active",
        },
    )


def _stub(mem, verdict, merged=""):
    assistant = Mock()

    async def _classified(existing, new):
        return verdict, merged

    assistant.merge_conventions_classified = _classified
    mem._memory_assistant = assistant


def _rows(mem):
    rows = mem.conventions_collection.get()
    return {
        doc: (rows['metadatas'][i] or {})
        for i, doc in enumerate(rows['documents'])
    }


OLD = "Use State.t and StateOrder as the only representation of time"
NEW = "Use State.t and StateOrder as the single ordered time variable; abolish redundant time representations"
CLASH = "Model time with an explicit time index rather than State.t and StateOrder"


def _seed(mem, text=OLD, iteration=1):
    _stub(mem, "CONTRADICTORY")  # no prior row, so the verdict is never used
    mem.store(text, "convention", "RE", "UpdateAlloyModel", iteration)


# --------------------------------------------------------------- merge #

def test_a_compatible_pair_becomes_one_row_keeping_the_original(memory):
    _seed(memory)
    _stub(memory, "COMPLEMENTARY", "State.t and StateOrder are the single ordered time variable")

    memory.store(NEW, "convention", "RE", "UpdateAlloyModel", 2)

    rows = _rows(memory)
    assert len(rows) == 1
    text, meta = next(iter(rows.items()))
    assert text == "State.t and StateOrder are the single ordered time variable"
    # The record of what it said before - without this a merge is a one-way door.
    assert meta['prior_text'] == OLD


def test_a_gated_merge_is_left_pending_for_the_caller_to_settle(memory):
    _seed(memory)
    _stub(memory, "SAME", "merged text")

    decision = memory.store(NEW, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    assert decision['kind'] == "merge"
    assert decision['prior_text'] == OLD
    assert _rows(memory)["merged text"]['merge_pending'] is True


def test_an_ungated_merge_leaves_nothing_pending(memory):
    """Nobody is watching the Build path, so nothing may be left waiting there."""
    _seed(memory)
    _stub(memory, "SAME", "merged text")

    decision = memory.store(NEW, "convention", "Builder", "Build", 2)

    assert decision is None
    assert not _rows(memory)["merged text"].get('merge_pending')


def test_a_confirmed_merge_stands_and_keeps_its_history(memory):
    _seed(memory)
    _stub(memory, "SAME", "merged text")
    decision = memory.store(NEW, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    LearningSystem(memory).apply_convention_retractions([decision], iteration=5)

    meta = _rows(memory)["merged text"]
    assert meta['merge_pending'] is False
    assert meta['prior_text'] == OLD


def test_a_merge_whose_fix_did_not_hold_goes_back_to_the_old_wording(memory):
    _seed(memory)
    _stub(memory, "SAME", "merged text")
    decision = memory.store(NEW, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    LearningSystem(memory).revert_convention_retractions([decision])

    rows = _rows(memory)
    assert OLD in rows
    assert "merged text" not in rows
    assert rows[OLD]['merge_reverted'] is True


def test_a_second_merge_still_reverts_to_the_last_wording_that_held(memory):
    """Two merges before either settles must not lose the confirmed original."""
    first = "State.t and StateOrder are the single ordered time representation"
    second = "State.t and StateOrder order every state; no other time field exists"

    _seed(memory)
    _stub(memory, "SAME", first)
    memory.store(NEW, "convention", "RE", "UpdateAlloyModel", 2, gated=True)
    _stub(memory, "SAME", second)
    memory.store("Time progression is represented only by State.t and StateOrder",
                 "convention", "RE", "UpdateAlloyModel", 3, gated=True)

    # Not `first` - that wording never survived probation, so reverting to it
    # would restore something the run was never entitled to rely on.
    assert _rows(memory)[second]['prior_text'] == OLD


def test_a_merge_with_no_recorded_original_refuses_to_revert(memory):
    """Better to keep the merged text than to blank the row on a guess."""
    _seed(memory)
    row_id = memory.conventions_collection.get()['ids'][0]

    assert memory.restore_merge(row_id, "convention") is False


# --------------------------------------------------------- contradiction #

def test_a_contradiction_keeps_both_rows_and_suspends_the_older(memory):
    _seed(memory)
    _stub(memory, "CONTRADICTORY")

    decision = memory.store(CLASH, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    rows = _rows(memory)
    assert rows[OLD]['status'] == "pending_withdrawn"
    assert rows[CLASH]['status'] == "active"
    assert decision['kind'] == "conflict"
    # The new one is injected immediately: an item nobody can act on can never
    # demonstrate it was right.
    assert memory.get_conventions() == [CLASH]


def test_a_confirmed_contradiction_retires_the_older_convention(memory):
    _seed(memory)
    _stub(memory, "CONTRADICTORY")
    decision = memory.store(CLASH, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    LearningSystem(memory).apply_convention_retractions([decision], iteration=5)

    assert _rows(memory)[OLD]['status'] == "superseded"
    assert memory.get_conventions() == [CLASH]


def test_a_contradiction_whose_fix_did_not_hold_restores_the_older_one(memory):
    _seed(memory)
    _stub(memory, "CONTRADICTORY")
    decision = memory.store(CLASH, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    LearningSystem(memory).revert_convention_retractions([decision])

    rows = _rows(memory)
    assert rows[OLD]['status'] == "active"
    # The new one never earned its place; leaving it active would keep injecting
    # the reading that just failed.
    assert rows[CLASH]['status'] == "superseded"
    assert memory.get_conventions() == [OLD]


def test_an_ungated_contradiction_suspends_nothing(memory):
    """No gate on this path means no one to restore it - so set nothing aside."""
    _seed(memory)
    _stub(memory, "CONTRADICTORY")

    decision = memory.store(CLASH, "convention", "Builder", "Build", 2)

    assert decision is None
    assert sorted(memory.get_conventions()) == sorted([OLD, CLASH])


# ------------------------------------------------- refusing to act blind #

def test_an_unparseable_verdict_merges_nothing_and_suspends_nothing(memory):
    _seed(memory)
    _stub(memory, "UNPARSED", "some reply the model wrote instead")

    memory.store(NEW, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    assert sorted(memory.get_conventions()) == sorted([OLD, NEW])


def test_a_failed_classifier_call_keeps_both_conventions(memory):
    """An infrastructure error must not decide which binding rule survives."""
    _seed(memory)
    assistant = Mock()

    async def _boom(existing, new):
        raise RuntimeError("LLM unavailable")

    assistant.merge_conventions_classified = _boom
    memory._memory_assistant = assistant

    memory.store(NEW, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    assert sorted(memory.get_conventions()) == sorted([OLD, NEW])


def test_observe_mode_records_the_band_but_changes_nothing(memory):
    memory.dedup_config['convention_mode'] = "observe"
    _seed(memory)
    _stub(memory, "CONTRADICTORY")

    memory.store(CLASH, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    assert sorted(memory.get_conventions()) == sorted([OLD, CLASH])


def test_a_duplicate_above_the_drop_band_is_not_stored(memory):
    memory.dedup_config['convention_drop_threshold'] = 0.5
    _seed(memory)
    _stub(memory, "SAME", "should never be reached")

    memory.store(NEW, "convention", "RE", "UpdateAlloyModel", 2)

    assert memory.get_conventions() == [OLD]


# ------------------------------------------------------------- evidence #

def test_the_shadow_log_records_the_verdict_not_just_the_band(memory, _store_root):
    """The band is testable; whether the classifier is RIGHT is not.

    The verdict column is the only evidence of that, which is what makes the log
    worth writing even now that the mechanism acts.
    """
    import json

    _seed(memory)
    _stub(memory, "CONTRADICTORY")
    memory.store(CLASH, "convention", "RE", "UpdateAlloyModel", 2, gated=True)

    log = _store_root / "Output" / "ConventionDedup" / "shadow.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    latest = records[-1]
    assert latest['verdict'] == "CONTRADICTORY"
    assert latest['would'] == "merge"
    assert latest['item_type'] == "convention"
    assert latest['top_match'] == OLD


def test_lessons_get_their_own_shadow_log(memory, _store_root):
    """Their floor has never been calibrated against anything - now it can be."""
    import json

    assistant = Mock()

    async def _classified(existing, new):
        return "SAME", "merged lesson"

    assistant.merge_lessons_classified = _classified
    memory._memory_assistant = assistant
    memory.dedup_config['merge_threshold'] = 0.5

    memory.store("Always check syntax first", "lesson", "RE", "Build", 1)
    memory.store("Always check syntax before running", "lesson", "RE", "Build", 2)

    log = _store_root / "Output" / "LessonDedup" / "shadow.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert records[-1]['item_type'] == "lesson"
    assert records[-1]['verdict'] == "SAME"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
