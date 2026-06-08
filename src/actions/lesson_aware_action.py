"""
Base class for all actions with learning capabilities.
"""
from metagpt.actions import Action
from typing import List, Dict, Any
from ..utils.runtime_context import SharedRuntimeContext
from ..utils.file_manager import FileManager
from ..utils.artifact_store import ArtifactStore


class LessonAwareAction(Action):
    """
    Base class for all actions with learning and context awareness.

    Provides access to:
    - Long-term memory (lessons, patterns, events)
    - User preferences
    - Prompt rendering
    - File management
    - Artifact storage
    - Iteration tracking

    Usage:
        class MyAction(LessonAwareAction):
            def __init__(self, context: SharedRuntimeContext, agent_name: str):
                super().__init__(context, agent_name)

            async def run(self, **kwargs):
                # Access lessons
                lessons = self.get_lessons()

                # Render prompt
                prompt = self.render_prompt(
                    input_data=data,
                    lessons=self.format_lessons(lessons)
                )

                # ... rest of action logic
    """

    def __init__(self, context: SharedRuntimeContext, agent_name: str):
        """
        Initialize action with shared context.

        Args:
            context: Shared runtime context
            agent_name: Name of the agent this action belongs to
        """
        super().__init__()
        self.context = context
        self.agent_name = agent_name
        self.action_name = self.__class__.__name__

    # ========== Memory Access ==========

    def get_lessons(self, limit: int = 5) -> List[str]:
        """
        Get lessons for this agent/action.

        Args:
            limit: Maximum number of lessons

        Returns:
            List of lesson strings
        """
        return self.context.memory.get_lessons(
            agent=self.agent_name,
            action=self.action_name,
            limit=limit
        )

    def get_lessons_for_context(self, context_query: str, limit: int = 5) -> List[str]:
        """
        Get lessons relevant to a specific context using semantic search.

        This uses semantic similarity to find lessons related to the given context,
        even if they're from different actions or agents.

        Args:
            context_query: Description of current context/problem
            limit: Maximum number of lessons

        Returns:
            List of lesson strings
        """
        # Check if semantic memory is available
        if hasattr(self.context.memory, 'retrieve_similar'):
            # Use semantic search across all lessons
            return self.context.memory.get_lessons(
                query=context_query,
                limit=limit
            )
        else:
            # Fall back to tag-based retrieval for current action
            return self.get_lessons(limit=limit)

    def get_patterns(self, limit: int = 5) -> List[str]:
        """
        Get patterns for this agent/action.

        Args:
            limit: Maximum number of patterns

        Returns:
            List of pattern strings
        """
        return self.context.memory.get_patterns(
            agent=self.agent_name,
            action=self.action_name,
            limit=limit
        )

    def record_lesson(self, lesson: str):
        """
        Record a lesson learned during execution.

        Args:
            lesson: Lesson text
        """
        self.context.learning.record_lesson(
            lesson=lesson,
            agent_name=self.agent_name,
            action_name=self.action_name,
            iteration=self.context.iteration.current
        )

    def record_pattern(self, pattern: str):
        """
        Record an observed pattern.

        Args:
            pattern: Pattern text
        """
        self.context.learning.record_pattern(
            pattern=pattern,
            agent_name=self.agent_name,
            action_name=self.action_name,
            iteration=self.context.iteration.current
        )

    def record_event(self, event: str):
        """
        Record an event.

        Args:
            event: Event text
        """
        self.context.learning.record_event(
            event=event,
            agent_name=self.agent_name,
            action_name=self.action_name,
            iteration=self.context.iteration.current
        )

    # ========== Prompt Management ==========

    def render_prompt(self, **variables) -> str:
        """
        Render prompt for this action with variables.

        Args:
            **variables: Template variables to substitute

        Returns:
            Fully rendered prompt string
        """
        return self.context.prompt_manager.render_prompt(
            agent_name=self.agent_name,
            action_name=self.action_name,
            **variables
        )

    def format_lessons(self, lessons: List[str]) -> str:
        """
        Format lessons for prompt inclusion.

        Args:
            lessons: List of lesson strings

        Returns:
            Formatted string
        """
        if not lessons:
            return "No previous lessons."

        lines = ["Previous Lessons:"]
        for i, lesson in enumerate(lessons, 1):
            lines.append(f"{i}. {lesson}")

        return "\n".join(lines)

    def format_patterns(self, patterns: List[str]) -> str:
        """
        Format patterns for prompt inclusion.

        Args:
            patterns: List of pattern strings

        Returns:
            Formatted string
        """
        if not patterns:
            return ""

        lines = ["Observed Patterns:"]
        for i, pattern in enumerate(patterns, 1):
            lines.append(f"{i}. {pattern}")

        return "\n".join(lines)

    def get_user_preferences(self) -> str:
        """
        Get formatted user preferences for prompt.

        Returns:
            Formatted user preferences string
        """
        return self.context.user_preferences.format_for_prompt()

    # ========== File and Artifact Access ==========

    def get_file_manager(self) -> FileManager:
        """Access file manager for I/O operations."""
        return self.context.file_manager

    def get_artifacts(self) -> ArtifactStore:
        """Access artifact store for outputs."""
        return self.context.artifacts

    def get_current_iteration(self) -> int:
        """Get current iteration number."""
        return self.context.iteration.current

    def _debug(self, message: str):
        """Log debug message to both console and log file."""
        if hasattr(self.context, 'logger') and self.context.logger:
            self.context.logger.log(message)

    # ========== Utility Methods ==========

    def parse_and_record_learning(self, output: str) -> str:
        """
        Parse output for learning signals, record them, and return cleaned output.

        Looks for [LESSON]:, [EVENT]: markers and removes them from output.

        Args:
            output: Agent output text to parse

        Returns:
            Cleaned output with learning markers removed
        """
        return self.context.learning.parse_and_record(
            agent_output=output,
            agent_name=self.agent_name,
            action_name=self.action_name,
            iteration=self.context.iteration.current
        )

    async def _aask(self, prompt: str, system_msgs: list = None) -> str:
        """
        Override _aask to log all LLM communications.

        Args:
            prompt: Prompt to send to LLM
            system_msgs: Optional system messages

        Returns:
            LLM response
        """
        # Call parent _aask
        response = await super()._aask(prompt, system_msgs)

        # Log the communication if logger is available
        if hasattr(self.context, 'logger') and self.context.logger:
            self.context.logger.log_agent_communication(
                agent_name=self.agent_name,
                action_name=self.action_name,
                prompt=prompt,
                response=response,
                iteration=self.context.iteration.current
            )

        return response

    def __repr__(self) -> str:
        return (
            f"{self.action_name}("
            f"agent={self.agent_name}, "
            f"iteration={self.context.iteration.current})"
        )
