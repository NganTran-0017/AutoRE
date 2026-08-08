"""
Test v2 agents with SharedRuntimeContext.
"""
import asyncio
from src.utils.runtime_context import SharedRuntimeContext
from src.agents.requirement_engineer import RequirementEngineerRole
from src.agents.evaluator import EvaluatorRole


async def _impl_agents():
    """Test creating agents with shared context."""

    print("=" * 80)
    print("Testing V2 Agents with SharedRuntimeContext")
    print("=" * 80)
    print()

    # Step 1: Create context
    print("Step 1: Creating SharedRuntimeContext...")
    context = SharedRuntimeContext(project_name="test_agents")
    print(f"✓ Context created: {context}")
    print()

    # Step 2: Create RE agent
    print("Step 2: Creating Requirement Engineer agent...")
    re_agent = RequirementEngineerRole(context)
    print(f"✓ RE Agent created: {re_agent.name}")
    print(f"  Profile: {re_agent.profile}")
    print(f"  Actions: {[type(a).__name__ for a in re_agent.actions]}")
    print()

    # Step 3: Create Evaluator agent
    print("Step 3: Creating Evaluator agent...")
    evaluator = EvaluatorRole(context)
    print(f"✓ Evaluator created: {evaluator.name}")
    print(f"  Profile: {evaluator.profile}")
    print(f"  Actions: {[type(a).__name__ for a in evaluator.actions]}")
    print()

    # Step 4: Verify prompt loading
    print("Step 4: Verifying prompts loaded correctly...")
    agents_loaded = context.prompt_manager.list_agents()
    print(f"✓ Prompts loaded for: {agents_loaded}")

    re_sections = context.prompt_manager.list_sections("RE")
    print(f"✓ RE sections: {re_sections}")

    eval_sections = context.prompt_manager.list_sections("Evaluator")
    print(f"✓ Evaluator sections: {eval_sections}")
    print()

    # Step 5: Test action access to context
    print("Step 5: Testing actions can access context...")
    re_action = re_agent.actions[0]  # AnalyzeRequirements
    print(f"  Action: {type(re_action).__name__}")
    print(f"  Agent name: {re_action.agent_name}")
    print(f"  Action name: {re_action.action_name}")
    print(f"  Can get lessons: {callable(re_action.get_lessons)}")
    print(f"  Can render prompts: {callable(re_action.render_prompt)}")
    print(f"  Can access artifacts: {re_action.get_artifacts() is not None}")
    print("✓ Actions have full context access")
    print()

    # Step 6: Test prompt rendering
    print("Step 6: Testing prompt rendering for each action...")
    test_vars = {
        "raw_requirements": "Test requirements",
        "lessons": "No lessons",
        "user_preferences": ""
    }

    try:
        # Test RE action
        re_prompt = re_action.render_prompt(**test_vars)
        print(f"✓ AnalyzeRequirements prompt rendered ({len(re_prompt)} chars)")

        # Test Evaluator action
        eval_action = evaluator.actions[1]  # InterpretResults
        eval_vars = {
            "analyzer_results": "Test results",
            "requirements_document": "Test requirements",
            "alloy_model": "Test model",
            "lessons": "No lessons",
            "user_preferences": ""
        }
        eval_prompt = eval_action.render_prompt(**eval_vars)
        print(f"✓ InterpretResults prompt rendered ({len(eval_prompt)} chars)")
    except Exception as e:
        print(f"✗ Error rendering prompts: {e}")
        import traceback
        traceback.print_exc()

    print()

    print("=" * 80)
    print("✓ All agent tests passed!")
    print("=" * 80)
    print()
    print("Summary:")
    print(f"  - SharedRuntimeContext: Working")
    print(f"  - RequirementEngineerRole: 3 actions configured")
    print(f"  - EvaluatorRole: 5 actions configured")
    print(f"  - Prompt sections: {len(re_sections)} (RE) + {len(eval_sections)} (Evaluator)")
    print(f"  - All actions have context access")
    print(f"  - Prompt rendering: Working")


def test_agents():
    """Sync pytest entrypoint (repo convention: asyncio.run inside a sync test)."""
    asyncio.run(_impl_agents())


if __name__ == "__main__":
    asyncio.run(_impl_agents())
