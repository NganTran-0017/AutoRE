# AutoRE Session Summary — July 6, 2026

## Goals

1. Overcome persistent / repeated / oscillating syntax errors: make the Evaluator recognize error cycles and repair plateaus and change strategy instead of retrying failed fixes.
2. Make the agents directly identify requirement gaps, ambiguities, and inconsistencies during modeling/verification and propose English-requirement updates, instead of accepting a defective model.

## Root causes (from code map + 0618 / 0703_11AM / 0706 log analysis)

- **Tracking data was write-only.** `ErrorNormalizer` + `IssuePatternTracker` (chain steps 1–2) correctly classified `repair_plateau`, `alternating_error_loop`, etc., but nothing consumed the classifications — not the Evaluator prompts, not the RE agent, not control flow. Result: the same fix was re-applied verbatim (0618: identical `precedes`/`next` fix at iterations 19 and 22).
- **Semantic issues had no tracking at all.** `ErrorNormalizer` handles only syntax errors, so UNSAT predicates and counterexamples — the actual signals of requirement problems — were invisible. 0618: `EmergencyBypassFIFOScenario` UNSAT for 9+ iterations, never escalated; 0703: escalation to requirement clarification only at iteration 65/91, by LLM judgment alone. Feedback sometimes converted failing assertions into facts, masking the gap.

## New code

| File | Why |
|------|-----|
| `src/utils/semantic_issue_tracker.py` (chain step 3) | Deterministically tracks each UNSAT predicate / counterexample across **measurable** (syntax-OK) iterations, so interleaved syntax-error iterations don't reset persistence. Escalates at ≥3 consecutive or ≥4 total in a 10-iteration window. Output stored as `RegressionLogEntry.semantic_issue_persistence`. |
| `src/utils/repair_plateau_detector.py` (chain step 4) | Converts classifications into escalation decisions + **data-only** directive blocks (facts in Python, rules in prompt files). Syntax: `FORBID_PRIOR_FIXES` (level 1) → `BREAK_OSCILLATION` (2) → `REWRITE_BLOCK` (3). Semantic: `REQUIREMENTS_DIAGNOSIS` (3). Directives list every previously attempted fix: Evaluator `[FIX INTENT]`s from stored feedback of matched iterations + RE `fix_intent` from the entry at matched_iteration+1. |
| `test/test_escalation_chain.py` | Scenario tests replaying the observed failures (0618 semantic persistence, syntax plateau, A-B-A-B oscillation, no premature escalation, entry serialization round-trip incl. old logs, prompt rendering of all modified templates). |

## Edited code

| File | Change | Why |
|------|--------|-----|
| `src/utils/regression_log.py` | New `RegressionLogEntry` fields `semantic_issue_persistence`, `repair_escalation` (+ `to_dict`/`from_dict` back-compat). | Persist the chain outputs per iteration; old logs load unchanged. |
| `src/workflow.py` | `__init__`: instantiate `SemanticIssueTracker`. `_step4`: run it after `IssuePatternTracker`. `_step5_6` syntax path: build `build_syntax_escalation`, store on entry, pass directive as `pattern_status` to all three `generate_syntax_repair.run` call sites; failed-attempt loading now unions IssuePatternTracker's matched iterations with the symbol-based index (catches the same error when the issue string differs). `_step5_6` semantic path: build `build_semantic_escalation`, pass directive as `persistence_status` to `generate_semantic_feedback.run`. `_step8`: read previous iteration's `repair_escalation` and pass its directive to `UpdateAlloyModel` as `escalation_directive`. | This is the consumption layer — makes the chain change agent behavior instead of being telemetry. Step 8 reads the *previous* entry because the iteration counter increments between steps 5-6 and 8. |
| `src/actions/evaluation_actions.py` | `GenerateSyntaxRepairInstruction.run`: new `pattern_status` param rendered into the prompt (defaults to a "first occurrence" note). `GenerateSemanticFeedback.run`: new `persistence_status` param; when non-empty, appends the `PersistentIssueEscalation` prompt section (same mechanism as `QAContextReuseAndUpdate`). | Feed escalation evidence to the Evaluator at generation time. |
| `src/actions/requirement_actions.py` | `UpdateAlloyModel.run` / `_build_prompt`: new `escalation_directive` param, always substituted into the base template. | The RE agent must see which fixes are forbidden and when a block rewrite is required — previously it was never told a fix had already failed. |

## Edited prompts

