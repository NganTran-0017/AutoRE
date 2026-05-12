# Multi-Agent Discussion System - Implementation Plan

## Overview
Enable Evaluator-RE dialogue to break circular feedback loops and improve solution quality for persistent issues.

## Problem Addressed
- Evaluator provides circular feedback that repeats across iterations
- RE blindly follows Evaluator feedback without critical thinking
- Issues persist for 2+ iterations without resolution

## Architecture: Evaluator-RE Dialogue

```
Issue Detected (persistent 2+ iterations)
    ↓
Evaluator: Propose 2-3 alternative solutions
    ↓
RE: Critique proposals + suggest alternatives
    ↓
Synthesize: Agreed solution (different from previous attempts)
    ↓
RE: Implement agreed solution
```

## Trigger Conditions

Discussion activates when:
1. **Same issue type persists for 2+ iterations** (default threshold), OR
2. **User explicitly requests discussion**

Otherwise, use standard workflow (no discussion).

## Components to Implement

### 1. IssueTracker Class
**File:** `src/utils/issue_tracker.py`

```python
class IssueTracker:
    - record_issue(iteration, issue_type, description, solution)
    - is_issue_persistent(issue_type, min_iterations=2) -> bool
    - is_feedback_circular(current_feedback, lookback=3) -> bool
```

**Issue Types:** `syntax_error`, `counterexample`, `unsat_predicate`

### 2. New Actions

**ProposeAlternativeSolutions** (Evaluator)
- Input: current_issue, failed_attempts, analyzer_results, requirements, model
- Output: 2-3 alternative solutions with rationale
- Prompt section: `[SECTION: ProposeAlternativeSolutions]` in Evaluator_prompt.txt

**CritiqueProposals** (RE)
- Input: evaluator_proposals, current_model, requirements, previous_attempts
- Output: Feasibility analysis + RE's alternative
- Prompt section: `[SECTION: CritiqueProposals]` in RE_prompt.txt

**SynthesizeDiscussion** (Evaluator or new)
- Input: evaluator_proposals, re_critique, failed_attempts, requirements
- Output: Final agreed solution (must differ from previous attempts)
- Prompt section: `[SECTION: SynthesizeDiscussion]` in Evaluator_prompt.txt

### 3. Workflow Integration

**Modify:** `src/workflow.py`

```python
async def _step5_6_generate_feedback_and_get_user_input(self):
    should_discuss = self._should_trigger_discussion(evaluation_result)

    if should_discuss:
        feedback = await self._conduct_discussion(evaluation_result)
    else:
        feedback = await self.generate_feedback.run(...)

    # Record issue for tracking
    self.context.issue_tracker.record_issue(...)
```

## File Structure

### Discussion Logs
**Location:** `Output/Discussions/{iteration}_discussion.md`

**Format:**
```markdown
# Discussion Log - Iteration {N}

## Issue Summary
[What problem persisted]

## Failed Attempts
- Iteration X: [solution attempted]
- Iteration Y: [solution attempted]

## Round 1: Evaluator Proposals
[Full proposals text]

## Round 2: RE Critique
[Full critique text]

## Final Agreed Solution
[Synthesized solution]
```

## Basic Prompt Templates

### ProposeAlternativeSolutions (Evaluator_prompt.txt)
```
[SECTION: ProposeAlternativeSolutions]
The issue has persisted despite previous attempts. Analyze why previous solutions failed and propose 2-3 DIFFERENT approaches.

**Current Issue:** {{current_issue}}
**Failed Attempts:** {{failed_attempts}}
**Analyzer Results:** {{analyzer_results}}
**Requirements:** {{requirements_document}}
**Model:** {{alloy_model}}

OUTPUT FORMAT:

SOLUTION 1: [Title]
- Description: [What to change]
- Rationale: [Why this might work]
- Root Cause: [Real problem]
- Trade-offs: [Considerations]

SOLUTION 2: [Title]
...

SOLUTION 3: [Title]
...

ANALYSIS: [Why previous attempts failed]
```

### CritiqueProposals (RE_prompt.txt)
```
[SECTION: CritiqueProposals]
Critically evaluate Evaluator's proposals from modeling perspective. Challenge infeasible proposals.

**Evaluator Proposals:** {{evaluator_proposals}}
**Current Model:** {{current_model}}
**Requirements:** {{requirements_document}}

OUTPUT FORMAT:

PROPOSAL 1 CRITIQUE:
- Feasibility: [FEASIBLE/INFEASIBLE/PARTIAL]
- Analysis: [Why it will/won't work]
- Constraints Missed: [What Evaluator didn't consider]

PROPOSAL 2 CRITIQUE:
...

RE'S ALTERNATIVE: [If all proposals flawed, suggest own approach]

ROOT CAUSE: [Issue from modeling perspective]
```

### SynthesizeDiscussion (Evaluator_prompt.txt)
```
[SECTION: SynthesizeDiscussion]
Combine Evaluator proposals + RE critique into final actionable solution. Must differ from failed attempts.

**Evaluator Proposals:** {{evaluator_proposals}}
**RE Critique:** {{re_critique}}
**Failed Attempts:** {{failed_attempts}}

OUTPUT FORMAT:

FINAL SOLUTION:
[Concrete action plan]

WHY DIFFERENT FROM PREVIOUS:
[How this differs from failed attempts]

EXPECTED OUTCOME:
[What should happen]
```

## Configuration

**In config.yaml:**
```yaml
workflow:
  discussion:
    enabled: true
    persistence_threshold: 2  # iterations before triggering discussion
    user_control: true  # Allow user to force/disable discussion
```

## Cost Impact

- Normal iteration: 4-6 LLM calls
- Discussion iteration: 7-9 LLM calls (+3)
- Estimated trigger rate: ~30% of iterations
- **Net cost increase: ~20-30%**

## Implementation Checklist

See TODO list for detailed tasks. Key phases:
1. IssueTracker class
2. Three new actions (ProposeAlternativeSolutions, CritiqueProposals, SynthesizeDiscussion)
3. Workflow integration with conditional trigger
4. Basic prompt templates
5. Discussion logging to file
6. Testing circular feedback detection

**Estimated Time:** 4 days
