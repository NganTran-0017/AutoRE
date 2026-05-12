# RefineFeedback Prompt Migration - May 1, 2026

## Summary

Moved the `RefineFeedback` action's hardcoded prompt from code into the Evaluator prompt file for consistency with other actions.

## Changes Made

### 1. Added Prompt Section to Evaluator_prompt.txt

**File:** `prompts/Evaluator_prompt.txt`
**Location:** Lines 160-182 (inserted after `UpdateRequirements`, before `ResponseFormat`)

**New Section:**
```
[SECTION: RefineFeedback]
### TASK: REFINE FEEDBACK

Refine feedback based on user review.

**Your objectives:**
1. Incorporate user's review comments
2. Maintain the structure from the draft feedback
3. Adjust based on user input
4. Keep feedback actionable and specific

**Draft Feedback:**
{{draft_feedback}}

**User Review:**
{{user_review}}

{{lessons}}

{{user_preferences}}

Provide the refined, final feedback incorporating the user's review.
```

### 2. Updated RefineFeedback Action Code

**File:** `src/actions/evaluation_actions.py`
**Method:** `RefineFeedback.run()` (lines 274-312)

**Before:**
```python
# Build simple prompt (no section in Evaluator prompt for this)
prompt = f"""You are refining feedback based on user review.

DRAFT FEEDBACK:
{draft_feedback}

USER REVIEW:
{user_review}

{lessons_str}

{user_prefs}

Provide the refined, final feedback incorporating the user's review.
Maintain the structure from the draft but adjust based on user input.
"""

# Call LLM
response = await self._aask(prompt)
```

**After:**
```python
# Render prompt from template
prompt = self.render_prompt(
    draft_feedback=draft_feedback,
    user_review=user_review,
    lessons=lessons_str,
    user_preferences=user_prefs
)

# Call LLM
response = await self._aask(prompt)
```

## Benefits

### Before Migration:
- ❌ Prompt hardcoded in action code
- ❌ Inconsistent with other actions
- ❌ Harder to modify prompt without touching code
- ❌ No access to shared sections (Role, QualityStandards, LearningInstructions)

### After Migration:
- ✅ Prompt in standardized location (prompt file)
- ✅ Consistent with other actions
- ✅ Easy to modify prompt without code changes
- ✅ Automatically includes shared sections:
  - Role
  - RefineFeedback (action-specific)
  - ResponseFormat
  - QualityStandards
  - LearningInstructions

## Prompt Composition

When `RefineFeedback.run()` is called, the prompt manager combines these sections:

1. **Role** (from Evaluator_prompt.txt:1-58)
2. **RefineFeedback** (from Evaluator_prompt.txt:160-182)
3. **ResponseFormat** (from Evaluator_prompt.txt:183-257)
4. **QualityStandards** (from Evaluator_prompt.txt:258-275)
5. **LearningInstructions** (from Evaluator_prompt.txt:276+)

The sections are joined with double newlines and all `{{variables}}` are substituted with actual values.

## Testing

To verify the changes work:

```bash
# Run workflow that triggers two-phase evaluation
python main.py example_input.txt --max-iterations 2

# Check logs for RefineFeedback prompt
grep -A 50 "AGENT COMMUNICATION: Evaluator - RefineFeedback" Output/outputlog/*.log
```

Expected: The logged prompt should show all sections combined (Role + RefineFeedback + ResponseFormat + QualityStandards + LearningInstructions).

## Updated Evaluator Prompt Structure

**All Sections (in order):**
1. `[SECTION: Role]` - Line 1
2. `[SECTION: InterpretResults]` - Line 59
3. `[SECTION: GenerateFeedback]` - Line 92
4. `[SECTION: UpdateRequirements]` - Line 127
5. `[SECTION: RefineFeedback]` - Line 160 ⭐ **NEW**
6. `[SECTION: ResponseFormat]` - Line 183
7. `[SECTION: QualityStandards]` - Line 258
8. `[SECTION: LearningInstructions]` - Line 276

**All Evaluator Actions:**
1. `RunAlloyAnalyzer` - No prompt (doesn't call LLM)
2. `InterpretResults` - Uses prompt file ✅
3. `GenerateFeedback` - Uses prompt file ✅
4. `UpdateRequirements` - Uses prompt file ✅
5. `RefineFeedback` - Uses prompt file ✅ (fixed)

## Files Modified

1. **prompts/Evaluator_prompt.txt**
   - Added `[SECTION: RefineFeedback]` (lines 160-182)

2. **src/actions/evaluation_actions.py**
   - Updated `RefineFeedback.run()` to use `self.render_prompt()` (lines 274-312)

## Related Documentation

- `PROMPT_SECTIONS_USAGE.md` - Should be updated to reflect this change
