"""
Unit tests for QA database functionality.
"""
import pytest
import tempfile
from pathlib import Path
from src.utils.qa_database import QADatabase, QARecord, create_qa_id


class TestQARecord:
    """Test QARecord dataclass."""

    def test_qa_record_creation(self):
        """Test creating a QA record."""
        record = QARecord(
            id="Q5_1",
            iteration=5,
            question="Should Emergency require 2 admins?",
            answer="Yes, exactly 2.",
            source="user",
            context="Emergency",
            status="confirmed"
        )

        assert record.id == "Q5_1"
        assert record.iteration == 5
        assert record.status == "confirmed"
        assert record.reuse_count == 0

    def test_qa_record_to_dict(self):
        """Test converting QA record to dictionary."""
        record = QARecord(
            id="Q5_1",
            iteration=5,
            question="Test question",
            answer="Test answer",
            source="user",
            context="R4",
            status="confirmed"
        )

        record_dict = record.to_dict()
        assert isinstance(record_dict, dict)
        assert record_dict["id"] == "Q5_1"
        assert record_dict["question"] == "Test question"

    def test_qa_record_from_dict(self):
        """Test creating QA record from dictionary."""
        data = {
            "id": "Q5_1",
            "iteration": 5,
            "question": "Test question",
            "answer": "Test answer",
            "source": "user",
            "context": "R4",
            "status": "confirmed",
            "created_at": "2024-01-01T00:00:00",
            "reuse_count": 2
        }

        record = QARecord.from_dict(data)
        assert record.id == "Q5_1"
        assert record.reuse_count == 2


