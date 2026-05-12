# Iteration Counter Timing Fix - May 1, 2026

## The Problem

`AlloyModel__0.als` was never evaluated! Instead, the workflow tried to evaluate `AlloyModel__1.als` in the first iteration, which didn't exist yet, causing the workflow to terminate with "Model file not found".

## Root Cause

**Location:** `src/workflow.py:174-236` (AutoREWorkflow.run() method)

**Incorrect Flow:**

```python
# Step 3: Build initial model
await self._step3_build_initial_model()  # Creates AlloyModel__0.als (iteration=0)

# Iterative refinement loop
for iteration in range(1, self.max_iterations + 1):
    self.context.next_iteration()  # ← BUG: Increments to 1 BEFORE evaluation!

    # Step 4: Evaluate model
    evaluation_result = await self._step4_evaluate_model()  # Looks for AlloyModel__1.als
```

**What happened:**

1. **Step 3** creates `AlloyModel__0.als` (iteration counter = 0)
2. **Loop starts**, immediately calls `self.context.next_iteration()` → counter becomes **1**
3. **Step 4** evaluates model for iteration 1 → looks for `AlloyModel__1.als` ❌ **Doesn't exist!**
4. Workflow terminates with error: "No Alloy model found to evaluate"

**Why this is wrong:**

The initial model (`AlloyModel__0.als`) was built with user clarifications but never verified! The workflow skipped straight to trying to evaluate a non-existent `AlloyModel__1.als`.

## The Fix

**Location:** `src/workflow.py:174-230`

**Move `next_iteration()` call to AFTER evaluation, BEFORE model update:**

```python
# Step 3: Build initial model
await self._step3_build_initial_model()  # Creates AlloyModel__0.als (iteration=0)

# Iterative refinement loop
for iteration in range(1, self.max_iterations + 1):
    print(f"\nIteration {iteration}/{self.max_iterations}")

    # Step 4: Evaluate model (iteration=0 on first loop)
    evaluation_result = await self._step4_evaluate_model()  # Evaluates AlloyModel__0.als ✅

    if evaluation_result is None:
        break

    if evaluation_result:  # Converged
        break

    # Step 5-6: Generate feedback and get user input
    await self._step5_6_generate_feedback_and_get_user_input()

    # Step 7: Update requirements
    await self._step7_update_requirements()

    # Increment iteration counter before creating new model
    self.context.next_iteration()  # ← MOVED HERE: Now increments to 1

    # Step 8: Update model
    await self._step8_update_model()  # Creates AlloyModel__1.als (iteration=1)
```

**Correct Flow Now:**

| Loop Iteration | Iteration Counter | Evaluates | Creates |
|----------------|-------------------|-----------|---------|
| (before loop) | 0 | - | AlloyModel__0.als |
| 1 | 0 → 1 | AlloyModel__0.als ✅ | AlloyModel__1.als |
| 2 | 1 → 2 | AlloyModel__1.als ✅ | AlloyModel__2.als |
| 3 | 2 → 3 | AlloyModel__2.als ✅ | AlloyModel__3.als |

## Impact

### Before Fix:
- ❌ `AlloyModel__0.als` created but never evaluated
- ❌ First evaluation tries to find `AlloyModel__1.als` (doesn't exist)
- ❌ Workflow terminates immediately: "No Alloy model found to evaluate"
- ❌ User clarifications in `AlloyModel__0.als` wasted
- ❌ No iterative refinement happens

### After Fix:
- ✅ `AlloyModel__0.als` created AND evaluated
- ✅ First evaluation correctly finds `AlloyModel__0.als`
- ✅ Workflow proceeds to generate feedback and create `AlloyModel__1.als`
- ✅ User clarifications are verified
- ✅ Iterative refinement works as designed

## Verification

To verify the fix works:

```bash
# Run workflow
python main.py example_input.txt --max-iterations 3

# Check which models were created
ls -la Output/AlloyModels/

# Expected output:
# AlloyModel__0.als  ← Created in Step 3, evaluated in iteration 1
# AlloyModel__1.als  ← Created in iteration 1, evaluated in iteration 2
# AlloyModel__2.als  ← Created in iteration 2, evaluated in iteration 3
# AlloyModel__3.als  ← Created in iteration 3, (evaluated in iteration 4 if it existed)

# Check logs to see evaluation sequence
grep "Step 4: Evaluating" Output/outputlog/*.log
grep "Saved to:.*AlloyModel" Output/outputlog/*.log
```

**Expected Log Pattern:**

```
Step 3: Building initial Alloy model...
  Saved to: Output/AlloyModels/AlloyModel__0.als

Iteration 1/3
Step 4: Evaluating Alloy model...
  Running Alloy Analyzer... (evaluating AlloyModel__0.als)

Step 8: Updating Alloy model...
  Saved to: Output/AlloyModels/AlloyModel__1.als

Iteration 2/3
Step 4: Evaluating Alloy model...
  Running Alloy Analyzer... (evaluating AlloyModel__1.als)

Step 8: Updating Alloy model...
  Saved to: Output/AlloyModels/AlloyModel__2.als
```

## Related Code

**Files Modified:**
- `src/workflow.py` - Lines 174-230 (AutoREWorkflow.run method)

**Key Methods:**
- `AutoREWorkflow.run()` - Main workflow orchestration
- `AutoREWorkflow._step3_build_initial_model()` - Creates AlloyModel__0.als
- `AutoREWorkflow._step4_evaluate_model()` - Evaluates current iteration's model
- `AutoREWorkflow._step8_update_model()` - Creates next iteration's model
- `IterationTracker.next_iteration()` - Increments counter

**Key Insight:**

The iteration counter determines which model file to **read** (evaluate) and **write** (create). The timing of `next_iteration()` must ensure:
1. Evaluation reads the model just created
2. Update creates the model for the next evaluation

## Summary

This was a critical bug that prevented the workflow from ever evaluating `AlloyModel__0.als`. By moving `next_iteration()` to **after** evaluation and **before** model update, we ensure:

1. The initial model (with user clarifications) is evaluated
2. Each iteration evaluates the model created in the previous iteration/step
3. The iterative refinement loop works correctly
