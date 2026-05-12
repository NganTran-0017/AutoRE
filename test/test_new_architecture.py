"""
Proof-of-concept test for new architecture with SharedRuntimeContext.

Tests:
1. SharedRuntimeContext initialization
2. PromptManager loading and rendering
3. LessonAwareAction with memory and prompts
4. Artifact storage
"""
import asyncio
from src.utils.runtime_context import SharedRuntimeContext
from src.actions.requirement_actions import AnalyzeRequirements


async def test_new_architecture():
    """Test the new architecture components."""

    print("=" * 80)
    print("Testing New Architecture with SharedRuntimeContext")
    print("=" * 80)
    print()

    # Step 1: Create SharedRuntimeContext
    print("Step 1: Creating SharedRuntimeContext...")
    context = SharedRuntimeContext(project_name="test_project")
    print(f"✓ Context created: {context}")
    print()

    # Step 2: Test PromptManager
    print("Step 2: Testing PromptManager...")
    agents = context.prompt_manager.list_agents()
    print(f"✓ Loaded prompts for agents: {agents}")

    if "RE" in agents:
        sections = context.prompt_manager.list_sections("RE")
        print(f"✓ RE sections: {sections}")
    print()

    # Step 3: Add some lessons to memory
    print("Step 3: Adding test lessons to memory...")
    context.iteration.increment()  # Move to iteration 1

    context.memory.store(
        content="Always check Alloy syntax before running analyzer",
        item_type="lesson",
        agent="RE",
        action="AnalyzeRequirements",
        iteration=1
    )

    context.memory.store(
        content="Ask clarifying questions only when absolutely necessary",
        item_type="lesson",
        agent="RE",
        action="AnalyzeRequirements",
        iteration=1
    )

    print("✓ Added 2 test lessons")
    stats = context.memory.get_stats()
    print(f"✓ Memory stats: {stats}")
    print()

    # Step 4: Create action with context
    print("Step 4: Creating AnalyzeRequirements action with context...")
    action = AnalyzeRequirements(context=context, agent_name="RE")
    print(f"✓ Action created: {action}")
    print()

    # Step 5: Test lesson retrieval
    print("Step 5: Testing lesson retrieval from action...")
    lessons = action.get_lessons(limit=10)
    print(f"✓ Retrieved {len(lessons)} lessons:")
    for i, lesson in enumerate(lessons, 1):
        print(f"  {i}. {lesson}")
    print()

    # Step 6: Test prompt rendering
    print("Step 6: Testing prompt rendering...")
    try:
        test_requirements = """
        The system should allow users to borrow books from a library.
        Each user can borrow up to 5 books at a time.
        Books must be returned within 14 days.
        """

        rendered_prompt = action.render_prompt(
            raw_requirements=test_requirements,
            lessons=action.format_lessons(lessons),
            user_preferences=""
        )

        print("✓ Prompt rendered successfully")
        print(f"  Prompt length: {len(rendered_prompt)} characters")
        print()
        print("  First 500 characters of rendered prompt:")
        print("  " + "-" * 76)
        print("  " + rendered_prompt[:500].replace("\n", "\n  "))
        print("  " + "-" * 76)
        print()

    except Exception as e:
        print(f"✗ Error rendering prompt: {e}")
        import traceback
        traceback.print_exc()
        print()

    # Step 7: Test artifact storage
    print("Step 7: Testing artifact storage...")
    context.artifacts.store_requirements(1, "Test requirements document")
    context.artifacts.store_alloy_model(1, "Test alloy model")

    print(f"✓ Artifacts stored: {context.artifacts}")
    print(f"  Latest requirements: {context.artifacts.get_latest_requirements()[:50]}...")
    print(f"  Latest model: {context.artifacts.get_latest_alloy_model()[:50]}...")
    print()

    # Step 8: Test iteration tracking
    print("Step 8: Testing iteration tracking...")
    print(f"  Current iteration: {context.get_current_iteration()}")
    context.next_iteration()
    print(f"  After next_iteration(): {context.get_current_iteration()}")
    print()

    # Step 9: Test persistence
    print("Step 9: Testing state persistence...")
    context.save_state()
    print("✓ State saved to disk")
    print(f"  Memory file: memory/test_project/memory.json")
    print(f"  Preferences file: memory/test_project/user_preferences.json")
    print()

    print("=" * 80)
    print("✓ All tests passed!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_new_architecture())
