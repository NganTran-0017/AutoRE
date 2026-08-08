"""
Routing of requirement changes to the right remedy, and E-requirement coverage.

  MODIFY -> REGENERATE_PREDICATES (rebuild from the requirement's new text)
  REMOVE -> REMOVE_STALE_CONSTRUCTS (delete; there is no text to rebuild from)

Routing REMOVE to regeneration told the RE to rebuild from a requirement that no
longer existed, and the ownership audit then ordered the same construct deleted
one step later - two contradictory instructions.
"""

from unittest.mock import Mock

from src.utils.repair_plateau_detector import (
    REGENERATE_PREDICATES,
    REMOVE_STALE_CONSTRUCTS,
)
from src.utils.semantic_diagnostics import requirement_ids
from src.utils.traceability_store import TraceabilityStore
from src.workflow import AutoREWorkflow


MODEL = """
fact R6_CredentialPolicy { all a: Admin | a.updated = True }
fact E3_DelegationRules { all d: Delegation | d.role in d.delegator.roles }
fun sharedHelper[a: Admin]: Int { 1 }
pred R7_Witness[a: Admin] { some a and some sharedHelper[a] }
run R7_Witness for 4
"""


def _workflow(applied_ops):
    """Minimal workflow with a patch log reporting `applied_ops` this iteration."""
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.iteration.current = 12
    wf.context.artifacts.get_latest_alloy_model.return_value = MODEL
    wf.context.pending_requirement_regeneration = None
    wf.context.pending_stale_removal = None

    store = TraceabilityStore()
    store.rebuild(MODEL)
    wf.context.traceability = store

    def changed(iteration_id, ops=("MODIFY", "REMOVE")):
        return [target for op, target in applied_ops if op in ops]

    wf.context.requirement_patch_log.changed_requirement_ids.side_effect = changed
    return wf


# ------------------------------------------------------------- MODIFY path #

def test_modify_stages_regeneration_only():
    wf = _workflow([("MODIFY", "R6")])
    wf._stage_requirement_change_regeneration("R6: new text")

    regen = wf.context.pending_requirement_regeneration
    assert regen["strategy"] == REGENERATE_PREDICATES
    assert regen["regenerate_targets"] == ["R6_CredentialPolicy"]
    assert wf.context.pending_stale_removal is None


# ------------------------------------------------------------- REMOVE path #

def test_remove_stages_deletion_not_regeneration():
    wf = _workflow([("REMOVE", "R6")])
    wf._stage_requirement_change_regeneration("(R6 deleted)")

    # The critical assertion: a removed requirement is never sent to the
    # regenerate path, which would ask the RE to rebuild from nothing.
    assert wf.context.pending_requirement_regeneration is None
    removal = wf.context.pending_stale_removal
    assert removal["strategy"] == REMOVE_STALE_CONSTRUCTS
    assert "R6_CredentialPolicy" in removal["remove_targets"]
    assert "DELETE these constructs entirely" in removal["directive"]


def test_remove_and_modify_are_routed_separately():
    wf = _workflow([("MODIFY", "R7"), ("REMOVE", "R6")])
    wf._stage_requirement_change_regeneration("R7: new text")

    assert wf.context.pending_requirement_regeneration["regenerate_targets"] == ["R7_Witness"]
    assert wf.context.pending_stale_removal["remove_targets"] == ["R6_CredentialPolicy"]


def test_removal_does_not_take_helpers_still_in_use():
    # sharedHelper is also called by the surviving R7_Witness.
    wf = _workflow([("REMOVE", "R6")])
    wf._stage_requirement_change_regeneration("(R6 deleted)")
    assert "sharedHelper" not in wf.context.pending_stale_removal["remove_targets"]


def test_remove_of_untraced_requirement_stages_nothing():
    wf = _workflow([("REMOVE", "R99")])
    wf._stage_requirement_change_regeneration("(R99 deleted)")
    assert wf.context.pending_stale_removal is None
    assert wf.context.pending_requirement_regeneration is None


def test_existing_pending_removal_is_not_discarded():
    # A removal staged by the previous iteration's audit must survive a step 7
    # that has no REMOVE of its own.
    wf = _workflow([("MODIFY", "R6")])
    wf.context.pending_stale_removal = {"directive": "from the audit"}
    wf._stage_requirement_change_regeneration("R6: new text")
    assert wf.context.pending_stale_removal == {"directive": "from the audit"}


# ----------------------------------------------- existing-system (E#) reqs #

def test_existing_system_requirement_change_is_routed():
    wf = _workflow([("MODIFY", "E3")])
    wf._stage_requirement_change_regeneration("E3: new text")
    # E# requirements were dropped before lookup while the roots were R-only.
    assert wf.context.pending_requirement_regeneration["regenerate_targets"] == [
        "E3_DelegationRules"
    ]


def test_e_requirement_removal_is_routed_to_deletion():
    wf = _workflow([("REMOVE", "E3")])
    wf._stage_requirement_change_regeneration("(E3 deleted)")
    assert wf.context.pending_stale_removal["remove_targets"] == ["E3_DelegationRules"]


# ------------------------------- deletion is gated by construct kind #

ORPHAN_MODEL = """
fact E9_OrphanFact { all s: State | some s }
assert assertE9_Orphan { all s: State | some s }
pred R7_Witness[s: State] { some s }
check assertE9_Orphan for 4
run R7_Witness for 4
"""


def _audit_workflow():
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    wf.context = Mock()
    wf.context.iteration.current = 12
    wf.context.pending_stale_removal = None
    return wf


def test_audit_path_deletes_orphan_facts_but_not_orphan_assertions():
    from src.utils.traceability_store import audit_ownership

    wf = _audit_workflow()
    audit = audit_ownership(ORPHAN_MODEL, {'R7'})   # E9 no longer exists
    assert set(audit['orphan']) == {'E9_OrphanFact', 'assertE9_Orphan'}

    wf._stage_stale_construct_removal(ORPHAN_MODEL, audit)
    targets = wf.context.pending_stale_removal['remove_targets']
    # The fact goes: removing it only relaxes the model.
    assert 'E9_OrphanFact' in targets
    # The assertion stays: "absent from the parsed requirements" is inferred,
    # and deleting a check silently removes verification coverage.
    assert 'assertE9_Orphan' not in targets


def test_explicit_removal_deletes_assertions_too():
    # A REMOVE in the patch log is proof the requirement is gone, so every kind
    # its constructs cover is deleted - including the assertion.
    wf = _workflow([("REMOVE", "R6")])
    wf.context.artifacts.get_latest_alloy_model.return_value = (
        "fact R6_Policy { all a: Admin | a.ok = True }\n"
        "assert assertR6_Check { all a: Admin | a.ok = True }\n"
        "check assertR6_Check for 4\n"
    )
    store = TraceabilityStore()
    store.rebuild(wf.context.artifacts.get_latest_alloy_model.return_value)
    wf.context.traceability = store

    wf._stage_requirement_change_regeneration("(R6 deleted)")
    targets = wf.context.pending_stale_removal['remove_targets']
    assert 'R6_Policy' in targets and 'assertR6_Check' in targets


def test_root_extraction_covers_both_families():
    assert requirement_ids(["E3.1", "R6"], prefixes=("R", "E")) == ["E3", "R6"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All requirement-change-routing tests passed.")
