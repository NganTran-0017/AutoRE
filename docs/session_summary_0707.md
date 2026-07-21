# AutoRE Session Summary — July 7, 2026

Continues `session_summary_0706.md` (escalation chain steps 3–4, prompt consumption, requirement-gap escalation). This session: codebase condensing, five reliability fixes driven by observed log defects, and the full anti-plateau escalation ladder.

---

## 1. Codebase condensing

**Dead-code inventory (no deletions, per user instruction)** — `Documentations/UNUSED_CODE.txt`: 6 modules unreachable from `main.py` (942 lines: `prompt_parser.py`, `user_interaction.py`, `alloy_formatter.py`, `src/agents/*`) + 28 unused functions/methods (536 lines), each verified to have zero references across runtime, tests, scripts, and tools (AST scan + reference search + dynamic-ref check + import-reachability walk).

**Duplicate-helper consolidation (items 1–6 of `Documentations/DUPLICATE_HELPERS.txt`; 7–8 intentionally skipped)** — net −61 lines, 16 scattered copies → 6 single sources of truth:

| Consolidation | Shared implementation |
|---|---|
| Alloy code-fence extraction (6 sites, incl. a buggy `workflow.py` variant that dropped models whose last line abuts the closing fence) | `extract_alloy_code()` in `alloy_model_validator.py` |
| Feedback persistence sequence (3× in `workflow.py`) | `AutoREWorkflow._store_final_feedback()` |
| CONVERGENCE_RECOMMENDATION regex (2×) | `AutoREWorkflow._parse_convergence()` |
| Issue-string parsing cascade (2× in `regression_log.py`) | `_parse_issue_components()` |
| `[FIX INTENT]` extraction (2 variants) | widened `extract_fix_intent()` (now also matches same-line intents) |
| `_log` helper (3 identical copies) | `SafeLogMixin` in `logger.py` |

Backups: `Documentations/consolidation_backup/` (verbatim originals of all 11 edited files, unified patch `consolidation_0707.patch`, `README_REVERSAL.md` with full/patch/per-item reversal — patch reversal dry-run verified).

## 2. `outcome_classification` never left "pending"

**Defect** (`regression0706_11AM.log`): every entry stuck at `pending` — `InterpretResults` (the only writer) is skipped on syntax-error iterations; also skipped when `actual_impact is None`; and a parse failure returned the truthy string `"pending"`, which could clobber a real value.

**Fix**: `derive_outcome_classification()` in `regression_log.py` — deterministic classification from facts step 4 already has (syntax state, `resolved_target_issue`, prior-entry existence, issue string), set in `_step4` for every iteration; the LLM classification overwrites it only when successfully parsed (`!= "pending"` guard added). New values: `initial_verification`, `syntax_error_blocked`, `no_improvement`, `provisional_improvement` (see §5), `unclassified` — each with a detail suffix. Test: `test/test_outcome_classification.py` (incl. exhaustive no-input-yields-pending sweep).

## 3. Lessons stored only after sustained resolution

**Defect**: staged lessons were confirmed when their target issue was absent for ONE iteration — in an A-B-A-B oscillation the "fix A" lesson was stored at the B iteration and then fed back into prompts as a proven fix.

**Fix**: `LessonProbation` in `learning_system.py`, wired into `_step4`/`run()` of `workflow.py`. Lessons go on probation at first resolution; discarded if the target issue recurs (signature or issue-component match); stored only after 3 consecutive *observable* iterations (syntax-broken iterations neither advance nor break semantic-issue probation); remaining probationers confirmed on convergence (hard metrics passing is stronger evidence). Test: `test/test_lesson_probation.py`.

## 4. User guidance made binding in syntax repair (prompt changes)

**Defect** (`070726.log`, iteration 12): the user prescribed "use `pred` instead of `fun`; use `util/ordering`"; `RefineSyntaxRepairInstruction` demoted this to "Step 3: Optionally…" and led with its own smaller fix; the RE agent's minimal-change syntax mode then skipped the optional step; the error persisted.

**Prompt fixes** (`Evaluator_prompt.txt`, `RE_prompt.txt`):
- `RefineSyntaxRepairInstruction`: BINDING RULES — the user's approach is the primary and only fix path; "optionally/consider/alternatively" forbidden for it; no substituting a smaller own-fix; named mechanisms must anchor every step; the only deviation is invalid-Alloy-6 guidance, which must be quoted and realized as closely as possible. New `[USER GUIDANCE COMPLIANCE]` output section maps each guidance element to a step; FINAL CHECK blocks non-compliant responses.
- `UpdateAlloyModel_Mode1_SyntaxRepair`: USER-DIRECTED FIX OVERRIDE — when feedback contains `[USER GUIDANCE COMPLIANCE]`, applying it fully (construct replacements, new `open` statements, call-site updates) takes precedence over the minimal-change constraint.

## 5. Provisional resolution tracking (no false "solved" in the regression log)

**Defect**: `resolved_target_issue: true` was recorded permanently at the first absent iteration; oscillating fixes were then *hidden* from failed-fix history by the resolved filter.

