# CLI Timeout Input Capture Bug Fix

## Bug Description
**Issue:** When users typed feedback but forgot to type "END" before timeout, the system returned `None` and reported "No input received", losing the user's typed content.

**Example scenario:**
```
User types:
> The syntax error is not related to `&&` operator. it is the (). replace () and []
> and use logical `and` instead.
⏱  Time remaining: 0m 59s
[TIMEOUT occurs - user forgot to type END]

Old behavior: Returns None, loses input
New behavior: Captures the typed input
```

## Root Cause
In `cli_interaction.py:311-324`, the `TimeoutError` exception handler immediately returned `None` without checking if the `lines` list contained any user input.

## Fix
**File:** `src/utils/cli_interaction.py`
**Lines:** 311-344

Changed the `TimeoutError` handler to:
1. Check if `lines` contains any content
2. If yes: Return the captured input with appropriate logging
3. If no: Return `None` as before

```python
except TimeoutError:
    # ... stop countdown ...

    # Check if user had typed anything before timeout
    user_input = '\n'.join(lines).strip()

    if user_input:
        # User typed content but forgot to type END - capture it!
        logger.log("⏱️  TIMEOUT: Time limit reached (user forgot to type 'END')")
        logger.log("User had typed content - capturing input provided before timeout")
        return user_input
    else:
        # User truly provided no input
        logger.log("⏱️  TIMEOUT: No input received within time limit")
        return None
```

## Test Coverage
**File:** `test_cli_timeout_with_input.py`

Tests verify:
- ✅ Input captured when timeout occurs with content
- ✅ None returned when timeout occurs without content
- ✅ Normal END completion works correctly
- ✅ Whitespace-only input returns None

All 4 tests pass.

## Benefits
- **No data loss**: User input is preserved even if they forget to type END
- **Better UX**: Clear logging distinguishes "forgot END" vs "no input"
- **Backward compatible**: No input still returns None as before
