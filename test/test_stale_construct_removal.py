"""
Fix D (removal): an orphaned construct encodes a requirement that no longer
exists, so there is nothing to rebuild it from - it is DELETED, and the helpers
it strands go with it.

Distinct from REGENERATE_PREDICATES, which rewrites a construct from its
requirement's UPDATED text.
"""

from src.utils.repair_plateau_detector import (
    REMOVE_STALE_CONSTRUCTS,
    build_stale_construct_removal,
)
from src.utils.traceability_store import audit_ownership, compute_removable_closure


MODEL = """
fact R1_Live { all s: State | one s.mode and some liveHelper[s] }
fact E5_Orphan { all r: Request | some auditOnlyHelper[r] and some sharedHelper[r] }

fun liveHelper[s: State]: Int { 1 }
fun auditOnlyHelper[r: Request]: Int { 1 }
fun sharedHelper[r: Request]: Int { 1 }

pred R2_Witness[s: State] { some s and some sharedHelper[s.req] }

run R2_Witness for 4
"""

LIVE = {'R1', 'R2'}   # E5 no longer exists


def _audit():
    return audit_ownership(MODEL, LIVE)


# --------------------------------------------------------------- closure #

def test_orphan_is_detected():
    audit = _audit()
    assert audit['orphan'] == {'E5_Orphan': ['E5']}


def test_closure_cascades_to_stranded_helper():
    closure = compute_removable_closure(MODEL, ['E5_Orphan'])
    # auditOnlyHelper was used ONLY by the orphan -> it goes too.
    assert 'E5_Orphan' in closure['remove']
    assert 'auditOnlyHelper' in closure['cascaded']


def test_closure_keeps_helpers_still_used_elsewhere():
    closure = compute_removable_closure(MODEL, ['E5_Orphan'])
    # sharedHelper is also used by the live R2_Witness -> must survive.
    assert 'sharedHelper' not in closure['remove']
    assert 'liveHelper' not in closure['remove']


def test_closure_blocks_a_seed_that_survivors_still_reference():
    # Asking to delete a helper the live fact still calls must not silently
    # break the model - it is reported as blocked and kept.
    closure = compute_removable_closure(MODEL, ['liveHelper'])
    assert closure['remove'] == []
    assert closure['blocked']['liveHelper'] == ['R1_Live']


def test_entry_point_predicate_never_cascades_away():
    closure = compute_removable_closure(MODEL, ['E5_Orphan'])
    assert 'R2_Witness' not in closure['remove']


def test_protect_list_is_honoured():
    closure = compute_removable_closure(MODEL, ['E5_Orphan'], protect={'auditOnlyHelper'})
    assert 'auditOnlyHelper' not in closure['remove']


# -------------------------------------------------------------- directive #

def test_directive_deletes_rather_than_rebuilds():
    audit = _audit()
    closure = compute_removable_closure(MODEL, list(audit['orphan']) + audit['dead'])
    d = build_stale_construct_removal(7, audit, closure)

    assert d['strategy'] == REMOVE_STALE_CONSTRUCTS
    assert 'E5_Orphan' in d['remove_targets']
    assert 'DELETE these constructs entirely' in d['directive']
    # Must not invite the weaken/convert-to-assertion misdiagnosis.
    assert 'Do NOT rewrite, weaken' in d['directive']
    # Each target carries its reason.
    assert 'encodes E5, which is no longer in the requirements' in d['directive']
    assert 'no caller once the constructs above are deleted' in d['directive']


def test_directive_reports_blocked_constructs():
    audit = _audit()
    closure = compute_removable_closure(MODEL, ['E5_Orphan', 'liveHelper'])
    d = build_stale_construct_removal(7, audit, closure)
    assert 'STILL REFERENCED' in d['directive']
    assert 'liveHelper <- R1_Live' in d['directive']


def test_no_targets_is_a_noop():
    d = build_stale_construct_removal(7, {'orphan': {}, 'dead': []}, {'remove': []})
    assert d['directive'] == ''
    assert d['remove_targets'] == []


def test_unclassified_constructs_are_not_removed():
    # Unlabelled is not the same as proven stale: never delete on silence alone.
    audit = _audit()
    seeds = list(audit['orphan']) + audit['dead']
    closure = compute_removable_closure(MODEL, seeds)
    for name in audit['unclassified']:
        assert name not in closure['remove']


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All stale-construct-removal tests passed.")
