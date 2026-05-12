"""Test that response format sections are correctly separated."""

from src.utils.prompt_manager import PromptManager

def test_response_format_sections():
    """Test that each Evaluator action gets the correct response format."""
    
    pm = PromptManager()
    
    # Test cases: (action_name, expected_section_name)
    test_cases = [
        ("InterpretResults", "ResponseFormatInterpretation"),
        ("GenerateFeedback", "ResponseFormatFeedback"),
        ("UpdateRequirements", "ResponseFormatRequirements"),
        ("RefineFeedback", "ResponseFormatFeedback"),
    ]
    
    print("Testing Response Format Section Separation")
    print("=" * 80)
    
    all_passed = True
    
    for action_name, expected_section in test_cases:
        # Get the sections available for Evaluator
        evaluator_sections = pm.prompts.get("Evaluator", {})
        
        # Check if the expected section exists
        if expected_section in evaluator_sections:
            print(f"✓ {action_name:25} -> {expected_section:35} EXISTS")
        else:
            print(f"✗ {action_name:25} -> {expected_section:35} MISSING")
            all_passed = False
    
    print("\n" + "=" * 80)
    
    # Test that a prompt can be rendered for each action
    print("\nTesting Prompt Rendering:")
    print("=" * 80)
    
    for action_name, expected_section in test_cases:
        try:
            # Create comprehensive variables needed for rendering
            test_vars = {
                "analyzer_results": "test",
                "requirements_document": "test requirements",
                "alloy_model": "test model",
                "user_preferences": "test prefs",
                "interpretation": "test interpretation",
                "feedback": "test feedback",
                "draft_feedback": "test draft",
                "user_review": "test review",
                "lessons": "test lessons",
                "user_feedback": "test user feedback",
                "evaluation_feedback": "test eval feedback",
            }
            
            prompt = pm.render_prompt("Evaluator", action_name, **test_vars)
            
            # Check if the expected format is in the prompt
            if expected_section == "ResponseFormatInterpretation" and "SYNTAX STATUS:" in prompt:
                print(f"✓ {action_name:25} renders with InterpretResults format")
            elif expected_section == "ResponseFormatFeedback" and "=== VERIFICATION STATUS ===" in prompt:
                print(f"✓ {action_name:25} renders with Feedback format")
            elif expected_section == "ResponseFormatRequirements" and "SYSTEM OVERVIEW" in prompt:
                print(f"✓ {action_name:25} renders with Requirements format")
            else:
                print(f"✗ {action_name:25} format markers not found in prompt")
                all_passed = False
                
        except Exception as e:
            print(f"✗ {action_name:25} ERROR: {str(e)}")
            all_passed = False
    
    print("\n" + "=" * 80)
    
    if all_passed:
        print("\n✓✓✓ All tests passed! Response formats correctly separated.")
        return True
    else:
        print("\n✗✗✗ Some tests failed.")
        return False

if __name__ == "__main__":
    success = test_response_format_sections()
    exit(0 if success else 1)
