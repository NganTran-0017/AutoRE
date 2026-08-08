"""
Resuming to iteration N must discard audit-log entries from N onward.

Those entries describe a timeline the resume is about to rewrite. Left in place:
  - a surviving RegressionLog entry N shadows the fresh one, because add_entry
    appends and get_entry returns the first match;
  - RequirementPatchLog reports requirement changes that have not happened yet,
    which is what drives the stale-construct diagnosis;
  - ConstructRemovalLog claims a construct was deleted at an unreached iteration.

History BEFORE the resume point is deliberately kept.
"""

from unittest.mock import Mock

import pytest

from src.utils.construct_removal_log import ConstructRemovalEntry, ConstructRemovalLog
from src.utils.regression_log import (
    ImpactAnalysis,
    RegressionLog,
    RegressionLogEntry,
    VerificationResult,
)
from src.utils.requirement_patch_log import RequirementPatchLog, RequirementPatchLogEntry
from src.workflow import AutoREWorkflow


def _reg_entry(iteration_id, issue=None):
    """Minimal valid RegressionLogEntry - only iteration_id and issue matter here."""
    return RegressionLogEntry(
        iteration_id=iteration_id,
        model_file_location=f"AlloyModel__{iteration_id}.als",
        fix_intent="",
        source_ref="",
        current_result=VerificationResult(syntax="OK"),
        previous_result=None,
        updated_lines="",
        expected_impact=ImpactAnalysis(),
        issue=issue,
    )


def _workflow(tmp_path, resume_point, iterations=(20, 23, 40, 65)):
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.iteration.current = resume_point

    reg = RegressionLog(log_path=tmp_path / "regression.json")
    patch = RequirementPatchLog(log_path=tmp_path / "patch.json")
    removal = ConstructRemovalLog(log_path=tmp_path / "removal.json")

    # Requirement IDs deliberately do NOT track the iteration number: a fixture
    # writing "MODIFY R20" at iteration 20 reads, in a leaked log file, as if
    # the code stamped the iteration into the ID field.
    req_ids = {20: "R6", 23: "R1.2", 40: "R3", 65: "R6"}

    for i in iterations:
        req = req_ids.get(i, "R1")
        reg.add_entry(_reg_entry(i, issue=f"issue in Sym{i}"))
        patch.add_entry(RequirementPatchLogEntry(
            iteration_id=i, raw_response=f"[MODIFY] {req}", applied=[f"MODIFY {req}"],
            changes=[{"op": "MODIFY", "target": req,
                      "before": f"old text of {req}", "after": f"new text of {req}"}]))
        removal.add_entry(ConstructRemovalEntry(iteration_id=i, removed=[f"C{i}"]))

    wf.context.regression_log = reg
    wf.context.requirement_patch_log = patch
    wf.context.construct_removal_log = removal
    return wf


def _ids(log):
    return [e.iteration_id for e in log.entries]


# ------------------------------------------------------------------- trim #

def test_all_three_logs_drop_entries_at_and_after_the_resume_point(tmp_path):
    wf = _workflow(tmp_path, resume_point=23)
    wf._trim_logs_to_resume_point()

    # 23 itself goes: the resume re-runs iteration 23 and writes a new entry.
    assert _ids(wf.context.regression_log) == [20]
    assert _ids(wf.context.requirement_patch_log) == [20]
    assert _ids(wf.context.construct_removal_log) == [20]


def test_history_before_the_resume_point_is_preserved(tmp_path):
    wf = _workflow(tmp_path, resume_point=41)
    wf._trim_logs_to_resume_point()
    assert _ids(wf.context.regression_log) == [20, 23, 40]


def test_trim_is_persisted_not_just_in_memory(tmp_path):
    wf = _workflow(tmp_path, resume_point=23)
    wf._trim_logs_to_resume_point()

    # A later resume constructs fresh log objects from the same files.
    assert _ids(RegressionLog(log_path=tmp_path / "regression.json")) == [20]
    assert _ids(RequirementPatchLog(log_path=tmp_path / "patch.json")) == [20]
    assert _ids(ConstructRemovalLog(log_path=tmp_path / "removal.json")) == [20]


def test_resuming_past_all_entries_is_a_no_op(tmp_path):
    wf = _workflow(tmp_path, resume_point=99)
    wf._trim_logs_to_resume_point()
    assert _ids(wf.context.regression_log) == [20, 23, 40, 65]


def test_one_failing_log_does_not_stop_the_others(tmp_path):
    wf = _workflow(tmp_path, resume_point=23)
    broken = Mock()
    broken.entries = [Mock(iteration_id=65)]
    broken.trim_to_iteration.side_effect = OSError("disk gone")
    wf.context.regression_log = broken

    wf._trim_logs_to_resume_point()   # must not raise
    assert _ids(wf.context.construct_removal_log) == [20]


# ------------------------------------------------------- the shadowing bug #

def test_stale_entry_no_longer_shadows_the_rerun_of_that_iteration(tmp_path):
    # get_entry returns the FIRST match and add_entry appends, so without the
    # trim the pre-resume entry 23 wins over the one the rerun writes.
    wf = _workflow(tmp_path, resume_point=23)
    wf._trim_logs_to_resume_point()

    reg = wf.context.regression_log
    reg.add_entry(_reg_entry(23, issue="fresh result"))
    assert reg.get_entry(23).issue == "fresh result"


def test_future_requirement_changes_are_not_reported_after_trim(tmp_path):
    # changed_requirement_ids_since drives the stale-construct diagnosis; a
    # MODIFY recorded at iteration 65 must not be visible when resuming to 23.
    wf = _workflow(tmp_path, resume_point=23)
    wf._trim_logs_to_resume_point()
    assert "R65" not in wf.context.requirement_patch_log.changed_requirement_ids_since(0)


# ---------------------------------------------------------- symbol index #

def test_error_symbol_index_drops_trimmed_iterations(tmp_path):
    log = RegressionLog(log_path=tmp_path / "regression.json")
    log.add_entry(_reg_entry(20, issue="syntax error in factA"))
    log.add_entry(_reg_entry(65, issue="syntax error in factB"))
    assert log.error_symbol_index == {"factA": [20], "factB": [65]}

    log.trim_to_iteration(23)
    # factB only ever appeared in a discarded iteration, so it leaves entirely.
    assert log.error_symbol_index == {"factA": [20]}


def test_symbol_seen_in_both_kept_and_trimmed_iterations_keeps_the_kept_one(tmp_path):
    log = RegressionLog(log_path=tmp_path / "regression.json")
    log.add_entry(_reg_entry(20, issue="syntax error in factA"))
    log.add_entry(_reg_entry(65, issue="syntax error in factA"))
    log.trim_to_iteration(23)
    assert log.error_symbol_index == {"factA": [20]}


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
