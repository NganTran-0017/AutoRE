# Q&A Workflow Summary

## Flow Overview

### Phase 1: InterpretResults (Questions Asked)
**Action**: `InterpretResults.run()`
**Responsibility**: Analyze verification results and formulate user questions

**Input:**
- Analyzer results
- Requirements document
- Alloy model

**Output:**
```
SYNTAX STATUS: OK
COUNTEREXAMPLES: None
SATISFYING INSTANCES: Meaningful
VACUITY: None
INCREMENTAL ANALYSIS: [...]

=== USER QUESTIONS ===
1. Should Emergency mode require exactly 2 administrators or allow 2-4?
2. Can delegations granted before Emergency continue after Emergency ends?
```

**System Action:**
- Parses questions from `=== USER QUESTIONS ===` section
- Stores as `pending_questions` in ArtifactStore
- Questions used to retrieve relevant Q&A in next phase

---

### Phase 2: GenerateFeedback (Q&A Context Provided)
**Action**: `GenerateFeedback.run()`
**Responsibility**: Generate actionable feedback using Q&A context

**Input:**
- Interpretation (from InterpretResults)
- Requirements document
- Alloy model
- **Relevant Q&A** (NEW - retrieved based on pending_questions)
- Lessons
- User preferences

**Q&A Retrieval Logic:**
```python
# Get questions from InterpretResults
pending_questions = artifacts.get_pending_questions(iteration)

# Retrieve top 3 relevant Q&A based on semantic similarity
relevant_qa_records = qa_database.retrieve_relevant(
    questions=pending_questions,
    current_iteration=iteration,
    max_results=3,
    similarity_threshold=0.3
)

# Format for prompt
relevant_qa_str = qa_database.format_for_prompt(relevant_qa_records)
```

**Q&A Context Example:**
```
=== RELEVANT PRIOR CLARIFICATIONS ===

[Q3_1] Context: R4
Q: Should delegations be automatically revoked at Emergency end?
A: Yes, auto-revoke all Emergency delegations. Pre-Emergency delegations unaffected.
Status: confirmed | Source: user | Iteration: 3

[Q7_2] Context: Emergency
Q: Can Emergency mode be activated by a single administrator?
A: No, exactly 2 administrators must jointly activate.
Status: confirmed | Source: user | Iteration: 7
```

**Instructions Provided to Evaluator (from prompt template):**
```
**Instructions for using Q&A records (if provided above):**
- If any prior clarification addresses your current concern, reference it by ID (e.g., "Per Q5_1, Emergency requires...")
- Before asking new questions, check if prior Q&A already answered them
- If a Q&A is now outdated due to requirement changes, mark it in Q&A UPDATE section
- Only ask genuinely new questions not covered by existing Q&A
```

**Output:**
```
=== VERIFICATION STATUS ===
[...]

=== ALLOY_MODEL_IMPROVEMENTS ===
Per Q3_1, ensure Emergency delegations are auto-revoked at end...
Per Q7_2, require exactly 2 admins for activation...

=== UPDATED USER QUESTIONS ===
1. Should Emergency mode require exactly 2 administrators or allow 2-4?

NOTE: Question 2 is already addressed by Q3_1 (pre-Emergency delegations unaffected)

=== Q&A UPDATE ===
Q3_1: status: confirmed
Q7_2: status: confirmed

=== HANDOFF TO RE ===
[...]
```

**System Actions:**
1. Parse `=== UPDATED USER QUESTIONS ===` for new questions
2. Parse `=== Q&A UPDATE ===` for status changes
3. Detect Q&A ID references (Q3_1, Q7_2) in response text
4. Update database:
   - Apply status changes
   - Increment reuse_count for referenced Q&A
5. Store new questions for user to answer

---

### Phase 3: User Feedback & Q&A Record Creation
**Workflow**: After GenerateFeedback, user reviews and provides feedback

**Scenario A: User Answers Questions**
```
User input: "Exactly 2 administrators only - no flexibility on this."
```

**System Creates Q&A Record:**
```python
QARecord(
    id="Q10_1",  # Iteration 10, Question 1
    iteration=10,
    question="Should Emergency mode require exactly 2 administrators or allow 2-4?",
    answer="Exactly 2 administrators only - no flexibility on this.",
    source="user",
    context="Emergency",  # Extracted from question
    status="confirmed"
)
```

**Scenario B: User Doesn't Answer (Agent Makes Assumption)**

If Evaluator made an assumption in feedback:
```
=== ALLOY_MODEL_IMPROVEMENTS ===
Assuming smallest reasonable choice: exactly 2 administrators required...
```

