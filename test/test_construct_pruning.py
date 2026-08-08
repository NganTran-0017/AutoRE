"""
Deterministic deletion of stale constructs.

The RE is not asked to delete an orphan - the construct is removed from the
model it is about to edit. The observed failure mode was the RE weakening such
a fact instead of removing it, so compliance is not relied on.

Pruning is fail-safe: any validation failure returns the ORIGINAL text with
ok=False and the caller falls back to instructing the RE.
"""

from src.utils.repair_plateau_detector import build_stale_construct_removal
from src.utils.semantic_diagnostics import build_reference_graph, extract_all_blocks
from src.utils.traceability_store import prune_constructs


MODEL = """// header comment
sig State {}

// -- Emergency uniqueness: only one Emergency ever
// (superseded wording that must not survive the deletion)
fact E5_Orphan {
    all disj s1, s2: State | s1 != s2
}

fact R1_Live { all s: State | some s }

pred E5_Scenario[s: State] { some s }

assert assertE5_Audit { all s: State | some s }

pred R2_Witness[s: State] { some s }

check assertE5_Audit for 4
run E5_Scenario for 4
run R2_Witness for 4
"""


# ------------------------------------------------------- command detection #

def test_graph_reports_command_lines_per_construct():
    g = build_reference_graph(MODEL)
    assert set(g['commands']) == {'assertE5_Audit', 'E5_Scenario', 'R2_Witness'}
    assert g['entry_points'] == set(g['commands'])


# ------------------------------------------------------------------ prune #

def test_prune_removes_block_command_and_attached_comment():
    result = prune_constructs(MODEL, ['E5_Orphan', 'E5_Scenario', 'assertE5_Audit'])
    assert result['ok'], result['reason']
    text = result['model_text']

    # Blocks gone.
    assert {b['name'] for b in extract_all_blocks(text)} == {'R1_Live', 'R2_Witness'}
    # Commands gone - a check naming a deleted assertion would not parse.
    assert 'check assertE5_Audit' not in text
    assert 'run E5_Scenario' not in text
    # The superseded wording in the attached comment goes with the construct,
    # so it cannot invite the RE to re-add the rule.
    assert 'superseded wording' not in text
    assert 'only one Emergency ever' not in text


def test_prune_keeps_survivors_and_their_commands():
    result = prune_constructs(MODEL, ['E5_Orphan', 'E5_Scenario', 'assertE5_Audit'])
    text = result['model_text']
    assert 'fact R1_Live' in text
    assert 'pred R2_Witness' in text
    assert 'run R2_Witness for 4' in text
    assert '// header comment' in text
    assert 'sig State {}' in text


def test_prune_reports_what_it_removed():
    result = prune_constructs(MODEL, ['E5_Orphan'])
    assert result['removed'] == ['E5_Orphan']
    assert result['dropped_lines'] > 0


# -------------------------------------------------------------- fail-safe #

def test_prune_refuses_when_a_target_is_absent():
    result = prune_constructs(MODEL, ['E5_Orphan', 'NotInModel'])
    assert result['ok'] is False
    assert 'not in model' in result['reason']
    assert result['model_text'] == MODEL       # original returned untouched


def test_prune_refuses_when_a_reference_would_dangle():
    model = (
        "fact R1_Live { all s: State | some helperX[s] }\n"
        "fun helperX[s: State]: Int { 1 }\n"
    )
    result = prune_constructs(model, ['helperX'])
    assert result['ok'] is False
    assert 'references remain' in result['reason']
    assert result['model_text'] == model


def test_prune_of_nothing_is_a_safe_noop():
    result = prune_constructs(MODEL, [])
    assert result['ok'] is False
    assert result['model_text'] == MODEL


# -------------------------------------------------------------- directive #

def test_already_removed_directive_tells_the_re_not_to_re_add():
    audit = {'orphan': {'E5_Orphan': ['E5']}, 'dead': []}
    closure = {'remove': ['E5_Orphan'], 'cascaded': [], 'blocked': {}}
    d = build_stale_construct_removal(9, audit, closure, already_removed=True)

    assert 'ALREADY BEEN REMOVED' in d['directive']
    assert 'Do NOT' in d['directive'] and 're-introduce' in d['directive']
    # Must not ask for a deletion that already happened.
    assert 'DELETE these constructs entirely' not in d['directive']
    assert 'encodes E5, which is no longer in the requirements' in d['directive']


def test_instruction_mode_is_unchanged():
    audit = {'orphan': {'E5_Orphan': ['E5']}, 'dead': []}
    closure = {'remove': ['E5_Orphan'], 'cascaded': [], 'blocked': {}}
    d = build_stale_construct_removal(9, audit, closure)
    assert 'DELETE these constructs entirely' in d['directive']
    assert 'ALREADY BEEN REMOVED' not in d['directive']


def test_directive_carries_audit_for_later_rerender():
    audit = {'orphan': {'E5_Orphan': ['E5']}, 'dead': ['deadFun']}
    closure = {'remove': ['E5_Orphan', 'deadFun'], 'cascaded': [], 'blocked': {}}
    d = build_stale_construct_removal(9, audit, closure)
    assert d['audit']['orphan'] == {'E5_Orphan': ['E5']}
    assert d['audit']['dead'] == ['deadFun']


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All construct-pruning tests passed.")
