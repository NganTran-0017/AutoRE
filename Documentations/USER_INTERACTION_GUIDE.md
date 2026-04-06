re# User Interaction Guide

## Overview

AutoRE uses a **file-based interaction system** that allows asynchronous communication between the agents and the user. The system waits **5 minutes** for your response at each interaction point. If no response is provided within 5 minutes, the system automatically proceeds with the assumption that you have no feedback.

## How User Interaction Works

### The File-Based Communication System

The system uses two primary files for user interaction:

1. **`user_prompt.txt`** - **READ THIS**: System writes prompts and questions here
2. **`user_feedback.txt`** - **WRITE THIS**: You write your responses here

### Interaction Flow

```
┌─────────────────┐
│  System/Agents  │
└────────┬────────┘
         │
         │ 1. Writes prompt
         ▼
  ┌──────────────────┐
  │ user_prompt.txt  │ ◄── YOU READ THIS
  └──────────────────┘
         │
         │ 2. You review
         ▼
    ┌──────────┐
    │   You    │
    └─────┬────┘
          │
          │ 3. You write response
          ▼
  ┌──────────────────┐
  │user_feedback.txt │ ◄── YOU WRITE THIS
  └──────────────────┘
          │
          │ 4. System reads
          ▼
   ┌─────────────────┐
   │  System/Agents  │
   │   (continues)   │
   └─────────────────┘
```

## Step-by-Step: What Happens at Each Interaction Point

### Interaction Point 1: Initial Clarification (Steps 1-2)

**When:** After the RE agent analyzes your initial requirements

**System does:**
1. RE agent analyzes your input file
2. Creates structured requirements document (`ReqsDoc/Reqs_0.txt`)
3. Identifies assumptions needing clarification
4. **WRITES** a prompt to `user_prompt.txt`
5. **WAITS** for 5 minutes (pauses execution)
6. Terminal shows:
   ```
   ======================================================================
   USER INPUT REQUESTED
   ======================================================================
   A prompt has been written to: user_prompt.txt
   Please review the prompt and provide your response in: user_feedback.txt
   ======================================================================

   Waiting for user feedback...
   Wait started at: 2026-04-06 15:30:00
   Timeout: 300 seconds (5 minutes)
   Checking for feedback file: user_feedback.txt

   Still waiting... 270 seconds remaining (4 min 30 sec)
   Still waiting... 240 seconds remaining (4 min 0 sec)
   ...
   ```

**You should:**
1. **READ** `user_prompt.txt` - contains assumptions and questions
2. Think about your answers
3. **CREATE** `user_feedback.txt` (new file)
4. **WRITE** your clarifications in that file
5. **SAVE** the file

