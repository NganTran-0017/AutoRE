"""
Long-term memory system with multi-dimensional tagging.
"""
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path
import json


@dataclass
class MemoryItem:
    """
    Single memory item with tags.

    Tags allow multi-dimensional querying:
    - agent: Which agent created this (RE, Evaluator)
    - action: Which action created this (AnalyzeRequirements, etc.)
    - iteration: When it was created (1, 2, 3, ...)
    - project: Which project (default, library_system, etc.)
    - type: What kind of memory (lesson, pattern, event)
    """
    content: str
    type: str  # "lesson", "pattern", "event"
    tags: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: str

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'MemoryItem':
        """Create from dictionary."""
        return cls(**data)


class LongTermMemorySystem:
    """
    Multi-dimensional tagged memory system.

    Supports flexible querying across dimensions:
    - By agent (RE, Evaluator)
    - By action (AnalyzeRequirements, BuildAlloyModel, etc.)
    - By iteration (1, 2, 3, ...)
    - By project (default, library_system, etc.)
    - By type (lesson, pattern, event)

    All memory is persisted to disk as JSON.
    """

    def __init__(self, project_name: str):
        """
        Initialize memory system.

        Args:
            project_name: Project identifier for isolation
        """
        self.project_name = project_name
        self.storage_path = Path(f"memory/{project_name}/")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.items: List[MemoryItem] = []
        self._load()

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
        Store item with full tagging.

        Args:
            content: The actual content to remember
            item_type: "lesson", "pattern", or "event"
            agent: Agent name (e.g., "RE", "Evaluator")
            action: Action name (e.g., "AnalyzeRequirements")
            iteration: Current iteration number
            metadata: Additional arbitrary data
        """
        item = MemoryItem(
            content=content,
            type=item_type,
            tags={
                "agent": agent,
                "action": action,
                "iteration": iteration,
                "project": self.project_name
            },
            metadata=metadata or {},
            timestamp=datetime.now().isoformat()
        )
        self.items.append(item)

    def retrieve(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        iteration: Optional[int] = None,
        item_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[MemoryItem]:
        """
        Retrieve items matching filters.

        All filters are optional. If not provided, that dimension is not filtered.

        Examples:
            retrieve(agent="RE", action="BuildAlloyModel")
            → Lessons from RE's BuildAlloyModel action

            retrieve(iteration=2)
            → Everything from iteration 2

            retrieve(item_type="lesson", limit=5)
            → 5 most recent lessons

        Args:
            agent: Filter by agent name
            action: Filter by action name
            iteration: Filter by iteration number
            item_type: Filter by type (lesson, pattern, event)
            limit: Maximum number to return (most recent first)

        Returns:
            List of matching memory items
        """
        filtered = self.items

        # Apply filters
        if agent:
            filtered = [i for i in filtered if i.tags.get("agent") == agent]
        if action:
            filtered = [i for i in filtered if i.tags.get("action") == action]
        if iteration is not None:
            filtered = [i for i in filtered if i.tags.get("iteration") == iteration]
        if item_type:
            filtered = [i for i in filtered if i.type == item_type]

        # Sort by timestamp (most recent first)
        filtered.sort(key=lambda x: x.timestamp, reverse=True)

        # Apply limit
        if limit is not None:
            filtered = filtered[:limit]

        return filtered

    def get_lessons(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 10
    ) -> List[str]:
        """
        Convenience method to get lesson content.

        Args:
            agent: Filter by agent
            action: Filter by action
            limit: Maximum number

        Returns:
            List of lesson strings
        """
        items = self.retrieve(
            agent=agent,
            action=action,
            item_type="lesson",
            limit=limit
        )
        return [item.content for item in items]

    def get_patterns(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 10
    ) -> List[str]:
        """
        Convenience method to get pattern content.

        Args:
            agent: Filter by agent
            action: Filter by action
            limit: Maximum number

        Returns:
            List of pattern strings
        """
        items = self.retrieve(
            agent=agent,
            action=action,
            item_type="pattern",
            limit=limit
        )
        return [item.content for item in items]

    def get_events(
        self,
        agent: Optional[str] = None,
        iteration: Optional[int] = None,
        limit: int = 10
    ) -> List[str]:
        """
        Convenience method to get event content.

        Args:
            agent: Filter by agent
            iteration: Filter by iteration
            limit: Maximum number

        Returns:
            List of event strings
        """
        items = self.retrieve(
            agent=agent,
            iteration=iteration,
            item_type="event",
            limit=limit
        )
        return [item.content for item in items]

    def clear_all(self):
        """Clear all memory items (use with caution)."""
        self.items.clear()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about stored memory.

        Returns:
            Dictionary with counts by type, agent, etc.
        """
        total = len(self.items)
        by_type = {}
        by_agent = {}
        by_action = {}

        for item in self.items:
            # Count by type
            by_type[item.type] = by_type.get(item.type, 0) + 1

            # Count by agent
            agent = item.tags.get("agent", "unknown")
            by_agent[agent] = by_agent.get(agent, 0) + 1

            # Count by action
            action = item.tags.get("action", "unknown")
            by_action[action] = by_action.get(action, 0) + 1

        return {
            "total": total,
            "by_type": by_type,
            "by_agent": by_agent,
            "by_action": by_action
        }

    def save(self):
        """Persist all memory to disk."""
        file_path = self.storage_path / "memory.json"
        with open(file_path, 'w') as f:
            data = [item.to_dict() for item in self.items]
            json.dump(data, f, indent=2)

    def _load(self):
        """Load memory from disk."""
        file_path = self.storage_path / "memory.json"
        if file_path.exists():
            with open(file_path) as f:
                data = json.load(f)
                self.items = [MemoryItem.from_dict(d) for d in data]

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"LongTermMemorySystem("
            f"project={self.project_name}, "
            f"items={stats['total']}, "
            f"lessons={stats['by_type'].get('lesson', 0)}, "
            f"patterns={stats['by_type'].get('pattern', 0)}, "
            f"events={stats['by_type'].get('event', 0)})"
        )
