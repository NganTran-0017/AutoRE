# User Interaction Guide

## Overview

AutoRE uses **CLI-based interaction** for real-time communication with users. When the system needs your input, you type responses directly in the terminal. All interactions are automatically logged to `outputlog/MMDDYY.log` files for a complete audit trail.

## How CLI Interaction Works

### Communication Method

**Direct Terminal Input:**
- System displays prompts directly in the terminal
- You type your responses in the CLI
- No external files needed for communication
- Everything logged automatically

### Interaction Flow

```
┌─────────────────┐
│  System/Agents  │
└────────┬────────┘
         │
         │ 1. Displays prompt in terminal
         ▼
  ┌──────────────────┐
  │   Terminal CLI   │ ◄── YOU SEE THIS
  └──────────────────┘
         │
         │ 2. You type response
         ▼
    ┌──────────┐
    │   You    │
    └─────┬────┘
          │
          │ 3. Type 'END' and press Enter
          ▼
  ┌──────────────────┐
  │ System reads and │
  │    continues     │
  └──────────────────┘
```

## Providing Input

### Multi-line Input Format

When prompted for feedback:

1. **Type your response** (can span multiple lines)
2. **Press Enter** after each line
3. **Type `END`** on a new line when finished
4. **Press Enter** to submit

**Example:**
```
Your response (type your feedback, then 'END' on a new line):
Timeout: 300 seconds (5 minutes)

> Members cannot reserve books they currently have borrowed.
> Members can only reserve books that are checked out by others.
> If membership expires, all reservations are cancelled.
> Reserved books must be picked up within 3 days.
> END
```

### Single-line Input Format

Some prompts may request simple yes/no or brief responses:

1. **Type your response**
2. **Press Enter** to submit

**Example:**
```
Your response (press Enter when done):
Timeout: 300 seconds (5 minutes)

> yes
```

### Important Rules

- **Always end multi-line input with `END` on its own line**
- **Press Enter after typing `END`**
- **The system won't process your input without the `END` marker**
- **`END` is case-insensitive** (END, end, End all work)

## Step-by-Step: What Happens at Each Interaction Point

### Interaction Point 1: Initial Clarification (Steps 1-2)

**When:** After the RE agent analyzes your initial requirements

**System displays:**
```
======================================================================
Step 1: Analyzing initial requirements...
======================================================================

Requirements document created: ReqsDoc/Reqs_0.txt

======================================================================
CLARIFICATION REQUEST - Iteration 0
======================================================================

Requirements document created: ReqsDoc/Reqs_0.txt

Please review and provide clarification on assumptions and requirements.
Type your feedback below (end with 'END' on a new line):
======================================================================

Your response (type your feedback, then 'END' on a new line):
Timeout: 300 seconds (5 minutes)

_
```

**What you should do:**

1. **Review the requirements document:**
   - Open `ReqsDoc/Reqs_0.txt` in a text editor or another terminal
   - Read the assumptions and structured requirements

2. **Type your clarifications in the terminal:**
   ```
   > Clarification for assumption 1: [your response]
   > Clarification for assumption 2: [your response]
   > Additional context: [more details]
   > END
   ```

3. **System responds:**
   ```
   User clarification received!
   ```

**If you don't respond within 5 minutes:**
```
======================================================================
TIMEOUT: No input received within time limit
Proceeding with assumption: No feedback from user
======================================================================

No user clarification provided (timeout)
Proceeding with current understanding of requirements
```

---

### Interaction Point 2: Evaluation Review (Steps 5-6)

**When:** After each Alloy Analyzer verification iteration

**System displays:**
```
======================================================================
Step 4: Running Alloy Analyzer...
======================================================================

Analysis Results:
  Syntax Errors: NO
  Counterexamples: YES
  Satisfying Instances: YES
  Complete: NO

Analysis results saved to: AnalyzerOutput/1/

======================================================================
EVALUATION REVIEW - Iteration 1
======================================================================

✓ Syntax: OK
✗ Counterexamples: Found
✓ Instances: Valid scenarios exist

Results in: AnalyzerOutput/1/

Provide feedback, additional scenarios, or type 'SATISFIED':
(End with 'END' on a new line)
======================================================================

Your response (type your feedback, then 'END' on a new line):
Timeout: 300 seconds (5 minutes)

_
```

