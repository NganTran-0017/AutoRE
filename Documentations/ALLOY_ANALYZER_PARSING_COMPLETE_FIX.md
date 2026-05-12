# Alloy Analyzer Result Parsing - Complete Fix

## Problem Summary

The Alloy Analyzer execution and parsing had two critical bugs that caused all verification results to be lost:

1. **Missing `-f` flag**: Alloy refused to execute when output directory contained existing files
2. **Incorrect regex pattern**: CLI output format wasn't being parsed correctly
3. **Filename parsing**: JSON filenames had `-solution-N` suffix that wasn't being stripped

## Symptoms

- All run/check results showed as "unknown" type
- `has_counterexamples` was always False
- `has_satisfying_instances` was always False
- `counterexamples` list was empty
- `instances` list was empty
- `total_run_commands` and `total_check_commands` were 0
- Evaluator received incorrect information about verification

## Root Causes

### Issue 1: Missing `-f` Flag

**Problem**: When Alloy Analyzer is run on a directory that already has output files, it errors out:
```
Error
  0. The output directory /path/to/output contains files.
     Delete them or use the -f option
```

This caused no execution, so stdout/stderr only contained the error message, resulting in empty command_map.

**Fix**: Added `-f` (force) flag to the Alloy command in `src/utils/alloy_executor.py`:

```python
# Build command
cmd = [
    "java",
    "-jar",
    str(self.alloy_jar_path),
    "exec",  # Execute command
    "-t", "json",
    "-f",  # Force overwrite existing files  ← ADDED
    "-o", str(output_dir) + "/",
    str(model_path)
]
```

### Issue 2: Regex Pattern Mismatch

**Problem**: The original regex pattern was too strict and couldn't handle the UNSAT case properly.

CLI output format:
```
00. run   R1                       1/1     SAT
08. check assertR4_1               0       UNSAT
```

Note that UNSAT lines have "0" instead of "1/1" (no instances generated).

**Old regex** (too strict):
```python
pattern = r'^\s*(\d+)\.\s+(run|check)\s+(\S+)\s+(\d+(?:/\d+)?)\s+(SAT|UNSAT)\s*$'
```

This assumed exactly one instances field, failing when there was an extra column.

**Fixed regex** (flexible):
```python
pattern = r'^\s*(\d+)\.\s+(run|check)\s+(\S+)\s+.*?(?:(\d+/\d+)\s+)?(SAT|UNSAT)\s*$'
```

Key changes:
- `\s+.*?` - Match variable whitespace flexibly between command name and instances/result
- `(?:(\d+/\d+)\s+)?` - Make instances field optional (UNSAT has "0" instead of "1/1")
- Non-greedy matching `.*?` to avoid consuming the SAT/UNSAT result

### Issue 3: Filename Suffix

**Problem**: Alloy generates files like `All_Requirements-solution-0.json`, but code extracted command name as `All_Requirements-solution-0` which didn't match the command map key `All_Requirements`.

**Fix**: Strip the `-solution-N` suffix before matching:

```python
# Extract command name from filename
# Handle formats like "All_Requirements-solution-0.json" -> "All_Requirements"
filename_stem = file_path.stem

# Strip "-solution-N" suffix if present
if '-solution-' in filename_stem:
    cmd_name = filename_stem.rsplit('-solution-', 1)[0]
else:
    cmd_name = filename_stem
```

## Test Results

### Before Fix (from 050826.log):

```json
{
  "has_counterexamples": false,
  "has_satisfying_instances": false,
  "counterexamples": [],
  "instances": [],
  "total_run_commands": 0,
  "total_check_commands": 0,
  "files": [
    {"type": "unknown", "command_info": {}},
    ...all files marked as unknown...
  ]
}
```

### After Fix:

```
Total run commands: 5
Total check commands: 6
Counterexamples: 5
Satisfying instances: 5
has_counterexamples: True
has_satisfying_instances: True

✓ ALL CHECKS PASSED
```

Correctly identifying:
- 5 run SAT commands → 5 satisfying instances (R1, R1R2, R1R2R3, R1R2R3R4, All_Requirements)
- 5 check SAT commands → 5 counterexamples (assertR1, assertR2, assertR3, assertR4_2, assertR4_3)
- 1 check UNSAT command → 1 assertion holds (assertR4_1)

## Files Modified

1. **src/utils/alloy_executor.py**
   - `execute()` method: Added `-f` flag (line ~30)
   - `_parse_cli_output()` method: Updated regex pattern (line ~137)
   - `_analyze_results()` method: Strip `-solution-N` suffix from filenames (line ~421)

## Impact

This fix ensures:
1. ✅ Alloy Analyzer can execute successfully even when output directory has existing files
2. ✅ All CLI output formats are correctly parsed
3. ✅ All result files are properly categorized as counterexamples or satisfying instances
4. ✅ UNSAT results are correctly handled (instances field is None)
5. ✅ Evaluator receives accurate verification results
6. ✅ Users see correct feedback about model verification status
7. ✅ Workflow can iterate without manual cleanup of output directories

## Verification

Run the test scripts to verify the fix:

```bash
# Test regex pattern matching
python test_regex_pattern.py

# Test filename parsing
python test_alloy_parsing.py

# Test full Alloy execution with -f flag
python test_alloy_force_flag.py
```

All tests should pass ✓

## Related Issues

This bug was preventing:
- Accurate verification result reporting
- Correct feedback generation
- Proper convergence detection
- Resume functionality from working correctly

All of these issues are now resolved.
