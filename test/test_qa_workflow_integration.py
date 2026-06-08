"""
Integration tests for Q&A workflow.

Tests the complete Q&A lifecycle:
1. InterpretResults asks questions
2. Questions stored as pending_questions
3. Relevant Q&A retrieved for GenerateFeedback
4. Q&A status updates applied
5. Reused Q&A IDs tracked
6. User feedback creates confirmed Q&A records
7. No user feedback creates provisional Q&A records (agent assumptions)
"""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from src.workflow import AutoREWorkflow
from src.utils.runtime_context import SharedRuntimeContext
from src.utils.qa_database import QADatabase, QARecord, create_qa_id
from src.utils.artifact_store import ArtifactStore


@pytest.fixture
def temp_context():
    """Create a temporary runtime context with Q&A database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create context (it will use default memory/ directory)
        context = SharedRuntimeContext(
            project_name="test_qa_workflow_temp",
            use_semantic_memory=False  # Use traditional memory for faster tests
        )

        # Override qa_database path to use temp directory
        qa_path = Path(tmpdir) / "qa_test.json"
        context.qa_database = QADatabase(storage_path=qa_path)

        yield context


@pytest.fixture
def mock_workflow(temp_context):
    """Create a mock workflow with temporary context."""
    # Mock ConfigLoader
    mock_config = Mock()
    mock_config.get_llm_config.return_value = {
        'api_key': 'test_key',
        'model': 'gpt-4',
        'api_type': 'openai',
        'base_url': 'https://api.openai.com/v1',
        'temperature': 0.7
    }

    with patch('src.workflow.ConfigLoader', return_value=mock_config):
        with patch('src.workflow.AutoRELogger'):
            with patch('src.workflow.CLIInteraction'):
                with patch('src.workflow.SharedRuntimeContext', return_value=temp_context):
                    workflow = AutoREWorkflow(
                        input_file="dummy_requirements.txt",
                        project_name="test_qa_workflow"
                    )
                    workflow.context = temp_context

                    # Mock actions
                    workflow.interpret_results = AsyncMock()
                    workflow.generate_feedback = AsyncMock()
                    workflow.refine_feedback = AsyncMock()

                    yield workflow


class TestStep4_ParseQuestionsFromInterpretResults:
    """Test Step 4: Parse questions from InterpretResults."""

    @pytest.mark.asyncio
    async def test_parse_questions_from_interpretation(self, mock_workflow):
        """Test that questions from InterpretResults are parsed and stored."""
        # Set iteration to 1
        mock_workflow.context.iteration._current = 1

        # Mock InterpretResults response with questions
        interpretation_response = """
=== SYNTAX STATUS ===
OK

=== COUNTEREXAMPLES ===
None

=== SATISFYING INSTANCES ===
Meaningful scenarios found.

=== VACUITY ===
None

=== USER QUESTIONS ===
1. Should all global coverage facts be enforced in every scenario, or only in dedicated verification scenarios?
2. Is it acceptable for the system to occasionally lack a pre-Emergency delegation that spans Emergency?
3. Can a user be assigned both mutually exclusive roles in Emergency only via direct assignment?

