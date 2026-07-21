# AutoRE Session Summary - June 30, 2026

## Overview
This session focused on improving the syntax error handling and user feedback solicitation mechanisms in the AutoRE workflow, particularly addressing issues with persistent syntax errors and comment line handling.

---

## 1. User Guidance Refinement for Syntax Errors

### Problem
When user feedback was provided for persistent syntax errors, it was simply concatenated as a string rather than being properly refined by the Evaluator.

### Solution
Modified `GenerateSyntaxRepairInstruction` action to dynamically switch between two prompt sections:
- **Without user guidance**: Uses `GenerateSyntaxRepairInstruction` prompt section
- **With user guidance**: Uses `RefineSyntaxRepairInstruction` prompt section

### Implementation Details

**File: `src/actions/evaluation_actions.py`**
- Modified `GenerateSyntaxRepairInstruction.run()` method (lines 858-928)
- Added logic to select prompt section based on `user_guidance` parameter:
  ```python
  if user_guidance and user_guidance.strip():
      section_name = "RefineSyntaxRepairInstruction"
  else:
      section_name = "GenerateSyntaxRepairInstruction"
  ```
- Directly calls `prompt_manager.render_prompt()` with dynamic action name

**File: `src/utils/prompt_manager.py`**
- Added `RefineSyntaxRepairInstruction` to exclusion lists:
  - `actions_without_convergence`
  - `actions_without_quality_standards`
  - `actions_without_learning`
  - `actions_without_role`

**File: `prompts/Evaluator_prompt.txt`**
- Already contains `RefineSyntaxRepairInstruction` section (lines 676-752)
- This section focuses specifically on incorporating user guidance

### Benefits
- Cleaner implementation (no duplicate action class needed)
- Automatic prompt section selection based on context
- Less code to maintain
- Proper refinement of user guidance through Evaluator

---

## 2. Reduced Syntax Error Threshold

### Change
Updated the threshold for requesting user feedback from **5** to **3** consecutive same syntax errors.

**File: `src/workflow.py:874`**
```python
# Before
max_failed_fixes = 5

# After
max_failed_fixes = 3
```

### Rationale
Earlier intervention allows users to provide guidance before too many failed attempts accumulate, improving efficiency and reducing wasted iterations.

---

## 3. Comment Line Handling in Error Distance Calculation

### Problem Identified
Syntax errors separated by large comment blocks were treated as different errors, even when they were the same error or cascading errors from the same root cause.

**Example:**
- Error at line 104 (`fun requestClassification` - missing bracket)
- Cascading error reported at line 117 (`fact InitialState`)
- Lines 105-116 contain only comments
- Raw distance: 13 lines (exceeds threshold of 5)
- These were treated as different errors ❌

### Solution
Created logic to count only **non-comment lines** when calculating distance between errors.

### Implementation

**New Function: `count_non_comment_lines_between()`**
- Location: `src/utils/regression_log.py` (lines 739-813)
- Reads Alloy file and counts only executable code lines
- Handles:
  - Single-line comments (`//`)
  - Multi-line comments (`/* */`)
  - Empty lines
- Falls back to raw distance if file cannot be read

```python
def count_non_comment_lines_between(file_path: str, line1: int, line2: int) -> int:
    """
    Count non-comment lines between two line numbers in an Alloy file.

    Returns:
        Number of non-comment lines between line1 and line2 (inclusive).
        Falls back to abs(line2 - line1) if file cannot be read.
    """
```

**Modified Function: `count_consecutive_same_syntax_errors()`**
- Location: `src/utils/regression_log.py` (lines 893-911)
- When raw distance > 5 lines:
  - Calculates non-comment distance
  - Only treats as different error if code distance > 5
- Constructs Alloy model file paths internally
- Adds debug logging for both distances

```python
if raw_distance > 5:
    # Try non-comment distance calculation
    current_model_path = f"Output/AlloyModels/AlloyModel__{current_iteration}.als"
    code_distance = count_non_comment_lines_between(
        current_model_path,
        min(entry_line, current_line),
        max(entry_line, current_line)
    )

    if code_distance > 5:
        break  # Different location
```

