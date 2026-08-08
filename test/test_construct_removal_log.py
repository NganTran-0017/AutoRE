"""
Persistence of the deterministic construct-removal audit trail.

The log exists so the Evaluator can tell "the workflow deleted this on purpose"
from "this regressed". That only works if the record survives a resume, which an
in-memory list does not - the context is rebuilt from disk on every resume.
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.utils.construct_removal_log import ConstructRemovalEntry, ConstructRemovalLog
from src.workflow import AutoREWorkflow


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "construct_removal_log.json"


def _entry(iteration=65, removed=None, **kw):
    return ConstructRemovalEntry(
        iteration_id=iteration,
        removed=removed if removed is not None else ["E5_RequestProcessorAudit"],
        kinds=kw.pop("kinds", {"E5_RequestProcessorAudit": "fact"}),
        orphan_owners=kw.pop("orphan_owners", {"E5_RequestProcessorAudit": ["E5"]}),
        **kw,
    )


# ------------------------------------------------------------- persistence #

def test_entry_survives_a_new_log_instance(log_path):
    ConstructRemovalLog(log_path=log_path).add_entry(_entry())

    # A resume constructs a fresh context - and therefore a fresh log object.
    reloaded = ConstructRemovalLog(log_path=log_path)
    assert len(reloaded.entries) == 1
    assert reloaded.entries[0].removed == ["E5_RequestProcessorAudit"]
    assert reloaded.entries[0].orphan_owners == {"E5_RequestProcessorAudit": ["E5"]}
    assert reloaded.entries[0].kinds == {"E5_RequestProcessorAudit": "fact"}


def test_round_trip_preserves_every_field(log_path):
    original = _entry(dropped_lines=7, blocked={"helper": ["survivor"]})
    ConstructRemovalLog(log_path=log_path).add_entry(original)
    restored = ConstructRemovalLog(log_path=log_path).entries[0]
    assert restored.to_dict() == original.to_dict()


def test_corrupt_log_does_not_break_the_run(log_path):
    log_path.write_text("{ not json")
    log = ConstructRemovalLog(log_path=log_path)   # must not raise
    assert log.entries == []


def test_empty_file_is_not_an_error(log_path):
    log_path.write_text("")
    assert ConstructRemovalLog(log_path=log_path).entries == []


# ------------------------------------------------------------------ resume #

def test_trim_discards_removals_after_the_resume_point(log_path):
    log = ConstructRemovalLog(log_path=log_path)
    log.add_entry(_entry(iteration=20, removed=["OldFact"]))
    log.add_entry(_entry(iteration=65, removed=["E5_RequestProcessorAudit"]))

    # Resuming to 23: the iteration-65 deletion has not happened yet.
    log.trim_to_iteration(23)
    assert [e.iteration_id for e in log.entries] == [20]
    # and the trim is persisted, not just applied in memory
    assert [e.iteration_id for e in ConstructRemovalLog(log_path=log_path).entries] == [20]


def test_clear_removes_the_file_for_a_fresh_start(log_path):
    log = ConstructRemovalLog(log_path=log_path)
    log.add_entry(_entry())
    log.clear()
    assert log.entries == []
    assert not log_path.exists()


# ------------------------------------------------------------------ lookup #

def test_removed_names_dedupes_across_iterations(log_path):
    log = ConstructRemovalLog(log_path=log_path)
    log.add_entry(_entry(iteration=10, removed=["A", "B"]))
    log.add_entry(_entry(iteration=12, removed=["B", "C"]))
    assert log.removed_names() == ["A", "B", "C"]
    assert log.removed_names(since_iteration=12) == ["B", "C"]


def test_entries_for_iteration(log_path):
    log = ConstructRemovalLog(log_path=log_path)
    log.add_entry(_entry(iteration=10, removed=["A"]))
    log.add_entry(_entry(iteration=12, removed=["B"]))
    assert [e.removed for e in log.get_entries_for_iteration(12)] == [["B"]]


# ------------------------------------------------------------ prompt block #

def test_prompt_block_states_the_deletion_was_deliberate(log_path):
    log = ConstructRemovalLog(log_path=log_path)
    log.add_entry(_entry())
    block = log.format_for_prompt()
    assert "DELETED DELIBERATELY" in block
    assert "E5_RequestProcessorAudit" in block
    assert "[fact]" in block
    assert "declared E5" in block
    # The instruction the whole mechanism exists to deliver:
    assert "regression" in block


def test_prompt_block_is_explicit_when_nothing_was_removed(log_path):
    # A blank block would read as missing data; say so instead.
    assert "None" in ConstructRemovalLog(log_path=log_path).format_for_prompt()


def test_prompt_block_reports_constructs_that_could_not_be_removed(log_path):
    log = ConstructRemovalLog(log_path=log_path)
    log.add_entry(_entry(blocked={"sharedHelper": ["R7_Witness"]}))
    block = log.format_for_prompt()
    assert "sharedHelper KEPT - still referenced by R7_Witness" in block


def test_prompt_block_shows_only_recent_entries(log_path):
    log = ConstructRemovalLog(log_path=log_path)
    for i in range(6):
        log.add_entry(_entry(iteration=i, removed=[f"C{i}"]))
    block = log.format_for_prompt(count=2)
    assert "C5" in block and "C4" in block
    assert "C0" not in block


# ------------------------------------------------------ workflow recording #

def test_workflow_records_a_prune_with_kinds_and_owners(log_path):
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.iteration.current = 65
    wf.context.construct_removal_log = ConstructRemovalLog(log_path=log_path)
    wf.logger = Mock()

    pending = {
        "audit": {
            "orphan": {"E5_RequestProcessorAudit": ["E5"]},
            "kinds": {"E5_RequestProcessorAudit": "fact", "Untouched": "pred"},
        },
        "blocked": {},
    }
    pruned = {"removed": ["E5_RequestProcessorAudit"], "dropped_lines": 5}

    wf._record_construct_removal(pending, pruned)

    entry = wf.context.construct_removal_log.entries[0]
    assert entry.iteration_id == 65
    assert entry.removed == ["E5_RequestProcessorAudit"]
    # kinds is filtered to what was actually removed - not the whole model.
    assert entry.kinds == {"E5_RequestProcessorAudit": "fact"}
    assert entry.dropped_lines == 5
    # and it reached disk, so the next resume still sees it
    assert json.loads(log_path.read_text())[0]["removed"] == ["E5_RequestProcessorAudit"]


def test_kinds_survive_the_directive_builder(log_path):
    # Regression (run 073026): the record showed 'kinds': {} because the
    # directive builder rebuilt a stripped audit that dropped the kinds map,
    # so the Evaluator saw a bare name instead of "E5_... [fact]".
    from src.utils.repair_plateau_detector import build_stale_construct_removal

    directive = build_stale_construct_removal(
        current_iteration=67,
        audit={"orphan": {"E5_Audit": ["E5"]}, "dead": [],
               "kinds": {"E5_Audit": "fact"}},
        closure={"remove": ["E5_Audit"], "cascaded": [], "blocked": {}},
    )
    assert directive["audit"]["kinds"] == {"E5_Audit": "fact"}


def test_recording_failure_never_breaks_the_model_update(log_path):
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.iteration.current = 65
    wf.logger = Mock()
    # A malformed prune result must not propagate out of the audit trail.
    wf._record_construct_removal({"audit": {}}, {"removed": ["X"]})   # no 'dropped_lines'


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