=== HANDOFF TO RE ===
[Action items]
"""

        mock_workflow.interpret_results.run.return_value = interpretation_response

        # Mock analyzer results - these would be retrieved by the workflow
        results = {
            'analysis': {
                'has_syntax_errors': False,
                'has_counterexamples': False,
                'positive_run_commands': 5,
                'satisfied_positive_runs': 5
            }
        }

        # Mock RunAlloyAnalyzer to return results
        mock_workflow.run_analyzer = AsyncMock()
        mock_workflow.run_analyzer.run.return_value = results

        # Store mock artifacts (requirements and model)
        mock_workflow.context.artifacts.store_requirements(1, "Requirements")
        mock_workflow.context.artifacts.store_alloy_model(1, "Model")

        # Mock file_manager to return a valid model path
        with tempfile.NamedTemporaryFile(mode='w', suffix='.als', delete=False) as f:
            f.write("// Test Alloy model")
            model_path = f.name

        try:
            mock_workflow.context.file_manager.get_alloy_model_path = Mock(return_value=Path(model_path))

            # Run Step 4 (it retrieves results from artifacts internally)
            await mock_workflow._step4_evaluate_model()

            # Verify questions were parsed and stored
            pending_questions = mock_workflow.context.artifacts.get_pending_questions(1)

            assert len(pending_questions) == 3
            assert "coverage facts" in pending_questions[0]
            assert "pre-Emergency delegation" in pending_questions[1]
            assert "mutually exclusive roles" in pending_questions[2]
        finally:
            # Clean up temp file
            Path(model_path).unlink(missing_ok=True)


class TestStep56_RetrieveAndUseQA:
    """Test Step 5-6: Retrieve and use Q&A context."""

    @pytest.mark.asyncio
    async def test_retrieve_relevant_qa_based_on_pending_questions(self, mock_workflow):
        """Test that relevant Q&A is retrieved based on pending questions."""
        # Set iteration to 6
        mock_workflow.context.iteration._current = 6

        # Add some Q&A records to database
        record1 = QARecord(
            id="Q3_1",
            iteration=3,
            question="Should coverage facts be enforced globally?",
            answer="Only in dedicated verification scenarios, not globally.",
            source="user",
            context="coverage",
            status="confirmed"
        )

        record2 = QARecord(
            id="Q5_1",
            iteration=5,
            question="Can Emergency delegation be assigned by single admin?",
            answer="No, exactly two administrators must jointly trigger Emergency.",
            source="user",
            context="Emergency",
            status="confirmed"
        )

        mock_workflow.context.qa_database.add_record(record1)
        mock_workflow.context.qa_database.add_record(record2)

        # Store pending questions
        pending_questions = [
            "Should all coverage facts be enforced in every scenario?",
            "Can Emergency mode be triggered by one administrator?"
        ]
        mock_workflow.context.artifacts.store_pending_questions(6, pending_questions)

        # Store artifacts needed for GenerateFeedback
        mock_workflow.context.artifacts.store_evaluation(6, "Interpretation")
        mock_workflow.context.artifacts.store_requirements(6, "Requirements")
        mock_workflow.context.artifacts.store_alloy_model(6, "Model")

        # Mock GenerateFeedback response
        mock_workflow.generate_feedback.run.return_value = """
=== VERIFICATION STATUS ===
Ready

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE

=== ALLOY_MODEL_IMPROVEMENTS ===
Per Q3_1, coverage facts should only be enforced in verification scenarios.
Per Q5_1, require two administrators for Emergency trigger.

=== UPDATED USER QUESTIONS ===
None

=== Q&A UPDATE ===
Q3_1: status: confirmed
Q5_1: status: confirmed
"""

        # Mock CLI to return None (no user feedback)
        mock_workflow.cli = Mock()
        mock_workflow.cli.request_input.return_value = None

        # Run Step 5-6
        result = await mock_workflow._step5_6_generate_feedback_and_get_user_input()

        # Verify GenerateFeedback was called with relevant_qa
        call_kwargs = mock_workflow.generate_feedback.run.call_args[1]
        assert 'relevant_qa' in call_kwargs
        assert 'Q3_1' in call_kwargs['relevant_qa']
        assert 'Q5_1' in call_kwargs['relevant_qa']
        assert 'coverage facts' in call_kwargs['relevant_qa']

        # Verify reuse counts were incremented
        record1 = mock_workflow.context.qa_database.get_record_by_id("Q3_1")
        record2 = mock_workflow.context.qa_database.get_record_by_id("Q5_1")
        assert record1.reuse_count == 1
        assert record2.reuse_count == 1


class TestStep56_ParseQAUpdates:
    """Test Step 5-6: Parse and apply Q&A status updates."""

    @pytest.mark.asyncio
    async def test_parse_and_apply_qa_status_updates(self, mock_workflow):
        """Test that Q&A status updates from GenerateFeedback are applied."""
        # Set iteration to 8
        mock_workflow.context.iteration._current = 8

        # Add Q&A record with provisional status
        record = QARecord(
            id="Q7_1",
            iteration=7,
            question="Should role hierarchy be enforced?",
            answer="Agent assumption: Yes, maintain strict hierarchy.",
            source="agent_assumption",
            context="Role",
            status="provisional"
        )
        mock_workflow.context.qa_database.add_record(record)

        # Store artifacts
        mock_workflow.context.artifacts.store_evaluation(8, "Interpretation")
        mock_workflow.context.artifacts.store_requirements(8, "Requirements")
        mock_workflow.context.artifacts.store_alloy_model(8, "Model")
        mock_workflow.context.artifacts.store_pending_questions(8, [])

        # Mock GenerateFeedback response with status update
        mock_workflow.generate_feedback.run.return_value = """
