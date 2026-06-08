"""
MemoryAssistant action for merging similar lessons.
"""
from metagpt.actions import Action


class MergeLessonsAction(Action):
    """
    Action to merge two similar lessons into one concise lesson.

    Uses a lightweight model (gpt-4o-mini) for cost efficiency.
    """

    name: str = "MergeLessons"

    def __init__(self, model: str = "gpt-4o-mini", prompt_path: str = "prompts/MemoryAssistant_prompt.txt"):
        """
        Initialize MemoryAssistant action.

        Args:
            model: Model to use (default: gpt-4o-mini)
            prompt_path: Path to prompt template file
        """
        super().__init__()

        # Configure LLM with specified model
        from metagpt.provider.openai_api import OpenAILLM
        from metagpt.config2 import Config

        config = Config.default()
        config.llm.model = model
        self.llm = OpenAILLM(config.llm)

        # Load prompt template
        self.prompt_template = self._load_prompt_template(prompt_path)

    def _load_prompt_template(self, prompt_path: str) -> str:
        """Load prompt template from file."""
        from pathlib import Path

        path = Path(prompt_path)
        if not path.exists():
            # Fallback to simple inline prompt
            return """Merge these lessons into one brief sentence:

Existing: {{existing_lesson}}
New: {{new_lesson}}

Merged lesson (one sentence):"""

        return path.read_text()

    async def run(self, existing_lesson: str, new_lesson: str) -> str:
        """
        Merge two similar lessons into one concise lesson.

        Args:
            existing_lesson: The existing lesson in memory
            new_lesson: The newly received lesson

        Returns:
            Single merged lesson (one brief sentence)
        """
        # Substitute variables in prompt template
        prompt = self.prompt_template.replace("{{existing_lesson}}", existing_lesson)
        prompt = prompt.replace("{{new_lesson}}", new_lesson)

        # Use the lightweight model to merge
        merged = await self.llm.aask(prompt)

        return merged.strip()


class MemoryAssistant:
    """
    Helper class to manage lesson merging operations.
    Provides a simple interface for SemanticMemorySystem.
    """

    def __init__(self, config: dict = None):
        """
        Initialize MemoryAssistant.

        Args:
            config: Configuration dict with 'model' key (default uses gpt-4o-mini)
        """
        config = config or {}
        model = config.get('model', 'gpt-4o-mini')
        self.action = MergeLessonsAction(model=model)

    async def merge_lessons(self, existing: str, new: str) -> str:
        """
        Merge two similar lessons.

        Args:
            existing: Existing lesson
            new: New lesson

        Returns:
            Merged lesson
        """
        return await self.action.run(existing, new)