### Test Results
Using `AlloyModel__75.als`, lines 104-117:
- **Raw distance**: 13 lines
- **Code distance**: 1 line (only the `};` at line 104)
- **Result**: Correctly identified as same error ✅

---

## 4. Enhanced Persistent Error Detection Rules

### Problem
The original rule only detected **3 consecutive** occurrences of the same error. This failed to catch:
- Errors that alternate with other errors
- Errors that appear multiple times but not consecutively

**Example that was missed:**
- Iteration 75: Error A
- Iteration 76: Error B (different)
- Iteration 77: Error A
- Iteration 78: Error B (different)
- Iteration 79: Error A (3 total occurrences, but never 3 consecutive)

### New Rules
User feedback is now requested when **EITHER**:
- **2 consecutive** occurrences, OR
- **3 total** occurrences (even non-consecutive)

### Implementation

**Modified Function: `count_consecutive_same_syntax_errors()`**
- Location: `src/utils/regression_log.py` (lines 816-950)
- **Return type changed**: `Dict[str, int]` instead of `int`
- Returns: `{'consecutive': X, 'total': Y}`
- **Algorithm changes**:
  - Loops through ALL previous iterations (not just until first mismatch)
  - Tracks `consecutive_broken` flag to stop consecutive counting
  - Continues counting total occurrences even after consecutive breaks

```python
def count_consecutive_same_syntax_errors(
    regression_log_entries: List['RegressionLogEntry'],
    current_iteration: int,
    current_issue: str,
    current_syntax_error: Optional[Dict[str, Any]] = None
) -> Dict[str, int]:
    """
    Returns both consecutive count (how many times in a row) and total count
    (how many times overall, even with gaps).

    Returns:
        Dict with 'consecutive' and 'total' counts (both including current iteration)
    """
```

**Updated Workflow Logic**
- Location: `src/workflow.py` (lines 867-904)
- Gets both counts from function
- Checks: `consecutive_count >= 2 OR total_count >= 3`
- Updated log messages to show which condition triggered
- Shows both counts in output

```python
error_counts = count_consecutive_same_syntax_errors(...)
consecutive_count = error_counts['consecutive']
total_count = error_counts['total']

# Trigger user feedback if: 2 consecutive OR 3 total occurrences
threshold_consecutive = 2
threshold_total = 3

if consecutive_count >= threshold_consecutive or total_count >= threshold_total:
    # Request user feedback
```

**Updated Progress Logging**
- Location: `src/workflow.py` (lines 987-988)
- Shows both counts during retry loops
- Message: "🔄 Cross-iteration fix attempt: X consecutive, Y total for this error"

### Example Scenarios

**Scenario 1: Fast consecutive detection (2 in a row)**
- Iteration 75: Error A (1 consecutive, 1 total)
- Iteration 76: Error A ← **Triggered** (2 consecutive, 2 total)

**Scenario 2: Non-consecutive detection (3 total)**
- Iteration 75: Error A (1 consecutive, 1 total)
- Iteration 76: Error B (different)
- Iteration 77: Error A (1 consecutive, 2 total)
- Iteration 78: Error B (different)
- Iteration 79: Error A ← **Triggered** (1 consecutive, 3 total)

**Scenario 3: Alternating errors**
- Iteration 75: line 104 error (1 consecutive, 1 total)
- Iteration 76: line 780 error (different)
- Iteration 77: line 104 error (1 consecutive, 2 total) - Not triggered
- Iteration 78: line 780 error (1 consecutive, 2 total)
- Iteration 79: line 104 error ← **Triggered** (1 consecutive, 3 total)

### Benefits
- **Faster detection**: Consecutive errors trigger after just 2 occurrences
- **Broader coverage**: Catches alternating/intermittent errors that persist
- **Better UX**: Users can provide guidance earlier when errors are truly stuck
- **More accurate**: Comment-aware distance calculation prevents false negatives

---

## Files Modified

### Core Logic
1. **`src/utils/regression_log.py`**
   - Added `count_non_comment_lines_between()` function (lines 739-813)
   - Modified `count_consecutive_same_syntax_errors()` to return dict with consecutive and total counts (lines 816-950)
   - Added comment-aware distance calculation