**What you should do:**

1. **Review the analysis results:**
   - Check `AnalyzerOutput/[iteration]/` for detailed results
   - Look at counterexamples to understand what failed
   - Review satisfying instances to see valid scenarios

2. **Provide feedback in one of three ways:**

   **Option A: Additional scenarios to check**
   ```
   > Please check: Member with overdue books tries to reserve
   > Expected: Reservation should be blocked
   >
   > Also check: Member reserves while membership is expiring
   > Expected: System should verify membership validity
   > END
   ```

   **Option B: General feedback**
   ```
   > The model looks good overall.
   > Please tighten the constraint on maximum reservations.
   > I think the overdue handling needs refinement.
   > END
   ```

   **Option C: Satisfaction (when everything looks good)**
   ```
   > SATISFIED
   > END
   ```

3. **System responds:**
   ```
   User feedback received!
   ```

   Or, if you typed SATISFIED:
   ```
   ======================================================================
   User is satisfied with results!
   ======================================================================

   WORKFLOW COMPLETED SUCCESSFULLY!
   ```

**If you don't respond within 5 minutes:**
```
======================================================================
TIMEOUT: No input received within time limit
Proceeding with assumption: No feedback from user
======================================================================

No user feedback provided (timeout)
Proceeding to next iteration with agent-suggested improvements only
```

---

## Timeout Behavior

### The 5-Minute Window

**Timeout setting:** You have **5 minutes (300 seconds)** to respond to each prompt.

**How it works:**
- Timer starts when prompt is displayed
- System checks for your input continuously
- Countdown updates displayed periodically
- After 5 minutes, system automatically proceeds

**Timeout display:**
```
Your response (type your feedback, then 'END' on a new line):
Timeout: 300 seconds (5 minutes)

_
```

**What happens on timeout:**
1. System shows timeout message
2. Workflow continues automatically with no user input
3. Agents use their own suggestions
4. You can provide input at the next interaction point
5. All progress is saved

### Timeout Recovery

**If you need more than 5 minutes:**

**Option 1: Provide quick acknowledgment**
```
> Reviewing - will provide details in next iteration
> END
```

**Option 2: Let timeout occur**
- Review output files at your own pace
- System continues with agent suggestions
- Provide detailed feedback in next iteration

**Option 3: Interrupt and review offline**
- Press `Ctrl+C` to stop the workflow
- Review all outputs: `ReqsDoc/`, `AlloyModels/`, `AnalyzerOutput/`
- All progress is automatically saved
- Note: Resume functionality is manual (future enhancement)

## Logging and Audit Trail

### Session Logs

**Location:** `outputlog/MMDDYY.log`

**Filename format:** Date-based (e.g., `040626.log` for April 6, 2026)

**Contents:**
- All terminal output (prompts, messages, status)
- **Full prompts** (detailed versions with complete context)
- **Complete user inputs** (everything you typed)
- File update notifications
- Timestamps for all events
- Session start/end markers

### Log Format

```
================================================================================
SESSION START: 2026-04-06 15:30:00
================================================================================

[2026-04-06 15:30:00] ======================================================================
[2026-04-06 15:30:00] AutoRE - Automated Requirement Engineering System
[2026-04-06 15:30:00] ======================================================================

[2026-04-06 15:30:05] Step 1: Analyzing initial requirements...

--- USER PROMPT (FULL) ---
CLARIFICATION REQUEST - Iteration 0

The Requirement Engineer has analyzed your requirements and created a structured
requirements document. Please review the document and provide clarification on any
assumptions or ambiguities.

Requirements document: ReqsDoc/Reqs_0.txt

Please review the document and provide:
- Clarifications on any assumptions
- Corrections to any misunderstandings
- Additional context or constraints

You can also confirm if the requirements are correctly understood.
--- END PROMPT ---

[2026-04-06 15:30:45] --- USER INPUT ---
Members cannot reserve books they currently have borrowed.
Members can only reserve books that are checked out by others.
If membership expires, all reservations are cancelled.
Reserved books must be picked up within 3 days.
[2026-04-06 15:30:45] --- END INPUT ---

[2026-04-06 15:30:46] User clarification received!

...

================================================================================
SESSION END: 2026-04-06 16:15:30
================================================================================
```