=== VERIFICATION STATUS ===
Ready

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE

=== ALLOY_MODEL_IMPROVEMENTS ===
None

=== UPDATED USER QUESTIONS ===
None

=== Q&A UPDATE ===
Q7_1: status: confirmed
"""

        # Mock CLI
        mock_workflow.cli = Mock()
        mock_workflow.cli.request_input.return_value = None

        # Run Step 5-6
        await mock_workflow._step5_6_generate_feedback_and_get_user_input()

        # Verify status was updated
        updated_record = mock_workflow.context.qa_database.get_record_by_id("Q7_1")
        assert updated_record.status == "confirmed"


class TestStep56_CreateQAFromUserFeedback:
    """Test Step 5-6: Create Q&A records from user feedback."""

    @pytest.mark.asyncio
    async def test_create_confirmed_qa_from_user_feedback(self, mock_workflow):
        """Test that user feedback creates confirmed Q&A records."""
        # Set iteration to 10
        mock_workflow.context.iteration._current = 10

        # Store artifacts
        mock_workflow.context.artifacts.store_evaluation(10, "Interpretation")
        mock_workflow.context.artifacts.store_requirements(10, "Requirements")
        mock_workflow.context.artifacts.store_alloy_model(10, "Model")
        mock_workflow.context.artifacts.store_pending_questions(10, [])

        # Mock GenerateFeedback response with new questions
        mock_workflow.generate_feedback.run.return_value = """
=== VERIFICATION STATUS ===
Ready

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE

=== ALLOY_MODEL_IMPROVEMENTS ===
Need clarification on delegation expiry policy.

=== UPDATED USER QUESTIONS ===
1. Should delegation expiry be the only condition governing persistence across mode transitions?
2. Is there ever a case where Emergency privilege should persist in Normal mode?

=== Q&A UPDATE ===
None
"""

        # Mock RefineFeedback response
        mock_workflow.refine_feedback.run.return_value = """
=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE

