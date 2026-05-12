"""
Shared runtime context for workflow execution.
"""
from pathlib import Path
from .memory_system import LongTermMemorySystem
from .user_preferences import UserPreferenceTracker
from .prompt_manager import PromptManager
from .learning_system import LearningSystem
from .iteration_tracker import IterationTracker
from .file_manager import FileManager
from .artifact_store import ArtifactStore


class SharedRuntimeContext:
    """
    Shared runtime context for one workflow run.

    Created once by workflow at startup and passed to all agents/actions.
    Contains all shared services and state.

    Components:
    - memory: Long-term memory with multi-dimensional tagging
    - user_preferences: Accumulates user preferences across iterations
    - prompt_manager: Renders prompts for any agent/action
    - learning: Coordinates learning across agents
    - iteration: Tracks current iteration number
    - file_manager: Handles file I/O
    - artifacts: In-memory store of all outputs

    Lifecycle:
    1. Created at workflow start
    2. Iteration incremented between cycles
    3. State persisted to disk at end

    Not shared:
    - Each agent's MetaGPT short-term memory (rc.memory)
    - Temporary prompt construction details
    """

    def __init__(self, project_name: str = "default", logger=None, use_semantic_memory: bool = True):
        """
        Initialize shared runtime context.

        Args:
            project_name: Project identifier for isolation
            logger: Optional AutoRELogger instance
            use_semantic_memory: Use ChromaDB for semantic retrieval (default: True)
        """
        self.project_name = project_name
        self.logger = logger

        # Initialize memory system (semantic or traditional)
        if use_semantic_memory:
            from .semantic_memory import SemanticMemorySystem
            self.memory = SemanticMemorySystem(project_name)
            self._memory_type = "semantic"
        else:
            self.memory = LongTermMemorySystem(project_name)
            self._memory_type = "traditional"

        # User preference storage path
        pref_path = Path(f"memory/{project_name}/user_preferences.json")
        self.user_preferences = UserPreferenceTracker(storage_path=pref_path)

        self.prompt_manager = PromptManager()
        self.learning = LearningSystem(self.memory)
        self.iteration = IterationTracker()
        self.file_manager = FileManager()
        self.artifacts = ArtifactStore()

    def next_iteration(self):
        """Move to next iteration."""
        self.iteration.increment()

    def get_current_iteration(self) -> int:
        """Get current iteration number."""
        return self.iteration.current

    def save_state(self):
        """
        Persist all state to disk.

        Saves:
        - Long-term memory
        - User preferences
        """
        self.memory.save()
        self.user_preferences.save()

    def __repr__(self) -> str:
        return (
            f"SharedRuntimeContext("
            f"project={self.project_name}, "
            f"iteration={self.iteration.current}, "
            f"memory_items={self.memory.get_stats()['total']}, "
            f"preferences={len(self.user_preferences.preferences)})"
        )