**System then (if you provide feedback within 5 minutes):**
1. Detects that `user_feedback.txt` exists and has content
2. Reads your feedback
3. Archives it to `archived_user_feedback.txt`
4. Deletes `user_feedback.txt` (so it's ready for next time)
5. Shows: "User feedback received at: [timestamp]"
6. **CONTINUES** to next step

**System then (if timeout - no feedback after 5 minutes):**
1. Shows:
   ```
   ======================================================================
   WAIT TIME EXPIRED
   ======================================================================
   Wait ended at: 2026-04-06 15:35:00
   No user feedback received within 300 seconds (5 minutes)
   Proceeding with assumption: No feedback from user
   ======================================================================

   ======================================================================
   No user clarification provided (timeout)
   Proceeding with current understanding of requirements
   ======================================================================
   ```
2. **CONTINUES** to next step without user input

---

### Interaction Point 2: Evaluation Review (Steps 5-6)

**When:** After each Alloy Analyzer verification iteration

**System does:**
1. Evaluator runs Alloy Analyzer on the model
2. Interprets results (errors, counterexamples, instances)
3. Generates feedback and improvement suggestions
4. **WRITES** evaluation summary to `user_prompt.txt`
5. **WAITS** for 5 minutes (pauses execution)
6. Terminal shows:
   ```
   ======================================================================
   USER INPUT REQUESTED
   ======================================================================
   A prompt has been written to: user_prompt.txt
   Please review the prompt and provide your response in: user_feedback.txt
   ======================================================================

   Waiting for user feedback...
   Wait started at: 2026-04-06 16:00:00
   Timeout: 300 seconds (5 minutes)
   Checking for feedback file: user_feedback.txt

   Still waiting... 270 seconds remaining (4 min 30 sec)
   Still waiting... 240 seconds remaining (4 min 0 sec)
   ...
   ```

**You should:**
1. **READ** `user_prompt.txt` - contains:
   - Analysis results
   - Issues found
   - Suggested improvements
   - Questions about additional scenarios
2. Review the analysis carefully
3. **CREATE** `user_feedback.txt`
4. **WRITE** your response:
   - Feedback on suggestions
   - Additional scenarios to check
   - OR simply: `SATISFIED` (if done)
5. **SAVE** the file

**System then (if you provide feedback within 5 minutes):**
1. Reads your feedback
2. Archives it
3. Deletes `user_feedback.txt`
4. Shows: "User feedback received at: [timestamp]"
5. If you wrote "SATISFIED" → workflow completes
6. Otherwise → continues with updates and next iteration

**System then (if timeout - no feedback after 5 minutes):**
1. Shows:
   ```
   ======================================================================
   WAIT TIME EXPIRED
   ======================================================================
   Wait ended at: 2026-04-06 16:05:00
   No user feedback received within 300 seconds (5 minutes)
   Proceeding with assumption: No feedback from user
   ======================================================================

   ======================================================================
   No user feedback provided (timeout)
   Proceeding to next iteration with agent-suggested improvements only
   ======================================================================
   ```
2. **CONTINUES** to next iteration without user input

---

## Detailed File Descriptions

### `user_prompt.txt` (System → You)

**Purpose:** System communicates with you

**Created by:** The agents (via UserInteraction class)

**When:** At each interaction point

**Contains:**
- Structured prompt with sections
- Questions requiring your input
- Context about current iteration
- Clear instructions on what to do next

**Example content:**
```
======================================================================
CLARIFICATION REQUEST - Iteration 0
======================================================================

REQUIREMENTS SUMMARY:
Enhanced Library Borrowing System with reservations and overdue management

ASSUMPTIONS REQUIRING CLARIFICATION:
1. Can a member reserve a book they currently have borrowed?
2. Can members reserve books that are currently available?
3. What happens to reservations when membership expires?
4. Should there be a time limit for picking up reserved books?

INSTRUCTIONS:
Please review the above assumptions and provide clarification for each point.
Your feedback will help refine the requirements and create a more accurate model.

Provide your clarification in the file: user_feedback.txt

Format your response as clear, structured text.
======================================================================
```

**What to do:** Read it, then respond in `user_feedback.txt`

---

### `user_feedback.txt` (You → System)

**Purpose:** You communicate with the system

**Created by:** YOU (manually)

**When:** In response to `user_prompt.txt`

**Contains:** Your answers, clarifications, or feedback

**Format options:**

**For clarifications:**
```
1. Members cannot reserve books they currently have borrowed - that would be redundant.
2. Members can only reserve books that are currently borrowed by others.
3. All reservations are cancelled if membership expires.
4. Yes, reserved books must be picked up within 3 days or reservation is cancelled.

Additional context:
- Priority should be given to members who made reservations earlier
- Reservation queue should be strictly FIFO
```

**For evaluation feedback:**
```
The analysis looks good. I agree with the suggested improvements.

Additional scenarios to check:

1. Scenario: Member with multiple overdue books
   Check: Verify that having multiple overdue books doesn't allow any borrowing
   Expected: Should be completely blocked from new borrows and reservations

2. Scenario: Book return clears overdue status
   Check: When an overdue book is returned, member can immediately borrow/reserve again
   Expected: Overdue status should be cleared immediately upon return

I'd like to see these checked before finalizing.
```

**To indicate satisfaction:**
```
SATISFIED
```

**Important notes:**
- File must have actual content (not empty)
- System checks for this file every 2 seconds
- Once read, system automatically deletes it and archives content

---

### `archived_user_feedback.txt` (Archive)

**Purpose:** Permanent record of all your feedback

**Created by:** System (automatically)

**Contains:** All your past feedback with timestamps

**Format:**
```
======================================================================
Feedback at 2026-04-06 15:30:22
======================================================================
[Your feedback from that time]
======================================================================

======================================================================
Feedback at 2026-04-06 15:45:18
======================================================================
[Your next feedback]
======================================================================
```

**What to do:** Nothing - this is just for reference/audit trail

---

## Timing: How Does Waiting Work?

### The Waiting Mechanism

**Timeout setting**: The system waits **5 minutes (300 seconds)** for your response.

**Implementation details** (from `src/utils/user_interaction.py`):

```python
def _wait_for_feedback(self, timeout: int = 300):
    """Wait for user feedback file to be created."""
    start_time = time.time()
    start_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    print(f"Waiting for user feedback...")
    print(f"Wait started at: {start_timestamp}")
    print(f"Timeout: {timeout} seconds ({timeout//60} minutes)")

    while True:
        current_time = time.time()
        elapsed = current_time - start_time

        # Print periodic updates every 30 seconds
        if current_time - last_update >= 30:
            remaining = timeout - elapsed
            print(f"Still waiting... {int(remaining)} seconds remaining")

        # Check if file exists
        if self.feedback_file.exists():
            # Read and process feedback
            return content

        # Check timeout - proceed without feedback after 5 minutes
        if timeout > 0 and elapsed > timeout:
            print("WAIT TIME EXPIRED")
            print("Proceeding with assumption: No feedback from user")
            return None

        # Wait 2 seconds before checking again
        time.sleep(2)
```

### What This Means for You

**✓ 5-MINUTE WINDOW** (300 seconds)
- You have 5 minutes to provide feedback at each interaction point
- System checks every 2 seconds for your feedback file
- Progress updates shown every 30 seconds
- Clear start and end timestamps displayed

**✓ AUTOMATIC TIMEOUT HANDLING**
- After 5 minutes without feedback, system automatically continues
- Proceeds with assumption: No feedback from user
- System uses only agent-generated suggestions
- No data loss - all progress is saved

**✓ FLEXIBLE RESPONSE TIME**
- 5 minutes is usually enough to read prompt and provide quick response
- For longer reviews, respond within 5 minutes to acknowledge
- Can provide detailed feedback even if brief
- System shows countdown so you know remaining time

### What If It Takes You A While?

**Scenario 1: You need 2-3 minutes to think**
- ✓ No problem - you have 5 minutes
- Read prompt carefully
- Respond within the 5-minute window

**Scenario 2: You need more than 5 minutes**
- ✗ System will timeout after 5 minutes
- System proceeds with no feedback
- Workflow continues with agent suggestions only
- **Workaround**: Provide quick initial response within 5 minutes, then you can influence later iterations

**Scenario 3: You want to review with team (30+ minutes)**
- Option 1: Let timeout occur, review outputs in files, provide feedback in next iteration
- Option 2: Interrupt process (Ctrl+C), review files offline, then restart
- All progress is saved in `ReqsDoc/`, `AlloyModels/`, `AnalyzerOutput/`, `memory/`

**Scenario 4: You're not at computer when prompt arrives**
- System will timeout after 5 minutes
- Workflow continues automatically
- You can review all outputs in directories later
- Next iteration will ask for feedback again

### Can You Interrupt and Resume?

**Current implementation:** System state is saved progressively

**To interrupt:**
1. Press `Ctrl+C` to stop the process
2. System will show: "Workflow interrupted by user."
3. All progress is saved:
   - Requirements documents in `ReqsDoc/`
   - Alloy models in `AlloyModels/`
   - Analyzer outputs in `AnalyzerOutput/`
   - Agent memory in `memory/`

**To resume:**
Currently, you would need to:
1. Review the last outputs
2. Continue manually from where you left off
3. OR (future enhancement): Add resume functionality

**Note:** For future enhancement, we could add a `--resume` flag to continue from last state.

## Common Scenarios

### Scenario: Quick Response (< 1 minute)

1. System writes `user_prompt.txt`
2. You immediately read it
3. You create `user_feedback.txt` with response
4. Within 2 seconds, system detects file
5. System reads, archives, continues
6. **Total wait: ~2-5 seconds**

---

### Scenario: Thoughtful Response (2-4 minutes)

1. System writes `user_prompt.txt` at 2:00 PM
2. Terminal shows "Waiting for user feedback..." with 5-minute countdown
3. You read the prompt carefully
4. You think through implications
5. You write response
6. You save `user_feedback.txt` at 2:03 PM (3 minutes later)
7. Within 2 seconds, system detects file
8. System continues
9. **Total wait: ~3 minutes** - within 5-minute window!

---

### Scenario: Need More Time (Response After Timeout)

1. System writes prompt at 2:00 PM
2. Terminal shows "Waiting for user feedback..."
3. You're in a meeting and don't see it
4. At 2:05 PM, system timeout occurs
5. Terminal shows "WAIT TIME EXPIRED"
6. System proceeds with no feedback
7. Workflow continues automatically with agent suggestions
8. Later, you can review outputs in `ReqsDoc/`, `AlloyModels/`, `AnalyzerOutput/`
9. **Result:** System continues, you provide input in next iteration

---

### Scenario: Longer Review Needed

**Option A: Provide Quick Acknowledgment**
1. System writes prompt and starts 5-minute timer
2. You read it quickly
3. Within 5 minutes, create `user_feedback.txt` with:
   ```
   Acknowledged. Reviewing in detail.
   Will provide detailed feedback in next iteration.
   ```
4. System continues, you review thoroughly offline
5. Provide detailed input at next interaction point

**Option B: Let Timeout Occur**
1. System times out after 5 minutes
2. Review all outputs in directories at your pace
3. System continues with agent suggestions
4. Provide your input in subsequent iterations

**Option C: Interrupt and Resume**
1. Press `Ctrl+C` to stop workflow
2. Review files offline: `ReqsDoc/`, `AlloyModels/`, `AnalyzerOutput/`
3. Discuss with team over days if needed
4. Note: Manual resume not yet automated (future enhancement)

---

## File Location Summary

All interaction files are in the **project root** directory:

```
/home/nati/autoRE/
├── user_prompt.txt           ← System writes, you read
├── user_feedback.txt         ← You create and write
├── archived_user_feedback.txt ← System maintains
├── ReqsDoc/                  ← Reference: requirement versions
├── AlloyModels/              ← Reference: model versions
└── AnalyzerOutput/           ← Reference: verification results
```

## Troubleshooting

### System times out after 5 minutes

**This is normal behavior!**

The system waits 5 minutes for your feedback, then automatically proceeds.

**What happens:**
- After 5 minutes, system shows "WAIT TIME EXPIRED"
- Workflow continues with agent suggestions only
- All progress is saved
- You can provide feedback in the next iteration

**If you want to provide feedback:**
- You must create `user_feedback.txt` within the 5-minute window
- Check that file is in `/home/nati/autoRE/user_feedback.txt`
- Make sure file has content (not empty)
- Save the file before timeout

---

### System doesn't detect my feedback

**Problem:** File might be empty or in wrong location

**Check:**
```bash
# From project directory
ls -la user_feedback.txt     # Should exist
cat user_feedback.txt        # Should show your content
```

**Solution:**
1. Ensure file is saved with content
2. Check file permissions (should be readable)
3. Wait 2 seconds for system to detect

---

### I want to start over / provide different feedback

**If you haven't saved yet:**
- Just edit `user_feedback.txt` before saving

**If system already read it:**
- System has moved on to next step
- Your feedback is archived in `archived_user_feedback.txt`
- Wait for next interaction point to provide clarification

---

### Can I see what the agents are doing?

**Yes!** Check these files while system is working:

**Current iteration status:**
```bash
# Latest requirements
ls -lt ReqsDoc/*.txt | head -1

# Latest model
ls -lt AlloyModels/*.als | head -1

# Latest analyzer output
ls -lt AnalyzerOutput/

# Agent memories
cat memory/RE_memory.json
cat memory/Evaluator_memory.json
```

---

## Quick Reference Card

| When System Shows | You Should | File to Use |
|-------------------|------------|-------------|
| "USER INPUT REQUESTED" | Read the prompt | `user_prompt.txt` |
| "Waiting for user feedback..." | Write your response | `user_feedback.txt` (create it) |
| "User feedback received!" | Nothing - system continues | - |
| Normal processing | Wait or check progress | Check `ReqsDoc/`, `AlloyModels/`, `memory/` |

## Best Practices

1. **Respond Within 5 Minutes**
   - System timeout is 5 minutes
   - Read `user_prompt.txt` quickly
   - If need more time, provide brief acknowledgment

2. **Be Specific and Concise**
   - Provide clear, focused responses
   - Answer all questions in the prompt
   - Can be brief - you'll have more chances to provide input

3. **Use Timeout Strategically**
   - If unsure, let timeout occur and review files offline
   - Provide feedback in subsequent iterations
   - System continues productively even without immediate input

4. **Monitor Progress**
   - Watch terminal for countdown messages
   - Check remaining time (updates every 30 seconds)
   - Know when timeout is approaching

5. **Use SATISFIED Wisely**
   - Only when truly satisfied with results
   - Review all outputs before declaring satisfaction
   - Remember: iteration is okay!

6. **Keep Archive**
   - `archived_user_feedback.txt` is your record
   - Useful for reviewing what was decided
   - Can help explain final requirements

## Summary

**Key Points:**
- ✓ File-based system: `user_prompt.txt` ← READ, `user_feedback.txt` ← WRITE
- ✓ System waits **5 minutes** for your response
- ✓ Progress updates shown every 30 seconds
- ✓ After timeout, system proceeds with no feedback
- ✓ System checks every 2 seconds for your feedback file
- ✓ All feedback is automatically archived
- ✓ Can interrupt with Ctrl+C if needed
- ✓ Progress is always saved
- ✓ Timeout is normal - provides feedback in next iteration

**The 5-minute window keeps the workflow moving while giving you time to respond.**
