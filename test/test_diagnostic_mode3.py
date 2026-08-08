"""
Unit tests for RE Mode 3, Phase 3 - the RE receives a diagnostic rulebook and a
response format that reports what it MEASURED, not what it fixed.

Run: python test/test_diagnostic_mode3.py   (from the repo root)
"""

import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.actions.requirement_actions import (
    UpdateAlloyModel,
    swap_fix_intent_for_diagnostic_execution,
)
from src.utils.regression_log import parse_re_response_for_regression


SHARED_FORMAT = """### RESPONSE FORMAT FOR MODEL UPDATES:

```
=== FIX INTENT ===
[1 sentence describing what you are fixing/changing and why]

=== SOURCE REFERENCE ===
[What prompted this update]

=== EXPECTED IMPACT ===
satToUnsat: [...]
```
"""

DIAGNOSTIC_BLOCK = """=== DIAGNOSTIC EXECUTION ===
- Experiment: [the plan item restated]
- Probe: [probe1_X, or "none"]
- Executed: [yes / no]
- Reason: [one line]"""


# ------------------------------------------------- the response-format swap #

def test_fix_intent_is_replaced_not_supplemented():
    """
    Shipping both fields is the two-rulebook mistake in miniature: "state what you
    are fixing" and "this iteration fixes nothing" cannot both be followed, and the
    model resolves it however it likes.
    """
    out = swap_fix_intent_for_diagnostic_execution(SHARED_FORMAT, DIAGNOSTIC_BLOCK)

    assert "=== FIX INTENT ===" not in out
    assert "[1 sentence describing what you are fixing" not in out
    assert "=== DIAGNOSTIC EXECUTION ===" in out
    # Everything after it is untouched
    assert "=== SOURCE REFERENCE ===" in out
    assert "=== EXPECTED IMPACT ===" in out
    assert "satToUnsat:" in out
    assert out.index("=== DIAGNOSTIC EXECUTION ===") < out.index("=== SOURCE REFERENCE ===")
    print("PASS test_fix_intent_is_replaced_not_supplemented")


def test_the_swap_degrades_by_appending():
    """Prompt drift must not silently drop the field - append rather than lose it."""
    drifted = "### RESPONSE FORMAT:\n=== SOMETHING ELSE ===\n[x]\n"
    out = swap_fix_intent_for_diagnostic_execution(drifted, DIAGNOSTIC_BLOCK)
    assert "=== DIAGNOSTIC EXECUTION ===" in out
    assert "=== SOMETHING ELSE ===" in out

    # An empty replacement changes nothing
    assert swap_fix_intent_for_diagnostic_execution(SHARED_FORMAT, "") == SHARED_FORMAT
    print("PASS test_the_swap_degrades_by_appending")


# ------------------------------------------------------- prompt assembly #

def _make_action():
    from src.utils.prompt_manager import PromptManager

    action = UpdateAlloyModel.__new__(UpdateAlloyModel)
    ctx = Mock()
    ctx.prompt_manager = PromptManager()
    object.__setattr__(action, "context", ctx)
    object.__setattr__(action, "agent_name", "RE")
    object.__setattr__(action, "annotate_requirements", lambda doc, **kw: doc)
    return action


def _build(mode):
    action = _make_action()

    return UpdateAlloyModel._build_prompt(
        action,
        mode=mode,
        current_model="pred p {}",
        evaluation_feedback="=== DIAGNOSTIC PLAN ===\n- Construct: p\n",
        requirements_document="R1: something",
        lessons_str="none",
        user_prefs="",
        escalation_directive="=== DIAGNOSTIC ITEMS NOT RUN (already measured) ===\n- Construct: F\n",
        conventions_str="none",
        promotion_directive="",
    )


def test_diagnostic_mode_ships_the_diagnostic_rulebook_only():
    prompt = _build("diagnostic")

    assert "### TASK: DIAGNOSTIC EXPERIMENTS" in prompt
    # The other modes' rulebooks must not ride along - they permit exactly what
    # Mode 3 forbids ("Revise, add, or remove facts", "relax overconstraints")
    assert "### TASK: SEMANTIC MODEL IMPROVEMENT" not in prompt
    assert "Relax overconstraints causing unsat predicates" not in prompt
    # And the response format asks for the measurement, not the fix
    assert "=== DIAGNOSTIC EXECUTION ===" in prompt
    assert "=== FIX INTENT ===" not in prompt
    print("PASS test_diagnostic_mode_ships_the_diagnostic_rulebook_only")


def test_semantic_mode_is_unchanged():
    prompt = _build("semantic")

    assert "### TASK: SEMANTIC MODEL IMPROVEMENT" in prompt
    assert "=== FIX INTENT ===" in prompt
    assert "### TASK: DIAGNOSTIC EXPERIMENTS" not in prompt
    assert "=== DIAGNOSTIC EXECUTION ===" not in prompt
    print("PASS test_semantic_mode_is_unchanged")


