# CLI Interaction Usage Guide

## Overview

AutoRE uses **CLI-based interaction** for real-time communication with users. All interactions are logged to `outputlog/MMDDYY.log` files.

## How It Works

### User Input

When the system needs your input, you'll see a prompt in the terminal like this:

```
======================================================================
CLARIFICATION REQUEST - Iteration 0

Requirements document created: ReqsDoc/Reqs_0.txt

Please review and provide clarification on assumptions and requirements.
Type your feedback below (end with 'END' on a new line):
======================================================================

Your response (type your feedback, then 'END' on a new line):
Timeout: 300 seconds (5 minutes)

_
```

### Providing Input

**Multi-line Input:**
1. Type your response (can be multiple lines)
2. Press Enter after each line
3. Type `END` on a new line when finished
4. Press Enter

**Example:**
```
> The member cannot reserve books they currently have borrowed.
> Members can only reserve books that are checked out by others.
> If membership expires, all reservations are cancelled.
> END
```

### Timeout Behavior

- **5-minute window**: You have 5 minutes to start/finish your response
- **Countdown**: System shows remaining time
- **Auto-proceed**: After timeout, system continues with no feedback
- **Recovery**: You can provide input in the next iteration

### Terminal Output

**Concise prompts displayed in terminal:**
- Brief summary of what's needed
- File references for detailed information
- Clear instructions

**Full prompts logged to file:**
- Complete details saved to `outputlog/MMDDYY.log`
- Review log file for full context

## Example Interaction

### Step 1: Initial Clarification

```
Step 1: Analyzing initial requirements...
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

> Members cannot reserve books they already have borrowed.
> Only books currently checked out can be reserved.
> Reservations are cancelled if membership expires.
> Reserved books must be picked up within 3 days.
> END

[2026-04-06 15:30:45] User clarification received!
```

### Step 2: Evaluation Feedback

```
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

> Please check scenario: Member tries to reserve while having overdue books
> Expected: Reservation should be rejected
> END

[2026-04-06 15:32:10] User feedback received!
```

### Step 3: Satisfaction

```
======================================================================
EVALUATION REVIEW - Iteration 3
======================================================================

✓ Syntax: OK
✓ Counterexamples: None
✓ Instances: Valid scenarios exist

Results in: AnalyzerOutput/3/

Provide feedback, additional scenarios, or type 'SATISFIED':
(End with 'END' on a new line)
======================================================================

Your response (type your feedback, then 'END' on a new line):
Timeout: 300 seconds (5 minutes)

> SATISFIED
> END

======================================================================
User is satisfied with results!
======================================================================
```

## File Updates

When files are updated, you'll see notifications like:

```
Requirements document created: ReqsDoc/Reqs_0.txt
Alloy model created: AlloyModels/AlloyModel__0.als
Analysis results saved to: AnalyzerOutput/1/
Requirements updated: ReqsDoc/Reqs_1.txt
```

**To view these files:**
- Open them in a separate terminal or editor
- Files are in directories relative to project root
- All updates are also logged to `outputlog/MMDDYY.log`

## Log Files

### Location

`outputlog/MMDDYY.log` where MMDDYY is the current date

Example: `outputlog/040626.log` for April 6, 2026

### Contents

The log file contains:
- All terminal output (prompts, messages, status updates)
- **Full prompts** (detailed versions)
- **User inputs** (complete responses)
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
[Full detailed prompt text here]
--- END PROMPT ---

[2026-04-06 15:30:45] --- USER INPUT ---
[2026-04-06 15:30:45] Members cannot reserve books they already have borrowed.
[2026-04-06 15:30:45] Only books currently checked out can be reserved.
...
[2026-04-06 15:30:45] --- END INPUT ---

[2026-04-06 15:30:46] User clarification received!

...

================================================================================
SESSION END: 2026-04-06 16:15:30
================================================================================
```

## Tips

### For Quick Responses

```
> Brief clarification here
> END
```

### For Detailed Feedback

```
> Assumption 1: Clarification for first point
> Additional context about first point
>
> Assumption 2: Clarification for second point
> More details here
>
> Additional constraints:
> - Constraint 1
> - Constraint 2
> END
```

### For Additional Scenarios

```
> Scenario: Member with multiple overdue books
> Check: Cannot borrow or reserve
> Expected: All operations blocked
>
> Scenario: Book return clears overdue
> Check: Member can immediately borrow again
> Expected: Overdue status cleared on return
> END
```

### To Express Satisfaction

```
> SATISFIED
> END
```

## Troubleshooting

### Input Not Detected

**Problem:** Typed response but system says "TIMEOUT"

**Cause:** Didn't type `END` on a new line

**Solution:**
- Always end with `END` on its own line
- Press Enter after `END`

### Timeout Occurred

**Problem:** Didn't respond within 5 minutes

**Effect:** System proceeds automatically

**Recovery:**
- Review files: `ReqsDoc/`, `AlloyModels/`, `AnalyzerOutput/`
- Provide input in next iteration
- System will ask again at next checkpoint

### Want to See Full Prompt

**Solution:**
- Check `outputlog/MMDDYY.log`
- Full prompts are always logged there
- Search for "USER PROMPT (FULL)"

### Review Previous Inputs

**Solution:**
- Open `outputlog/MMDDYY.log`
- Search for "USER INPUT"
- All your responses are logged with timestamps

## Summary

**Key Points:**
- ✓ CLI-based: Type directly in terminal
- ✓ Multi-line: End with `END` on new line
- ✓ 5-minute timeout: Auto-proceed if no response
- ✓ All logged: Full history in `outputlog/MMDDYY.log`
- ✓ File references: View detailed files separately
- ✓ Concise terminal: Full details in log

**The CLI mode keeps interaction simple while logging everything for reference.**
