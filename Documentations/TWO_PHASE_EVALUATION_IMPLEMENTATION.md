# Two-Phase Evaluation Implementation

**Date**: 2026-04-30
**Status**: ✅ COMPLETE

---

## Overview

Implemented a two-phase evaluation workflow where the Evaluator generates draft feedback, presents it to the user for review, incorporates user input, and then publishes final feedback.

### Key Principle
**Draft feedback is shown to user BEFORE being finalized**, allowing user to:
- Comment on evaluator's suggestions
- Suggest additional scenarios/edge cases
- Provide corrections or disagreements

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ WORKFLOW ORCHESTRATOR                                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ Step 4: Evaluate Model                                             │
│   → Sends EvaluationRequest to Evaluator                           │
│   ← Receives DraftFeedbackResponse                                 │
│                                                                     │
│ Step 5-6: User Review (OPTIONAL)                                   │
│   → Shows draft feedback to user                                   │
│   → User provides feedback or skips                                │
│   → Sends FeedbackRefinementRequest to Evaluator                   │
│   ← Receives final EvaluationResponse                              │
│                                                                     │
│ Step 7: Update Requirements                                        │
│   → Sends RequirementUpdateRequest to Evaluator                    │
│                                                                     │
│ Step 8: Update Model                                               │
│   → Sends AlloyModelRequest to RE agent                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ EVALUATOR AGENT                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ Phase 1: Generate Draft (_handle_evaluation)                       │
│   1. Run Alloy Analyzer                                            │
│   2. InterpretResults action                                       │
│   3. GenerateFeedback action → draft                               │
│   4. Store context in self.current_evaluation_context              │
│   5. Publish DraftFeedbackResponse (NOT final!)                    │
│                                                                     │
│ Phase 2: Refine (_handle_feedback_refinement)                      │
│   1. Receive FeedbackRefinementRequest with user input             │
│   2. RefineFeedback action → incorporates user feedback            │
│   3. Publish FINAL EvaluationResponse                              │
│   4. Clear stored context                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ RE AGENT                                                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ ✅ Only subscribes to:                                              │
│   - RequirementAnalysisRequest                                     │
│   - AlloyModelRequest (contains final feedback)                    │
│   - UserInputMessage                                               │
│                                                                     │
│ ❌ Does NOT see:                                                    │
│   - DraftFeedbackResponse                                          │
│   - EvaluationResponse                                             │
│   - FeedbackRefinementRequest                                      │
│                                                                     │
│ Receives feedback via AlloyModelRequest from Workflow              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Files Modified

### 1. **src/messages.py**

Added two new message types:

```python
class DraftFeedbackResponse(AutoREMessage):
    """Draft feedback from Evaluator for user review (NOT seen by RE agent)."""
    execution_result: Dict[str, Any]
    interpretation: str
    draft_feedback: Dict[str, str]  # {alloy_improvements, requirement_updates}
    has_syntax_errors: bool
    has_counterexamples: bool
    has_satisfying_instances: bool
    output_directory: str

class FeedbackRefinementRequest(AutoREMessage):
    """Request to refine draft feedback with user input."""
    draft_feedback: Dict[str, str]
    user_feedback: str
    interpretation: str
    execution_result: Dict[str, Any]
    requirements_document: str
    alloy_model_content: str
```

---

### 2. **src/actions/evaluation_actions.py**

Added new action:

```python
class RefineFeedback(Action):
    """Refine evaluator's draft feedback based on user input."""

    async def run(
        self,
        draft_alloy_improvements: str,
        draft_requirement_updates: str,
        user_feedback: Optional[str],  # Empty if no feedback
        ...
    ) -> Dict[str, str]:
        """
        If user_feedback is empty:
          - Returns draft as-is
        If user_feedback provided:
          - Incorporates user's comments, scenarios, corrections
          - Returns refined feedback
        """
```

**Export**: Added to `src/actions/__init__.py`

---

### 3. **src/agents/evaluator.py**

**Changes:**

#### 3.1 Added imports:
```python
from ..actions import RefineFeedback
from ..messages import DraftFeedbackResponse, FeedbackRefinementRequest
```

#### 3.2 Updated `__init__`:
- Added `RefineFeedback` to actions
- Subscribed to `FeedbackRefinementRequest`
- Added `self.current_evaluation_context` for storing state between phases

#### 3.3 Updated `_think`:
```python
elif isinstance(latest_msg, FeedbackRefinementRequest):
    self.rc.todo = RefineFeedback()
```

#### 3.4 Updated `_act`:
```python
elif isinstance(todo, RefineFeedback):
    await self._handle_feedback_refinement(latest_msg)
```

#### 3.5 Modified `_handle_evaluation`:
**OLD**: Published final EvaluationResponse immediately
**NEW**:
- Generates draft feedback
- Stores context in `self.current_evaluation_context`
- Publishes `DraftFeedbackResponse` (not final)
- Does NOT save feedback to file yet
- Waits for refinement request

#### 3.6 Added `_handle_feedback_refinement`:
```python
async def _handle_feedback_refinement(self, request: FeedbackRefinementRequest):
    """
    1. Retrieves stored context
    2. Calls RefineFeedback action with user input
    3. Saves FINAL feedback to file
    4. Publishes FINAL EvaluationResponse
    5. Clears stored context
    """
```

---

### 4. **src/workflow.py**

**Changes:**

#### 4.1 Added imports:
```python
from .messages import DraftFeedbackResponse, FeedbackRefinementRequest
```

