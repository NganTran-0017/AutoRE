"""Test that RefineFeedback action does not include Role section."""

from src.utils.prompt_manager import PromptManager

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
        
        # Check if Role section is present
        has_role_section = "### ROLE:" in prompt or "You are an Evaluator" in prompt
        
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
            "requirements_document": "test",
            "alloy_model": "test",
            "user_preferences": ""
        }),
        ("GenerateFeedback", {
            "interpretation": "test",
            "requirements_document": "test",
            "alloy_model": "test",
            "lessons": "",
            "user_preferences": ""
        }),
    ]
    
    all_passed = True
    
    for action_name, test_vars in test_cases:
        try:
            prompt = pm.render_prompt("Evaluator", action_name, **test_vars)
            
            has_role = "### ROLE:" in prompt or "You are an Evaluator" in prompt
            
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
