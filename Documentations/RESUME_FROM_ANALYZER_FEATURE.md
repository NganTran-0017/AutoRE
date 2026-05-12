# Resume from Analyzer Feature

## Overview
This feature allows you to resume the AutoRE workflow from an existing Alloy model and requirements document, skipping the initial analysis and model building steps (Steps 1-3) and jumping directly to the Alloy Analyzer evaluation step (Step 4).

## Use Cases
- **Recovery from interruption**: Resume after workflow was stopped or crashed
- **Iterative refinement**: Continue refinement from a specific point
- **Manual edits**: Make manual changes to model/requirements and continue verification
- **Testing**: Quickly test evaluation logic on existing artifacts

## Usage

### Basic Resume (from latest iteration)
```bash
python main.py example_input.txt --resume
```

This will:
1. Find the latest common iteration between requirements and models
2. Load both files from that iteration
3. Set iteration counter to continue from that point
4. Load existing memory and learning
5. Jump directly to Step 4 (Evaluate Model)

### Resume from Specific Iteration
```bash
python main.py example_input.txt --resume --resume-iteration 5
```

This will resume from iteration 5 specifically.

### List Available Iterations
```bash
python main.py --list-iterations
```

This will display:
- All available iterations
- Which iterations have requirements
- Which iterations have models
- Which iterations are complete (both files exist)
- Latest complete iteration
- Example commands to resume

Example output:
```
================================================================================
Available Iterations
================================================================================

Total iterations found: 7
Complete iterations (both requirements and model): 6

✓ Latest complete iteration: 6

Iteration Details:
--------------------------------------------------------------------------------
Iteration    Requirements         Model                Status              
--------------------------------------------------------------------------------
0            ✓                    ✓                    Complete            
1            ✓                    ✓                    Complete            
2            ✓                    ✓                    Complete            
3            ✓                    ✓                    Complete            
4            ✓                    ✓                    Complete            
5            ✓                    ✓                    Complete            
6            ✓                    ✓                    Complete            
7            ✓                    ✗                    Incomplete          
--------------------------------------------------------------------------------

To resume from latest: python main.py --resume
To resume from specific iteration: python main.py --resume --resume-iteration N
```

## Implementation Details

### File Detection
- Uses `FileManager.get_all_requirement_versions()` to find available requirement files
- Uses `FileManager.get_all_model_versions()` to find available model files
- Finds the latest common iteration where both files exist
- Validates that target iteration exists before resuming

### Iteration Handling
- When resuming from iteration N, the counter is set to N
- The next refinement loop will start at iteration N and run Step 4
- After feedback, the counter increments to N+1 for updates
- This means: **resume continues from the loaded iteration, not as a new iteration**

### Memory & Context
- Loads existing `SharedRuntimeContext` state if available
- Preserves all learning and memory from previous session
- Maintains full continuity with previous workflow execution

### Interactive Mode
- Remains fully interactive after resuming
- Still prompts for user feedback in Steps 5-6
- User can provide additional guidance as normal

## Command-Line Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--resume` | boolean | False | Enable resume mode |
| `--resume-iteration` | int | None | Specific iteration to resume from (None = latest) |
| `--list-iterations` | boolean | False | List available iterations and exit |

## File Requirements

For resume to work, the following files must exist:
- `output/requirements/Reqs_N.txt` - Requirements for iteration N
- `output/models/AlloyModel__N.als` - Alloy model for iteration N

Optional files (loaded if available):
- `output/feedback/Feedback_N.txt` - Feedback from iteration N

## Error Handling

The feature validates:
1. ✓ At least one requirement version exists
2. ✓ At least one model version exists
3. ✓ Target iteration exists in both requirements and models
4. ✓ Files can be loaded successfully

If validation fails, a clear error message indicates what's missing.

## Example Workflow

### Scenario 1: Resume after interruption
```bash
# Initial run (interrupted at iteration 7)
python main.py requirements.txt --max-iterations 10

# Resume from where it left off
python main.py requirements.txt --resume
# → Resumes from iteration 7
```

### Scenario 2: Manual model edits
```bash
# Run to iteration 3
python main.py requirements.txt --max-iterations 3

# Manually edit output/models/AlloyModel__3.als

# Resume from edited model
python main.py requirements.txt --resume --resume-iteration 3
# → Re-evaluates iteration 3 with manual changes
```

### Scenario 3: Retry specific iteration
```bash
# Had issues at iteration 5, want to retry with different feedback
python main.py requirements.txt --resume --resume-iteration 5
# → Restarts from iteration 5
```

### Scenario 4: Check available iterations before resuming
```bash
# List all available iterations
python main.py --list-iterations

# Review output, then resume from desired iteration
python main.py requirements.txt --resume --resume-iteration 3
```

## Code Changes Summary

### Modified Files
1. **main.py**
   - Added `--resume` flag
   - Added `--resume-iteration` flag
   - Added `--list-iterations` flag
   - Implemented iteration listing functionality
   - Pass resume parameters to `workflow.run()`

2. **src/workflow.py**
   - Updated `run()` method signature to accept resume parameters
   - Added `_resume_from_analyzer()` method
   - Modified refinement loop to start from `context.iteration.current`

### Minimum Changes Principle
The implementation follows the minimum changes principle:
- No changes to existing workflow steps
- No changes to action classes
- No changes to context or artifact management
- Only added new optional parameters and one new method
- Existing functionality remains 100% unchanged

## Testing

To test the resume feature:

1. Run a normal workflow for a few iterations
2. Stop it (Ctrl+C or let it complete)
3. Run with `--resume` flag
4. Verify it continues from the correct iteration
5. Check that memory/learning is preserved
6. Verify interactive feedback still works

## Future Enhancements

Potential future improvements (not implemented yet):
- `--non-interactive` flag to skip user input when resuming
- Automatic detection of manual file edits with confirmation prompt
- Resume from feedback step (instead of analyzer step)
- Resume from specific workflow step (e.g., --resume-from-step 5)
