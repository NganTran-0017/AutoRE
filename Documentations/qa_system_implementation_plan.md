# Q&A System Implementation Plan

## Overview
Implement a Q&A database system to track user clarifications and prevent repeated questions across iterations.

## Components Created

### 1. `src/utils/qa_database.py`
- **QARecord**: Dataclass with fields: id, iteration, question, answer, source, context, status (confirmed/provisional/outdated), created_at, reuse_count
- **QADatabase**: Database class with methods:
  - `add_record()`: Add new Q&A record
  - `get_record_by_id()`: Retrieve by ID
  - `update_status()`: Update record status
  - `increment_reuse_count()`: Track reuse
  - `retrieve_relevant()`: Semantic search for relevant Q&A
  - `format_for_prompt()`: Format records for inclusion in prompts
  - Persistent storage via JSON

### 2. `src/utils/qa_parser.py`
- `parse_user_questions()`: Extract questions from === USER QUESTIONS === section
- `parse_qa_updates()`: Extract status updates from === Q&A UPDATE === section
- `parse_reused_qids()`: Detect Q&A ID references in response text
- `extract_question_context()`: Extract context/requirement ref from question
- `parse_user_feedback_for_answers()`: Map user feedback to questions

### 3. Prompt Template Updates (`prompts/Evaluator_prompt.txt`)
- Added `{{relevant_qa}}` placeholder in GenerateFeedback section
- Updated QAContextReuseAndUpdate section with clear instructions
- Response format includes `=== Q&A UPDATE ===` section

### 4. Runtime Context Updates (`src/utils/runtime_context.py`)
- Added `qa_database` to SharedRuntimeContext
- Stored in `memory/{project_name}/qa_database.json`

## Workflow Integration

### Step 4: Evaluate Model (`_step4_evaluate_model`)
**After InterpretResults (line 477):**
```python
# Parse questions from interpretation
from src.utils.qa_parser import parse_user_questions
questions = parse_user_questions(interpretation, section_name="USER QUESTIONS")

# Store temporarily for use in GenerateFeedback
self.context.artifacts.store_pending_questions(
    self.context.iteration.current,
    questions
)
```

### Step 5-6: Generate Feedback (`_step5_6_generate_feedback_and_get_user_input`)
**Before GenerateFeedback.run() (line 517):**
```python
# Retrieve pending questions from InterpretResults
pending_questions = self.context.artifacts.get_pending_questions(
    self.context.iteration.current
)

# Retrieve relevant Q&A from database
relevant_qa_records = self.context.qa_database.retrieve_relevant(
    questions=pending_questions,
    current_iteration=self.context.iteration.current,
    max_results=3
)

# Format for prompt
relevant_qa_str = self.context.qa_database.format_for_prompt(relevant_qa_records)

# Pass to GenerateFeedback
draft_feedback = await self.generate_feedback.run(
    interpretation=interpretation,
    requirements_document=requirements,
    alloy_model=alloy_model,
    relevant_qa=relevant_qa_str  # NEW parameter
)
```

**After GenerateFeedback (line 540):**
```python
# Parse new questions from draft_feedback
from src.utils.qa_parser import (
    parse_user_questions,
    parse_qa_updates,
    parse_reused_qids,
    extract_question_context
)

new_questions = parse_user_questions(draft_feedback, section_name="UPDATED USER QUESTIONS")

# Parse Q&A status updates
qa_updates = parse_qa_updates(draft_feedback)

# Parse reused Q&A IDs
reused_qids = parse_reused_qids(draft_feedback)

# Update database with status changes
for qa_id, new_status in qa_updates.items():
    self.context.qa_database.update_status(qa_id, new_status)

# Update reuse counts
for qa_id in reused_qids:
    self.context.qa_database.increment_reuse_count(qa_id)
```

