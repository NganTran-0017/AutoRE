# Prompt Sections Usage Analysis

## How Prompt Sections Are Combined

**Location:** `src/utils/prompt_manager.py` - `PromptManager.render_prompt()` (lines 86-174)

**For each action, the following sections are combined in order:**
1. `Role` (required)
2. `{ActionName}` (required - specific action instructions)
3. `ResponseFormat{Type}` (optional - action-specific or generic)
4. `QualityStandards` (optional)
5. `LearningInstructions` (optional)

---

## RE Agent (Requirement Engineer)

**Prompt File:** `prompts/RE_prompt.txt`

**Available Sections:**
1. `[SECTION: Role]` - Line 1
2. `[SECTION: AnalyzeRequirements]` - Line 51
3. `[SECTION: IncorporateClarifications]` - Line 77
4. `[SECTION: BuildAlloyModel]` - Line 104
5. `[SECTION: UpdateAlloyModel]` - Line 127
6. `[SECTION: ResponseFormatRequirements]` - Line 152
7. `[SECTION: ResponseFormatAlloyModel]` - Line 182
8. `[SECTION: QualityStandards]` - Line 189
9. `[SECTION: LearningInstructions]` - Line 199

**Actions in Code:**
1. `AnalyzeRequirements` (src/actions/requirement_actions.py)
2. `IncorporateClarifications` (src/actions/requirement_actions.py)
3. `BuildAlloyModel` (src/actions/requirement_actions.py)
4. `UpdateAlloyModel` (src/actions/requirement_actions.py)

### Section Usage by Action

#### AnalyzeRequirements
**USED:**
- ✅ Role
- ✅ AnalyzeRequirements
- ✅ ResponseFormatRequirements
- ✅ QualityStandards
- ✅ LearningInstructions

**NOT USED:**
- ❌ IncorporateClarifications
- ❌ BuildAlloyModel
- ❌ UpdateAlloyModel
- ❌ ResponseFormatAlloyModel

---

#### IncorporateClarifications
**USED:**
- ✅ Role
- ✅ IncorporateClarifications
- ✅ ResponseFormatRequirements
- ✅ QualityStandards
- ✅ LearningInstructions

**NOT USED:**
- ❌ AnalyzeRequirements
- ❌ BuildAlloyModel
- ❌ UpdateAlloyModel
- ❌ ResponseFormatAlloyModel

---

#### BuildAlloyModel
**USED:**
- ✅ Role
- ✅ BuildAlloyModel
- ✅ ResponseFormatAlloyModel
- ✅ QualityStandards
- ✅ LearningInstructions

**NOT USED:**
- ❌ AnalyzeRequirements
- ❌ IncorporateClarifications
- ❌ UpdateAlloyModel
- ❌ ResponseFormatRequirements

---

#### UpdateAlloyModel
**USED:**
- ✅ Role
- ✅ UpdateAlloyModel
- ✅ ResponseFormatAlloyModel
- ✅ QualityStandards
- ✅ LearningInstructions

**NOT USED:**
- ❌ AnalyzeRequirements
- ❌ IncorporateClarifications
- ❌ BuildAlloyModel
- ❌ ResponseFormatRequirements

---

## Evaluator Agent

**Prompt File:** `prompts/Evaluator_prompt.txt`

**Available Sections:**
1. `[SECTION: Role]` - Line 1
2. `[SECTION: InterpretResults]` - Line 59
3. `[SECTION: GenerateFeedback]` - Line 92
4. `[SECTION: UpdateRequirements]` - Line 127
5. `[SECTION: RefineFeedback]` - Line 160
6. `[SECTION: ResponseFormat]` - Line 183
7. `[SECTION: QualityStandards]` - Line 258
8. `[SECTION: LearningInstructions]` - Line 276

**Actions in Code:**
1. `RunAlloyAnalyzer` (src/actions/evaluation_actions.py) - **NO LLM, no prompt used**
2. `InterpretResults` (src/actions/evaluation_actions.py)
3. `GenerateFeedback` (src/actions/evaluation_actions.py)
4. `UpdateRequirements` (src/actions/evaluation_actions.py)
5. `RefineFeedback` (src/actions/evaluation_actions.py) - **Uses hardcoded prompt, not from file**

### Section Usage by Action

