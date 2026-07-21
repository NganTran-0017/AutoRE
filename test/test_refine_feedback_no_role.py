"""Test that RefineFeedback action does not include Role section."""

from src.utils.prompt_manager import PromptManager


def shared_role_present(pm: PromptManager, prompt: str) -> bool:
    """Check whether the shared [SECTION: Role] content was prepended to a prompt.

    Note: some action sections (e.g. RefineFeedback) legitimately carry their own
    focused "You are an Evaluator..." intro line, so a phrase heuristic misfires;
    compare against the actual Role section content instead.
    """
    role = pm.prompts.get("Evaluator", {}).get("Role", "").strip()
    if not role:
        return False
    return role.splitlines()[0].strip() in prompt


def test_no_role_in_refine_feedback():
    """Test that Role section is excluded from RefineFeedback."""
    
    pm = PromptManager()
    
    print("Testing RefineFeedback Role Exclusion")
    print("=" * 80)
    
    # Render prompt for RefineFeedback
    test_vars = {
        "draft_feedback": "Test draft feedback",
        "user_review": "Test user review",
        "lessons": "Test lessons",
        "user_preferences": "Test preferences",
    }
    
    try:
        prompt = pm.render_prompt("Evaluator", "RefineFeedback", **test_vars)
        
        # Check if the shared Role section is present (the RefineFeedback section
        # itself contains a focused intro line, which is expected and allowed)
        has_role_section = shared_role_present(pm, prompt)
        
        if not has_role_section:
            print("✓ Role section successfully excluded from RefineFeedback")
            print(f"✓ Prompt length: {len(prompt)} characters")
            return True
        else:
            print("✗ Role section still present in prompt")
            return False
            
    except Exception as e:
        print(f"✗ Error rendering prompt: {str(e)}")
        return False

def test_other_evaluator_actions_have_role():
    """Verify that other Evaluator actions still include Role section."""
    
    pm = PromptManager()
    
    print("\nTesting Other Evaluator Actions Still Have Role")
    print("=" * 80)
    
    test_cases = [
        ("InterpretResults", {
            "analyzer_results": "test",
            "regression_log": "test regression log",
            "requirements_document": "test",
            "alloy_model": "test",
            "user_preferences": ""
        }),
        ("GenerateSemanticFeedback", {
            "interpretation": "test",
            "requirements_document": "test",
            "alloy_model": "test",
            "lessons": "",
            "failed_fix_history": "None - this is the first attempt.",
            "relevant_qa": "No relevant prior Q&A pairs found.",
            "user_preferences": ""
        }),
    ]
    
    all_passed = True
    
    for action_name, test_vars in test_cases:
        try:
            prompt = pm.render_prompt("Evaluator", action_name, **test_vars)
            
            has_role = shared_role_present(pm, prompt)
            
            if has_role:
                print(f"✓ {action_name:30} still has Role section")
            else:
                print(f"✗ {action_name:30} missing Role section")
                all_passed = False
                
        except Exception as e:
            print(f"✗ {action_name:30} ERROR: {str(e)}")
            all_passed = False
    
    return all_passed

if __name__ == "__main__":
    result1 = test_no_role_in_refine_feedback()
    result2 = test_other_evaluator_actions_have_role()
    
    print("\n" + "=" * 80)
    if result1 and result2:
        print("\n✓✓✓ All tests passed!")
        print("\nRefineFeedback now has a more focused prompt without Role context.")
        exit(0)
    else:
        print("\n✗✗✗ Some tests failed")
        exit(1)
