"""Memory management system for agents using JSON storage."""
import json
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime


class AgentMemory:
    """Manages agent memory using JSON files."""

    def __init__(self, agent_name: str, memory_dir: str = "memory"):
        """
        Initialize agent memory.

        Args:
            agent_name: Name of the agent (e.g., "RE", "Evaluator")
            memory_dir: Directory to store memory files
        """
        self.agent_name = agent_name
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.memory_file = self.memory_dir / f"{agent_name}_memory.json"
        self.memory = self._load_memory()

    def _load_memory(self) -> Dict[str, Any]:
        """Load memory from JSON file."""
        if self.memory_file.exists():
            with open(self.memory_file, 'r') as f:
                return json.load(f)
        return {
            "iteration": 0,
            "last_update": None,
            "high_level_history": [],
            "detailed_history": [],
            "lessons_learned": [],
            "current_iteration_data": {}
        }

    def _save_memory(self):
        """Save memory to JSON file."""
        with open(self.memory_file, 'w') as f:
            json.dump(self.memory, f, indent=2)

    def increment_iteration(self):
        """Increment iteration counter."""
        self.memory["iteration"] += 1
        self.memory["last_update"] = datetime.now().isoformat()
        self._save_memory()

    def get_iteration(self) -> int:
        """Get current iteration number."""
        return self.memory["iteration"]

    def add_high_level_entry(self, entry: str):
        """
        Add a high-level summary entry.

        Args:
            entry: Summary text describing what was done
        """
        self.memory["high_level_history"].append({
            "iteration": self.memory["iteration"],
            "timestamp": datetime.now().isoformat(),
            "entry": entry
        })
        self._save_memory()

    def add_detailed_entry(self, entry: Dict[str, Any]):
        """
        Add a detailed entry.

        Args:
            entry: Dictionary with detailed information
        """
        entry_with_meta = {
            "iteration": self.memory["iteration"],
            "timestamp": datetime.now().isoformat(),
            **entry
        }
        self.memory["detailed_history"].append(entry_with_meta)
        self._save_memory()

    def add_lesson(self, lesson: str, category: str = "general"):
        """
        Add a lesson learned to avoid repeating mistakes.

        Args:
            lesson: Description of the lesson learned
            category: Category of the lesson (e.g., "modeling", "syntax", "requirements")
        """
        self.memory["lessons_learned"].append({
            "iteration": self.memory["iteration"],
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "lesson": lesson
        })
        self._save_memory()

    def get_lessons(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get lessons learned, optionally filtered by category.

        Args:
            category: Optional category filter

        Returns:
            List of lessons
        """
        lessons = self.memory["lessons_learned"]
        if category:
            return [l for l in lessons if l.get("category") == category]
        return lessons

    def get_recent_high_level_history(self, n: int = 5) -> List[Dict[str, Any]]:
        """
        Get recent high-level history entries.

        Args:
            n: Number of recent entries to retrieve

        Returns:
            List of recent entries
        """
        return self.memory["high_level_history"][-n:]

    def set_current_iteration_data(self, key: str, value: Any):
        """
        Set data for current iteration.

        Args:
            key: Data key
            value: Data value
        """
        self.memory["current_iteration_data"][key] = value
        self._save_memory()

    def get_current_iteration_data(self, key: str, default: Any = None) -> Any:
        """
        Get data for current iteration.

        Args:
            key: Data key
            default: Default value if key not found

        Returns:
            Value for the key
        """
        return self.memory["current_iteration_data"].get(key, default)

    def clear_current_iteration_data(self):
        """Clear current iteration data."""
        self.memory["current_iteration_data"] = {}
        self._save_memory()

    def get_summary(self) -> str:
        """
        Get a summary of the memory state.

        Returns:
            Summary string
        """
        return f"""
Agent: {self.agent_name}
Current Iteration: {self.memory["iteration"]}
Last Update: {self.memory.get("last_update", "Never")}
Total High-Level Entries: {len(self.memory["high_level_history"])}
Total Detailed Entries: {len(self.memory["detailed_history"])}
Total Lessons Learned: {len(self.memory["lessons_learned"])}
""".strip()
