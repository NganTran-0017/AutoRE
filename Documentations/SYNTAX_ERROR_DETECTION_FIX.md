# Syntax Error Detection Fix - May 1, 2026

## The Problem

When running the workflow with `AlloyModel__0.als` that contained syntax errors, the Evaluator printed:
```
✓ Evaluation complete
  Syntax: ✓ OK           <-- WRONG! There were syntax errors
  Counterexamples: ✓ None
  Instances: ✗ None
```

## Root Cause

**Location:** `src/workflow.py:380` (in `_step4_evaluate_model()`)

**Incorrect code:**
```python
# Check convergence
no_syntax_errors = not results.get('syntax_errors')      # WRONG!
no_counterexamples = not results.get('counterexamples')  # WRONG!
has_instances = bool(results.get('instances'))           # WRONG!
```

**Why it's wrong:**

The `AlloyExecutor.execute()` returns a structure like:
```python
{
    "success": True,
    "return_code": 0,
    "stdout": "...",
    "stderr": "...",
    "output_files": [...],
    "analysis": {                          # ← Nested here!
        "has_syntax_errors": True,
        "syntax_errors": [...],
        "has_counterexamples": False,
        "counterexamples": [],
        "has_satisfying_instances": False,
        "instances": []
    }
}
```

The workflow was checking the **top-level** keys (`results.get('syntax_errors')`), but the actual data is **nested** under `results['analysis']`.

So:
- `results.get('syntax_errors')` → `None` → `not None` → `True` (no errors) ❌ **WRONG**
- `results['analysis'].get('has_syntax_errors')` → `True` → `not True` → `False` (has errors) ✅ **CORRECT**

## The Fix

**Location:** `src/workflow.py:379-397`

**Corrected code:**
```python
# Check convergence - analysis results are nested under 'analysis' key
analysis = results.get('analysis', {})
no_syntax_errors = not analysis.get('has_syntax_errors', False)
no_counterexamples = not analysis.get('has_counterexamples', False)
has_instances = analysis.get('has_satisfying_instances', False)

print(f"  Syntax: {'✓ OK' if no_syntax_errors else '✗ Errors'}")
print(f"  Counterexamples: {'✓ None' if no_counterexamples else '✗ Found'}")
print(f"  Instances: {'✓ Found' if has_instances else '✗ None'}")

# Show syntax error details if present
if not no_syntax_errors:
    syntax_errors = analysis.get('syntax_errors', [])
    print(f"  ⚠ Found {len(syntax_errors)} syntax error(s)")
    for err in syntax_errors[:3]:  # Show first 3
        if isinstance(err, dict):
            print(f"    - Line {err.get('line', '?')}: {err.get('message', 'Unknown error')}")
        else:
            print(f"    - {err}")
```

## What Changed

1. **Extract analysis dict first:** `analysis = results.get('analysis', {})`
2. **Check correct keys:**
   - `has_syntax_errors` instead of `syntax_errors`
   - `has_counterexamples` instead of `counterexamples`
   - `has_satisfying_instances` instead of `instances`
3. **Added error details:** When syntax errors are found, print first 3 with line numbers

## Expected Output Now

With the same `AlloyModel__0.als` that has syntax errors:
```
✓ Evaluation complete
  Syntax: ✗ Errors              <-- Correctly detects errors now!
  Counterexamples: ✓ None
  Instances: ✗ None
  ⚠ Found 2 syntax error(s)
    - Line 17: Syntax error at line 17, column 10
    - Line 23: Syntax error at line 23, column 5
```

## Related Issue

This was discovered as part of the Alloy Analyzer debugging, which also revealed:
1. Wrong method call (`run_analyzer()` instead of `execute()`) - **FIXED**
2. Missing Alloy CLI output logging - **FIXED**
3. This incorrect key access - **FIXED**

All three issues are now resolved.

## Impact

**Before:**
- ❌ Syntax errors silently ignored
- ❌ Workflow thought model was valid
- ❌ Continued to next iteration incorrectly
- ❌ No visibility into what errors existed

**After:**
- ✅ Syntax errors correctly detected
- ✅ Workflow knows model is invalid
- ✅ Error details shown in console
- ✅ Full error details logged to file
- ✅ Convergence check works properly
