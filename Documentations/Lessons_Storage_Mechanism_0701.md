 Investigation Report: Lesson Recording and Storage in AutoRE

  1. Lesson Parsing from LLM Responses

  File: /home/nati/autoRE/src/utils/learning_system.py (lines 33-80)

  Lessons are parsed via LearningSystem.parse_and_record(), which uses regex to extract content marked with [LESSON]: or [EVENT]: markers from agent outputs. The pattern matches
  single-line format ([LESSON]: text) and multi-line format with bullets. Once extracted, lessons are immediately stored via self.memory.store() and markers are removed from the output
  string.

  Called from: LessonAwareAction.parse_and_record_learning() at /home/nati/autoRE/src/actions/lesson_aware_action.py (lines 241-258), which is invoked in evaluation_actions.py and
  requirement_actions.py after every LLM call.

  2. Lesson Storage Structure

  File: /home/nati/autoRE/src/utils/memory_system.py (lines 39-100)

  Lessons are stored in LongTermMemorySystem as MemoryItem objects (dataclass at lines 11-37) with:
  - content: lesson text
  - type: "lesson", "pattern", or "event"
  - tags: dict with agent (RE/Evaluator), action (e.g., BuildAlloyModel), iteration (current iteration #), project
  - metadata: arbitrary extra data
  - timestamp: ISO datetime

  Storage is in-memory as a list (self.items at line 64), persisted to disk via save() method to memory/{project_name}/memory.json (lines 265-270).

  3. Lesson Retrieval and Prompt Injection

  Files:
  - /home/nati/autoRE/src/utils/learning_system.py (lines 148-178, 249-295)
  - /home/nati/autoRE/src/actions/evaluation_actions.py (lines 703-704, 768)
  - /home/nati/autoRE/src/actions/requirement_actions.py (lines 34-45, 85-92, 131-143, 195)

  Lessons are retrieved via action.get_lessons(limit=5) which calls memory.get_lessons(agent=..., action=..., limit=5) and returns most recent 5 lessons. The format_lessons() method
  formats them as numbered bullet points. These are passed as lessons=lessons_str variables into prompts which substitute {{lessons}} placeholders. No semantic filtering occurs—all lessons
  from the same agent/action are included (up to limit).

  4. Issue Comparison Logic Between Iterations

  File: /home/nati/autoRE/src/utils/regression_log.py (lines 816-878)
  Called from: /home/nati/autoRE/src/workflow.py (lines 858-875)

  Function: count_consecutive_same_syntax_errors(regression_log_entries, current_iteration, current_issue, current_syntax_error) compares errors across iterations by:
  - Extracting line numbers from error descriptions
  - Matching error messages from the context field (truncated at location info)
  - Checking if line numbers are within ±5 non-comment lines
  - Counting both consecutive occurrences (broken by any non-matching iteration) and total occurrences (all matches, even with gaps)

  Returns: {'consecutive': int, 'total': int} (both include current iteration). Thresholds: 2 consecutive OR 3 total triggers user feedback request (line 878-881).

  5. Lesson Granularity and Tagging

  File: /home/nati/autoRE/src/utils/memory_system.py (lines 87-99)

  Granularity: One lesson per parse_and_record() call (roughly one per LLM response). Multiple lessons can be extracted from a single response if multiple [LESSON]: markers exist. No
  automatic deduplication.

  Tagging: Each lesson is tagged with:
  - iteration: Current iteration when recorded (set via context.iteration.current at line 124 in lesson_aware_action.py)
  - agent and action: Allows filtering lessons by source

  This enables querying "all lessons from iteration 3" or "lessons from RE's BuildAlloyModel action" but does NOT tag lessons with "this lesson fixed iteration 5's error"—that relationship
  would need to be added if lessons were deferred.

  6. Lesson Persistence Timing

  File: /home/nati/autoRE/src/utils/runtime_context.py (lines 105-114)
  Called from: /home/nati/autoRE/src/workflow.py (lines 278, 299)

  Lessons are NOT persisted immediately. They remain in-memory (in LongTermMemorySystem.items list) during the entire workflow run. context.save_state() calls self.memory.save() at only
  two points:
  - End of workflow (line 278 in workflow.py)
  - On Ctrl+C interrupt (line 299 in workflow.py)

  This means lessons are lost if the workflow crashes without graceful shutdown. Persisted format: JSON file with MemoryItem objects (lines 269-270).

  ---
  Brainstorm implication for deferring lessons: To defer recording until a fix is confirmed, you'd need to:
  1. Add an optional resolved_in_iteration tag to MemoryItem (currently only tracks when recorded)
  2. Defer the memory.store() call in parse_and_record() until a downstream check confirms RegressionLogEntry.resolved_target_issue == True
  3. Store pending lessons in a staging area (e.g., context.pending_lessons) keyed by iteration