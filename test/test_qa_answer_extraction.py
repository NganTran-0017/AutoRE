"""
Integration test for Q&A answer extraction bug fix.

This tests the fix for the issue where all Q&A records from the same iteration
were receiving the full combined answer text instead of individual numbered answers.
"""
import pytest
from src.utils.qa_parser import parse_user_feedback_for_answers
from src.utils.qa_database import QARecord, QADatabase, create_qa_id
from pathlib import Path
import tempfile
import json


class TestQAAnswerExtraction:
    """Test individual answer extraction for Q&A records."""

    def test_numbered_answers_extracted_individually(self):
        """
        Test that numbered answers are correctly split and assigned to individual questions.

        This is the main bug fix test - previously all questions would get the full
        combined text containing all answers.
        """
        user_feedback = """1. Yes, it is a strict system invariant that every request must eventually be processed. NO indefinitely pending requests allowed.
2. Every approvalStatus of a request must occur within a unique state.
3. Model 1 specific Emergency scenario where there is at least one Request of each classification (High, Medium, Low) to fully verify the Emergency processing order constraints. In other scenarios, it is acceptable for some classifications to be absent in some Emergency states.
4. Yes, since both happens at the same time step: a request is processed, which is either approved or denied by a specific user at the same time.
5. No, indefinitely pending request is not allowed."""

        questions = [
            "In Emergency mode, must all requests present at the start of Emergency be processed before Emergency ends, or can some remain unprocessed until a later (Normal) state?",
            "Is it permissible for requests to have their approvalStatus set without being associated with a specific State (processedIn), or must approval/denial always be tied to a processing state for audit purposes?",
            "For verification purposes, should the model enforce that, during Emergency, at least one request of each classification (High, Medium, Low) is present, or is it sufficient to allow empty or partial classification sets?",
            "Should processedIn relationship and approvalStatus assignment occur simultaneously, or can there be temporal separation?",
            "Can requests remain in pending state indefinitely?"
        ]

        answers = parse_user_feedback_for_answers(user_feedback, questions)

        # Each question should get its own individual answer
        assert len(answers) == 5

        # Question 1 should only contain answer 1
        assert "strict system invariant" in answers[0]
        assert "eventually be processed" in answers[0]
        assert "unique state" not in answers[0]  # Should NOT contain answer 2

        # Question 2 should only contain answer 2
        assert "unique state" in answers[1]
        assert "approvalStatus" in answers[1]
        assert "Emergency scenario" not in answers[1]  # Should NOT contain answer 3

        # Question 3 should only contain answer 3
        assert "Emergency scenario" in answers[2]
        assert "High, Medium, Low" in answers[2]
        assert "same time step" not in answers[2]  # Should NOT contain answer 4

        # Question 4 should only contain answer 4
        assert "same time step" in answers[3]
        assert "approved or denied" in answers[3]
        assert "indefinitely pending" not in answers[3]  # Should NOT contain answer 5

        # Question 5 should only contain answer 5
        assert "indefinitely pending request is not allowed" in answers[4]
        assert "unique state" not in answers[4]  # Should NOT contain answer 2

    def test_format_with_forward_slash(self):
        """Test parsing answers formatted with forward slash (1/ answer 2/ answer)."""
        user_feedback = """1/ During Emergency mode, all high-classification requests must be processed concurrently.
2/ No, the request processor cannot be the submitter, and the processor must have strictly higher clearance.
3/ Yes, users are permitted to hold multiple mutually exclusive roles through delegation."""

        questions = [
            "How should high-classification requests be processed?",
            "Can a processor be the submitter?",
            "Can users hold mutually exclusive roles?"
        ]

        answers = parse_user_feedback_for_answers(user_feedback, questions)

        assert len(answers) == 3
        assert "high-classification requests must be processed concurrently" in answers[0]
        assert "processor cannot be the submitter" in answers[1]
        assert "mutually exclusive roles through delegation" in answers[2]

        # Verify no cross-contamination
        assert "processor cannot be the submitter" not in answers[0]
        assert "mutually exclusive roles" not in answers[1]

    def test_format_with_space_only(self):
        """Test parsing answers formatted with space only (1 answer\\n2 answer)."""
        user_feedback = """1 During Emergency, users can hold mutually exclusive roles only via delegation.
2 The processor's clearance must be strictly higher than the request's classification."""

        questions = [
            "Can users hold mutually exclusive roles?",
            "What is the clearance requirement?"
        ]

        answers = parse_user_feedback_for_answers(user_feedback, questions)

        assert len(answers) == 2
        assert "mutually exclusive roles only via delegation" in answers[0]
        assert "strictly higher than the request's classification" in answers[1]

        # Verify separation
        assert "clearance must be strictly higher" not in answers[0]

    def test_mixed_format_prioritizes_period(self):
        """Test that period format is matched first when multiple formats present."""
        # If text contains both "1." and "1 ", the period format should take precedence
        user_feedback = """1. This is answer one.
2. This is answer two with number 1 reference."""

        questions = [
            "Question 1?",
            "Question 2?"
        ]

        answers = parse_user_feedback_for_answers(user_feedback, questions)

        assert len(answers) == 2
        assert "This is answer one." in answers[0]
        assert "This is answer two" in answers[1]
        assert "number 1 reference" in answers[1]  # The "1" inside should not split it

    def test_unnumbered_feedback_fallback(self):
        """
        Test that unnumbered feedback correctly falls back to using full text for all questions.

        This ensures backward compatibility when users don't provide numbered answers.
        """
        user_feedback = "All requests must follow the priority order and require proper clearance verification."

        questions = [
            "What is the request processing order?",
            "What clearance requirements apply?"
        ]

        answers = parse_user_feedback_for_answers(user_feedback, questions)

        # Both should get the full text since it's not numbered
        assert len(answers) == 2
        assert answers[0] == answers[1]
        assert "priority order" in answers[0]
        assert "clearance verification" in answers[1]

    def test_multiline_numbered_answers(self):
        """Test that multiline numbered answers are correctly parsed."""
        user_feedback = """1. During Emergency, users can hold mutually exclusive roles only via delegation.
A user can never be directly assigned 2 roles that are mutually exclusive to each other.
2. The processor's clearance must be strictly higher (>) than the request's classification and submitter."""

        questions = [
            "Can users be assigned mutually exclusive roles?",
            "What is the clearance requirement for processors?"
        ]

        answers = parse_user_feedback_for_answers(user_feedback, questions)

        assert len(answers) == 2

        # Answer 1 should include both lines
        assert "mutually exclusive roles" in answers[0]
        assert "only via delegation" in answers[0]
        assert "never be directly assigned" in answers[0]

        # Answer 2 should be separate
        assert "strictly higher" in answers[1]
        assert "via delegation" not in answers[1]

    def test_real_world_bug_scenario_from_iteration_33(self):
        """
        Test the exact scenario from the bug report where Q33_1, Q33_2, Q33_3
        all had the same combined answer.
        """
        user_feedback = """1. Yes, it is a strict system invariant that every request must eventually be processed. NO indefinitely pending requests allowed.
2. Every approvalStatus of a request must occur within a unique state.
3. Model 1 specific Emergency scenario where there is at least one Request of each classification (High, Medium, Low) to fully verify the Emergency processing order constraints. In other scenarios, it is acceptable for some classifications to be absent in some Emergency states.
4. Yes, since both happens at the same time step: a request is processed, which is either approved or denied by a specific user at the same time.
5. No, indefinitely pending request is not allowed."""

        questions = [
            "In Emergency mode, must all requests present at the start of Emergency be processed before Emergency ends, or can some remain unprocessed until a later (Normal) state?",
            "Is it permissible for requests to have their approvalStatus set without being associated with a specific State (processedIn), or must approval/denial always be tied to a processing state for audit purposes?",
            "For verification purposes, should the model enforce that, during Emergency, at least one request of each classification (High, Medium, Low) is present, or is it sufficient to allow empty or partial classification sets?"
        ]

        answers = parse_user_feedback_for_answers(user_feedback, questions)

        # BEFORE the fix: all 3 would have the full combined text
        # AFTER the fix: each should have only its corresponding numbered answer

        # Verify Q33_1 gets only answer 1
        assert "strict system invariant" in answers[0]
        assert "every request must eventually be processed" in answers[0]
        assert "unique state" not in answers[0]  # Should NOT contain answer 2
        assert "Emergency scenario" not in answers[0]  # Should NOT contain answer 3

        # Verify Q33_2 gets only answer 2
        assert "unique state" in answers[1]
        assert answers[1].startswith("Every approvalStatus")
        assert "Emergency scenario" not in answers[1]
        assert "strict system invariant" not in answers[1]  # Should NOT contain answer 1

        # Verify Q33_3 gets only answer 3
        assert "Emergency scenario" in answers[2]
        assert "High, Medium, Low" in answers[2]
        assert "unique state" not in answers[2]
        assert "strict system invariant" not in answers[2]  # Should NOT contain answer 1

    def test_real_world_format_variations(self):
        """Test various real-world formatting variations users might use."""

        # Test with extra whitespace
        feedback1 = """1.  Answer with extra space
2.    Answer with many spaces"""
        questions1 = ["Q1", "Q2"]
        answers1 = parse_user_feedback_for_answers(feedback1, questions1)
        assert "extra space" in answers1[0]
        assert "many spaces" in answers1[1]

        # Test with forward slash and no space
        feedback2 = """1/Answer without space after slash
2/Another answer"""
        questions2 = ["Q1", "Q2"]
        answers2 = parse_user_feedback_for_answers(feedback2, questions2)
        assert "without space" in answers2[0]
        assert "Another answer" in answers2[1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