#### 4.2 Modified `_step4_evaluate_model`:
**OLD**: Waited for `EvaluationResponse`
**NEW**: Waits for `DraftFeedbackResponse`

```python
async def _step4_evaluate_model(self) -> DraftFeedbackResponse:
    # Publish EvaluationRequest (same)
    # Wait for DraftFeedbackResponse (not final!)
    draft_response = await self._wait_for_message(DraftFeedbackResponse, timeout=180)
    return draft_response
```

#### 4.3 Modified `_step5_6_user_feedback`:
**OLD**: Took `EvaluationResponse`, showed summary
**NEW**: Takes `DraftFeedbackResponse`, shows full draft feedback

```python
async def _step5_6_user_feedback(
    self,
    draft_response: DraftFeedbackResponse
) -> tuple[EvaluationResponse, bool]:
    """
    1. Format and show draft feedback to user
    2. Collect user feedback (optional - can timeout/skip)
    3. Publish FeedbackRefinementRequest
    4. Wait for FINAL EvaluationResponse
    5. Return (final_response, user_satisfied)
    """
```

**User sees:**
```
======================================================================
EVALUATOR'S DRAFT FEEDBACK (for your review)
======================================================================

ALLOY MODEL IMPROVEMENTS:
----------------------------------------------------------------------
[Draft suggestions for model]

REQUIREMENT UPDATES:
----------------------------------------------------------------------
[Draft suggestions for requirements]

======================================================================

Please review the Evaluator's suggestions above.
You may:
  - Provide comments or corrections
  - Suggest additional scenarios or edge cases to check
  - Ask questions or raise concerns

Press Enter without typing to skip (draft feedback will be used as-is).
Or type 'SATISFIED' if you're satisfied with the results.
```

#### 4.4 Updated main loop:
```python
while not converged and iteration < max_iterations:
    # Step 4: Get draft
    draft_response = await self._step4_evaluate_model()

    # Step 5-6: User review + get final
    final_response, user_satisfied = await self._step5_6_user_feedback(draft_response)

    # Check satisfaction
    if user_satisfied or final_response.is_complete:
        converged = True
        break

    # Step 7: Update requirements (uses final_response)
    await self._step7_update_requirements(final_response)

    # Step 8: Update model (uses final_response)
    await self._step8_update_model(final_response)
```

---

## Message Flow Diagram

```
Workflow                    Evaluator                   RE Agent
   |                           |                           |
   |---EvaluationRequest------>|                           |
   |                           |                           |
   |                           |--Run Analyzer             |
   |                           |--InterpretResults         |
   |                           |--GenerateFeedback         |
   |                           |  (draft)                  |
   |                           |                           |
   |<--DraftFeedbackResponse---|                           |
   |                           |                           |
   |--Show to user             |                           |
   |--Collect feedback         |                           |
   |                           |                           |
   |---FeedbackRefinementReq-->|                           |
   |                           |                           |
   |                           |--RefineFeedback           |
   |                           |  (incorporates user)      |
   |                           |                           |
   |<--EvaluationResponse------|                           |
   |  (FINAL)                  |                           |
   |                           |                           |
   |---RequirementUpdateReq--->|                           |
   |                           |                           |
   |---AlloyModelRequest------------------------------>|   |
   |  (contains final feedback)|                           |
   |                           |                           |
```

---

## User Feedback Handling

### If user provides feedback:
1. Workflow sends feedback to Evaluator
2. Evaluator calls `RefineFeedback` action
3. LLM incorporates user's comments into final feedback
4. Final feedback published

### If user skips (timeout or Enter):
1. Workflow sends empty string as user_feedback
2. Evaluator calls `RefineFeedback` with empty feedback
3. LLM returns draft as-is (no changes)
4. Final feedback published

### If user types "SATISFIED":
1. User satisfaction recorded
2. Workflow still sends refinement request (for consistency)
3. Final feedback published
4. Workflow exits successfully

---

## Benefits

✅ **User can review and improve evaluator's analysis** before it becomes final
✅ **User can suggest additional scenarios** for checking
✅ **Feedback is more accurate** - incorporates user domain knowledge
✅ **RE agent only sees final feedback** - no confusion from draft versions
✅ **Optional user input** - can skip if in a hurry
✅ **Consistent architecture** - all feedback goes through same refinement flow

---

## Testing Checklist

- [ ] User provides feedback → Feedback incorporated into final version
- [ ] User skips (Enter) → Draft becomes final unchanged
- [ ] User types "SATISFIED" → Workflow completes successfully
- [ ] User timeout → Draft becomes final unchanged
- [ ] RE agent never sees DraftFeedbackResponse
- [ ] RE agent receives final feedback in AlloyModelRequest
- [ ] Evaluator saves feedback to file only after refinement
- [ ] Token counting works for draft feedback display

---

## Related Issues Fixed

- ✅ GAP #8: Separated UNSAT run vs check commands
- ✅ Implemented ratio scores for analysis summary
- ✅ Implemented actual token counting (tiktoken)
- ✅ Two-phase evaluation with user review

---

## Dependencies

**New dependency added:**
```
tiktoken>=0.5.0  # Token counting for OpenAI models
```

Install with: `pip install tiktoken>=0.5.0`

---

## Notes

- Evaluator stores context in `self.current_evaluation_context` between phases
- Context is cleared after publishing final response
- If refinement never comes (timeout), context remains until next evaluation
- Workflow acts as orchestrator - mediates all agent communication
- No agent directly subscribes to another agent's response messages