[Refined feedback]
"""

        # Mock user providing feedback
        user_feedback = "1. Yes, delegation expiry is the only condition. 2. No, Emergency privilege must never persist in Normal mode."
        mock_workflow.cli = Mock()
        mock_workflow.cli.request_input.return_value = user_feedback

        # Run Step 5-6
        result = await mock_workflow._step5_6_generate_feedback_and_get_user_input()

        # Verify user provided feedback
        assert result['user_provided_feedback'] is True

        # Verify Q&A records were created
        record1 = mock_workflow.context.qa_database.get_record_by_id("Q10_1")
        record2 = mock_workflow.context.qa_database.get_record_by_id("Q10_2")

        assert record1 is not None
        assert record2 is not None
        assert record1.status == "confirmed"
        assert record2.status == "confirmed"
        assert record1.source == "user"
        assert record2.source == "user"
        assert "delegation expiry" in record1.question
        assert "Emergency privilege" in record2.question
        assert record1.answer == user_feedback
        assert record2.answer == user_feedback


class TestStep56_HandleAgentAssumptions:
    """Test Step 5-6: Handle agent assumptions when user doesn't answer."""

    @pytest.mark.asyncio
    async def test_create_provisional_qa_from_agent_assumptions(self, mock_workflow):
        """Test that agent assumptions related to USER QUESTIONS create provisional Q&A records.

        IMPORTANT: Only assumptions made in response to unanswered questions should be captured,
        not assumptions from ASSUMPTIONS REVIEW or other sections.
        """
        # Set iteration to 12
        mock_workflow.context.iteration._current = 12

        # Store artifacts
        mock_workflow.context.artifacts.store_evaluation(12, "Interpretation")
        mock_workflow.context.artifacts.store_requirements(12, "Requirements")
        mock_workflow.context.artifacts.store_alloy_model(12, "Model")
        mock_workflow.context.artifacts.store_pending_questions(12, [])

        # Mock GenerateFeedback response with:
        # 1. Assumptions in ALLOY_MODEL_IMPROVEMENTS (related to unanswered questions)
        # 2. Assumptions in ASSUMPTIONS REVIEW (NOT related to user questions - should NOT be captured)
        mock_workflow.generate_feedback.run.return_value = """
=== VERIFICATION STATUS ===
Ready

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE

=== ALLOY_MODEL_IMPROVEMENTS ===
Assuming the weakest reasonable interpretation: coverage facts should be enforced only in dedicated verification scenarios, not globally, to avoid overconstraint.

Proceeding with assumption: Emergency privilege must be explicitly revoked and cannot persist in Normal mode.

=== ASSUMPTIONS REVIEW ===
- Confirm mutual exclusion pairs are always present (this is a modeling assumption, not answering a user question)
- Assuming symmetric mutual exclusivity (this should NOT create a Q&A record)

=== UPDATED USER QUESTIONS ===
1. Should all coverage facts be enforced in every scenario, or only in dedicated verification scenarios?
2. Can Emergency privilege ever persist in Normal mode after Emergency exit?

=== Q&A UPDATE ===
None
"""

        # Mock user NOT providing feedback (timeout or empty)
        mock_workflow.cli = Mock()
        mock_workflow.cli.request_input.return_value = None

        # Run Step 5-6
        result = await mock_workflow._step5_6_generate_feedback_and_get_user_input()

        # Verify no user feedback
        assert result['user_provided_feedback'] is False

        # Verify provisional Q&A records were created ONLY for unanswered user questions
        record1 = mock_workflow.context.qa_database.get_record_by_id("Q12_1")
        record2 = mock_workflow.context.qa_database.get_record_by_id("Q12_2")

        assert record1 is not None
        assert record2 is not None
        assert record1.status == "provisional"
        assert record2.status == "provisional"
        assert record1.source == "agent_assumption"
        assert record2.source == "agent_assumption"
        assert "Agent assumption:" in record1.answer
        assert "Agent assumption:" in record2.answer

        # Check that assumptions from ALLOY_MODEL_IMPROVEMENTS were captured
        # (because they answer the USER QUESTIONS)
        # Note: The assumption matching is simple - it finds assumptions and pairs them with questions.
        # More sophisticated matching could be added later.
        assert "Agent assumption:" in record1.answer
        assert "Agent assumption:" in record2.answer
        # At least one should have relevant content
        all_answers = record1.answer + " " + record2.answer
        assert ("coverage facts" in all_answers or "verification scenarios" in all_answers or
                "Emergency privilege" in all_answers or "explicitly revoked" in all_answers)

        # Verify assumptions from ASSUMPTIONS REVIEW were NOT captured as Q&A
        # (they are not answering user questions, just modeling decisions)
        all_records = mock_workflow.context.qa_database.records
        for record in all_records:
            # Should not find "symmetric mutual exclusivity" from ASSUMPTIONS REVIEW
            assert "symmetric mutual exclusivity" not in record.answer.lower()

    @pytest.mark.asyncio
    async def test_no_provisional_qa_if_no_assumptions_found(self, mock_workflow):
        """Test that no provisional Q&A created if no assumption patterns found."""
        # Set iteration to 13
        mock_workflow.context.iteration._current = 13

        # Store artifacts
        mock_workflow.context.artifacts.store_evaluation(13, "Interpretation")
        mock_workflow.context.artifacts.store_requirements(13, "Requirements")
        mock_workflow.context.artifacts.store_alloy_model(13, "Model")
        mock_workflow.context.artifacts.store_pending_questions(13, [])

        # Mock GenerateFeedback response with questions but NO assumptions
        mock_workflow.generate_feedback.run.return_value = """
=== VERIFICATION STATUS ===
Ready

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE

=== ALLOY_MODEL_IMPROVEMENTS ===
Need user clarification before proceeding.

=== UPDATED USER QUESTIONS ===
1. Should role hierarchy be enforced strictly?

=== Q&A UPDATE ===
None
"""

        # Mock user NOT providing feedback
        mock_workflow.cli = Mock()
        mock_workflow.cli.request_input.return_value = None

        # Initial record count
        initial_count = len(mock_workflow.context.qa_database.records)

        # Run Step 5-6
        result = await mock_workflow._step5_6_generate_feedback_and_get_user_input()

        # Verify no user feedback
        assert result['user_provided_feedback'] is False

        # Verify no new Q&A records created (no assumptions found)
        final_count = len(mock_workflow.context.qa_database.records)
        assert final_count == initial_count