#### RunAlloyAnalyzer
**NOT APPLICABLE** - This action doesn't call the LLM. It directly executes Alloy Analyzer.

**ALL SECTIONS UNUSED:**
- ❌ All sections (action doesn't use prompts)

---

#### InterpretResults
**USED:**
- ✅ Role
- ✅ InterpretResults
- ✅ ResponseFormat
- ✅ QualityStandards
- ✅ LearningInstructions

**NOT USED:**
- ❌ GenerateFeedback
- ❌ UpdateRequirements

---

#### GenerateFeedback
**USED:**
- ✅ Role
- ✅ GenerateFeedback
- ✅ ResponseFormat
- ✅ QualityStandards
- ✅ LearningInstructions

**NOT USED:**
- ❌ InterpretResults
- ❌ UpdateRequirements

---

#### UpdateRequirements
**USED:**
- ✅ Role
- ✅ UpdateRequirements
- ✅ ResponseFormatRequirements (mapped in code)
- ✅ QualityStandards
- ✅ LearningInstructions

**NOT USED:**
- ❌ InterpretResults
- ❌ GenerateFeedback
- ❌ ResponseFormat (overridden by ResponseFormatRequirements)

**NOTE:** This action uses `ResponseFormatRequirements` from the RE agent's prompt file, not from the Evaluator prompt file. This is configured in the code mapping (line 146 of prompt_manager.py).

---

#### RefineFeedback
**USED:**
- ✅ Role
- ✅ RefineFeedback
- ✅ ResponseFormat
- ✅ QualityStandards
- ✅ LearningInstructions

**NOT USED:**
- ❌ InterpretResults
- ❌ GenerateFeedback
- ❌ UpdateRequirements

---

## Summary: Unused Sections

### RE Agent - Sections NEVER Used
None - all sections are used by at least one action.

### Evaluator Agent - Sections NEVER Used
None - all sections are used by at least one action.

### Notes on "Unused" Sections

**Per-Action Unused:**
Each action only uses 5 sections maximum:
1. Role (shared by all actions of same agent)
2. ActionName (specific to that action)
3. ResponseFormat (shared by some actions)
4. QualityStandards (shared by all actions)
5. LearningInstructions (shared by all actions)

So for any given action, the other action-specific sections (e.g., `AnalyzeRequirements` section is unused when running `BuildAlloyModel`) are not included in the prompt.

**Special Cases:**
1. **RunAlloyAnalyzer** - Doesn't use any prompt sections (no LLM call)
2. **RefineFeedback** - Uses hardcoded prompt instead of prompt file
3. **UpdateRequirements** (Evaluator) - Borrows `ResponseFormatRequirements` from RE agent's prompt

---

## Potential Issues

### ~~Issue 1: Missing RefineFeedback Section~~ ✅ RESOLVED
**Problem:** `RefineFeedback` action used a hardcoded prompt in the code instead of using the prompt file.

**Status:** FIXED - `[SECTION: RefineFeedback]` added to `Evaluator_prompt.txt` (line 160) and action updated to use `self.render_prompt()`.

**See:** `REFINE_FEEDBACK_PROMPT_MIGRATION.md` for details.

---

### Issue 2: Cross-Agent Section Borrowing
**Problem:** Evaluator's `UpdateRequirements` action borrows `ResponseFormatRequirements` from the RE agent's prompt file.

**Location:** Code mapping in `src/utils/prompt_manager.py:146`

**Current Behavior:** Works because both agents are loaded, but it's non-obvious.

**Recommendation:** Either:
1. Add `[SECTION: ResponseFormatRequirements]` to Evaluator_prompt.txt (duplicate)
2. Document this cross-agent dependency clearly
3. Keep as-is if intentional design

---

## Code Location Reference

**Prompt Section Extraction:**
- `src/utils/prompt_manager.py` - `PromptManager.render_prompt()` (lines 86-174)

**Action-to-Format Mapping:**
- `src/utils/prompt_manager.py` - Lines 133-148

**Prompt Files:**
- `prompts/RE_prompt.txt` - RE agent prompts
- `prompts/Evaluator_prompt.txt` - Evaluator agent prompts

**Action Implementations:**
- `src/actions/requirement_actions.py` - RE agent actions
- `src/actions/evaluation_actions.py` - Evaluator agent actions
