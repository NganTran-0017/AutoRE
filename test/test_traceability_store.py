"""
TraceabilityStore: reconciled requirement -> Alloy-construct map, built from the
deterministic R-prefix layer plus validated RE annotations.
"""

from src.utils.semantic_diagnostics import extract_all_blocks
from src.utils.traceability_store import TraceabilityStore


MODEL = """
fact R1R2_policy { some x }
pred R3[s: State] { some s }
assert assertR6 { no x }
fact EmergencyUnique { one e }
fun helper : Int { 1 }
"""


def test_extract_all_blocks_covers_every_kind():
    blocks = {b['name']: b['kind'] for b in extract_all_blocks(MODEL)}
    assert blocks == {
        'R1R2_policy': 'fact',
        'R3': 'pred',
        'assertR6': 'assert',
        'EmergencyUnique': 'fact',
        'helper': 'fun',
    }


def test_deterministic_layer_maps_prefixed_constructs():
    ts = TraceabilityStore()
    ts.rebuild(MODEL)
    assert ts.constructs_for(['R1']) == ['R1R2_policy']
    assert ts.constructs_for(['R2']) == ['R1R2_policy']
    assert ts.constructs_for(['R3']) == ['R3']
    assert ts.constructs_for(['R6']) == ['assertR6']
    # Un-prefixed construct is invisible to the deterministic layer alone.
    assert 'EmergencyUnique' not in ts.constructs_for(['R2'])


def test_annotation_layer_catches_unprefixed_construct():
    ts = TraceabilityStore()
    ts.rebuild(MODEL, annotations={'EmergencyUnique': ['R2']})
    assert ts.constructs_for(['R2']) == ['EmergencyUnique', 'R1R2_policy']
    assert ts.requirements_for('EmergencyUnique') == ['R2']


def test_in_model_req_comment_annotation():
    model = (
        "fact R1R2_policy { some x }\n"
        "fact EmergencyUnique { one e } //@req R2\n"
        "assert assertSafety { no y }  // @req R3, R4.1\n"
    )
    ts = TraceabilityStore()
    ts.rebuild(model)
    # Un-prefixed constructs are picked up from their //@req comment.
    assert ts.requirements_for('EmergencyUnique') == ['R2']
    assert ts.requirements_for('assertSafety') == ['R3', 'R4']  # R4.1 -> R4 root
    assert ts.constructs_for(['R2']) == ['EmergencyUnique', 'R1R2_policy']


def test_req_comment_auto_reconciles_when_construct_removed():
    ts = TraceabilityStore()
    ts.rebuild("fact EmergencyUnique { one e } //@req R2")
    assert ts.constructs_for(['R2']) == ['EmergencyUnique']
    # Construct (and its comment) removed next iteration -> mapping gone.
    ts.rebuild("fact R1R2_policy { some x }")
    assert ts.constructs_for(['R2']) == ['R1R2_policy']
    assert 'EmergencyUnique' not in ts.requirements_for('EmergencyUnique')


def test_reconciliation_drops_stale_annotation():
    ts = TraceabilityStore()
    # GhostConstruct is not present in the model -> its annotation is discarded.
    ts.rebuild(MODEL, annotations={'GhostConstruct': ['R9'], 'EmergencyUnique': ['R2']})
    assert ts.constructs_for(['R9']) == []
    assert 'R9' not in ts.as_dict()
    assert ts.constructs_for(['R2']) == ['EmergencyUnique', 'R1R2_policy']


def test_rebuild_is_idempotent_and_forgets_deleted_constructs():
    ts = TraceabilityStore()
    ts.rebuild(MODEL, annotations={'EmergencyUnique': ['R2']})
    # R6's construct is removed from the model on the next iteration.
    ts.rebuild("fact R1R2_policy { some x }")
    assert ts.constructs_for(['R6']) == []
    assert ts.constructs_for(['R1']) == ['R1R2_policy']


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All traceability-store tests passed.")