class TestQADatabase:
    """Test QADatabase class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary QA database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "qa_test.json"
            db = QADatabase(storage_path=db_path)
            yield db

    @pytest.fixture
    def sample_records(self):
        """Create sample QA records."""
        return [
            QARecord(
                id="Q3_1",
                iteration=3,
                question="Should delegations be automatically revoked?",
                answer="Yes, auto-revoke at Emergency end.",
                source="user",
                context="R4",
                status="confirmed"
            ),
            QARecord(
                id="Q5_1",
                iteration=5,
                question="Can Emergency mode allow multiple admins?",
                answer="Yes, exactly 2 admins required.",
                source="user",
                context="Emergency",
                status="confirmed"
            ),
            QARecord(
                id="Q7_1",
                iteration=7,
                question="Should role hierarchy be maintained?",
                answer="Agent assumption: yes, maintain hierarchy.",
                source="agent_assumption",
                context="Role",
                status="provisional"
            )
        ]

    def test_add_record(self, temp_db, sample_records):
        """Test adding records to database."""
        temp_db.add_record(sample_records[0])
        assert len(temp_db.records) == 1
        assert temp_db.records[0].id == "Q3_1"

    def test_get_record_by_id(self, temp_db, sample_records):
        """Test retrieving record by ID."""
        temp_db.add_record(sample_records[0])
        temp_db.add_record(sample_records[1])

        record = temp_db.get_record_by_id("Q5_1")
        assert record is not None
        assert record.question == "Can Emergency mode allow multiple admins?"

        # Non-existent record
        record = temp_db.get_record_by_id("Q99_1")
        assert record is None

    def test_update_status(self, temp_db, sample_records):
        """Test updating record status."""
        temp_db.add_record(sample_records[0])

        # Update status
        result = temp_db.update_status("Q3_1", "outdated")
        assert result is True

        record = temp_db.get_record_by_id("Q3_1")
        assert record.status == "outdated"

        # Update non-existent record
        result = temp_db.update_status("Q99_1", "confirmed")
        assert result is False

    def test_increment_reuse_count(self, temp_db, sample_records):
        """Test incrementing reuse count."""
        temp_db.add_record(sample_records[0])

        # Initial reuse count
        record = temp_db.get_record_by_id("Q3_1")
        assert record.reuse_count == 0

        # Increment
        temp_db.increment_reuse_count("Q3_1")
        record = temp_db.get_record_by_id("Q3_1")
        assert record.reuse_count == 1

        # Increment again
        temp_db.increment_reuse_count("Q3_1")
        record = temp_db.get_record_by_id("Q3_1")
        assert record.reuse_count == 2

    def test_retrieve_relevant_semantic_similarity(self, temp_db, sample_records):
        """Test retrieving relevant records by semantic similarity."""
        for record in sample_records:
            temp_db.add_record(record)

        # Query similar to Q5_1
        questions = ["How many administrators can activate Emergency mode?"]
        relevant = temp_db.retrieve_relevant(
            questions=questions,
            current_iteration=10,
            max_results=2,
            similarity_threshold=0.2
        )

        # Should find Q5_1 as most relevant
        assert len(relevant) > 0
        assert relevant[0].id == "Q5_1"

    def test_retrieve_relevant_filters_outdated(self, temp_db, sample_records):
        """Test that outdated records are not retrieved."""
        # Add records
        for record in sample_records:
            temp_db.add_record(record)

        # Mark Q5_1 as outdated
        temp_db.update_status("Q5_1", "outdated")

        # Query for Emergency-related questions
        questions = ["Can Emergency mode allow multiple admins?"]
        relevant = temp_db.retrieve_relevant(
            questions=questions,
            current_iteration=10,
            max_results=3,
            similarity_threshold=0.1
        )

        # Q5_1 should not be in results (outdated)
        ids = [r.id for r in relevant]
        assert "Q5_1" not in ids

    def test_retrieve_relevant_recency_bonus(self, temp_db):
        """Test that more recent records rank higher."""
        # Add two similar records from different iterations
        old_record = QARecord(
            id="Q3_1",
            iteration=3,
            question="Should Emergency require 2 admins?",
            answer="Yes.",
            source="user",
            context="Emergency",
            status="confirmed"
        )

        new_record = QARecord(
            id="Q8_1",
            iteration=8,
            question="Should Emergency need 2 administrators?",
            answer="Yes.",
            source="user",
            context="Emergency",
            status="confirmed"
        )

        temp_db.add_record(old_record)
        temp_db.add_record(new_record)

        # Query from iteration 10
        questions = ["How many admins for Emergency?"]
        relevant = temp_db.retrieve_relevant(
            questions=questions,
            current_iteration=10,
            max_results=2,
            similarity_threshold=0.1
        )

        # Newer record should rank higher (iteration 8 vs 3)
        assert len(relevant) == 2
        assert relevant[0].id == "Q8_1"  # More recent

    def test_format_for_prompt(self, temp_db, sample_records):
        """Test formatting records for prompt."""
        # Empty database
        formatted = temp_db.format_for_prompt([])
        assert formatted == "No relevant prior Q&A pairs found."

        # With records
        formatted = temp_db.format_for_prompt(sample_records[:2])
        assert "=== RELEVANT PRIOR CLARIFICATIONS ===" in formatted
        assert "Q3_1" in formatted
        assert "Q5_1" in formatted
        assert "Should delegations be automatically revoked?" in formatted
        assert "Status: confirmed" in formatted

    def test_get_all_active_records(self, temp_db, sample_records):
        """Test getting only active (non-outdated) records."""
        for record in sample_records:
            temp_db.add_record(record)

        # Mark one as outdated
        temp_db.update_status("Q7_1", "outdated")

        active = temp_db.get_all_active_records()
        assert len(active) == 2
        ids = [r.id for r in active]
        assert "Q7_1" not in ids

    def test_persistence(self):
        """Test that database persists to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "qa_test.json"

            # Create database and add record
            db1 = QADatabase(storage_path=db_path)
            record = QARecord(
                id="Q5_1",
                iteration=5,
                question="Test question",
                answer="Test answer",
                source="user",
                context="Test",
                status="confirmed"
            )
            db1.add_record(record)

            # Load from same file
            db2 = QADatabase(storage_path=db_path)
            assert len(db2.records) == 1
            assert db2.records[0].id == "Q5_1"

    def test_get_statistics(self, temp_db, sample_records):
        """Test database statistics."""
        for record in sample_records:
            temp_db.add_record(record)

        # Increment reuse counts
        temp_db.increment_reuse_count("Q3_1")
        temp_db.increment_reuse_count("Q3_1")
        temp_db.increment_reuse_count("Q5_1")

        stats = temp_db.get_statistics()

        assert stats["total_records"] == 3
        assert stats["by_status"]["confirmed"] == 2
        assert stats["by_status"]["provisional"] == 1
        assert stats["by_source"]["user"] == 2
        assert stats["by_source"]["agent_assumption"] == 1
        assert stats["most_reused"] == 2  # Q3_1 reused twice


class TestHelperFunctions:
    """Test helper functions."""

    def test_create_qa_id(self):
        """Test creating Q&A IDs."""
        qa_id = create_qa_id(5, 1)
        assert qa_id == "Q5_1"

        qa_id = create_qa_id(12, 3)
        assert qa_id == "Q12_3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
