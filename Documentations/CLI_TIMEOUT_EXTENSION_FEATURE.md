# CLI Timeout Extension Feature

## Overview
Added live countdown timer and timeout extension capability to `CLIInteraction` class for better user experience during input sessions.

## Implementation Date
May 5, 2026

## Features Implemented

### 1. Live Countdown Timer
- **Display Frequency**: Every 2 minutes
- **Format**: `⏱ Time remaining: Xm XXs | Type 'EXTEND' to add 5 min (X extensions left)`
- **Non-intrusive**: Prints on new lines, doesn't interfere with typing

### 2. Time Extension Command
- **Command**: Type `EXTEND` on a new line
- **Extension Duration**: 5 minutes per extension
- **Maximum Extensions**: 10 per input session
- **Total Possible Time**: 5 + (10 × 5) = 55 minutes

### 3. Session Management
- Extension counter resets for each new input request
- Clear feedback on extensions used and remaining
- Automatic timeout handling when deadline reached

## Files Modified

### `src/utils/cli_interaction.py`
**Changes:**
1. Added imports: `threading`, `time`, `datetime`, `timedelta`
2. Updated `__init__` method:
   - Added `max_extensions = 10`
   - Added `extension_duration = 300` (seconds)
   - Added `extensions_used = 0`
   - Added countdown state variables

3. New methods:
   - `_display_countdown()` - Background thread showing countdown every 2 minutes
   - `_handle_extension()` - Processes extension requests and updates deadline

4. Updated methods:
   - `_get_multiline_input()` - Now supports countdown and EXTEND command
   - `_get_singleline_input()` - Now supports countdown and EXTEND command

## Usage

### Multiline Input Mode (Default)
```python
from src.utils.cli_interaction import CLIInteraction
from src.utils.logger import AutoRELogger

logger = AutoRELogger()
cli = CLIInteraction(logger, timeout=300)  # 5 minutes

result = cli.request_input(
    prompt="Please provide your feedback:",
    concise_prompt="Your feedback:",
    multiline=True
)
```

**User Experience:**
```
────────────────────────────────────────────────────────────────────────────────
Your response (type your feedback, then 'END' on a new line):
Initial timeout: 300 seconds (5 minutes)
You can extend time up to 10 times by typing 'EXTEND' on a new line
────────────────────────────────────────────────────────────────────────────────

⏱  Time remaining: 5m 00s | Type 'EXTEND' to add 5 min (10 extensions left)
This is my first line
This is my second line
⏱  Time remaining: 3m 00s | Type 'EXTEND' to add 5 min (10 extensions left)
EXTEND

✓ Time extended by 5 minutes!
  Extensions used: 1/10
  Total time remaining: ~8 minutes

⏱  Time remaining: 8m 00s | Type 'EXTEND' to add 5 min (9 extensions left)
This is more feedback
END

✓ Input received
```

### Single-line Input Mode
```python
result = cli.request_input(
    prompt="Your answer:",
    concise_prompt="Answer:",
    multiline=False
)
```

## Testing

### Test File Created
`test_cli_countdown_extension.py`

**Test Cases:**
1. Test countdown display every 2 minutes
2. Test extension limit (10 max)
3. Test single-line input with extension
4. Quick demo of all features

**Run Tests:**
```bash
# Quick demo
python test_cli_countdown_extension.py

# Specific tests
python test_cli_countdown_extension.py 1  # Countdown display
python test_cli_countdown_extension.py 2  # Extension limit
python test_cli_countdown_extension.py 3  # Single-line mode
```

## Benefits

✅ **User Control** - Users can extend time as needed
✅ **Clear Feedback** - Always know time remaining and extensions available
✅ **Non-intrusive** - Updates every 2 minutes, doesn't interrupt typing
✅ **Flexible** - Up to 55 minutes total time
✅ **Session-based** - Extension count resets each session
✅ **Well-logged** - All actions logged for audit trail

## Backward Compatibility

✅ No breaking changes
✅ Default behavior unchanged (5-minute timeout)
✅ Extension feature is optional (users can ignore EXTEND)
✅ Existing code continues to work without modification

## Configuration (Future Enhancement)

Currently hardcoded values:
- `max_extensions = 10`
- `extension_duration = 300` (5 minutes)

Future: Can be made configurable via `config.yaml`:
```yaml
user_interaction:
  cli:
    default_timeout_seconds: 300
    extension_duration_seconds: 300
    max_extensions_per_session: 10
```

## Example Scenarios

### Scenario 1: User needs more time
User is typing detailed feedback, sees countdown at 3 minutes, types `EXTEND` to add 5 more minutes.

### Scenario 2: Long clarification session
User extends time 3 times during a complex clarification, using 20 total minutes (5 + 15).

### Scenario 3: Timeout reached
User doesn't finish in time. System logs timeout with total time allowed including extensions.

### Scenario 4: Extension limit reached
User tries to extend beyond 10 times, system shows warning that max extensions reached.

## Technical Details

### Threading
- Countdown runs in daemon thread
- Non-blocking, doesn't interfere with input
- Properly cleaned up on completion/timeout

### Time Management
- Uses `datetime.now()` and `timedelta` for precise timing
- Deadline-based approach (not alarm-based for countdown)
- Extension adds to deadline dynamically

### Error Handling
- Graceful timeout handling
- Thread cleanup in finally blocks
- Extension limit enforcement

## Logging
- Initial timeout logged
- Each extension logged
- Final timeout status with total time logged
- Extensions used count logged

## Notes
- Countdown thread is daemon (won't prevent program exit)
- Display updates every 2 minutes to minimize log clutter
- Extension counter resets between input sessions
- Works with both multiline and single-line input modes
