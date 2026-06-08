"""
Unit tests for QA parser functions.
"""
import pytest
from src.utils.qa_parser import (
    parse_user_questions,
    parse_qa_updates,
    parse_reused_qids,
    extract_question_context,
    parse_user_feedback_for_answers,
    format_qa_updates_for_display
)


class TestParseUserQuestions:
    """Test parse_user_questions function."""

    def test_parse_basic_questions(self):
        """Test parsing basic numbered questions."""
        response = """
Some other text

=== USER QUESTIONS ===
1. Should Emergency mode require exactly 2 administrators?
2. Can delegations be revoked during Emergency?
3. What is the maximum duration for Emergency mode?

=== SOME OTHER SECTION ===
More text
"""
        questions = parse_user_questions(response, "USER QUESTIONS")
        assert len(questions) == 3
        assert questions[0] == "Should Emergency mode require exactly 2 administrators?"
        assert questions[1] == "Can delegations be revoked during Emergency?"
        assert questions[2] == "What is the maximum duration for Emergency mode?"

    def test_parse_updated_user_questions(self):
        """Test parsing from UPDATED USER QUESTIONS section."""
        response = """
=== UPDATED USER QUESTIONS ===
1. Should role hierarchy be enforced?
2. Can users delegate their own permissions?
"""
        questions = parse_user_questions(response, "UPDATED USER QUESTIONS")
        assert len(questions) == 2
        assert "role hierarchy" in questions[0]

    def test_parse_no_questions(self):
        """Test when no questions section exists."""
        response = """
Some text without questions section
"""
        questions = parse_user_questions(response, "USER QUESTIONS")
        assert len(questions) == 0

    def test_parse_none_questions(self):
        """Test when section says 'None'."""
        response = """
=== USER QUESTIONS ===
None
"""
        questions = parse_user_questions(response, "USER QUESTIONS")
        assert len(questions) == 0

    def test_parse_multiline_questions(self):
        """Test parsing questions that span multiple lines."""
        response = """
=== USER QUESTIONS ===
1. Should Emergency mode allow multiple
   administrators, or require exactly two?
2. Can delegations persist after Emergency?
"""
        questions = parse_user_questions(response, "USER QUESTIONS")
        assert len(questions) == 2
        # Multiline should be joined into single line
        assert "multiple administrators" in questions[0]
        assert "exactly two" in questions[0]


class TestParseQAUpdates:
    """Test parse_qa_updates function."""

    def test_parse_basic_updates(self):
        """Test parsing basic Q&A status updates."""
        response = """
=== Q&A UPDATE ===
Q5_1: status: confirmed
Q7_2: status: outdated
Q8_3: status: provisional
"""
        updates = parse_qa_updates(response)
        assert len(updates) == 3
        assert updates["Q5_1"] == "confirmed"
        assert updates["Q7_2"] == "outdated"
        assert updates["Q8_3"] == "provisional"

    def test_parse_no_updates(self):
        """Test when no Q&A UPDATE section exists."""
        response = """
Some text without Q&A UPDATE section
"""
        updates = parse_qa_updates(response)
        assert len(updates) == 0

    def test_parse_none_updates(self):
        """Test when section says 'None'."""
        response = """
=== Q&A UPDATE ===
None
"""
        updates = parse_qa_updates(response)
        assert len(updates) == 0

    def test_parse_with_notes(self):
        """Test parsing with additional notes."""
        response = """
=== Q&A UPDATE ===
Q5_1: status: confirmed
**Note:** Updated based on new requirements

Q7_2: status: outdated
"""
        updates = parse_qa_updates(response)
        assert len(updates) == 2
        assert updates["Q5_1"] == "confirmed"


