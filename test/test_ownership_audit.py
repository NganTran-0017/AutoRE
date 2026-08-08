"""
Fix A (ownership): every construct that CONSTRAINS the model must declare what
requirement it encodes; helpers derive their ownership from the call graph.

This is what catches a stale fact left behind by an outdated requirement: it
has no live owner, so it surfaces as orphan (declared a dead requirement) or
unclassified (declared nothing) instead of silently constraining every run.
"""

from src.utils.semantic_diagnostics import build_reference_graph, requirement_ids
from src.utils.traceability_store import (
    TraceabilityStore,
    audit_ownership,
    format_ownership_report,
)


MODEL = """
// A constraining fact that names its requirement by convention.
fact R1_ModeExclusive { all s: State | one s.mode and some midHelper[s.owner] }

// A constraining fact for an EXISTING-system requirement.
fact E1_ClearanceAssignment { all u: User | one u.clearance }

// The stale case: constrains everything, declares nothing.
fact EmergencyUniqueness { all disj s1, s2: State | s1.t = s2.t and some rolesHeld[s1.owner, s1] }

// Deliberately encodes no requirement - declared, not silent.
fact NonAdminUserPresent { some u: User | u.isAdmin = False } //@req none:harness
fact UniqueTimePerState { all disj s1, s2: State | s1.t != s2.t } //@req none:frame

// Helpers: no requirement of their own, ownership comes from callers.
// deepHelper <- midHelper <- fact R1_ModeExclusive : two hops from the owner.
fun deepHelper[u: User]: Int { 1 }
fun midHelper[u: User]: Int { deepHelper[u] }
fun clearanceOf[u: User]: Int { u.clearance }
fun rolesHeld[u: User, s: State]: set Role { s.directRoles[u] }
fun neverUsed[u: User]: Int { 1 }

pred R2_Witness[s: State] { some s and some clearanceOf[s.owner] }
pred orphanedHelper[s: State] { some s }

assert assertR1Safety { all s: State | one s.mode }

run R2_Witness for 4
check assertR1Safety for 4
"""


def _audit(live=('R1', 'R2', 'E1')):
    return audit_ownership(MODEL, set(live))


# ------------------------------------------------------- reference graph #

def test_reference_graph_links_callers_and_entry_points():
    g = build_reference_graph(MODEL)
    assert 'deepHelper' in g['refs']['midHelper']
    assert 'midHelper' in g['callers']['deepHelper']
    # run/check lines are call sites, else witnesses look like dead code.
    assert g['entry_points'] == {'R2_Witness', 'assertR1Safety'}
    assert g['callers']['neverUsed'] == set()


def test_entry_point_predicate_is_not_mistaken_for_dead():
    audit = _audit()
    assert 'R2_Witness' not in audit['dead']
    assert 'assertR1Safety' not in audit['dead']


# ------------------------------------------------- derived helper ownership #

def test_helper_ownership_is_derived_from_callers():
    audit = _audit()
    # clearanceOf is called by R2_Witness -> it serves R2. Never declared.
    assert audit['derived']['clearanceOf'] == ['R2']
    assert 'clearanceOf' not in audit['unclassified']


def test_helper_ownership_is_transitive():
    # deepHelper <- midHelper <- fact R1_ModeExclusive: the owner is two hops up.
    audit = _audit()
    assert audit['derived']['midHelper'] == ['R1']
    assert audit['derived']['deepHelper'] == ['R1']


def test_helper_of_an_unowned_construct_derives_nothing():
    # rolesHeld is only called by EmergencyUniqueness, which declares no owner.
    # The closure must not invent one - and a helper is never itself a finding.
    audit = _audit()
    assert audit['derived']['rolesHeld'] == []
    assert 'rolesHeld' not in audit['unclassified']


def test_unreferenced_helper_is_dead_code():
    audit = _audit()
    assert 'neverUsed' in audit['dead']
    assert 'orphanedHelper' in audit['dead']


# --------------------------------------------------------- classification #

def test_unclassified_catches_the_stale_fact():
    audit = _audit()
    # A fact constrains unconditionally, so declaring nothing is a finding.
    assert 'EmergencyUniqueness' in audit['unclassified']