**System Creates Provisional Q&A Record:**
```python
QARecord(
    id="Q10_1",
    iteration=10,
    question="Should Emergency mode require exactly 2 administrators or allow 2-4?",
    answer="Agent assumption: Smallest reasonable choice - exactly 2 administrators",
    source="agent_assumption",
    context="Emergency",
    status="provisional"
)
```

---

## Key Differences from Original Design

### ✅ Questions Asked Earlier (InterpretResults)
**Benefit**: Questions are formulated during interpretation when context is freshest

### ✅ Q&A Retrieved Based on Questions
**Benefit**: More accurate retrieval - we know exactly what's being asked

### ✅ GenerateFeedback Focuses on Using Q&A
**Benefit**:
- Evaluator can reference existing Q&A by ID
- Prevents duplicate questions
- Only asks NEW questions when necessary

---

## Prompt Template Sections

### InterpretResults Section
- ✅ Includes abstraction guidance
- ✅ Objective 7: "Formulate user questions"
- ✅ Response format includes `=== USER QUESTIONS ===`

### GenerateFeedback Section
- ✅ Receives `{{relevant_qa}}` placeholder
- ✅ Instructions on using Q&A records
- ✅ Objective: "Formulate NEW questions ONLY if existing Q&A insufficient"
- ✅ Response format includes:
  - `=== UPDATED USER QUESTIONS ===` (only new questions)
  - `=== Q&A UPDATE ===` (status changes)

### QAContextReuseAndUpdate Section
- ✅ Guidance on Q&A reuse
- ✅ Instructions on status updates
- ✅ Emphasis on avoiding duplication

---

## Implementation Checklist

### ✅ Completed
- [x] QA database with semantic search
- [x] QA parser utilities
- [x] Prompt template updated (InterpretResults asks questions)
- [x] Prompt template updated (GenerateFeedback uses Q&A)
- [x] GenerateFeedback accepts `relevant_qa` parameter
- [x] ArtifactStore supports pending_questions
- [x] All prompts originate from Evaluator_prompt.txt (no hardcoded instructions)

### 🚧 Remaining (Workflow Integration)
- [ ] Step 4: Parse questions from InterpretResults response
- [ ] Step 4: Store questions as pending_questions
- [ ] Step 5-6: Retrieve relevant Q&A based on pending_questions
- [ ] Step 5-6: Pass relevant_qa to GenerateFeedback
- [ ] Step 5-6: Parse new questions from GenerateFeedback
- [ ] Step 5-6: Parse Q&A status updates
- [ ] Step 5-6: Parse reused Q&A IDs
- [ ] Step 5-6: Create Q&A records from user feedback
- [ ] Step 5-6: Handle agent assumptions (provisional Q&A)

---

## Token Efficiency

### Before Q&A System
- No question tracking → repeated questions
- No context → rehashing same discussions

### With Q&A System
- **InterpretResults**: +0 tokens (questions asked anyway)
- **GenerateFeedback**: +300-500 tokens (3 relevant Q&A records)
- **Benefit**: Prevents duplication, provides context, reduces back-and-forth

**Net Result**: ~400 tokens per iteration for significantly better context and no repeated questions

---

## Example: Full Iteration Flow

**Iteration 10**

1. **InterpretResults output**:
   ```
   === USER QUESTIONS ===
   1. Admin count for Emergency?
   2. Delegation expiry policy?
   ```

2. **System retrieves Q&A**:
   - Q3_1 (delegation expiry - confirmed)
   - Q7_2 (admin count - provisional)

3. **GenerateFeedback receives**:
   ```
   === RELEVANT PRIOR CLARIFICATIONS ===
   [Q3_1] ... delegation expiry ...
   [Q7_2] ... admin count (provisional) ...
   ```

4. **GenerateFeedback output**:
   ```
   Per Q3_1, auto-revoke delegations...

   === UPDATED USER QUESTIONS ===
   1. Should admin count be exactly 2 or allow 2-4? (Q7_2 was provisional, needs confirmation)

   === Q&A UPDATE ===
   Q3_1: status: confirmed
   ```

5. **User answers**: "Exactly 2 only"

6. **System creates**:
   ```
   Q10_1: "admin count = exactly 2" (confirmed)
   ```

7. **Next iteration**: Q10_1 will be retrieved if similar question arises

---

This flow ensures:
- ✅ Questions asked at right time (InterpretResults)
- ✅ Q&A retrieved accurately (based on actual questions)
- ✅ Duplicate questions prevented (Q&A context provided)
- ✅ All prompts from template (no hardcoded text)
- ✅ Token efficient (~400 tokens for 3 Q&A records)