| File / section | Change | Why |
|----------------|--------|-----|
| `Evaluator_prompt.txt` — `GenerateSyntaxRepairInstruction` and `RefineSyntaxRepairInstruction` | New "CROSS-ITERATION ERROR PATTERN STATUS" block (`{{pattern_status}}`) with binding STRATEGY RULES: FORBID_PRIOR_FIXES = every listed fix forbidden incl. rephrasings; BREAK_OSCILLATION = one change resolving both oscillating errors at their shared root cause; REWRITE_BLOCK = no more local patches, instruct a from-scratch rewrite of the affected block. | The old "don't repeat failed fixes" prose was ignored without structured, prominent evidence + an explicit required strategy. |
| `Evaluator_prompt.txt` — new `[SECTION: PersistentIssueEscalation]` | Appended to `GenerateSemanticFeedback` only when semantic escalation fires. Makes `escalate to requirement clarification` mandatory; requires a full diagnosis in the **existing** feedback sections (`=== POTENTIAL REQUIREMENT ISSUES ===`: classification inconsistency/ambiguity/gap + evidence + minimal conflicting requirement set or ambiguous text with divergent interpretations; `=== REQUIREMENT UPDATES ===`: concrete replacement wording — which `_step7` already feeds into the English requirements). `model overconstraint` is the justified exception, routed to REPAIR INSTRUCTIONS. Forbids repeating attempted fixes, assert→fact conversion, and "keep fix" without diagnosis. | Goal 2: deterministic trigger + structured diagnosis, instead of relying on the LLM to decide (0618 never did; 0703 did at iteration 65). Reuses existing sections because ResponseFormatFeedback says "return exactly the sections listed". |
| `Evaluator_prompt.txt` — `GenerateSemanticFeedback` DECISION POLICY | Always-on rule: never repair a failing assertion by converting it to a fact / deleting / weakening it; diagnose the conflicting requirement instead. | 0618 feedback_20 converted `assertRequestProcessorClearance` into a fact, hiding the gap. |
| `Evaluator_prompt.txt` — `RefineFeedback` | Objective 5: preserve the requirements diagnosis (incl. proposed rewrites) through user review unless the review overrides it. | Prevents the refinement pass from dropping the escalation output. |
| `RE_prompt.txt` — `UpdateAlloyModel_Base` | New `{{escalation_directive}}` block after Evaluator Feedback. | Deliver the same evidence to the RE agent. |
| `RE_prompt.txt` — `Mode1_SyntaxRepair` | ESCALATION OVERRIDE: listed fixes may not be re-applied even if the feedback suggests one; REWRITE_BLOCK lifts the minimal-change constraint **for the named block only**; BREAK_OSCILLATION requires one coherent change for both errors. | Mode1's "smallest possible change" rule would otherwise contradict a rewrite instruction. |
| `RE_prompt.txt` — `Mode2_SemanticRepair` | Forbidden Changes: no re-applying fixes listed in the escalation status; no assert→fact/deletion/weakening when the diagnosis marks an issue requirement-level. | Stops the RE agent from undoing the escalation. |

## Test fixes (pre-existing failures, unrelated to the above)

`test/test_response_format_separation.py`, `test/test_refine_feedback_no_role.py`, `test/test_update_requirements_sections.py` failed at HEAD too:
- referenced the removed action name `GenerateFeedback` → renamed to `GenerateSemanticFeedback` with its current required variables (`failed_fix_history`, `relevant_qa`);
- didn't pass `regression_log`, now required by `InterpretResults`;
- detected the Role section via the phrase `"You are an Evaluator"`, which misfires because the `RefineFeedback` section carries its own focused intro line → replaced with a `shared_role_present()` helper comparing against the actual `[SECTION: Role]` content;
- checked for the old `SYNTAX STATUS:` marker in `ResponseFormatInterpretation`, which was rewritten on this branch → now checks `=== RESULT INTERPRETATION ===`.

## Verification

- `python test/test_escalation_chain.py` — all 6 scenario tests pass.
- Existing suites still pass: `test_regression_log_lifecycle`, `test_regression_log_parsing` (16), `test_workflow_regression_helpers` (17), `test_failed_fix_history`, `test_semantic_pattern_detection`.
- The three repaired tests pass (run with `PYTHONPATH=.` from the repo root).
- All modified Python modules compile; full `UpdateAlloyModel` prompt templates render for both modes with no unsubstituted placeholders.

## Docs updated

- `Documentations/Stateful_Error_Tracking_Repair_Plateau_Detection` — appended sections #3 (SemanticIssueTracker) and #4 (RepairPlateauDetector + consumption wiring). Note: the originally planned "ResolutionStatusTracker" role was already covered by `check_issue_resolved`/`resolved_target_issue`; step 3 was re-scoped to semantic persistence, the actual gap.