def test_declared_ownerless_is_not_a_finding():
    audit = _audit()
    assert audit['ownerless']['NonAdminUserPresent'] == 'harness'
    assert audit['ownerless']['UniqueTimePerState'] == 'frame'
    assert 'NonAdminUserPresent' not in audit['unclassified']


def test_orphan_is_a_construct_whose_requirement_is_gone():
    # E1 dropped from the live set -> its construct is orphaned, not merely
    # unclassified: it declares an owner that no longer exists.
    audit = audit_ownership(MODEL, {'R1', 'R2'})
    assert audit['orphan']['E1_ClearanceAssignment'] == ['E1']
    assert 'E1_ClearanceAssignment' not in audit['declared']


def test_existing_system_requirements_are_traced():
    # E-prefixed constructs must trace like R-prefixed ones.
    audit = _audit()
    assert audit['declared']['E1_ClearanceAssignment'] == ['E1']
    assert audit['declared']['R1_ModeExclusive'] == ['R1']


def test_requirement_ids_opt_in_to_e_prefix():
    assert requirement_ids(['E1_Clearance']) == []          # default: R-only
    assert requirement_ids(['E1_Clearance'], prefixes=('R', 'E')) == ['E1']
    assert requirement_ids(['R1R2_x'], prefixes=('R', 'E')) == ['R1', 'R2']


def test_annotation_parses_ids_and_ownerless_category():
    assert TraceabilityStore._parse_annotation('fact X { } //@req R2, R3.1') == (['R2', 'R3'], None)
    assert TraceabilityStore._parse_annotation('fact X { } //@req E1') == (['E1'], None)
    assert TraceabilityStore._parse_annotation('fact X { } //@req none:frame') == ([], 'frame')
    assert TraceabilityStore._parse_annotation('fact X { }') == ([], None)


# ------------------------------------------- assertions are not constraints #

PROBE_MODEL = """
fact R1_ModeExclusive { all s: State | one s.mode }
fact UndeclaredFact { all s: State | one s.t }

// An exploratory check that deliberately encodes no requirement.
assert assertEdgeCase { all s: State | some s } //@req none:probe

// An assertion that just never got labelled.
assert assertUnlabelled { all s: State | some s.mode }

check assertEdgeCase for 4
check assertUnlabelled for 4
"""


def test_undeclared_assertion_is_not_a_defect():
    audit = audit_ownership(PROBE_MODEL, {'R1'})
    # An assertion cannot over-constrain the model, so it is a documentation
    # gap - not the same finding as an undeclared fact.
    assert audit['undeclared_checks'] == ['assertUnlabelled']
    assert 'assertUnlabelled' not in audit['unclassified']


def test_undeclared_fact_is_still_a_defect():
    audit = audit_ownership(PROBE_MODEL, {'R1'})
    assert audit['unclassified'] == ['UndeclaredFact']


def test_probe_category_is_a_valid_ownerless_declaration():
    audit = audit_ownership(PROBE_MODEL, {'R1'})
    assert audit['ownerless']['assertEdgeCase'] == 'probe'
    assert 'assertEdgeCase' not in audit['undeclared_checks']
    assert 'assertEdgeCase' not in audit['unclassified']


def test_audit_reports_construct_kinds_for_gating():
    audit = audit_ownership(PROBE_MODEL, {'R1'})
    assert audit['kinds']['UndeclaredFact'] == 'fact'
    assert audit['kinds']['assertEdgeCase'] == 'assert'


def test_summary_and_report_are_consistent():
    audit = _audit()
    s = audit['summary']
    assert s['total'] == sum(
        s[k] for k in ('declared', 'derived', 'ownerless', 'orphan', 'dead',
                       'unclassified', 'undeclared_checks')
    )
    report = format_ownership_report(audit)
    assert 'OWNERSHIP AUDIT' in report
    assert 'EmergencyUniqueness' in report


def test_liveness_check_is_skipped_without_live_ids():
    # Structure-only mode: nothing can be orphaned if liveness is unknown.
    audit = audit_ownership(MODEL, None)
    assert audit['orphan'] == {}
    assert audit['declared']['E1_ClearanceAssignment'] == ['E1']


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All ownership-audit tests passed.")