class TestEndToEndQAWorkflow:
    """End-to-end test of Q&A workflow across multiple iterations."""

    @pytest.mark.asyncio
    async def test_qa_workflow_across_iterations(self, mock_workflow):
        """Test complete Q&A workflow across iterations with question reuse."""
        # === ITERATION 1: Ask question, user answers ===
        mock_workflow.context.iteration._current = 1

        # Store artifacts
        mock_workflow.context.artifacts.store_evaluation(1, "Interpretation 1")
        mock_workflow.context.artifacts.store_requirements(1, "Requirements 1")
        mock_workflow.context.artifacts.store_alloy_model(1, "Model 1")
        mock_workflow.context.artifacts.store_pending_questions(1, [])

        # GenerateFeedback asks question
        mock_workflow.generate_feedback.run.return_value = """
=== VERIFICATION STATUS ===
Ready

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE

=== ALLOY_MODEL_IMPROVEMENTS ===
Need clarification.

=== UPDATED USER QUESTIONS ===
1. Should Emergency require exactly 2 administrators?

=== Q&A UPDATE ===
None
"""

        # User answers
        mock_workflow.refine_feedback.run.return_value = """
=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE
"""
        mock_workflow.cli = Mock()
        mock_workflow.cli.request_input.return_value = "Yes, exactly 2 administrators always required."

        # Run iteration 1
        await mock_workflow._step5_6_generate_feedback_and_get_user_input()

        # Verify Q&A created
        record = mock_workflow.context.qa_database.get_record_by_id("Q1_1")
        assert record is not None
        assert record.status == "confirmed"
        assert "2 administrators" in record.answer

        # === ITERATION 2: Similar question asked, Q&A retrieved ===
        mock_workflow.context.iteration._current = 2

        # Store artifacts for iteration 2
        mock_workflow.context.artifacts.store_evaluation(2, "Interpretation 2")
        mock_workflow.context.artifacts.store_requirements(2, "Requirements 2")
        mock_workflow.context.artifacts.store_alloy_model(2, "Model 2")

        # Similar question asked
        similar_questions = [
            "How many administrators are required to trigger Emergency mode?"
        ]
        mock_workflow.context.artifacts.store_pending_questions(2, similar_questions)

        # GenerateFeedback should receive relevant Q&A
        mock_workflow.generate_feedback.run.return_value = """
=== VERIFICATION STATUS ===
Ready

=== CONVERGENCE_RECOMMENDATION ===
Status: FALSE

=== ALLOY_MODEL_IMPROVEMENTS ===
Per Q1_1, ensure exactly 2 administrators are required.

=== UPDATED USER QUESTIONS ===
None

=== Q&A UPDATE ===
Q1_1: status: confirmed
"""

        mock_workflow.cli.request_input.return_value = None

        # Run iteration 2
        await mock_workflow._step5_6_generate_feedback_and_get_user_input()

        # Verify Q&A was retrieved and reused
        record = mock_workflow.context.qa_database.get_record_by_id("Q1_1")
        assert record.reuse_count == 1

        # Verify GenerateFeedback received Q&A context
        call_kwargs = mock_workflow.generate_feedback.run.call_args[1]
        assert 'Q1_1' in call_kwargs['relevant_qa']


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
