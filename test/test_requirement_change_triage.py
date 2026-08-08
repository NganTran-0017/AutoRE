"""
Requirement-change triage: the shared decision block, RefineFeedback's document
wiring, and the in-iteration [CLASSIFICATION] passthrough.
"""

import asyncio

from src.utils.prompt_manager import PromptManager
from src.workflow import AutoREWorkflow


def test_triage_section_exists_with_all_buckets():
    pm = PromptManager()
    section = pm.get_section("Evaluator", "RequirementChangeTriage")
    for bucket in ("DUPLICATE", "MODELING", "CONSTRAINT", "REQUIREMENT", "UNSURE",
                   "CONTRADICTS"):
        assert bucket in section, f"missing bucket: {bucket}"
    # Bucket 5 must route the unclassifiable case to a taggable question.
    assert "[CLASSIFICATION]" in section
    # 'encoding' was renamed to 'modeling' in the triage block.
    assert "ENCODING" not in section


def test_contradicts_bucket_demands_citable_ids_and_biases_against_firing():
    """A wrongly declared contradiction discards a requirement and nothing
    downstream can recover it; a missed one resurfaces with solver evidence."""
    section = PromptManager().get_section("Evaluator", "RequirementChangeTriage")
    assert "Conflicts with:" in section
    assert "MINIMAL" in section
    assert "err toward NOT declaring" in section


def test_updates_entry_schema_carries_the_conflicts_field():
    """The parser reads this field per entry; without it nothing is declared."""
    section = PromptManager().get_section("Evaluator", "ResponseFormatFeedback")
    assert "Conflicts with:" in section


def test_refine_feedback_prompt_carries_requirements_document():
    pm = PromptManager()
    prompt = pm.render_prompt(
        "Evaluator", "RefineFeedback",
        draft_feedback="DRAFT", user_review="REVIEW",
        requirements_document="DOC_SENTINEL_123",
    )
    assert "DOC_SENTINEL_123" in prompt
    assert "{{requirements_document}}" not in prompt  # placeholder substituted


def test_resolve_classification_questions_passthrough_without_marker():
    # No [CLASSIFICATION] question -> feedback returned unchanged, no prompting.
    wf = AutoREWorkflow.__new__(AutoREWorkflow)
    feedback = (
        "=== REQUIREMENT UPDATES ===\nNone - no requirement updates justified\n\n"
        "=== UPDATED USER QUESTIONS ===\n1. Should timeout be 30s or 60s?\n"
    )
    result = asyncio.run(
        wf._resolve_classification_questions(feedback, "requirements doc")
    )
    assert result == feedback


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All requirement-change-triage tests passed.")


def test_bucket_six_requires_naming_both_sides():
    """A conflict whose own side is described only in prose cannot be attached
    to the requirement it is about, so it is dropped - the contradiction is
    then never put to the user however clearly it was described."""
    section = PromptManager().get_section("Evaluator", "RequirementChangeTriage")
    assert "Name BOTH SIDES" in section
    assert "Target kind & placement" in section


def test_the_updates_schema_demands_a_concrete_target_id():
    section = PromptManager().get_section("Evaluator", "ResponseFormatFeedback")
    assert "Name a CONCRETE id, not `R#`" in section
    assert "has its conflict dropped" in section
