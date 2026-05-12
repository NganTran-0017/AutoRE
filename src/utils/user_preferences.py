"""
User preference tracking across iterations.
"""
from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime
import json
from pathlib import Path


@dataclass
class UserPreference:
    """A single user preference observation."""
    content: str
    iteration: int
    context: str  # What triggered this preference
    confidence: float  # 0.0-1.0, how certain we are
    timestamp: str

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'UserPreference':
        """Create from dictionary."""
        return cls(**data)


class UserPreferenceTracker:
    """
    Tracks user preferences accumulated across iterations.

    Examples of preferences:
    - "User prefers detailed explanations"
    - "User wants to see counterexamples first"
    - "User focuses on security properties"
    - "User prefers concise feedback"

    Preferences are inferred from user interactions and can be
    included in prompts to personalize agent behavior.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize preference tracker.

        Args:
            storage_path: Where to persist preferences (optional)
        """
        self.preferences: List[UserPreference] = []
        self.storage_path = storage_path
        if storage_path:
            self._load()

    def add_preference(
        self,
        preference: str,
        iteration: int,
        context: str = "",
        confidence: float = 1.0
    ):
        """
        Add user preference observed during interaction.

        Args:
            preference: The preference text
            iteration: When it was observed
            context: What triggered it
            confidence: How certain (0.0-1.0)
        """
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")

        pref = UserPreference(
            content=preference,
            iteration=iteration,
            context=context,
            confidence=confidence,
            timestamp=datetime.now().isoformat()
        )
        self.preferences.append(pref)

    def get_preferences(
        self,
        min_confidence: float = 0.5,
        limit: Optional[int] = None
    ) -> List[str]:
        """
        Get preferences above confidence threshold.

        Args:
            min_confidence: Minimum confidence to include
            limit: Maximum number to return (most recent first)

        Returns:
            List of preference strings
        """
        filtered = [
            p for p in self.preferences
            if p.confidence >= min_confidence
        ]

        # Sort by timestamp (most recent first)
        filtered.sort(key=lambda p: p.timestamp, reverse=True)

        if limit:
            filtered = filtered[:limit]

        return [p.content for p in filtered]

    def format_for_prompt(
        self,
        min_confidence: float = 0.5,
        limit: int = 5
    ) -> str:
        """
        Format preferences for inclusion in prompts.

        Args:
            min_confidence: Minimum confidence to include
            limit: Maximum number to include

        Returns:
            Formatted string ready for prompt inclusion
        """
        prefs = self.get_preferences(min_confidence=min_confidence, limit=limit)

        if not prefs:
            return ""

        lines = ["User Preferences:"]
        for pref in prefs:
            lines.append(f"- {pref}")

        return "\n".join(lines)

    def clear(self):
        """Clear all preferences."""
        self.preferences.clear()

    def save(self):
        """Persist preferences to disk."""
        if not self.storage_path:
            return

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.storage_path, 'w') as f:
            data = [p.to_dict() for p in self.preferences]
            json.dump(data, f, indent=2)

    def _load(self):
        """Load preferences from disk."""
        if not self.storage_path or not self.storage_path.exists():
            return

        with open(self.storage_path) as f:
            data = json.load(f)
            self.preferences = [UserPreference.from_dict(d) for d in data]

    def __repr__(self) -> str:
        return f"UserPreferenceTracker(preferences={len(self.preferences)})"