### Benefits of Logging

1. **Complete audit trail** - Review all interactions later
2. **Full context** - See detailed prompts that may be truncated in terminal
3. **Debugging** - Understand what happened during execution
4. **Collaboration** - Share logs with team members
5. **Learning** - Review past decisions and feedback

## Common Scenarios

### Scenario 1: Quick Response (< 1 minute)

**Timeline:**
1. Prompt appears at 2:00:00 PM
2. You read it immediately
3. You type response and END
4. You press Enter at 2:00:30 PM
5. System processes instantly

**Total time:** ~30 seconds

---

### Scenario 2: Thoughtful Response (2-4 minutes)

**Timeline:**
1. Prompt appears at 2:00:00 PM
2. You review the requirements file
3. You think through implications
4. You type detailed response
5. You submit at 2:03:30 PM

**Result:** ✓ Accepted (within 5-minute window)

---

### Scenario 3: Timeout (> 5 minutes)

**Timeline:**
1. Prompt appears at 2:00:00 PM
2. You're away from computer
3. Timeout occurs at 2:05:00 PM
4. System continues automatically

**Result:** System proceeds without input, you can provide feedback in next iteration

---

### Scenario 4: Interrupted by Meeting

**Approach A: Quick response before leaving**
```
> Acknowledged - reviewing offline, will provide details next iteration
> END
```

**Approach B: Let it timeout**
- System continues
- Review files when you return
- Provide input in next iteration

**Approach C: Interrupt workflow**
- Press `Ctrl+C`
- Review offline at your pace
- Progress is saved

---

## File References During Interaction

While interacting via CLI, you'll want to view various files:

### Requirements Documents
**Location:** `ReqsDoc/Reqs_[iteration].txt`

**Contains:**
- Structured requirements
- System overview
- Assumptions and constraints
- Functional requirements

**When to view:**
- Before responding to clarification requests
- To understand current requirement state

---

### Alloy Models
**Location:** `AlloyModels/AlloyModel__[iteration].als`

**Contains:**
- Formal Alloy specifications
- Signatures (entities/concepts)
- Facts (constraints)
- Predicates (scenarios)
- Assertions (properties to verify)

**When to view:**
- To understand the formal model
- To check if requirements are accurately captured
- To review what's being verified

---

### Analyzer Output
**Location:** `AnalyzerOutput/[iteration]/`

**Contains JSON files with:**
- Syntax errors (if any)
- Counterexamples (failed assertions)
- Satisfying instances (valid scenarios)

**When to view:**
- Before providing evaluation feedback
- To understand what passed/failed verification
- To identify edge cases

---

### Memory Files
**Location:** `memory/`

**Files:**
- `RE_memory.json` - Requirement Engineer's memory
- `Evaluator_memory.json` - Evaluator's memory

**Contains:**
- Iteration history
- Lessons learned
- Detailed tracking

**When to view:**
- To understand agent learning
- To see what issues were previously addressed
- For debugging persistent problems

---

## Tips for Effective Interaction

### 1. Respond Within 5 Minutes

The timeout is there to keep the workflow moving:
- Read prompts quickly
- Provide focused responses
- You'll have multiple opportunities to refine

### 2. Be Specific and Concise

Good example:
```
> Members cannot reserve books they already borrowed
> Reservations expire after 3 days
> Maximum 2 active reservations per member
> END
```

