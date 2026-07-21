"""
Unit tests for src/utils/semantic_diagnostics.py - rungs 2-3 of the semantic
escalation ladder (scope/trace sweep + fact localization by delta debugging).

All Alloy runs are simulated through fake `check` callables, so no Alloy jar
is needed.

Run: python test/test_semantic_diagnostics.py   (from the repo root)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.semantic_diagnostics import (
    extract_fact_blocks,
    disable_facts,
    isolate_run_command,
    enlarge_run_scope,
    requirement_ids,
    scope_sweep,
    localize_blocking_facts,
    diagnose_unsat_predicates,
    make_alloy_sat_checker,
)


MODEL = """module diag_test

open util/ordering[State]

sig State { pending: set Job }
sig Job {}

fact R1_AllJobsPending {
    all j: Job | j in first.pending
}

fact R2_NoPending {
    no first.pending
}

fact R3_Unrelated { all s: State | some s.pending or no s.pending }

pred R1R2_Conflict {
    some Job
}

pred R4_Other { no Job }

run R1R2_Conflict for 4
run R4_Other for 3
check SomeAssert for 5
"""


def fact_enabled(model_text, name):
    return f"//DIAG fact {name}" not in model_text


def conflict_check(model_text, predicate):
    """SAT unless BOTH R1_AllJobsPending and R2_NoPending are enabled."""
    return not (fact_enabled(model_text, "R1_AllJobsPending")
                and fact_enabled(model_text, "R2_NoPending"))


def test_extract_and_disable_facts():
    facts = extract_fact_blocks(MODEL)
    names = [f['name'] for f in facts]
    assert names == ["R1_AllJobsPending", "R2_NoPending", "R3_Unrelated"], names

    disabled = disable_facts(MODEL, ["R2_NoPending"])
    assert "//DIAG fact R2_NoPending" in disabled
    assert "//DIAG     no first.pending" in disabled
    # Others untouched
    assert "//DIAG fact R1_AllJobsPending" not in disabled
    # Single-line fact block: start == end, still disabled cleanly
    one_line = disable_facts(MODEL, ["R3_Unrelated"])
    assert "//DIAG fact R3_Unrelated" in one_line
    print("PASS test_extract_and_disable_facts")


def test_isolate_run_command():
    isolated = isolate_run_command(MODEL, "R1R2_Conflict")
    assert isolated is not None
    assert "\nrun R1R2_Conflict for 4" in isolated
    assert "//DIAG run R4_Other for 3" in isolated
    assert "//DIAG check SomeAssert for 5" in isolated

    assert isolate_run_command(MODEL, "NoSuchPred") is None
    print("PASS test_isolate_run_command")


def test_enlarge_run_scope():
    # Doubles the bound but must NOT touch digits in the predicate name
    enlarged = enlarge_run_scope(MODEL, "R1R2_Conflict")
    assert enlarged is not None
    assert enlarged['command'] == "run R1R2_Conflict for 8", enlarged['command']
    assert "run R1R2_Conflict for 8" in enlarged['model_text']
    assert "R2R4_Conflict" not in enlarged['model_text']  # name-mangling regression

    # Cap at 16
    capped = enlarge_run_scope("pred P {}\nrun P for 10", "P")
    assert capped['command'] == "run P for 16", capped['command']

    # No bounds -> append " for 8"
    unbounded = enlarge_run_scope("pred P {}\nrun P", "P")
    assert unbounded['command'] == "run P for 8", unbounded['command']

    # Missing run command
    assert enlarge_run_scope(MODEL, "NoSuchPred") is None
    print("PASS test_enlarge_run_scope")


def test_requirement_ids():
    ids = requirement_ids(["R2_NoPending", "R1_AllJobsPending", "R1R2_Conflict"])
    assert ids == ["R1", "R2"], ids
    # Numeric (not lexicographic) sort: R10 after R2
    assert requirement_ids(["R10_x", "R2_y"]) == ["R2", "R10"]
    assert requirement_ids(["plainName", None]) == []
    print("PASS test_requirement_ids")


def test_scope_sweep():
    # Artifact: SAT once the run line carries the enlarged bound
    artifact_check = lambda text, pred: "run R1R2_Conflict for 8" in text
    sweep = scope_sweep(MODEL, "R1R2_Conflict", artifact_check)
    assert sweep['performed'] is True
    assert sweep['sat_at_larger_scope'] is True
    assert sweep['swept_command'] == "run R1R2_Conflict for 8"

    # Genuine over-constraint: still UNSAT at larger scope
    sweep = scope_sweep(MODEL, "R1R2_Conflict", lambda t, p: False)
    assert sweep['performed'] is True and sweep['sat_at_larger_scope'] is False

    # No run command
    sweep = scope_sweep(MODEL, "NoSuchPred", lambda t, p: True)
    assert sweep['performed'] is False and "no run command" in sweep['reason']

    # Variant failed to execute
    sweep = scope_sweep(MODEL, "R1R2_Conflict", lambda t, p: None)
    assert sweep['performed'] is False
    print("PASS test_scope_sweep")


def test_localize_blocking_facts_minimal_pair():
    result = localize_blocking_facts(MODEL, "R1R2_Conflict", conflict_check)
    assert result['verdict'] == 'localized', result
    assert result['blocking_facts'] == ["R1_AllJobsPending", "R2_NoPending"], result
    assert result['implicated_requirements'] == ["R1", "R2"], result
    assert result['approximate'] is False
    # baseline + one trial per fact
    assert result['runs'] == 4, result['runs']
    print("PASS test_localize_blocking_facts_minimal_pair")


def test_localize_internal_contradiction():
    # UNSAT even with every fact disabled -> conflict inside the predicate
    result = localize_blocking_facts(MODEL, "R1R2_Conflict", lambda t, p: False)
    assert result['verdict'] == 'internal_contradiction', result
    assert result['runs'] == 1
    print("PASS test_localize_internal_contradiction")


def test_localize_no_facts_and_errors():
    factless = "pred P { some none }\nrun P for 4"
    result = localize_blocking_facts(factless, "P", conflict_check)
    assert result['verdict'] == 'no_facts', result

    result = localize_blocking_facts(MODEL, "NoSuchPred", conflict_check)
    assert result['verdict'] == 'error' and "no run command" in result['reason']

    # Baseline variant fails to execute -> error
    result = localize_blocking_facts(MODEL, "R1R2_Conflict", lambda t, p: None)
    assert result['verdict'] == 'error' and 'baseline' in result['reason']
    print("PASS test_localize_no_facts_and_errors")


def test_localize_budget_exhausted_is_approximate():
    # max_runs=1: baseline consumes the budget, all facts stay suspects
    result = localize_blocking_facts(MODEL, "R1R2_Conflict", conflict_check, max_runs=1)
    assert result['verdict'] == 'localized'
    assert result['approximate'] is True
    assert set(result['blocking_facts']) == {
        "R1_AllJobsPending", "R2_NoPending", "R3_Unrelated"}
    print("PASS test_localize_budget_exhausted_is_approximate")


def test_localize_failed_variant_keeps_fact_conservatively():
    def flaky(model_text, predicate):
        # Trial disabling R3_Unrelated fails to execute; others behave normally
        if (not fact_enabled(model_text, "R3_Unrelated")
                and fact_enabled(model_text, "R1_AllJobsPending")):
            return None
        return conflict_check(model_text, predicate)
    result = localize_blocking_facts(MODEL, "R1R2_Conflict", flaky)
    assert result['verdict'] == 'localized'
    assert result['approximate'] is True
    # R3 could not be exonerated, so it is conservatively kept
    assert "R3_Unrelated" in result['blocking_facts']
    print("PASS test_localize_failed_variant_keeps_fact_conservatively")


def test_diagnose_artifact_short_circuits_localization():
    artifact_check = lambda text, pred: "run R1R2_Conflict for 8" in text
    diag = diagnose_unsat_predicates(MODEL, ["R1R2_Conflict"], artifact_check)
    assert "SATISFIABLE at enlarged bounds" in diag['directive_text']
    assert "bounded-search artifact" in diag['directive_text']
    # Rung 3 must NOT run when rung 2 already explains the UNSAT
    assert 'localization' not in diag['results']['R1R2_Conflict']
    print("PASS test_diagnose_artifact_short_circuits_localization")


def test_diagnose_genuine_conflict_renders_proven_set():
    diag = diagnose_unsat_predicates(MODEL, ["R1R2_Conflict"], conflict_check)
    text = diag['directive_text']
    assert "DETERMINISTIC DIAGNOSIS" in text
    assert "still UNSAT at enlarged bounds" in text
    assert "MINIMAL BLOCKING FACT SET" in text
    assert "R1_AllJobsPending, R2_NoPending" in text
    assert "implicated requirements: R1, R2" in text
    loc = diag['results']['R1R2_Conflict']['localization']
    assert loc['verdict'] == 'localized'
    print("PASS test_diagnose_genuine_conflict_renders_proven_set")


def test_diagnose_caps_predicates():
    diag = diagnose_unsat_predicates(
        MODEL, ["R1R2_Conflict", "R4_Other", "P3"], conflict_check, max_predicates=2)
    assert "diagnosis capped: not run for P3" in diag['directive_text']
    assert "P3" not in diag['results']
    print("PASS test_diagnose_caps_predicates")


def test_diagnose_internal_contradiction_message():
    diag = diagnose_unsat_predicates(MODEL, ["R1R2_Conflict"], lambda t, p: False)
    assert "UNSAT even" in diag['directive_text']
    assert "INSIDE the predicate body" in diag['directive_text']
    print("PASS test_diagnose_internal_contradiction_message")


def test_make_alloy_sat_checker_mapping(tmp_dir=None):
    import tempfile

    class FakeExecutor:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def execute(self, model_path, output_dir, timeout):
            self.calls.append(model_path)
            return self.result

    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "diag"

        # UNSAT: predicate listed in unsat_run_commands
        ex = FakeExecutor({'success': True, 'analysis': {
            'has_syntax_errors': False, 'has_results': True,
            'unsat_run_commands': [{'name': 'P', 'type': 'run', 'number': 1}]}})
        check = make_alloy_sat_checker(ex, work)
        assert check("pred P {}", "P") is False
        # Variant file was written for inspection
        assert ex.calls and ex.calls[0].exists()

        # SAT: results present, predicate not in the UNSAT list
        ex = FakeExecutor({'success': True, 'analysis': {
            'has_syntax_errors': False, 'has_results': True,
            'unsat_run_commands': []}})
        assert make_alloy_sat_checker(ex, work)("pred P {}", "P") is True

        # Syntax error in variant -> None
        ex = FakeExecutor({'success': True, 'analysis': {
            'has_syntax_errors': True, 'has_results': False,
            'unsat_run_commands': []}})
        assert make_alloy_sat_checker(ex, work)("pred P {}", "P") is None

        # Tool failure -> None
        ex = FakeExecutor({'success': False})
        assert make_alloy_sat_checker(ex, work)("pred P {}", "P") is None
    print("PASS test_make_alloy_sat_checker_mapping")


if __name__ == "__main__":
    test_extract_and_disable_facts()
    test_isolate_run_command()
    test_enlarge_run_scope()
    test_requirement_ids()
    test_scope_sweep()
    test_localize_blocking_facts_minimal_pair()
    test_localize_internal_contradiction()
    test_localize_no_facts_and_errors()
    test_localize_budget_exhausted_is_approximate()
    test_localize_failed_variant_keeps_fact_conservatively()
    test_diagnose_artifact_short_circuits_localization()
    test_diagnose_genuine_conflict_renders_proven_set()
    test_diagnose_caps_predicates()
    test_diagnose_internal_contradiction_message()
    test_make_alloy_sat_checker_mapping()
    print("\nAll semantic_diagnostics tests passed.")
