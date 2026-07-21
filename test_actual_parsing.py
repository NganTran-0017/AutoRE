#!/usr/bin/env python3
"""
Test parsing with actual InterpretResults output from log
"""
from src.utils.qa_parser import parse_user_questions

# Actual InterpretResults output from line 1959-1974 of 062926.log
actual_output = """=== RESULT INTERPRETATION ===
- What: The EmergencyBypassFIFOScenario predicate is UNSAT (no instance found), and the assertion assertEmergencyBypassFIFOReachable is violated (counterexample found). All other positive run predicates (e.g., baseline, All_Requirements, R1, R1R2, R1R2R3, R1R2R3R4, MutexPossibleDuringEmergency, EmergencyDelegationRevocationScenario, PreEmergencyDelegationPersistenceScenario) are now SAT. All assertions except assertEmergencyBypassFIFOReachable are passing. Syntax is OK.
- Expected vs. Actual: The regression log expected, after removing global clearance/classification coverage facts, that all positive runs except EmergencyBypassFIFOScenario would become SAT (matching what is observed), but it did not expect the assertion assertEmergencyBypassFIFOReachable to fail.

=== REGRESSION DIAGNOSIS ===
Discrepancies: The assertion assertEmergencyBypassFIFOReachable failing is unexpected – it was added to determine if the scenario is reachable, not to enforce a universal system constraint.
Analysis: The failure indicates that not all valid system instances can support the Emergency group-processing scenario, suggesting that the scenario is only possible in certain configurations (where appropriate request/processor distributions exist).

=== OUTCOME CLASSIFICATION ===
Classification: spec_clarification: the results reveal the need for clarification on whether the Emergency group-processing scenario must be universally realizable or only in certain runs.
Rationale: The positive scenario predicates are all realizable except the Emergency group-processing witness, and the corresponding assertion fails; this highlights a gap or ambiguity in the requirements regarding the necessary conditions for this scenario to be possible.

=== BLOCKING QUESTIONS ===
- Question: Is it a requirement that in every possible system instance (regardless of the number or distribution of requests and classifications), the Emergency group-processing scenario (i.e., with at least one pending request at each of High, Medium, and Low classifications and only the High-classification requests being processed in a step) must always be possible and realized, or is this scenario only required to be possible in instances/runs where such a distribution of requests exists?
  Why needed: This clarifies whether the EmergencyBypassFIFOScenario and assertEmergencyBypassFIFOReachable must be universally realizable (for all model instances), or only in those instances/runs that explicitly include the necessary coverage of request classifications."""

print("Testing parsing of actual InterpretResults output...")
print("=" * 60)

# Parse BLOCKING QUESTIONS section
questions = parse_user_questions(actual_output, section_name="BLOCKING QUESTIONS")

print(f"Found {len(questions)} question(s) in BLOCKING QUESTIONS section")

if questions:
    for i, q in enumerate(questions, 1):
        print(f"\n{i}. {q[:150]}...")
else:
    print("\nNo questions found!")
    print("\nChecking section content:")
    import re
    pattern = r"===\s*BLOCKING QUESTIONS\s*===(.*?)(?:===|$)"
    match = re.search(pattern, actual_output, re.DOTALL | re.IGNORECASE)
    if match:
        print("Section found:")
        print(match.group(1)[:200])
    else:
        print("Section not found in output!")

print("\n✓ Test complete!")