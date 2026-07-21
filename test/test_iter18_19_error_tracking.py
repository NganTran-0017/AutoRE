"""
Regression tests derived from the 0708 run (Output/outputlog/070826.log),
iterations 18-19, where pred R1R2 flip-flopped between a type/arity error and a
delimiter/syntax error.

Captured facts from that run:
  iter 15, 18 -> "This expression failed to be typechecked" (model line 169)
                 => type_error:arity_or_join_error:pred:R1R2:predicate_body:relation_arity_or_join_error
  iter 16,17,19 -> "There are 37 possible tokens that can appear here" (line 170)
                 => syntax_error:unexpected_token:pred:R1R2:predicate_body:delimiter_or_block_structure_error

The three tests below pin down how the current code treats this flip:
  1. classification  - the two errors are DIFFERENT (ErrorNormalizer)
  2. resolution      - iter 19 counts as resolving iter 18's target (check_issue_resolved)
  3. pattern         - the flip is NOT an alternating_error_loop, and the
                       root-family channel does NOT bridge the type<->syntax flip
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.error_normalizer import ErrorNormalizer
from src.utils.issue_pattern_tracker import IssuePatternTracker
from src.utils.regression_log import (
    RegressionLogEntry,
    VerificationResult,
    ImpactAnalysis,
    check_issue_resolved,
)

# --- Signatures as recorded by the live run -------------------------------- #
SIG_TYPE = ("type_error:arity_or_join_error:pred:R1R2:predicate_body:"
            "relation_arity_or_join_error")
SIG_SYNTAX = ("syntax_error:unexpected_token:pred:R1R2:predicate_body:"
              "delimiter_or_block_structure_error")
# Earlier delimiter-root errors on a different construct (fun leq), iters 13-14.
SIG_FUN = ("syntax_error:unexpected_token:fun:leq:function_declaration:"
           "delimiter_or_block_structure_error")

T_SIG = {"normalized_signature": SIG_TYPE, "root_error_family": "relation_arity_or_join_error",
         "affected_construct": "pred", "affected_symbol": "R1R2", "model_region": "predicate_body"}
S_SIG = {"normalized_signature": SIG_SYNTAX, "root_error_family": "delimiter_or_block_structure_error",
         "affected_construct": "pred", "affected_symbol": "R1R2", "model_region": "predicate_body"}
S2_SIG = {"normalized_signature": SIG_FUN, "root_error_family": "delimiter_or_block_structure_error",
          "affected_construct": "fun", "affected_symbol": "leq", "model_region": "function_declaration"}


def _vr(syntax="Error"):
    return VerificationResult(syntax=syntax, satisfied_predicates=[], unsatisfied_predicates=[],
                              counterexamples=[], no_counterexample=[])


def _entry(it, issue, sig):
    return RegressionLogEntry(
        iteration_id=it, model_file_location=f"AlloyModel__{it}.als", fix_intent="",
        source_ref="", current_result=_vr(), previous_result=None, updated_lines="",
        expected_impact=ImpactAnalysis(), issue=issue, error_signature=sig,
    )


# --------------------------------------------------------------------------- #
# 1. Classification: iter 18 vs iter 19 are DIFFERENT errors
# --------------------------------------------------------------------------- #
def test_iter18_19_classified_as_different_errors():
    norm = ErrorNormalizer()

    msg18 = ("Type error in AlloyModel__18.als at line 169 column 17:\n"
             "This expression failed to be typechecked line 169, column 17 (169,20)")
    a18 = {"syntax_errors": [{
        "message": msg18, "full_text": msg18, "context": msg18, "line": 169, "column": 17,
        "code_snippet": "CODE CONTEXT - COMPLETE BLOCK: pred R1R2 (lines 150-172):"}]}

    ctx19 = ("There are 37 possible tokens that can appear here:\n"
             "! # ( * @ Int NAME NUMBER STRING String ^ after all always before disj "
             "eventually fun historically iden int let lone no none once one pred seq "
             "set some steps sum this univ { ~")
    msg19 = "Syntax error in AlloyModel__19.als at line 170 column 13:\n" + ctx19
    a19 = {"syntax_errors": [{
        "message": msg19, "full_text": msg19, "context": ctx19, "line": 170, "column": 13,
        "code_snippet": "CODE CONTEXT - COMPLETE BLOCK: pred R1R2 (lines 150-172):"}]}

    s18 = norm.run(a18)["normalized_signature"]
    s19 = norm.run(a19)["normalized_signature"]

    assert s18 == SIG_TYPE, s18
    assert s19 == SIG_SYNTAX, s19
    assert s18 != s19, "iter 18 and 19 must be classified as DIFFERENT errors"
    print("[1] classification: DIFFERENT errors (type/arity vs delimiter/syntax) - OK")


# --------------------------------------------------------------------------- #
# 2. Resolution: iter 19 resolves iter 18's target issue (different signature)
# --------------------------------------------------------------------------- #
def test_iter19_resolves_iter18_target_issue():
    prev = _entry(18, "syntax error at line 169 in pred R1R2", T_SIG)
    curr = _entry(19, "syntax error at line 170 in pred R1R2", S_SIG)
    prev_analysis = {"syntax_errors": [{"line": 169}], "unsat_run_commands": [], "counterexamples": []}
    curr_analysis = {"syntax_errors": [{"line": 170}], "unsat_run_commands": [], "counterexamples": []}

    resolved = check_issue_resolved(curr_analysis, prev_analysis, curr, prev)
    assert resolved is True, (
        "different normalized signature => iter 18's error treated as resolved")
    print("[2] resolution: check_issue_resolved(18->19) = True (target resolved) - OK")


# --------------------------------------------------------------------------- #
# 3. Pattern: the flip is NOT alternating_error_loop; root-family does not bridge it
# --------------------------------------------------------------------------- #
def _flip_entries():
    # Reproduces the live-run window: 13,14 fun-leq delimiter errors; 15,18 type;
    # 16,17,19 delimiter-syntax on R1R2.
    seq = {13: S2_SIG, 14: S2_SIG, 15: T_SIG, 16: S_SIG, 17: S_SIG, 18: T_SIG, 19: S_SIG}
    return seq, [_entry(i, f"issue {i}", sig) for i, sig in seq.items()]


def test_flip_not_classified_as_alternating_loop():
    seq, entries = _flip_entries()
    tr = IssuePatternTracker()

    r18 = tr.run(18, seq[18], entries)
    r19 = tr.run(19, seq[19], entries)

    # Faithful to the log: both are recurring_same_error, not alternating_error_loop.
    assert r18["pattern_type"] == "recurring_same_error", r18["pattern_type"]
    assert r18["matched_exact_iterations"] == [15]
    assert r18["matched_root_family_iterations"] == []

    assert r19["pattern_type"] == "recurring_same_error", r19["pattern_type"]
    assert r19["matched_exact_iterations"] == [16, 17]

    assert r19["pattern_type"] != "alternating_error_loop", (
        "the type<->syntax flip is NOT detected as an alternating loop: the run is "
        "S,S,T,S (16,17,18,19), not a clean A,B,A,B, so _is_alternating's sig(N-3) "
        "strengthening check rejects it")
    print("[3a] pattern: flip is recurring_same_error, NOT alternating_error_loop - OK")


def test_root_family_channel_does_not_bridge_type_and_syntax():
    seq, entries = _flip_entries()
    tr = IssuePatternTracker()
    r19 = tr.run(19, seq[19], entries)

    # iter 19 (delimiter root) links via root-family only to 13,14 (delimiter root),
    # NOT to the type/arity iterations 15 & 18 -> the flip is invisible to the
    # root-family channel because the two errors have different root_error_family.
    assert r19["matched_root_family_iterations"] == [13, 14], r19["matched_root_family_iterations"]
    assert 15 not in r19["matched_root_family_iterations"]
    assert 18 not in r19["matched_root_family_iterations"]
    print("[3b] root-family channel does NOT bridge the type<->syntax flip (excludes 15,18) - OK")


if __name__ == "__main__":
    test_iter18_19_classified_as_different_errors()
    test_iter19_resolves_iter18_target_issue()
    test_flip_not_classified_as_alternating_loop()
    test_root_family_channel_does_not_bridge_type_and_syntax()
    print("\nAll iter18/19 error-tracking tests passed.")
