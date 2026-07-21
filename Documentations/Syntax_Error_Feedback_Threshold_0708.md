# Syntax Error Feedback Threshold Update (0708)

## Change
Adjusted the trigger for soliciting user feedback on recurring syntax errors.

**Previous:** 2 consecutive OR 3 total occurrences (unbounded)  
**New:** 3 consecutive OR 4 within a 7-iteration window

## Rationale
- Reduces noise: avoids prompting user for old/sporadic errors that reappear after many iterations
- Aligns with semantic path: matches the existing 3/4 escalation thresholds in `SemanticIssueTracker`
- Recency-aware: "total" count now has a rolling window, preventing ancient errors from accumulating

## Files Modified
1. **`src/utils/regression_log.py`** — `count_consecutive_same_syntax_errors()`
   - Added `window: int = 7` parameter
   - Loop bounds updated to stop past the window

2. **`src/workflow.py`** — `_step5_6_generate_feedback_and_get_user_input()` (syntax-error path)
   - Pass `window=7` to count function
   - Raise thresholds: `threshold_consecutive` 2→3, `threshold_total` 3→4
   - Update log messaging for clarity

## Verification
- Unit tests: 4 same errors within-7 → `total >= 4`; same 4 spread over 9 → `total < 4` (outside window); 3 consecutive → `consecutive == 3` ✓
- No existing tests pin the old 2/3 values
- Both files parse correctly