def test_the_dropped_items_block_reaches_the_re():
    """It travels on the escalation directive, and the rulebook tells the RE what to do with it."""
    prompt = _build("diagnostic")
    assert "=== DIAGNOSTIC ITEMS NOT RUN (already measured) ===" in prompt
    assert "Copy each into your report as `Executed: no`" in prompt
    print("PASS test_the_dropped_items_block_reaches_the_re")


def test_the_rulebook_forbids_mutation():
    prompt = _build("diagnostic")
    for rule in (
        "DO NOT modify ANY existing construct",
        "DO NOT delete anything",
        "DO NOT fix the failing scenario",
        "//@req none:probe",
        "One hypothesis per probe",
    ):
        assert rule in prompt, rule
    print("PASS test_the_rulebook_forbids_mutation")


def test_diagnostic_is_a_valid_mode():
    import asyncio

    action = _make_action()
    try:
        asyncio.run(
            action.run(current_model="", evaluation_feedback="", requirements_document="",
                       mode="nonsense")
        )
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "diagnostic" in str(e)
    print("PASS test_diagnostic_is_a_valid_mode")


# ------------------------------------------------- the regression entry (T3) #

RESPONSE = """=== DIAGNOSTIC EXECUTION ===
- Experiment: CredentialUpdatePerfomedSeq - flag reset timing blocks the scenario
- Probe: probe1_ScenarioMultiEmgA
- Executed: yes
- Experiment: EmergencyUnique - forbids a Normal state between emergencies
- Probe: none
- Executed: no
- Reason: dropped by the guard rails; the localizer already proved it blocks Scenario_MultiEmg_A

=== SOURCE REFERENCE ===
Evaluator DIAGNOSTIC PLAN, iteration 68

=== EXPECTED IMPACT ===
unsatToSat: [probe1_ScenarioMultiEmgA]
```alloy
pred x {}
```
"""


def test_diagnostic_execution_fills_fix_intent():
    """
    `fix_intent` is rendered in the failed-fix history, the Evaluator's regression
    view and the similarity clustering. Left blank, a diagnostic iteration vanishes
    from all three.
    """
    fields = parse_re_response_for_regression(RESPONSE)

    assert fields["fix_intent"].startswith("DIAGNOSTIC EXECUTION: ")
    assert "probe1_ScenarioMultiEmgA" in fields["fix_intent"]
    assert "EmergencyUnique" in fields["fix_intent"]
    assert "\n" not in fields["fix_intent"]  # rendered inline as "Fix Intent: ..."
    assert fields["diagnostic_execution"].startswith("- Experiment:")
    assert fields["source_ref"] == "Evaluator DIAGNOSTIC PLAN, iteration 68"
    assert fields["expected_impact"].unsat_to_sat == ["probe1_ScenarioMultiEmgA"]
    print("PASS test_diagnostic_execution_fills_fix_intent")


def test_a_repair_response_is_untouched():
    repair = ("=== FIX INTENT ===\nNarrow the guard in p\n\n"
              "=== SOURCE REFERENCE ===\nREPAIR INSTRUCTIONS 1\n")
    fields = parse_re_response_for_regression(repair)

    assert fields["fix_intent"] == "Narrow the guard in p"
    assert fields["diagnostic_execution"] == ""
    print("PASS test_a_repair_response_is_untouched")


def test_an_explicit_fix_intent_wins_over_the_report():
    """
    If a Mode 3 response emits both (prompt drift, or the swap degraded), the
    stated intent is the author's own words and is kept; the report is still
    recorded separately so nothing is lost.
    """
    both = "=== FIX INTENT ===\nRelax the guard\n\n" + RESPONSE
    fields = parse_re_response_for_regression(both)

    assert fields["fix_intent"] == "Relax the guard"
    assert "probe1_ScenarioMultiEmgA" in fields["diagnostic_execution"]
    print("PASS test_an_explicit_fix_intent_wins_over_the_report")


if __name__ == "__main__":
    test_fix_intent_is_replaced_not_supplemented()
    test_the_swap_degrades_by_appending()
    test_diagnostic_mode_ships_the_diagnostic_rulebook_only()
    test_semantic_mode_is_unchanged()
    test_the_dropped_items_block_reaches_the_re()
    test_the_rulebook_forbids_mutation()
    test_diagnostic_is_a_valid_mode()
    test_diagnostic_execution_fills_fix_intent()
    test_a_repair_response_is_untouched()
    test_an_explicit_fix_intent_wins_over_the_report()
    print("\nAll Mode 3 tests passed.")
