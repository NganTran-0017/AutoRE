"""
Q&A Database for tracking user clarifications and agent assumptions.
Uses ChromaDB for semantic search with sentence embeddings.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json
from pathlib import Path
import chromadb
from chromadb.config import Settings


@dataclass
class QARecord:
    """
    Represents a single question-answer pair with metadata.

    Fields:
        id: Unique identifier (format: Q{iteration}_{question_num})
        iteration: Iteration number when question was asked
        question: The question text
        answer: The answer text (from user or agent assumption)
        source: "user" or "agent_assumption"
        context: Keyword or requirement reference (e.g., "R4", "Emergency", "delegation")
        status: "confirmed" | "provisional" | "outdated"
        created_at: Timestamp when record was created
        reuse_count: Number of times this Q&A was referenced
    """
    id: str
    iteration: int
    question: str
    answer: str
    source: str  # "user" or "agent_assumption"
    context: str  # Keyword or requirement number
    status: str  # "confirmed" | "provisional" | "outdated"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    reuse_count: int = 0

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'QARecord':
        """Create QARecord from dictionary."""
        return cls(**data)


class QADatabase:
    """
    Database for storing and retrieving Q&A records using ChromaDB for semantic search.

    Uses ChromaDB with sentence embeddings (all-MiniLM-L6-v2) for true semantic similarity.
    Also maintains JSON file for easy inspection and backward compatibility.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize Q&A database with ChromaDB backend.

        Args:
            storage_path: Path to JSON file for persistent storage (for inspection)
        """
        self.records: List[QARecord] = []
        self.storage_path = storage_path

        # Initialize ChromaDB for semantic search
        if storage_path:
            # Create ChromaDB directory next to JSON file
            chroma_dir = storage_path.parent / f"{storage_path.stem}_chromadb"
        else:
            chroma_dir = Path("memory/qa_chromadb")

        chroma_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(chroma_dir),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=False
            )
        )

        # Create or get collection for Q&A records
        self.collection = self.client.get_or_create_collection(
            name="qa_records",
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity
        )

        # Load existing records from JSON
        if storage_path and storage_path.exists():
            self._load_from_file()

    def add_record(self, record: QARecord) -> None:
        """
        Add a new Q&A record to both ChromaDB and in-memory list.

        Args:
            record: QARecord to add
        """
        self.records.append(record)

        # Store in ChromaDB for semantic search
        # Question text is used as the document for embedding
        self.collection.add(
            ids=[record.id],
            documents=[record.question],  # ChromaDB will embed this
            metadatas=[{
                "iteration": record.iteration,
                "answer": record.answer,
                "source": record.source,
                "context": record.context,
                "status": record.status,
                "created_at": record.created_at,
                "reuse_count": record.reuse_count
            }]
        )

        self._save_to_file()

    def get_record_by_id(self, qa_id: str) -> Optional[QARecord]:
        """
        Retrieve a Q&A record by its ID.

        Args:
            qa_id: The Q&A record ID

        Returns:
            QARecord if found, None otherwise
        """
        for record in self.records:
            if record.id == qa_id:
                return record
        return None

    def update_status(self, qa_id: str, new_status: str) -> bool:
        """
        Update the status of a Q&A record in both memory and ChromaDB.

        Args:
            qa_id: The Q&A record ID
            new_status: New status ("confirmed", "provisional", or "outdated")

        Returns:
            True if updated, False if record not found
        """
        record = self.get_record_by_id(qa_id)
        if record:
            record.status = new_status

            # Update in ChromaDB
            self.collection.update(
                ids=[qa_id],
                metadatas=[{
                    "iteration": record.iteration,
                    "answer": record.answer,
                    "source": record.source,
                    "context": record.context,
                    "status": record.status,
                    "created_at": record.created_at,
                    "reuse_count": record.reuse_count
                }]
            )

            self._save_to_file()
            return True
        return False

    def increment_reuse_count(self, qa_id: str) -> bool:
        """
        Increment the reuse count for a Q&A record in both memory and ChromaDB.

        Args:
            qa_id: The Q&A record ID

        Returns:
            True if updated, False if record not found
        """
        record = self.get_record_by_id(qa_id)
        if record:
            record.reuse_count += 1

            # Update in ChromaDB
            self.collection.update(
                ids=[qa_id],
                metadatas=[{
                    "iteration": record.iteration,
                    "answer": record.answer,
                    "source": record.source,
                    "context": record.context,
                    "status": record.status,
                    "created_at": record.created_at,
                    "reuse_count": record.reuse_count
                }]
            )

            self._save_to_file()
            return True
        return False

    def retrieve_relevant(
        self,
        questions: List[str],
        current_iteration: int,
        max_results: int = 3,
        similarity_threshold: float = 0.3
    ) -> List[QARecord]:
        """
        Retrieve relevant Q&A records using ChromaDB semantic search.

        Args:
            questions: List of current questions being asked
            current_iteration: Current iteration number
            max_results: Maximum number of records to return
            similarity_threshold: Minimum similarity score (0.0-1.0)

        Returns:
            List of relevant QARecord objects, sorted by relevance and recency
        """
        if not questions:
            return []

        # Query ChromaDB for each question and aggregate results
        all_matches = []

        try:
            # Query with all questions at once for efficiency
            results = self.collection.query(
                query_texts=questions,
                n_results=max_results * 3,  # Get more candidates for re-ranking
                where={"status": {"$ne": "outdated"}}  # Exclude outdated records
            )

            # Process results from ChromaDB
            if results and results['documents'] and results['documents'][0]:
                seen_ids = set()

                # Iterate through all query results (one set per question)
                for query_idx in range(len(results['documents'])):
                    docs = results['documents'][query_idx]
                    distances = results['distances'][query_idx]
                    metadatas = results['metadatas'][query_idx]
                    ids = results['ids'][query_idx]

                    for i, doc_id in enumerate(ids):
                        # Skip duplicates (same record matched by multiple questions)
                        if doc_id in seen_ids:
                            continue
                        seen_ids.add(doc_id)

                        # Convert ChromaDB distance to similarity
                        # For cosine distance: similarity = 1 - distance
                        distance = distances[i]
                        base_similarity = 1.0 - distance

                        # Get the full record from memory
                        record = self.get_record_by_id(doc_id)
                        if not record:
                            continue

                        # Calculate bonus scores
                        # Recency bonus: decay over iterations
                        iteration_gap = current_iteration - record.iteration
                        recency_bonus = max(0, 0.3 - (iteration_gap * 0.03))

                        # Status bonus
                        status_bonus = {
                            'confirmed': 0.2,
                            'provisional': 0.1,
                            'outdated': 0.0
                        }.get(record.status, 0.0)

                        # Reuse bonus: indicates high-value Q&A
                        reuse_bonus = min(0.1, record.reuse_count * 0.02)

                        # Total score
                        total_score = base_similarity + recency_bonus + status_bonus + reuse_bonus

                        if total_score >= similarity_threshold:
                            all_matches.append((total_score, record))

            # Sort by score (descending), then by iteration (descending for recency)
            all_matches.sort(key=lambda x: (x[0], x[1].iteration), reverse=True)

            # Return top N
            return [record for score, record in all_matches[:max_results]]

        except Exception as e:
            print(f"Warning: Error querying ChromaDB for Q&A retrieval: {e}")
            return []

    def format_for_prompt(self, records: List[QARecord]) -> str:
        """
        Format Q&A records for inclusion in prompt.
        
        Note: This only formats the data. Instructions on how to use Q&A records
        are defined in the prompt template (Evaluator_prompt.txt).

        Args:
            records: List of QARecord objects

        Returns:
            Formatted string for prompt (data only, no instructions)
        """
        if not records:
            return "No relevant prior Q&A pairs found."

        formatted = "=== RELEVANT PRIOR CLARIFICATIONS ===\n\n"

        for record in records:
            formatted += f"[{record.id}] Context: {record.context}\n"
            formatted += f"Q: {record.question}\n"
            formatted += f"A: {record.answer}\n"
            formatted += f"Status: {record.status} | Source: {record.source} | Iteration: {record.iteration}\n\n"

        return formatted

    def get_all_active_records(self) -> List[QARecord]:
        """Get all records that are not marked as outdated."""
        return [r for r in self.records if r.status != 'outdated']

    def get_statistics(self) -> Dict:
        """Get database statistics."""
        total = len(self.records)
        by_status = {
            'confirmed': len([r for r in self.records if r.status == 'confirmed']),
            'provisional': len([r for r in self.records if r.status == 'provisional']),
            'outdated': len([r for r in self.records if r.status == 'outdated'])
        }
        by_source = {
            'user': len([r for r in self.records if r.source == 'user']),
            'agent_assumption': len([r for r in self.records if r.source == 'agent_assumption'])
        }

        return {
            'total_records': total,
            'by_status': by_status,
            'by_source': by_source,
            'most_reused': max([r.reuse_count for r in self.records], default=0)
        }

    def _save_to_file(self) -> None:
        """Save records to JSON file."""
        if not self.storage_path:
            return

        data = [record.to_dict() for record in self.records]

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_from_file(self) -> None:
        """Load records from JSON file and populate ChromaDB."""
        if not self.storage_path or not self.storage_path.exists():
            return

        with open(self.storage_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.records = [QARecord.from_dict(record_dict) for record_dict in data]
        
        # Populate ChromaDB with loaded records
        if self.records:
            # Clear existing ChromaDB data to avoid duplicates
            try:
                self.client.delete_collection("qa_records")
                self.collection = self.client.create_collection(
                    name="qa_records",
                    metadata={"hnsw:space": "cosine"}
                )
            except Exception:
                pass  # Collection might not exist yet
            
            # Add all records to ChromaDB
            for record in self.records:
                self.collection.add(
                    ids=[record.id],
                    documents=[record.question],
                    metadatas=[{
                        "iteration": record.iteration,
                        "answer": record.answer,
                        "source": record.source,
                        "context": record.context,
                        "status": record.status,
                        "created_at": record.created_at,
                        "reuse_count": record.reuse_count
                    }]
                )


def create_qa_id(iteration: int, question_number: int) -> str:
    """
    Create a unique Q&A ID.

    Args:
        iteration: Iteration number
        question_number: Question number within iteration (1-indexed)

    Returns:
        Q&A ID string (e.g., "Q5_1", "Q12_3")
    """
    return f"Q{iteration}_{question_number}"
