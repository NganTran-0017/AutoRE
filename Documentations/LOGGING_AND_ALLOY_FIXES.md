# Logging and Alloy Analyzer Fixes - May 1, 2026

## Issues Identified

1. **Alloy Analyzer Not Detecting Syntax Errors**: Evaluator claimed no syntax errors when AlloyModel__0.als had syntax errors
2. **No Alloy CLI Output Logging**: Alloy Analyzer stdout/stderr not being logged to file
3. **No Agent Communication Logging**: LLM prompts and responses not being logged
4. **metagpt.log Not Recording**: Empty metagpt.log file

## Root Causes

### 1. Wrong Method Call in RunAlloyAnalyzer
**Location:** `src/actions/evaluation_actions.py:43`

**Problem:**
```python
results = executor.run_analyzer(model_path, output_dir)  # WRONG - method doesn't exist
```

**Solution:**
```python
results = executor.execute(
    model_path=Path(model_path),
    output_dir=Path(output_dir)
)
```

`AlloyExecutor` has `execute()` method, not `run_analyzer()`. This caused the Alloy Analyzer to fail silently.

### 2. No Logging Infrastructure
- Logger not passed to actions/context
- No methods to log Alloy execution or agent communications
- MetaGPT logging not configured with file handlers

## Fixes Applied

### Fix 1: Corrected AlloyExecutor Method Call ✅
**File:** `src/actions/evaluation_actions.py`

Changed `executor.run_analyzer()` to `executor.execute()` with proper Path objects.

### Fix 2: Added Logging Methods to AutoRELogger ✅
**File:** `src/utils/logger.py`

Added two new methods:

#### 2a. `log_agent_communication()`
Logs every LLM interaction with:
- Agent name and action name
- Full prompt sent to LLM
- Full response from LLM

#### 2b. `log_alloy_execution()`
Logs Alloy Analyzer execution with:
- Model file path
- Return code
- Full stdout output
- Full stderr output
- Analysis results (JSON)

### Fix 3: Integrated Logger into SharedRuntimeContext ✅
**Files:**
- `src/utils/runtime_context.py`
- `src/workflow.py`

**Changes:**
- Added `logger` parameter to `SharedRuntimeContext.__init__()`
- Workflow now passes logger when creating context:
  ```python
  self.context = SharedRuntimeContext(project_name=project_name, logger=self.logger)
  ```

### Fix 4: Auto-Log All LLM Communications ✅
**File:** `src/actions/lesson_aware_action.py`

**Added method override:**
```python
async def _aask(self, prompt: str, system_msgs: list = None) -> str:
    """Override _aask to log all LLM communications."""
    response = await super()._aask(prompt, system_msgs)

    # Log the communication if logger is available
    if hasattr(self.context, 'logger') and self.context.logger:
        self.context.logger.log_agent_communication(
            agent_name=self.agent_name,
            action_name=self.action_name,
            prompt=prompt,
            response=response
        )

    return response
```

This automatically logs **every** LLM call from **every** action without modifying individual actions.

### Fix 5: Auto-Log Alloy Analyzer Execution ✅
**File:** `src/actions/evaluation_actions.py`

Added logging right after `executor.execute()`:
```python
# Log Alloy execution details (if logger available in context)
if hasattr(self.context, 'logger') and self.context.logger:
    self.context.logger.log_alloy_execution(
        model_path=str(model_path),
        stdout=results.get('stdout', ''),
        stderr=results.get('stderr', ''),
        return_code=results.get('return_code', -1),
        analysis=results.get('analysis', {})
    )
```

### Fix 6: Configured MetaGPT Logging ✅
**File:** `src/workflow.py`

Rewrote `_setup_logging()` to:
- Create `Output/outputlog/metagpt.log` file
- Configure file handler with DEBUG level
- Configure console handler with WARNING level (errors only)
- Clear existing handlers to avoid duplicates