**Fix** (`regression_log.py`, `workflow.py`): new entry field `resolution_status`. First absence → `{'status': 'temporarily_absent', target_issue, target_signature}` and classification `provisional_improvement`. `update_resolution_statuses()` (stateless — derives everything from the log, so resume-safe) runs every iteration: **reverts** on recurrence (status `resolution_reverted`, `resolved_target_issue` flipped to `False` so the fix re-enters failed-fix history, classification corrected to `no_improvement: … recurred`) or **confirms** after 3 consecutive observable iterations (status `resolved_confirmed`, classification upgraded to `expected_improvement`). Shared matcher `issues_match()` extracted; `LessonProbation` delegates to it. Test: `test/test_resolution_status.py`.

## 6. Repair signatures (fix-side analogue of the error signature)

**Gap**: attempted repairs were tracked only as free text; duplicate-fix rejection relied on 0.85 text similarity, which rephrased identical fixes slip past.

**Fix**: `normalize_repair()` in `repair_plateau_detector.py` — rule table classifying prescribed repairs into operation families (`construct_conversion`, `remove_return_type`, `add_open_import`, `quantifier_change`, `no_change`, …) anchored to the repaired block; stored per iteration as `RegressionLogEntry.repair_signature` (with the active strategy). Consumed twice: the retry loop rejects a repair whose signature matches a previously failed attempt (deterministic, on top of text similarity), and the escalation directive lists "REPAIR OPERATIONS ALREADY ATTEMPTED". Test: `test/test_repair_signature.py`.

## 7. Anti-plateau escalation ladder (Option 1 chained into Option 2)

**Design**: rung memory in `build_syntax_escalation` — for the matched error signature, prior entries' `repair_escalation.strategy` determines the next rung:

| Level | Strategy | Behavior |
|---|---|---|
| 3 | `REWRITE_BLOCK` | (existing) rewrite the affected block from scratch, no more local patches |
| 4 | `REGENERATE_BLOCK` | plateau survived a rewrite: DELETE the block and rebuild it **from the requirements it encodes**, not from the broken text (block transplant — no whole-model revert, so it works when no parseable ancestor exists). Evaluator states which requirement(s) the block serves, its intended meaning, and the interface to preserve; RE deletes + regenerates, updating call sites. `_step8` attaches the latest requirements to the escalation directive (syntax mode omits them). |
| 5 | `REQUIREMENTS_DIAGNOSIS` | regeneration failed too: the requirement itself is suspect. Evaluator must name the encoded requirement(s), diagnose (ambiguity with divergent readings / minimal inconsistent set / gap), emit `=== REQUIREMENT UPDATES ===` with concrete rewrites (picked up by `_step7` → English requirements change), and give an INTERIM repair so verification proceeds. |

Prompt rules for both new rungs added to `GenerateSyntaxRepairInstruction`, `RefineSyntaxRepairInstruction` (guidance-aware per rung), and `UpdateAlloyModel_Mode1_SyntaxRepair`. Test: `test_escalation_ladder_climbs` in `test/test_escalation_chain.py`.

---

## Files touched this session

- **Code**: `src/workflow.py`, `src/utils/regression_log.py`, `src/utils/repair_plateau_detector.py`, `src/utils/learning_system.py`, `src/actions/evaluation_actions.py`, `src/actions/requirement_actions.py`, `src/utils/logger.py`, `src/utils/alloy_model_validator.py`, `src/utils/artifact_store.py`, `src/utils/file_manager.py`, `src/utils/error_normalizer.py`, `src/utils/issue_pattern_tracker.py`, `src/utils/semantic_issue_tracker.py`
- **Prompts**: `prompts/Evaluator_prompt.txt` (RefineSyntaxRepairInstruction binding rules + compliance section; GenerateSyntaxRepairInstruction ladder rules), `prompts/RE_prompt.txt` (Mode1 user-directed override + ladder rules)
- **New regression-log entry fields** (all with back-compat serialization): `resolution_status`, `repair_signature` (plus 0706's `semantic_issue_persistence`, `repair_escalation`)
- **New tests**: `test_outcome_classification.py`, `test_lesson_probation.py`, `test_resolution_status.py`, `test_repair_signature.py`, `test_escalation_ladder_climbs` (in `test_escalation_chain.py`); fixed stale `test_response_format_separation.py`, `test_refine_feedback_no_role.py`, `test_update_requirements_sections.py`
- **Docs**: `Documentations/UNUSED_CODE.txt`, `Documentations/DUPLICATE_HELPERS.txt`, `Documentations/consolidation_backup/` (originals + patch + reversal README)

All suites pass as of session end.

## Tuning knobs

- `IssuePatternTracker(plateau_consecutive=3)` — lower to 2 to reach the ladder faster (a full ladder run currently takes ~12 iterations on one error).
- `SemanticIssueTracker(consecutive_threshold=3, total_threshold=4)` — semantic requirements-diagnosis trigger.
- `LessonProbation(required_clean_iterations=3)` and `update_resolution_statuses(required_clean_iterations=3)` — confirmation windows.