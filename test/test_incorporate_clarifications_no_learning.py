"""Test that IncorporateClarifications action does not include learning instructions."""

from src.utils.prompt_manager import PromptManager

def test_no_learning_in_incorporate_clarifications():
    """Test that learning instructions are excluded from IncorporateClarifications."""
    
    pm = PromptManager()
    
    print("Testing IncorporateClarifications Learning Exclusion")
    print("=" * 80)
    
    # Render prompt for IncorporateClarifications
    test_vars = {
        "requirements_document": "Test requirements",
        "user_clarifications": "Test clarifications",
        "lessons": "Test lessons",
    }
    
    try:
        prompt = pm.render_prompt("RE", "IncorporateClarifications", **test_vars)
        
        # Check if learning instructions are present
        has_learning_section = "[LESSON]" in prompt or "LEARNING:" in prompt
        has_event_marker = "[EVENT]" in prompt
        
        if not has_learning_section and not has_event_marker:
            print("✓ Learning instructions successfully excluded from IncorporateClarifications")
            print(f"✓ Prompt length: {len(prompt)} characters")
            return True
        else:
            print("✗ Learning instructions still present in prompt")
            if has_learning_section:
                print("  - Found LEARNING section")
            if has_event_marker:
                print("  - Found [EVENT] marker")
            return False
            
    except Exception as e:
        print(f"✗ Error rendering prompt: {str(e)}")
        return False

def test_other_actions_still_have_learning():
    """Verify that other RE actions still include learning instructions."""
    
    pm = PromptManager()
    
    print("\nTesting Other RE Actions Still Have Learning")
    print("=" * 80)
    
    test_cases = [
        ("AnalyzeRequirements", {"raw_requirements": "test"}),
        ("BuildAlloyModel", {"requirements_document": "test", "user_feedback": "", "lessons": "", "user_preferences": ""}),
    ]
    
    all_passed = True
    
    for action_name, test_vars in test_cases:
        try:
            prompt = pm.render_prompt("RE", action_name, **test_vars)
            
            has_learning = "[LESSON]" in prompt or "LEARNING:" in prompt
            
            if has_learning:
                print(f"✓ {action_name:30} still has learning instructions")
            else:
                print(f"✗ {action_name:30} missing learning instructions")
                all_passed = False
                
        except Exception as e:
            print(f"✗ {action_name:30} ERROR: {str(e)}")
            all_passed = False
    
    return all_passed

if __name__ == "__main__":
    result1 = test_no_learning_in_incorporate_clarifications()
    result2 = test_other_actions_still_have_learning()
    
    print("\n" + "=" * 80)
    if result1 and result2:
        print("\n✓✓✓ All tests passed!")
        exit(0)
    else:
        print("\n✗✗✗ Some tests failed")
        exit(1)
