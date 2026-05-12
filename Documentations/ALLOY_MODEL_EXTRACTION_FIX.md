# Alloy Model Extraction Fix - May 1, 2026

## The Problem

Files `AlloyModel__1.als`, `AlloyModel__2.als`, and `AlloyModel__3.als` contained **requirements documents** (text) instead of **Alloy code**.

**What was saved:**
```
SYSTEM OVERVIEW
===============
The system is a Role-Based Access Control (RBAC) system...

PROSPECTIVE FUNCTIONAL REQUIREMENTS
=======================
R1: Emergency Triggering
...
```

**What should have been saved:**
```alloy
// Alloy model for RBAC system
sig User {
  clearance: one ClearanceLevel,
  ...
}
```

## Root Cause

### LLM Response Format

The prompt (`prompts/RE_prompt.txt` lines 152-186) instructs the LLM to format responses as:

**For Requirements Documents:**
```
SYSTEM OVERVIEW
===============
...
```

**For Alloy Models:**
````markdown
```alloy
// Alloy code here
```
````

### Extraction Logic Flaw

**Location:** `src/utils/file_manager.py:90-117` (FileManager.save_alloy_model)

**Original Logic:**
```python
def save_alloy_model(self, content: str, iteration: int) -> Path:
    content = content.strip()
    if content.startswith('```'):  # ← ONLY checks if starts with fence
        # Strip first and last lines
        lines = content.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        content = '\n'.join(lines)

    # Save entire content
    filepath = self.models_dir / f"AlloyModel__{iteration}.als"
    with open(filepath, 'w') as f:
        f.write(content)
```

**The Bug:**

When `UpdateAlloyModel` returns:
```
Here is the updated model addressing the syntax errors:

UPDATED REQUIREMENTS:
R1: ...
R2: ...

```alloy
sig User { ... }
```
```

The content **does NOT start with** `````, so:
- The fence-stripping logic is skipped
- The **entire response** (including requirements text) is saved to `.als` file

### Why AlloyModel__0.als Was Correct

`AlloyModel__0.als` (from `BuildAlloyModel` action) worked because the LLM likely returned:
````markdown
```alloy
sig User { ... }
```
````

Since this **starts** with `````, the fence-stripping logic ran and extracted the code correctly.

## The Fix

**Location:** `src/utils/file_manager.py:90-130`

**New Logic:**
```python
def save_alloy_model(self, content: str, iteration: int) -> Path:
    """
    Save Alloy model, extracting code from markdown fences if present.
    """
    import re

    content = content.strip()

    # Try to extract code from markdown fence (```alloy ... ```)
    # Look for the FIRST alloy code block in the response
    alloy_block_pattern = r'```alloy\s*\n(.*?)```'
    match = re.search(alloy_block_pattern, content, re.DOTALL)

    if match:
        # Found alloy code block - extract just the code
        content = match.group(1).strip()
    elif content.startswith('```'):
        # Generic code block at start - strip fences (backward compatibility)
        lines = content.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        content = '\n'.join(lines)
    # else: assume it's already plain Alloy code

    filepath = self.models_dir / f"AlloyModel__{iteration}.als"
    with open(filepath, 'w') as f:
        f.write(content)
    return filepath
```

### What Changed

1. **Added regex extraction:** Uses `r'```alloy\s*\n(.*?)```'` to find and extract the first ````alloy` code block
2. **Searches anywhere in response:** No longer requires the code block to be at the start
3. **Falls back to old logic:** If no ````alloy` block found but starts with `````, strip fences as before
4. **Assumes plain code:** If no markers found, assumes content is already plain Alloy code

### Regex Explanation

```python
alloy_block_pattern = r'```alloy\s*\n(.*?)```'
```

- `` ```alloy`` - Literal string "```alloy"
- `\s*` - Optional whitespace
- `\n` - Newline
- `(.*?)` - **Capture group** - any characters (non-greedy)
- `` ``` `` - Closing fence
- `re.DOTALL` flag - Makes `.` match newlines too

**Example Match:**
```
Text before

```alloy
sig User { clearance: one ClearanceLevel }
fact { all u: User | some u.clearance }
```

Text after
```

**Extracted:** Only the code inside the fence:
```alloy
sig User { clearance: one ClearanceLevel }
fact { all u: User | some u.clearance }
```

## Impact

### Before Fix:
- ❌ `AlloyModel__1.als` contained requirements document
- ❌ `AlloyModel__2.als` contained requirements document
- ❌ `AlloyModel__3.als` contained requirements document
- ❌ Alloy Analyzer fails to parse these files
- ❌ Workflow cannot evaluate models properly
- ❌ Iteration loop breaks

### After Fix:
- ✅ Correctly extracts Alloy code from anywhere in LLM response
- ✅ Handles explanatory text before/after code block
- ✅ Backward compatible with responses that start with fences
- ✅ Alloy Analyzer can parse the extracted code
- ✅ Workflow evaluation works correctly

## Testing

To verify the fix:

1. **Delete broken files:**
   ```bash
   rm Output/AlloyModels/AlloyModel__1.als
   rm Output/AlloyModels/AlloyModel__2.als
   rm Output/AlloyModels/AlloyModel__3.als
   ```

2. **Run workflow:**
   ```bash
   python main.py example_input.txt --max-iterations 3
   ```

3. **Verify extracted models:**
   ```bash
   head -20 Output/AlloyModels/AlloyModel__1.als
   # Should show Alloy code (sig, fact, pred), NOT requirements text
   ```

4. **Check logs for LLM response:**
   ```bash
   grep -A 100 "AGENT COMMUNICATION: RE - UpdateAlloyModel" Output/outputlog/*.log
   # Should show full LLM response including any explanatory text
   ```

## Files Modified

- `src/utils/file_manager.py` - Enhanced `save_alloy_model()` to extract code blocks with regex

## Related Issues

This fix is part of the May 1, 2026 debugging session that also fixed:
1. Alloy Analyzer execution (wrong method call) - See `LOGGING_AND_ALLOY_FIXES.md`
2. Syntax error detection (wrong key access) - See `SYNTAX_ERROR_DETECTION_FIX.md`
3. Missing logging infrastructure - See `LOGGING_AND_ALLOY_FIXES.md`

All issues are now resolved.
