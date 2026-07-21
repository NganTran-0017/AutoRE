# Consolidation backup & reversal — 2026-07-07

This directory preserves the pre-consolidation state of every file touched by the
duplicate-code consolidation (items 1–6 of `Documentations/DUPLICATE_HELPERS.txt`;
items 7–8 were intentionally NOT applied).

## Contents

- `originals/` — verbatim copies of all 11 edited files, with their repo-relative
  paths preserved, taken immediately before any edit.
- `consolidation_0707.patch` — unified diff from the originals to the consolidated
  versions (11 files, one hunk set per file). Useful for review and for selective
  reversal.

## How to reverse

**Option A — full reversal (simplest, recommended):** copy the originals back.

```bash
cd /home/nati/autoRE
cp Documentations/consolidation_backup/originals/src/workflow.py                    src/workflow.py
cp Documentations/consolidation_backup/originals/src/utils/regression_log.py        src/utils/regression_log.py
cp Documentations/consolidation_backup/originals/src/utils/artifact_store.py        src/utils/artifact_store.py
cp Documentations/consolidation_backup/originals/src/utils/alloy_model_validator.py src/utils/alloy_model_validator.py
cp Documentations/consolidation_backup/originals/src/utils/file_manager.py          src/utils/file_manager.py
cp Documentations/consolidation_backup/originals/src/actions/requirement_actions.py src/actions/requirement_actions.py
cp Documentations/consolidation_backup/originals/src/utils/repair_plateau_detector.py src/utils/repair_plateau_detector.py
cp Documentations/consolidation_backup/originals/src/utils/logger.py                src/utils/logger.py
cp Documentations/consolidation_backup/originals/src/utils/error_normalizer.py      src/utils/error_normalizer.py
cp Documentations/consolidation_backup/originals/src/utils/issue_pattern_tracker.py src/utils/issue_pattern_tracker.py
cp Documentations/consolidation_backup/originals/src/utils/semantic_issue_tracker.py src/utils/semantic_issue_tracker.py
```

Or in one line: `cp -r Documentations/consolidation_backup/originals/src/. src/`
(safe: the originals tree contains only the 11 edited files).

**Option B — patch-based reversal (works even after unrelated later edits):**

```bash
cd /home/nati/autoRE
patch -R -p1 < Documentations/consolidation_backup/consolidation_0707.patch
```

**Option C — selective reversal per consolidation item.** Each item is independent;
to reverse one item only, restore just the parts listed below (or apply the relevant
hunks of the patch with `patch -R`). What each item changed:

1. **Alloy code-fence extraction** — new shared `extract_alloy_code()` in
   `src/utils/alloy_model_validator.py`; call sites replaced in
   `alloy_model_validator.py` (2 internal sites), `artifact_store.py`
   (`store_alloy_model`), `file_manager.py` (`save_alloy_model`),
   `requirement_actions.py` (`_validate_model_length`), `workflow.py`
   (`_step8_update_model`). To reverse: restore the old inline regex blocks at each
   call site, then delete `extract_alloy_code`. NOTE: reversing `workflow.py`
   reintroduces the old regex variant `r'```alloy\s*\n(.*?)\n```'` which silently
   fails when the model's last line abuts the closing fence.
2. **Feedback storage sequence** — new `AutoREWorkflow._store_final_feedback()`;
   3 inline blocks in `_step5_6_generate_feedback_and_get_user_input` replaced by
   calls. To reverse: re-inline the store_feedback/save_feedback/entry-update
   sequence at the three sites and delete the helper.
3. **CONVERGENCE_RECOMMENDATION parsing** — new `AutoREWorkflow._parse_convergence()`;
   2 inline regex blocks replaced. Reverse analogously to item 2.
4. **Issue-string parsing** — new module-level `_parse_issue_components()` in
   `src/utils/regression_log.py`; two ~25-line inline blocks in
   `get_same_issue_failed_fixes` replaced by calls.
5. **[FIX INTENT] extraction** — `regression_log.extract_fix_intent` pattern widened
   from `\[FIX INTENT\]:?\s*\n(.*?)...` to `\[FIX INTENT\]:?\s*(.*?)...` (now also
   matches same-line intents — a superset); `repair_plateau_detector.
   _extract_evaluator_fix_intent` now delegates to it (its local regex and the
   module's `import re` were removed).
6. **`_log` helper** — new `SafeLogMixin` in `src/utils/logger.py`; `ErrorNormalizer`,
   `IssuePatternTracker`, `SemanticIssueTracker` inherit it and their identical
   3-line `_log` methods were deleted.

## Intentionally NOT applied

- Item 7 (timestamp format constants): saves no lines and adds cross-module coupling.
- Item 8 (shared Alloy comment detection): MEDIUM risk — the two consumers
  (`count_non_comment_lines_between` counting vs `_strip_comments` stripping) need
  different outputs; consolidating only the boundary detection was judged not worth
  the behavioral risk in error matching.

## Verification performed after consolidation

- All 11 modules compile (`python -m py_compile`).
- Suites passing: test_escalation_chain, test_regression_log_lifecycle,
  test_regression_log_parsing (16), test_workflow_regression_helpers (17),
  test_failed_fix_history, test_semantic_pattern_detection,
  test_snippet_instead_of_model, test_response_format_separation,
  test_refine_feedback_no_role, test_update_requirements_sections.
- Behavioral spot-checks: `extract_alloy_code` reproduces every old call site's
  semantics (including the generic-fence storage path and the validator passthrough)
  and fixes the workflow fence edge case; `extract_fix_intent` matches both same-line
  and next-line intents; `_parse_issue_components` reproduces the old three-format
  cascade.
