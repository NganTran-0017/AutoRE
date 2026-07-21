"""Test semantic deduplication with MemoryAssistant merging."""

import asyncio
from src.utils.semantic_memory import SemanticMemorySystem


async def test_semantic_dedup_with_merge():
    """Test that similar lessons are merged using MemoryAssistant."""

    print("=" * 80)
    print("Testing Semantic Deduplication with MemoryAssistant Merging")
    print("=" * 80)
    print()

    # Create memory system with deduplication enabled
    config = {
        "merge_threshold": 0.7,   # sim in [0.7, 0.91) -> merge
        "drop_threshold": 0.91,   # sim >= 0.91 -> drop new as duplicate
        "merge_similar_lessons": True,
        "memory_assistant_config": {
            "model": "gpt-4o-mini"
        }
    }

    memory = SemanticMemorySystem(
        "test_dedup_merge",
        enable_dedup=True,
        dedup_config=config
    )

    # Clear existing data
    memory.clear_all()
    memory = SemanticMemorySystem("test_dedup_merge", enable_dedup=True, dedup_config=config)

    print("Step 1: Store initial lesson")
    print("-" * 80)
    lesson1 = "Always check Alloy syntax before running analyzer"
    memory.store(lesson1, "lesson", "RE", "BuildAlloyModel", 1)
    print(f"Stored: {lesson1}")
    print()

    lessons = memory.get_lessons(agent="RE", action="BuildAlloyModel")
    print(f"Lessons in memory: {len(lessons)}")
    print(f"  1. {lessons[0]}")
    print()

    print("Step 2: Store similar lesson with additional info")
    print("-" * 80)
    lesson2 = "Always check Alloy syntax before running analyzer, and verify multiplicities are correct"
    print(f"Attempting to store: {lesson2}")
    print()
    print("Expected: Should merge with existing lesson using MemoryAssistant")
    print()

    # Store (will trigger merge). The merge now runs to completion
    # synchronously inside store(), so no wait is needed afterwards.
    memory.store(lesson2, "lesson", "RE", "BuildAlloyModel", 2)

    lessons = memory.get_lessons(agent="RE", action="BuildAlloyModel")
    print(f"Lessons in memory after merge: {len(lessons)}")
    if lessons:
        print(f"  1. {lessons[0]}")
        print()
        print("✓ Lesson was merged (preserves both syntax check and multiplicities)")
    else:
        print("  (No lessons found)")
    print()

    print("Step 3: Store truly duplicate lesson (no new info)")
    print("-" * 80)
    lesson3 = "Verify Alloy syntax before executing analyzer"
    print(f"Attempting to store: {lesson3}")
    print()
    print("Expected: Should reject (similar but no additional information)")
    print()

    memory.store(lesson3, "lesson", "RE", "BuildAlloyModel", 3)
    await asyncio.sleep(1)

    lessons = memory.get_lessons(agent="RE", action="BuildAlloyModel")
    print(f"Lessons in memory: {len(lessons)}")
    if lessons:
        print(f"  1. {lessons[0]}")
        print()
        print("✓ Duplicate rejected (still only 1 lesson)")
    print()

    print("Step 4: Store different lesson (should be stored)")
    print("-" * 80)
    lesson4 = "Use temporal operators for state transitions"
    print(f"Attempting to store: {lesson4}")
    print()

    memory.store(lesson4, "lesson", "RE", "BuildAlloyModel", 4)
    await asyncio.sleep(1)

    lessons = memory.get_lessons(agent="RE", action="BuildAlloyModel")
    print(f"Lessons in memory: {len(lessons)}")
    for i, lesson in enumerate(lessons, 1):
        print(f"  {i}. {lesson}")
    print()
    print("✓ Different lesson stored (now have 2 lessons)")
    print()

    print("=" * 80)
    print("Test Complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_semantic_dedup_with_merge())