2. **`src/workflow.py`**
   - Changed `max_failed_fixes` from 5 to 3 (line 874)
   - Updated to use new error count dict structure (lines 867-904)
   - Updated threshold logic: 2 consecutive OR 3 total (lines 879-880)
   - Updated log messages to show both counts (lines 881-904)
   - Updated progress logging (lines 987-988)

3. **`src/actions/evaluation_actions.py`**
   - Modified `GenerateSyntaxRepairInstruction.run()` to dynamically select prompt section (lines 858-928)
   - Added logic to use `RefineSyntaxRepairInstruction` section when user guidance provided

4. **`src/utils/prompt_manager.py`**
   - Added `RefineSyntaxRepairInstruction` to exclusion lists:
     - `actions_without_convergence` (line 156)
     - `actions_without_quality_standards` (line 161)
     - `actions_without_learning` (line 170)
     - `actions_without_role` (line 177)

### Prompt Templates
5. **`prompts/Evaluator_prompt.txt`**
   - Already contains `RefineSyntaxRepairInstruction` section (lines 676-752)
   - Contains USER GUIDANCE section for syntax repair (lines 725-737)

---

## Testing

### Comment Line Counting Test
Created and ran test script to verify `count_non_comment_lines_between()`:

**Test Input**: `AlloyModel__75.als`, lines 104-117
**Expected**: Should recognize these as close despite comment block

**Results**:
```
Raw distance: 13 lines
Code distance (non-comment): 1 lines
Within threshold (≤5)? True ✅
```

**Verification**: Lines 105-116 are all comments, leaving only 1 actual code line (the `};` at 104) between the two error positions.

---

## Impact Summary

### Before Changes
- User feedback requested after 5 consecutive identical errors
- Comment blocks caused false negatives in error matching
- Alternating errors were never caught (could persist indefinitely)
- User guidance was concatenated as string rather than refined

### After Changes
- User feedback requested after 2 consecutive OR 3 total occurrences
- Comment-aware distance calculation (±5 non-comment lines)
- Alternating/intermittent persistent errors are now detected
- User guidance properly refined through `RefineSyntaxRepairInstruction` prompt section
- Faster intervention (thresholds reduced across the board)

### Key Metrics
| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Consecutive threshold | 5 | 2 | 60% reduction |
| Detection of non-consecutive errors | ❌ None | ✅ 3 total | New capability |
| Comment-aware distance | ❌ No | ✅ Yes | Prevents false negatives |
| User guidance refinement | ❌ String concat | ✅ Evaluator refinement | Better quality |

---

## Future Considerations

1. **Threshold Tuning**: Monitor if 2 consecutive / 3 total is too aggressive or too lenient
2. **Multi-line Comment Edge Cases**: Current implementation handles `/* */` but may need refinement for nested or malformed comments
3. **Error Similarity Metrics**: Consider using fuzzy matching for error messages beyond exact string comparison
4. **Historical Analysis**: Track how often each threshold condition triggers to optimize values

---

## Related Issues from Previous Sessions

This session builds on previous work:
- **Q&A Retrieval Pipeline**: Fixed in previous session (section name mismatch)
- **GenerateSemanticFeedback Enhancement**: Enhanced to incorporate UNSAT analysis
- **Mode Selection Bug**: Fixed iteration offset issue in feedback action lookup
- **User Guidance Integration**: Completed in this session

---

## Conclusion

Today's session significantly improved the AutoRE workflow's ability to detect and handle persistent syntax errors. The combination of comment-aware distance calculation and dual threshold detection (consecutive + total) provides more robust error tracking while reducing false negatives from comment blocks and alternating error patterns.

The user guidance refinement through dedicated prompt sections ensures that when users do provide feedback, it's properly incorporated into high-quality repair instructions rather than being crudely concatenated.

These changes should result in:
- Faster user intervention when truly needed
- Better detection of subtle persistent issues
- Higher quality guidance when user feedback is provided
- Fewer wasted iterations on stuck syntax errors
