#!/usr/bin/env python3
"""
Test script to verify BLOCKING QUESTIONS parsing works correctly
"""
from src.utils.qa_parser import parse_user_questions

# Test case 1: Actual BLOCKING QUESTIONS format from log
test_blocking = """=== BLOCKING QUESTIONS ===
- Question: Is it a requirement that in every possible system instance (regardless of the number or distribution of requests and classifications), the Emergency group-processing scenario (i.e., with at least one pending request at each of High, Medium, and Low classifications and only the High-classification requests being processed in a step) must always be possible and realized, or is this scenario only required to be possible in instances/runs where such a distribution of requests exists?
  Why needed: This clarifies whether the EmergencyBypassFIFOScenario and assertEmergencyBypassFIFOReachable must be universally realizable (for all model instances), or only in those instances/runs that explicitly include the necessary coverage of request classifications.
"""

# Test case 2: Numbered format (fallback)
test_numbered = """=== BLOCKING QUESTIONS ===
1. Should Emergency mode allow multiple administrators?
2. Can delegations be revoked during Emergency?
"""

# Test case 3: None
test_none = """=== BLOCKING QUESTIONS ===
None
"""

print("Testing BLOCKING QUESTIONS parsing...")
print("=" * 60)

# Test 1: "- Question:" format
questions1 = parse_user_questions(test_blocking, section_name="BLOCKING QUESTIONS")
print(f"\nTest 1 - '- Question:' format:")
print(f"Found {len(questions1)} question(s)")
if questions1:
    for i, q in enumerate(questions1, 1):
        print(f"{i}. {q[:100]}...")  # First 100 chars

# Test 2: Numbered format
questions2 = parse_user_questions(test_numbered, section_name="BLOCKING QUESTIONS")
print(f"\nTest 2 - Numbered format:")
print(f"Found {len(questions2)} question(s)")
if questions2:
    for i, q in enumerate(questions2, 1):
        print(f"{i}. {q}")

# Test 3: None
questions3 = parse_user_questions(test_none, section_name="BLOCKING QUESTIONS")
print(f"\nTest 3 - None:")
print(f"Found {len(questions3)} question(s)")

# Check if Q61_1 question would match the new parsed question
q61_question = "Is it required that the Emergency group-processing scenario (Emergency mode with at least one pending High-, Medium-, and Low-classification request, and group-processing of all-and-only the High-classification requests) be possible in every valid system instance, or is this only required in instances/scopes where such a distribution of requests exists?"

if questions1:
    from difflib import SequenceMatcher
    similarity = SequenceMatcher(None, questions1[0], q61_question).ratio()
    print(f"\n" + "=" * 60)
    print(f"Similarity between parsed question and Q61_1: {similarity:.2%}")
    print(f"(Should be high for Q&A retrieval to work)")

print("\n✓ Test complete!")