Less effective:
```
> I think the reservation system should work properly and handle edge cases
> END
```

### 3. Review Files Before Responding

Open relevant files in another terminal or editor:
```bash
# In another terminal
cat ReqsDoc/Reqs_0.txt
cat AlloyModels/AlloyModel__0.als
ls -la AnalyzerOutput/1/
```

### 4. Use END Consistently

Remember:
- Multi-line input **requires** `END` on a new line
- System waits for `END` before processing
- Without `END`, you'll timeout even if you typed feedback

### 5. Provide Scenarios Clearly

When requesting additional checks:
```
> Scenario: Member with overdue book
> Check: Cannot reserve additional books
> Expected: Reservation rejected with error
>
> Scenario: Return clears overdue
> Check: Member can immediately reserve after return
> Expected: Overdue status cleared
> END
```

### 6. Use SATISFIED Wisely

Only indicate satisfaction when:
- ✓ No syntax errors
- ✓ No counterexamples (or counterexamples are expected)
- ✓ Satisfying instances exist
- ✓ All your scenarios have been checked
- ✓ Requirements are clear and complete

### 7. Monitor Progress

Watch terminal output:
- File update notifications
- Analysis results
- Iteration progress
- Status messages

### 8. Leverage the Log Files

The `outputlog/MMDDYY.log` file is your friend:
- Full context when terminal is truncated
- Complete history of decisions
- Timestamps for everything
- Audit trail for team collaboration

## Troubleshooting

### Input Not Being Detected

**Problem:** You typed feedback but system says "TIMEOUT"

**Likely cause:** Forgot to type `END` on a new line

**Solution:**
- Always end multi-line input with `END`
- `END` must be on its own line
- Press Enter after `END`

---

### System Timed Out Too Quickly

**Problem:** Feel like you didn't have enough time

**Reality check:** 5 minutes is 300 seconds
- Shows countdown
- Sufficient for most responses

**Solutions:**
1. Provide quick acknowledgment within 5 minutes
2. Give brief feedback now, details in next iteration
3. Let timeout occur and review files offline

---

### Want to Change Response After Submitting

**Problem:** Pressed Enter and realized you wanted to add more

**Reality:** Response already submitted

**Solution:**
- Wait for next interaction point
- Provide additional input then
- System has multiple iterations for refinement

---

### Terminal Output Is Too Long

**Problem:** Important information scrolled off screen

**Solution:** Check the log file
```bash
tail -f outputlog/[MMDDYY].log
```

Or review the full log:
```bash
less outputlog/[MMDDYY].log
```

---

### Accidentally Pressed Ctrl+C

**Result:** Workflow interrupted

**Impact:** All progress is saved:
- Requirements in `ReqsDoc/`
- Models in `AlloyModels/`
- Results in `AnalyzerOutput/`
- Memory in `memory/`

**Recovery:**
- Review output files
- Note: Automatic resume not yet implemented (future enhancement)

---

## Quick Reference

| What System Shows | What You Do | How To End |
|-------------------|-------------|------------|
| "Your response (type your feedback, then 'END' on a new line):" | Type multiple lines of feedback | Type `END` on new line |
| "Your response (press Enter when done):" | Type single line | Press Enter |
| "Timeout: 300 seconds (5 minutes)" | Respond within 5 minutes | - |
| "TIMEOUT: No input received..." | System continues automatically | Nothing - system proceeds |

## Summary

**Key Points:**

✓ **CLI-based** - Type directly in terminal, no files needed
✓ **Multi-line input** - End with `END` on a new line
✓ **5-minute timeout** - Auto-proceed if no response
✓ **Fully logged** - Complete audit trail in `outputlog/MMDDYY.log`
✓ **File references** - View detailed files in separate terminal
✓ **Concise terminal prompts** - Full details in log file
✓ **Multiple iterations** - Don't worry about perfect responses
✓ **Progress saved** - Can interrupt with Ctrl+C safely

**The CLI interaction keeps communication simple and immediate while logging everything for reference.**
