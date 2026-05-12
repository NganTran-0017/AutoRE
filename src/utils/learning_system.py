"""
Learning system for coordinating learning across agents.
"""
from typing import List
import re
from .memory_system import LongTermMemorySystem


class LearningSystem:
    """
    Coordinates learning across agents and actions.

    Responsibilities:
    - Parse learning signals from agent outputs
    - Store in memory with proper tagging
    - Provide formatted learning summaries for prompts

    Learning signals in agent output:
        [LESSON]: Don't use undefined predicates in assertions
        [PATTERN]: Counterexamples often indicate missing constraints
        [EVENT]: User requested focus on security properties
    """

    def __init__(self, memory: LongTermMemorySystem):
        """
        Initialize learning system.

        Args:
            memory: Long-term memory system to store learning
        """
        self.memory = memory

    def parse_and_record(
        self,
        agent_output: str,
        agent_name: str,
        action_name: str,
        iteration: int
    ) -> str:
        """
        Parse agent output for learning signals, store them, and return cleaned output.

        Looks for patterns:
        - [LESSON]: <text>
        - [EVENT]: <text>

        Args:
            agent_output: The agent's output text
            agent_name: Name of the agent
            action_name: Name of the action
            iteration: Current iteration number

        Returns:
            Cleaned output with learning markers removed
        """
        # Extract and store lessons
        lessons = self._extract_marked_content(agent_output, "LESSON")
        for lesson in lessons:
            self.memory.store(
                content=lesson,
                item_type="lesson",
                agent=agent_name,
                action=action_name,
                iteration=iteration
            )

        # Extract and store events
        events = self._extract_marked_content(agent_output, "EVENT")
        for event in events:
            self.memory.store(
                content=event,
                item_type="event",
                agent=agent_name,
                action=action_name,
                iteration=iteration
            )

        # Remove learning markers from output
        cleaned_output = self._remove_learning_markers(agent_output)
        return cleaned_output

    def _extract_marked_content(self, text: str, marker: str) -> List[str]:
        """
        Extract content marked with [MARKER]: syntax.

        Args:
            text: Text to search
            marker: Marker name (e.g., "LESSON", "PATTERN")

        Returns:
            List of extracted content strings
        """
        pattern = rf'\[{marker}\]:\s*(.+?)(?:\n|$)'
        matches = re.finditer(pattern, text, re.MULTILINE)
        return [match.group(1).strip() for match in matches]

    def _remove_learning_markers(self, text: str) -> str:
        """
        Remove all learning markers from text.

        Removes:
        - [LESSON]: <single line text>
        - [LESSON]: <multi-line with bullets>
        - [EVENT]: <single line text>
        - [EVENT]: <multi-line with bullets>
        - [PATTERN]: <text> (legacy, no longer used but cleaned for backward compatibility)

        Args:
            text: Text with learning markers

        Returns:
            Text with markers removed
        """
        # Remove learning markers and their content
        # Handles both single-line and multi-line (bullet list) formats

        # Pattern 1: Single-line format: **[LESSON]: text on same line
        text = re.sub(r'^\s*\*?\*?\[LESSON\]:\s*.+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\*?\*?\[EVENT\]:\s*.+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\*?\*?\[PATTERN\]:\s*.+$', '', text, flags=re.MULTILINE)

        # Pattern 2: Multi-line format: **[LESSON]:** followed by bullet points
        # Remove marker line followed by consecutive lines starting with - or *
        text = re.sub(
            r'^\s*\*?\*?\[LESSON\]:\*?\*?\s*\n(^\s*[-*]\s+.+$\n?)+',
            '',
            text,
            flags=re.MULTILINE
        )
        text = re.sub(
            r'^\s*\*?\*?\[EVENT\]:\*?\*?\s*\n(^\s*[-*]\s+.+$\n?)+',
            '',
            text,
            flags=re.MULTILINE
        )
        text = re.sub(
            r'^\s*\*?\*?\[PATTERN\]:\*?\*?\s*\n(^\s*[-*]\s+.+$\n?)+',
            '',
            text,
            flags=re.MULTILINE
        )

        # Clean up excessive blank lines (more than 2 consecutive)
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def get_lessons_for_prompt(
        self,
        agent_name: str,
        action_name: str,
        limit: int = 10
    ) -> str:
        """
        Format recent lessons for prompt inclusion.

        Args:
            agent_name: Agent to get lessons for
            action_name: Action to get lessons for
            limit: Maximum number of lessons

        Returns:
            Formatted string ready for prompt insertion
        """
        lessons = self.memory.get_lessons(
            agent=agent_name,
            action=action_name,
            limit=limit
        )

        if not lessons:
            return ""

        lines = ["Previous Lessons Learned:"]
        for i, lesson in enumerate(lessons, 1):
            lines.append(f"{i}. {lesson}")

        return "\n".join(lines)

    def get_patterns_for_prompt(
        self,
        agent_name: str,
        action_name: str,
        limit: int = 5
    ) -> str:
        """
        Format recent patterns for prompt inclusion.

        Args:
            agent_name: Agent to get patterns for
            action_name: Action to get patterns for
            limit: Maximum number of patterns

        Returns:
            Formatted string ready for prompt insertion
        """
        patterns = self.memory.get_patterns(
            agent=agent_name,
            action=action_name,
            limit=limit
        )

        if not patterns:
            return ""

        lines = ["Observed Patterns:"]
        for i, pattern in enumerate(patterns, 1):
            lines.append(f"{i}. {pattern}")

        return "\n".join(lines)

    def get_all_learning_for_prompt(
        self,
        agent_name: str,
        action_name: str,
        lesson_limit: int = 10,
        pattern_limit: int = 5
    ) -> str:
        """
        Get all learning (lessons + patterns) formatted for prompt.

        Args:
            agent_name: Agent name
            action_name: Action name
            lesson_limit: Max lessons to include
            pattern_limit: Max patterns to include

        Returns:
            Formatted string with both lessons and patterns
        """
        sections = []

        # Add lessons
        lessons_str = self.get_lessons_for_prompt(
            agent_name, action_name, lesson_limit
        )
        if lessons_str:
            sections.append(lessons_str)

        # Add patterns
        patterns_str = self.get_patterns_for_prompt(
            agent_name, action_name, pattern_limit
        )
        if patterns_str:
            sections.append(patterns_str)

        return "\n\n".join(sections) if sections else ""

    def get_lessons_semantic(
        self,
        query: str,
        agent_name: str,
        action_name: str,
        limit: int = 10
    ) -> str:
        """
        Get lessons using semantic search based on query context.

        If semantic memory is available, retrieves lessons similar to the query.
        Otherwise, falls back to tag-based retrieval.

        Args:
            query: Query text describing current context/problem
            agent_name: Agent to get lessons for
            action_name: Action to get lessons for
            limit: Maximum number of lessons

        Returns:
            Formatted string ready for prompt insertion
        """
        # Check if semantic memory is available
        if hasattr(self.memory, 'retrieve_similar'):
            # Use semantic search
            lessons = self.memory.get_lessons(
                agent=agent_name,
                action=action_name,
                limit=limit,
                query=query
            )
        else:
            # Fall back to tag-based retrieval
            lessons = self.memory.get_lessons(
                agent=agent_name,
                action=action_name,
                limit=limit
            )

        if not lessons:
            return ""

        lines = ["Previous Lessons Learned:"]
        for i, lesson in enumerate(lessons, 1):
            lines.append(f"{i}. {lesson}")

        return "\n".join(lines)

    def record_lesson(
        self,
        lesson: str,
        agent_name: str,
        action_name: str,
        iteration: int
    ):
        """
        Directly record a lesson (without parsing).

        Useful for programmatically adding lessons.

        Args:
            lesson: Lesson text
            agent_name: Agent name
            action_name: Action name
            iteration: Current iteration
        """
        self.memory.store(
            content=lesson,
            item_type="lesson",
            agent=agent_name,
            action=action_name,
            iteration=iteration
        )

    def record_pattern(
        self,
        pattern: str,
        agent_name: str,
        action_name: str,
        iteration: int
    ):
        """
        Directly record a pattern (without parsing).

        Args:
            pattern: Pattern text
            agent_name: Agent name
            action_name: Action name
            iteration: Current iteration
        """
        self.memory.store(
            content=pattern,
            item_type="pattern",
            agent=agent_name,
            action=action_name,
            iteration=iteration
        )

    def record_event(
        self,
        event: str,
        agent_name: str,
        action_name: str,
        iteration: int
    ):
        """
        Directly record an event (without parsing).

        Args:
            event: Event text
            agent_name: Agent name
            action_name: Action name
            iteration: Current iteration
        """
        self.memory.store(
            content=event,
            item_type="event",
            agent=agent_name,
            action=action_name,
            iteration=iteration
        )

    def __repr__(self) -> str:
        stats = self.memory.get_stats()
        return (
            f"LearningSystem("
            f"lessons={stats['by_type'].get('lesson', 0)}, "
            f"patterns={stats['by_type'].get('pattern', 0)}, "
            f"events={stats['by_type'].get('event', 0)})"
        )