**After user provides feedback (lines 550-560):**
```python
if user_review and user_review.strip() and new_questions:
    # User answered questions - create Q&A records
    from src.utils.qa_parser import parse_user_feedback_for_answers
    from src.utils.qa_database import QARecord, create_qa_id

    answers = parse_user_feedback_for_answers(user_review, new_questions)

    for idx, question in enumerate(new_questions, start=1):
        answer = answers.get(idx-1, user_review)  # Fallback to full feedback
        context = extract_question_context(question)
        qa_id = create_qa_id(self.context.iteration.current, idx)

        record = QARecord(
            id=qa_id,
            iteration=self.context.iteration.current,
            question=question,
            answer=answer,
            source="user",
            context=context,
            status="confirmed"
        )

        self.context.qa_database.add_record(record)
        print(f"  ✓ Stored Q&A record: {qa_id}")

elif new_questions:
    # No user feedback but questions were asked - agent makes assumptions
    # Check if agent made assumptions in the feedback
    for idx, question in enumerate(new_questions, start=1):
        # Look for agent's assumption in the feedback text
        assumption_pattern = f"Assuming.*?{question[:30]}"
        if re.search(assumption_pattern, draft_feedback, re.IGNORECASE):
            # Extract assumption from feedback
            assumption = extract_agent_assumption(draft_feedback, question)
            context = extract_question_context(question)
            qa_id = create_qa_id(self.context.iteration.current, idx)

            record = QARecord(
                id=qa_id,
                iteration=self.context.iteration.current,
                question=question,
                answer=assumption,
                source="agent_assumption",
                context=context,
                status="provisional"
            )

            self.context.qa_database.add_record(record)
            print(f"  ~ Stored provisional Q&A record: {qa_id}")
```

## GenerateFeedback Action Updates

### File: `src/actions/evaluation_actions.py`

**Modify `GenerateFeedback.run()` signature:**
```python
async def run(
    self,
    interpretation: str,
    requirements_document: str,
    alloy_model: str,
    relevant_qa: str = ""  # NEW parameter
) -> str:
```

**Update prompt rendering (line 438):**
```python
prompt = self.render_prompt(
    interpretation=interpretation,
    requirements_document=requirements_document,
    alloy_model=model_context,
    lessons=lessons_str,
    relevant_qa=relevant_qa,  # NEW
    user_preferences=user_prefs
)
```

## ArtifactStore Updates

### File: `src/utils/artifact_store.py`

**Add methods for pending questions:**
```python
def __init__(self):
    ...
    self.pending_questions: Dict[int, List[str]] = {}

def store_pending_questions(self, iteration: int, questions: List[str]):
    """Store questions from InterpretResults for use in GenerateFeedback."""
    self.pending_questions[iteration] = questions

def get_pending_questions(self, iteration: int) -> List[str]:
    """Get pending questions for iteration."""
    return self.pending_questions.get(iteration, [])
```

## Testing Plan

1. **Unit Tests**:
   - Test QADatabase CRUD operations
   - Test semantic similarity matching
   - Test all parser functions
   - Test Q&A record creation with different sources

2. **Integration Tests**:
   - Test full workflow with Q&A lifecycle
   - Test question parsing from InterpretResults
   - Test Q&A retrieval in GenerateFeedback
   - Test status updates after feedback
   - Test agent assumptions when user doesn't answer

3. **End-to-End Test**:
   - Run workflow with repeated similar questions
   - Verify Q&A are retrieved and prevent duplication
   - Verify status updates work correctly

## Migration/Rollout

1. Deploy code changes
2. Initialize empty Q&A database for existing projects
3. Monitor first few iterations to ensure:
   - Questions are parsed correctly
   - Relevant Q&A are retrieved
   - Status updates work
   - No impact on existing functionality

## Success Metrics

- Reduction in repeated questions (track via logs)
- Q&A database growth rate
- Reuse count distribution
- Status transitions (confirmed → provisional → outdated)
- User satisfaction (fewer "you already asked this" moments)

## Potential Issues & Mitigations

1. **Issue**: Semantic similarity too low, misses relevant Q&A
   - **Mitigation**: Tune similarity threshold, add keyword matching boost

2. **Issue**: Evaluator doesn't properly reference Q&A IDs
   - **Mitigation**: Parse Q&A references from text automatically (already implemented)

3. **Issue**: Status updates not provided by Evaluator
   - **Mitigation**: Default to keeping existing status (already implemented)

4. **Issue**: Agent assumptions not properly detected
   - **Mitigation**: Use heuristics to detect assumption language in feedback

5. **Issue**: Q&A database grows too large
   - **Mitigation**: Implement periodic cleanup of outdated records (future enhancement)
