# Alloy Analyzer Output Parsing Bug Fix

## Bug Description
Alloy Analyzer results were not being parsed correctly, causing Evaluator to receive incorrect information:
- **Actual**: 5 run commands SAT, 5 check commands SAT (counterexamples), 1 check UNSAT
- **Sent to Evaluator**: "COUNTEREXAMPLES: None", "SATISFYING INSTANCES: None found"

This led to incorrect feedback from the Evaluator agent.

## Root Cause

### Issue 1: Wrong output stream (CRITICAL)
**File:** `src/utils/alloy_executor.py:160`

The parser only checked **stdout**, but Alloy 6 outputs command results to **stderr**:
```
--- ALLOY STDOUT ---
(empty)

--- ALLOY STDERR ---
00. run   R1                       1/1     SAT
01. run   R1R2                     1/1     SAT
...
```

### Issue 2: Missing counterexample data
**File:** `src/actions/evaluation_actions.py:194-209`

Counterexamples were shown as generic descriptions instead of including the actual JSON data that shows what violated the assertion.

## Fixes Applied

### Fix 1: Parse both stdout and stderr (alloy_executor.py:161-162)
```python
# OLD: Only checked stdout
for line in stdout.split('\n'):

# NEW: Check both stdout and stderr
for line in (stdout + '\n' + stderr).split('\n'):
```

### Fix 2: Include full counterexample JSON data (evaluation_actions.py:194-209)
```python
# OLD: Generic description
lines.append(f"  {i}. {ce.get('description', str(ce))}")

# NEW: Full JSON data
cmd_name = ce.get('command_name', 'Unknown')
lines.append(f"\n  {i}. {cmd_name}:")
ce_data = ce.get('data', {})
lines.append(f"     {json.dumps(ce_data, indent=6)}")
```

## Impact

✅ **Before**: Evaluator received no counterexample/instance information → incorrect feedback
✅ **After**: Evaluator receives complete analyzer results with full JSON data → accurate analysis

## Example Output Format

**Counterexamples now include full JSON:**
```
COUNTEREXAMPLES FOUND: 5

  1. assertR1:
     {
       "bitwidth": 4,
       "skolem": [...],
       "field": {...},
       ...
     }
```

This allows the Evaluator to understand **exactly** what scenario violated the assertion.