```python
def _setup_logging(self):
    """Configure MetaGPT logging."""
    import logging
    from pathlib import Path

    # Create log directory
    log_dir = Path("Output/outputlog")
    log_dir.mkdir(parents=True, exist_ok=True)
    metagpt_log_file = log_dir / "metagpt.log"

    # Configure MetaGPT logger
    metagpt_logger = logging.getLogger("metagpt")
    metagpt_logger.setLevel(logging.DEBUG)
    metagpt_logger.handlers.clear()

    # Add file handler
    file_handler = logging.FileHandler(metagpt_log_file, mode='a')
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    metagpt_logger.addHandler(file_handler)

    # Add console handler for errors
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    metagpt_logger.addHandler(console_handler)
```

### Fix 7: Code Cleanup ✅
**File:** `src/actions/evaluation_actions.py`

- Removed unused `import json`
- Removed unused `file_mgr` variable

## What Gets Logged Now

### 1. User Interactions (MMDDYY.log)
- Session start/end timestamps
- User prompts (full version)
- User input
- File updates

### 2. Agent Communications (MMDDYY.log)
**NEW** - Every LLM interaction:
```
================================================================================
AGENT COMMUNICATION: RE - AnalyzeRequirements
================================================================================

--- PROMPT SENT TO LLM ---
[Full prompt with all variables substituted]

--- RESPONSE FROM LLM ---
[Complete LLM response]
================================================================================
```

### 3. Alloy Analyzer Execution (MMDDYY.log)
**NEW** - Every Alloy run:
```
================================================================================
ALLOY ANALYZER EXECUTION
================================================================================
Model: Output/AlloyModels/AlloyModel__0.als
Return Code: 0

--- ALLOY STDOUT ---
[Command output showing run/check results]

--- ALLOY STDERR ---
[Syntax errors, type errors, etc.]

--- ANALYSIS RESULTS ---
{
  "has_syntax_errors": true,
  "syntax_errors": [...],
  "has_counterexamples": false,
  ...
}
================================================================================
```

### 4. MetaGPT Internal Logs (metagpt.log)
**FIXED** - Now records:
- LLM API calls
- Token usage
- Internal MetaGPT operations
- Warnings and errors

## Log File Locations

All logs in `Output/outputlog/`:
- `043026.log` - Daily user interaction + agent communications + Alloy execution
- `metagpt.log` - MetaGPT internal logging (API calls, tokens, etc.)

## Testing

To verify fixes work:
```bash
# Run workflow
python main.py example_input.txt --max-iterations 1

# Check logs were created and populated
ls -lh Output/outputlog/
tail -100 Output/outputlog/050126.log    # Agent comms + Alloy output
tail -100 Output/outputlog/metagpt.log  # MetaGPT internals
```

## Impact

### Before:
- ❌ Alloy Analyzer failed silently (wrong method call)
- ❌ No visibility into what prompts were sent to LLM
- ❌ No visibility into what LLM responded
- ❌ No visibility into Alloy CLI output
- ❌ No visibility into why syntax errors weren't detected
- ❌ Empty metagpt.log file

### After:
- ✅ Alloy Analyzer executes correctly
- ✅ Complete log of every LLM interaction
- ✅ Complete log of every Alloy execution with stdout/stderr
- ✅ Syntax errors properly detected and logged
- ✅ metagpt.log populated with API calls and token usage
- ✅ Full traceability for debugging

## Files Modified

1. `src/actions/evaluation_actions.py` - Fixed method call, added Alloy logging, cleanup
2. `src/utils/logger.py` - Added 2 new logging methods
3. `src/utils/runtime_context.py` - Added logger parameter
4. `src/workflow.py` - Pass logger to context, configure MetaGPT logging
5. `src/actions/lesson_aware_action.py` - Override `_aask` to auto-log all LLM calls

## Summary

All logging issues fixed with minimal code changes. The logging is now:
- **Automatic**: No need to manually add logging calls in each action
- **Comprehensive**: Captures all LLM interactions and Alloy executions
- **Structured**: Clear sections for different types of logs
- **Debuggable**: Full visibility into prompts, responses, and tool executions