class TestParseReusedQids:
    """Test parse_reused_qids function."""

    def test_parse_inline_references(self):
        """Test parsing Q&A IDs referenced inline."""
        response = """
Per Q5_1, Emergency requires 2 admins. As mentioned in Q7_2,
delegations must be auto-revoked. Following Q3_1 guidance...
"""
        qids = parse_reused_qids(response)
        assert len(qids) == 3
        assert "Q5_1" in qids
        assert "Q7_2" in qids
        assert "Q3_1" in qids

    def test_parse_no_duplicates(self):
        """Test that duplicate IDs are not repeated."""
        response = """
Per Q5_1, we do X. Also per Q5_1, we do Y.
And Q5_1 says Z.
"""
        qids = parse_reused_qids(response)
        assert len(qids) == 1
        assert qids[0] == "Q5_1"

    def test_parse_no_references(self):
        """Test when no Q&A IDs are referenced."""
        response = """
Some feedback without any Q&A references.
"""
        qids = parse_reused_qids(response)
        assert len(qids) == 0

    def test_parse_preserves_order(self):
        """Test that order of first occurrence is preserved."""
        response = """
First Q7_2, then Q3_1, finally Q5_1.
"""
        qids = parse_reused_qids(response)
        assert qids == ["Q7_2", "Q3_1", "Q5_1"]


class TestExtractQuestionContext:
    """Test extract_question_context function."""

    def test_extract_requirement_ref(self):
        """Test extracting requirement references."""
        question = "Regarding R4, should delegations be revoked?"
        context = extract_question_context(question)
        assert context == "R4"

        question = "For R2.1, what is the policy?"
        context = extract_question_context(question)
        assert context == "R2.1"

    def test_extract_keyword(self):
        """Test extracting domain keywords."""
        question = "Can Emergency mode allow multiple admins?"
        context = extract_question_context(question)
        assert context == "Emergency"

        question = "Should delegation persist after mode change?"
        context = extract_question_context(question)
        assert context == "Delegation"

        question = "What about role hierarchy during transitions?"
        context = extract_question_context(question)
        assert context == "Role"

    def test_extract_fallback(self):
        """Test fallback when no clear context."""
        question = "What should we do here?"
        context = extract_question_context(question)
        assert context is not None  # Should return something


class TestParseUserFeedbackForAnswers:
    """Test parse_user_feedback_for_answers function."""

    def test_parse_numbered_answers(self):
        """Test parsing numbered answers matching questions."""
        user_feedback = """
1. Yes, exactly 2 administrators.
2. No, delegations cannot be revoked during Emergency.
3. Maximum 24 hours.
"""
        questions = [
            "How many admins?",
            "Can revoke delegations?",
            "Max duration?"
        ]

        answers = parse_user_feedback_for_answers(user_feedback, questions)
        assert len(answers) == 3
        assert "exactly 2 administrators" in answers[0]
        assert "cannot be revoked" in answers[1]
        assert "24 hours" in answers[2]

    def test_parse_single_answer_for_all(self):
        """Test when user provides single answer for multiple questions."""
        user_feedback = "All of these should follow the same policy: exactly 2 admins required."
        questions = [
            "How many admins for activation?",
            "How many admins for deactivation?"
        ]

        answers = parse_user_feedback_for_answers(user_feedback, questions)
        assert len(answers) == 2
        # Same answer for both
        assert "exactly 2 admins required" in answers[0]
        assert "exactly 2 admins required" in answers[1]

    def test_parse_empty_feedback(self):
        """Test with empty feedback."""
        answers = parse_user_feedback_for_answers("", ["Question 1", "Question 2"])
        assert len(answers) == 0

    def test_parse_mismatched_counts(self):
        """Test when answer count doesn't match question count."""
        user_feedback = """
1. Answer one
2. Answer two
"""
        questions = ["Q1", "Q2", "Q3"]  # 3 questions but 2 answers

        answers = parse_user_feedback_for_answers(user_feedback, questions)
        # Should fall back to using entire feedback for all
        assert len(answers) == 3


class TestFormatQAUpdatesForDisplay:
    """Test format_qa_updates_for_display function."""

    def test_format_updates(self):
        """Test formatting Q&A updates for display."""
        updates = {
            "Q5_1": "confirmed",
            "Q7_2": "outdated",
            "Q8_3": "provisional"
        }

        formatted = format_qa_updates_for_display(updates)
        assert "Q&A Status Updates:" in formatted
        assert "Q5_1: confirmed" in formatted
        assert "Q7_2: outdated" in formatted
        assert "Q8_3: provisional" in formatted
        assert "✓" in formatted  # Confirmed emoji
        assert "✗" in formatted  # Outdated emoji
        assert "~" in formatted  # Provisional emoji

    def test_format_no_updates(self):
        """Test formatting when no updates."""
        formatted = format_qa_updates_for_display({})
        assert "No Q&A status updates" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
