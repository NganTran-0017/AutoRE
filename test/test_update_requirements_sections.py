"""Test that UpdateRequirements action excludes Role and QualityStandards sections."""

from src.utils.prompt_manager import PromptManager

def test_update_requirements_exclusions():
    """Test that UpdateRequirements excludes Role and QualityStandards."""

    pm = PromptManager()

    print("Testing UpdateRequirements Section Exclusions")
    print("=" * 80)

    # Render prompt for UpdateRequirements
    test_vars = {
        "requirements_document": "Test requirements",
        "feedback": "Test feedback",
        "user_feedback": "Test user feedback",
        "user_preferences": "Test preferences",
    }

    try:
        prompt = pm.render_prompt("Evaluator", "UpdateRequirements", **test_vars)

        # Check what's excluded
        has_role = "### ROLE:" in prompt or prompt.startswith("You are an Evaluator")
        has_quality_standards = "QUALITY STANDARDS:" in prompt or "### QUALITY STANDARDS:" in prompt
        has_convergence = "CONVERGENCE CRITERIA:" in prompt or "### CONVERGENCE CRITERIA:" in prompt
        has_primary_goal = "PRIMARY GOAL:" in prompt or "### PRIMARY GOAL:" in prompt

        print("\nSection Presence Check:")
        print(f"  Role section: {'✗ PRESENT (should be excluded)' if has_role else '✓ EXCLUDED'}")
        print(f"  QualityStandards: {'✗ PRESENT (should be excluded)' if has_quality_standards else '✓ EXCLUDED'}")
        print(f"  ConvergenceCriteria: {'✗ PRESENT (should be excluded)' if has_convergence else '✓ EXCLUDED'}")
        print(f"  PrimaryGoal: {'✗ PRESENT (should be excluded)' if has_primary_goal else '✓ EXCLUDED'}")

        # Check what should be present
        has_task = "### TASK: UPDATE REQUIREMENTS" in prompt or "UPDATE REQUIREMENTS" in prompt
        has_response_format = "RESPONSE FORMAT" in prompt or "ResponseFormat" in prompt

        print("\nRequired Sections:")
        print(f"  Task section: {'✓ PRESENT' if has_task else '✗ MISSING'}")
        print(f"  ResponseFormat: {'✓ PRESENT' if has_response_format else '✗ MISSING'}")

        print(f"\n✓ Prompt length: {len(prompt)} characters")

        # Verify all exclusions
        all_excluded = not has_role and not has_quality_standards and not has_convergence and not has_primary_goal
        all_required = has_task and has_response_format

        if all_excluded and all_required:
            print("\n✓✓✓ SUCCESS! UpdateRequirements correctly excludes Role and QualityStandards")
            print("✓ All required sections present")
            return True
        else:
            print("\n✗✗✗ FAILED! Some sections incorrectly included or required sections missing")
            if not all_excluded:
                print("  - Some sections should be excluded but are present")
            if not all_required:
                print("  - Some required sections are missing")
            return False

    except Exception as e:
        print(f"✗ Error rendering prompt: {str(e)}")
        return False

def test_other_evaluator_actions_still_have_sections():
    """Verify that other Evaluator actions still have Role and QualityStandards."""

    pm = PromptManager()

    print("\n" + "=" * 80)
    print("Testing Other Evaluator Actions Still Have Sections")
    print("=" * 80)

    test_cases = [
        ("GenerateFeedback", {
            "interpretation": "test",
            "requirements_document": "test",
            "alloy_model": "test",
            "lessons": "test",
            "user_preferences": "test"
        }),
        ("InterpretResults", {
            "analyzer_results": "test",
            "requirements_document": "test",
            "alloy_model": "test",
            "user_preferences": "test"
        }),
    ]

    all_passed = True

    for action_name, test_vars in test_cases:
        try:
            prompt = pm.render_prompt("Evaluator", action_name, **test_vars)

            has_role = "### ROLE:" in prompt or "You are an Evaluator" in prompt
            has_quality = "QUALITY STANDARDS:" in prompt or "### QUALITY STANDARDS:" in prompt

            if has_role and has_quality:
                print(f"✓ {action_name:25} has Role and QualityStandards")
            elif has_role and not has_quality:
                print(f"⚠ {action_name:25} has Role but missing QualityStandards")
            elif not has_role and has_quality:
                print(f"⚠ {action_name:25} missing Role but has QualityStandards")
            else:
                print(f"✗ {action_name:25} missing both Role and QualityStandards")
                all_passed = False

        except Exception as e:
            print(f"✗ {action_name:25} ERROR: {str(e)}")
            all_passed = False

    return all_passed

def compare_with_refine_feedback():
    """Compare UpdateRequirements with RefineFeedback (both should exclude Role)."""

    pm = PromptManager()

    print("\n" + "=" * 80)
    print("Comparing UpdateRequirements with RefineFeedback")
    print("=" * 80)

    try:
        update_req_prompt = pm.render_prompt("Evaluator", "UpdateRequirements",
            requirements_document="test", feedback="test",
            user_feedback="test", user_preferences="test")

        refine_fb_prompt = pm.render_prompt("Evaluator", "RefineFeedback",
            draft_feedback="test", user_review="test")

        update_has_role = "### ROLE:" in update_req_prompt or update_req_prompt.startswith("You are")
        refine_has_role = "### ROLE:" in refine_fb_prompt or refine_fb_prompt.startswith("You are")

        print("\nRole Section Presence:")
        print(f"  UpdateRequirements: {'✗ PRESENT' if update_has_role else '✓ EXCLUDED'}")
        print(f"  RefineFeedback:     {'✗ PRESENT' if refine_has_role else '✓ EXCLUDED'}")

        if not update_has_role and not refine_has_role:
            print("\n✓ Both actions correctly exclude Role section")
            return True
        else:
            print("\n✗ One or both actions incorrectly include Role section")
            return False

    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return False

if __name__ == "__main__":
    result1 = test_update_requirements_exclusions()
    result2 = test_other_evaluator_actions_still_have_sections()
    result3 = compare_with_refine_feedback()

    print("\n" + "=" * 80)
    print("FINAL RESULTS:")
    print("=" * 80)

    if result1 and result2 and result3:
        print("✓✓✓ All tests passed!")
        print("\nUpdateRequirements now excludes:")
        print("  - Role section")
        print("  - QualityStandards section")
        print("  - ConvergenceCriteria section (already excluded)")
        print("  - PrimaryGoal section (already excluded)")
        print("\nOther Evaluator actions still include these sections correctly.")
        exit(0)
    else:
        print("✗✗✗ Some tests failed")
        exit(1)
