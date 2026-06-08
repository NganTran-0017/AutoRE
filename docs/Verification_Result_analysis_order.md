Summary of Changes - Verification Result Analysis Order

  1. New Verification Order

  Predicate Structure:

  - baseline - Empty predicate (existing system requirements are in facts)
  - R1, R1R2, R1R2R3, ... - Incremental prospective requirement predicates
  - All_Requirements - Most comprehensive predicate (all prospective requirements)

  Run Command Order:

  1. run baseline - verify existing system alone
  2. run All_Requirements - most comprehensive first
  3. run R1, run R1R2, run R1R2R3, ... - incremental for localization
  4. check assert... - assertions

  Evaluator Analysis Order:

  1. Syntax errors → stop if found
  2. Baseline satisfiability → check if baseline is satisfiable
  3. Combined satisfiability → check All_Requirements, use R1, R1R2, R1R2R3 for localization
  4. Satisfying instances → analyze quality (when instances exist)
  5. Counterexamples → analyze violations (when they exist)
  6. Vacuity & stronger checks → only when all hard metrics pass

  ---
  2. Prompt Updates

  RE_prompt.txt (BuildAlloyModel & UpdateAlloyModel):

  - Instructions to create empty baseline predicate
  - Create incremental predicates: R1, R1R2, R1R2R3, ..., All_Requirements
  - Run commands in new order: baseline, All_Requirements, R1, R1R2, ..., checks

  Evaluator_prompt.txt:

  - InterpretResults: Updated analysis order (6 steps above)
  - ResponseFormatInterpretation: Updated sections to include:
    - === UNSATISFIABLE BASELINE ===
    - === UNSATISFIABLE COMBINED MODEL ===
    - === INCREMENTAL ANALYSIS === (R1, R1R2, R1R2R3 status)
    - === SATISFYING INSTANCES ===
    - === COUNTEREXAMPLES ===
    - === VACUITY ===
    - === USER QUESTIONS ===

  New Specialized Sections (conditionally included):

  - SyntaxError - when syntax errors exist
  - InterpretUNSATPred - when unsatisfiable predicates exist
  - InterpretCounterexample - when counterexamples exist
  - InterpretSatInstance - when satisfying instances exist
  - VacuityAnalysis - when all hard metrics pass

  ---
  3. Workflow Code Updates

  src/utils/alloy_executor.py:

  - Updated _analyze_results() to find most comprehensive instance:
    - Priority: All_Requirements → Longest R-chain → baseline → last

  src/utils/alloy_formatter.py:

  - Updated find_most_comprehensive_instance() with same priority logic

  src/actions/evaluation_actions.py:

  InterpretResults.run():

  - Conditionally appends specialized sections based on analysis results:
    - SyntaxError (if syntax errors)
    - InterpretUNSATPred (if unsat predicates)
    - InterpretCounterexample (if counterexamples) with {{counterexample}} variable
    - InterpretSatInstance (if satisfying instances) with {{satisfying_instances}} variable
    - VacuityAnalysis (if all hard metrics pass)

  _format_analyzer_results():

  - Shows summary only in {{analyzer_results}}:
    - Counterexamples: count and names (not JSON)
    - Satisfying instances: count and names (not JSON)
    - Unsatisfiable predicates: count and names
  - Detailed JSON data only in specialized sections (no duplication)

  New Methods:

  - _format_counterexamples() - formats up to 3 counterexamples with JSON
  - _format_satisfying_instances() - formats up to 3 instances with JSON
  - _find_comprehensive_instance() - updated priority logic

  ---
  4. Key Behaviors

  No Duplication:

  - Summary in {{analyzer_results}}
  - Detailed JSON only in specialized sections

  Conditional Inclusion:

  - SyntaxError → only when syntax errors
  - InterpretUNSATPred → only when unsat predicates
  - InterpretCounterexample → only when counterexamples
  - InterpretSatInstance → only when satisfying instances exist
  - VacuityAnalysis → only when all hard metrics pass

  Priority Logic (Most Comprehensive Instance):

  1. All_Requirements
  2. Longest R-chain (R1R2R3R4 > R1R2R3 > R1R2 > R1)
  3. baseline
  4. Last instance (fallback)

  Hard Metrics:

  - No syntax errors
  - No counterexamples
  - All positive runs satisfied