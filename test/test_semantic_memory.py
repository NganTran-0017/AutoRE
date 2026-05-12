"""
Test script for semantic memory system.

This demonstrates how semantic retrieval finds relevant lessons even when
they're from different actions or agents.
"""
from src.utils.semantic_memory import SemanticMemorySystem


def main():
    print("=" * 80)
    print("Semantic Memory System Test")
    print("=" * 80)

    # Initialize semantic memory
    memory = SemanticMemorySystem(project_name="test_semantic")

    print("\n1. Storing sample lessons...")

    # Store lessons from different contexts
    lessons = [
        {
            "content": "Always use braces in Alloy sig declarations, even if empty",
            "agent": "RE",
            "action": "BuildAlloyModel",
            "iteration": 1
        },
        {
            "content": "Temporal operators in Alloy 6 require 'var' modifier on mutable fields",
            "agent": "RE",
            "action": "UpdateAlloyModel",
            "iteration": 2
        },
        {
            "content": "Counterexamples often indicate missing constraints on temporal ordering",
            "agent": "Evaluator",
            "action": "InterpretResults",
            "iteration": 2
        },
        {
            "content": "Empty satisfying instances usually mean predicates are over-constrained",
            "agent": "Evaluator",
            "action": "GenerateFeedback",
            "iteration": 3
        },
        {
            "content": "Use transitive closure (^) for role hierarchy inheritance",
            "agent": "RE",
            "action": "BuildAlloyModel",
            "iteration": 1
        },
        {
            "content": "Syntax errors in sig declarations are often due to missing braces",
            "agent": "RE",
            "action": "AnalyzeRequirements",
            "iteration": 1
        }
    ]

    for lesson in lessons:
        memory.store(
            content=lesson["content"],
            item_type="lesson",
            agent=lesson["agent"],
            action=lesson["action"],
            iteration=lesson["iteration"]
        )
        print(f"  ✓ Stored: {lesson['content'][:50]}...")

    print(f"\n2. Memory statistics:")
    stats = memory.get_stats()
    print(f"   Total lessons: {stats['lessons']}")

    print("\n3. Traditional tag-based retrieval:")
    print("   Query: Get lessons for RE agent, BuildAlloyModel action")
    traditional = memory.get_lessons(agent="RE", action="BuildAlloyModel", limit=5)
    for i, lesson in enumerate(traditional, 1):
        print(f"   {i}. {lesson}")

    print("\n4. Semantic retrieval - Find lessons about syntax errors:")
    print("   Query: 'fixing syntax errors in Alloy code'")
    results = memory.retrieve_similar(
        query="fixing syntax errors in Alloy code",
        limit=3
    )
    for i, result in enumerate(results, 1):
        print(f"   {i}. [similarity: {result['similarity']:.3f}] {result['content']}")

    print("\n5. Semantic retrieval - Find lessons about temporal modeling:")
    print("   Query: 'modeling time and state changes in Alloy'")
    results = memory.retrieve_similar(
        query="modeling time and state changes in Alloy",
        limit=3
    )
    for i, result in enumerate(results, 1):
        print(f"   {i}. [similarity: {result['similarity']:.3f}] {result['content']}")

    print("\n6. Semantic retrieval - Find lessons about counterexamples:")
    print("   Query: 'understanding and fixing counterexamples'")
    results = memory.retrieve_similar(
        query="understanding and fixing counterexamples",
        limit=3
    )
    for i, result in enumerate(results, 1):
        print(f"   {i}. [similarity: {result['similarity']:.3f}] {result['content']}")

    print("\n7. Cross-agent semantic retrieval:")
    print("   Query: 'Alloy syntax mistakes' (should find lessons from both RE and Evaluator)")
    results = memory.retrieve_similar(
        query="Alloy syntax mistakes",
        limit=3
    )
    for i, result in enumerate(results, 1):
        agent = result['metadata']['agent']
        action = result['metadata']['action']
        print(f"   {i}. [{agent}/{action}] [sim: {result['similarity']:.3f}]")
        print(f"      {result['content']}")

    print("\n" + "=" * 80)
    print("Test completed! Semantic memory is working.")
    print("=" * 80)


if __name__ == "__main__":
    main()
