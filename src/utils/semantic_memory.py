"""
Semantic memory system using ChromaDB for vector-based retrieval.

This enhances the existing JSON-based memory system with semantic search
capabilities while maintaining backward compatibility.
"""
import chromadb
from chromadb.config import Settings
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import json


class SemanticMemorySystem:
    """
    Semantic memory system using ChromaDB for vector-based similarity search.

    Stores memories with embeddings and retrieves them using semantic similarity
    rather than just exact tag matching.
    """

    def __init__(self, project_name: str, embedding_model: str = "all-MiniLM-L6-v2"):
        """
        Initialize semantic memory system.

        Args:
            project_name: Project identifier for isolation
            embedding_model: Sentence transformer model for embeddings
                           (default: all-MiniLM-L6-v2 - fast and efficient)
        """
        self.project_name = project_name
        self.storage_path = Path(f"memory/{project_name}_semantic/")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(self.storage_path),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        # Create or get collections for different memory types
        self.lessons_collection = self.client.get_or_create_collection(
            name="lessons",
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity
        )

        self.patterns_collection = self.client.get_or_create_collection(
            name="patterns",
            metadata={"hnsw:space": "cosine"}
        )

        self.events_collection = self.client.get_or_create_collection(
            name="events",
            metadata={"hnsw:space": "cosine"}
        )

        self._collection_map = {
            "lesson": self.lessons_collection,
            "pattern": self.patterns_collection,
            "event": self.events_collection
        }

    def store(
        self,
        content: str,
        item_type: str,
        agent: str,
        action: str,
        iteration: int,
        metadata: Optional[Dict] = None
    ):
        """
        Store memory item with semantic embedding.

        Args:
            content: The actual content to remember
            item_type: "lesson", "pattern", or "event"
            agent: Agent name (e.g., "RE", "Evaluator")
            action: Action name (e.g., "AnalyzeRequirements")
            iteration: Current iteration number
            metadata: Additional arbitrary data
        """
        collection = self._collection_map.get(item_type)
        if not collection:
            raise ValueError(f"Unknown item_type: {item_type}")

        # Create unique ID
        timestamp = datetime.now().isoformat()
        doc_id = f"{agent}_{action}_{iteration}_{timestamp}"

        # Prepare metadata
        meta = {
            "agent": agent,
            "action": action,
            "iteration": iteration,
            "project": self.project_name,
            "timestamp": timestamp,
            "type": item_type
        }
        if metadata:
            meta.update(metadata)

        # Store in ChromaDB (automatically creates embeddings)
        collection.add(
            documents=[content],
            metadatas=[meta],
            ids=[doc_id]
        )

    def retrieve_similar(
        self,
        query: str,
        item_type: Optional[str] = None,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 10,
        similarity_threshold: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Retrieve memories semantically similar to the query.

        Args:
            query: Query text to find similar memories
            item_type: Filter by type ("lesson", "pattern", "event")
            agent: Filter by agent name
            action: Filter by action name
            limit: Maximum number of results
            similarity_threshold: Minimum similarity score (0-1)

        Returns:
            List of dicts with 'content', 'metadata', and 'similarity' keys
        """
        # Determine which collections to search
        if item_type:
            collections = [self._collection_map.get(item_type)]
            if not collections[0]:
                return []
        else:
            collections = [
                self.lessons_collection,
                self.patterns_collection,
                self.events_collection
            ]

        all_results = []

        for collection in collections:
            # Build metadata filter
            where_filter = {}
            if agent:
                where_filter["agent"] = agent
            if action:
                where_filter["action"] = action

            # Query collection
            try:
                results = collection.query(
                    query_texts=[query],
                    n_results=limit,
                    where=where_filter if where_filter else None
                )

                # Process results
                if results and results['documents'] and results['documents'][0]:
                    for i, doc in enumerate(results['documents'][0]):
                        # ChromaDB returns distance, convert to similarity
                        # For cosine distance: similarity = 1 - distance
                        distance = results['distances'][0][i]
                        similarity = 1.0 - distance

                        if similarity >= similarity_threshold:
                            all_results.append({
                                'content': doc,
                                'metadata': results['metadatas'][0][i],
                                'similarity': similarity
                            })
            except Exception as e:
                print(f"Warning: Error querying collection {collection.name}: {e}")
                continue

        # Sort by similarity (highest first) and limit
        all_results.sort(key=lambda x: x['similarity'], reverse=True)
        return all_results[:limit]

    def get_lessons(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 10,
        query: Optional[str] = None
    ) -> List[str]:
        """
        Get lessons, optionally using semantic search.

        Args:
            agent: Filter by agent
            action: Filter by action
            limit: Maximum number
            query: If provided, use semantic search with this query

        Returns:
            List of lesson strings
        """
        if query:
            # Use semantic search
            results = self.retrieve_similar(
                query=query,
                item_type="lesson",
                agent=agent,
                action=action,
                limit=limit
            )
            return [r['content'] for r in results]
        else:
            # Fall back to retrieving recent lessons using query with filters
            where_filter = None
            if agent and action:
                where_filter = {"$and": [{"agent": agent}, {"action": action}]}
            elif agent:
                where_filter = {"agent": agent}
            elif action:
                where_filter = {"action": action}

            try:
                results = self.lessons_collection.get(
                    where=where_filter,
                    limit=limit
                )

                if results and results['documents']:
                    return results['documents']
            except Exception as e:
                print(f"Warning: Error getting lessons: {e}")
            
            return []

    def get_patterns(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 5,
        query: Optional[str] = None
    ) -> List[str]:
        """
        Get patterns, optionally using semantic search.

        Args:
            agent: Filter by agent
            action: Filter by action
            limit: Maximum number
            query: If provided, use semantic search

        Returns:
            List of pattern strings
        """
        if query:
            results = self.retrieve_similar(
                query=query,
                item_type="pattern",
                agent=agent,
                action=action,
                limit=limit
            )
            return [r['content'] for r in results]
        else:
            where_filter = None
            if agent and action:
                where_filter = {"$and": [{"agent": agent}, {"action": action}]}
            elif agent:
                where_filter = {"agent": agent}
            elif action:
                where_filter = {"action": action}

            try:
                results = self.patterns_collection.get(
                    where=where_filter,
                    limit=limit
                )

                if results and results['documents']:
                    return results['documents']
            except Exception as e:
                print(f"Warning: Error getting patterns: {e}")
            
            return []

    def get_events(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 10,
        query: Optional[str] = None
    ) -> List[str]:
        """
        Get events, optionally using semantic search.

        Args:
            agent: Filter by agent
            action: Filter by action
            limit: Maximum number
            query: If provided, use semantic search

        Returns:
            List of event strings
        """
        if query:
            results = self.retrieve_similar(
                query=query,
                item_type="event",
                agent=agent,
                action=action,
                limit=limit
            )
            return [r['content'] for r in results]
        else:
            where_filter = None
            if agent and action:
                where_filter = {"$and": [{"agent": agent}, {"action": action}]}
            elif agent:
                where_filter = {"agent": agent}
            elif action:
                where_filter = {"action": action}

            try:
                results = self.events_collection.get(
                    where=where_filter,
                    limit=limit
                )

                if results and results['documents']:
                    return results['documents']
            except Exception as e:
                print(f"Warning: Error getting events: {e}")
            
            return []

    def clear_all(self):
        """Clear all collections."""
        self.client.delete_collection("lessons")
        self.client.delete_collection("patterns")
        self.client.delete_collection("events")

        # Recreate collections
        self.__init__(self.project_name)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about stored memories.

        Returns format compatible with LongTermMemorySystem for workflow summary.
        """
        lesson_count = self.lessons_collection.count()
        pattern_count = self.patterns_collection.count()
        event_count = self.events_collection.count()

        return {
            "total": lesson_count + pattern_count + event_count,
            "by_type": {
                "lesson": lesson_count,
                "pattern": pattern_count,
                "event": event_count
            }
        }

    def save(self):
        """
        Save memory state to disk.

        ChromaDB PersistentClient automatically persists data to disk,
        so this method is a no-op. Provided for interface compatibility
        with LongTermMemorySystem.
        """
        # ChromaDB auto-persists, no explicit save needed
        pass

    def __repr__(self) -> str:
        stats = self.get_stats()
        by_type = stats['by_type']
        return (
            f"SemanticMemorySystem(project='{self.project_name}', "
            f"lessons={by_type['lesson']}, "
            f"patterns={by_type['pattern']}, "
            f"events={by_type['event']})"
        )
