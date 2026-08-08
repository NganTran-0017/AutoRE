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

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        prompt_path: str = "prompts/MemoryAssistant_prompt.txt",
        section: str = "MergeLessons",
        existing_token: str = "{{existing_lesson}}",
        new_token: str = "{{new_lesson}}",
        fallback_template: str = None,
    ):
        """
        Initialize MemoryAssistant action.

        Args:
            model: Model to use (default: gpt-4o-mini)
            prompt_path: Path to prompt template file
            section: [SECTION: <name>] to render from the prompt file
                (e.g. "MergeLessons" or "MergeConventions"). The "Role" section,
                if present, is prepended.
            existing_token / new_token: placeholders substituted at run time.
            fallback_template: used if the file or section is missing.
        """
        super().__init__()

        # Configure LLM with specified model
        from metagpt.provider.openai_api import OpenAILLM
        from metagpt.config2 import Config

        config = Config.default()
        config.llm.model = model
        self.llm = OpenAILLM(config.llm)

        self.existing_token = existing_token
        self.new_token = new_token
        self.fallback_template = fallback_template or (
            "Merge these two memory items into one, preserving all important "
            "information:\n\nExisting: " + existing_token + "\nNew: " + new_token
            + "\n\nMerged item:"
        )

        # Load prompt template (the named task section, with Role prepended)
        self.prompt_template = self._load_prompt_template(prompt_path, section)

    def _load_prompt_template(self, prompt_path: str, section: str) -> str:
        """Render the given [SECTION: <section>] (with Role prepended) from the file."""
        from pathlib import Path

        path = Path(prompt_path)
        if not path.exists():
            return self.fallback_template

        sections = self._parse_sections(path.read_text())
        body = sections.get(section)
        if not body:
            return self.fallback_template

        role = sections.get("Role", "")
        return f"{role}\n\n{body}".strip() if role else body

    @staticmethod
    def _parse_sections(text: str) -> dict:
        """Split a prompt file into {section_name: content} on [SECTION: name] markers."""
        import re

        sections = {}
        current = None
        buf = []
        for line in text.splitlines():
            if line.strip().startswith("[SECTION:"):
                if current:
                    sections[current] = "\n".join(buf).strip()
                match = re.match(r'\[SECTION:\s*(.+?)\s*\]', line.strip())
                current = match.group(1) if match else None
                buf = []
            else:
                buf.append(line)
        if current:
            sections[current] = "\n".join(buf).strip()
        return sections

    async def run(self, existing: str, new: str) -> str:
        """
        Merge two similar items into one, per this action's section/prompt.

        Args:
            existing: The existing item in memory
            new: The newly received item

        Returns:
            The single merged item
        """
        # Substitute variables in prompt template
        prompt = self.prompt_template.replace(self.existing_token, existing)
        prompt = prompt.replace(self.new_token, new)

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
        self._model = config.get('model', 'gpt-4o-mini')
        self.action = MergeLessonsAction(model=self._model)
        self._convention_action = None

    @property
    def convention_action(self) -> MergeLessonsAction:
        """Lazily build the convention merge action (preserve-all prompt)."""
        if self._convention_action is None:
            self._convention_action = MergeLessonsAction(
                model=self._model,
                section="MergeConventions",
                existing_token="{{existing_convention}}",
                new_token="{{new_convention}}",
                fallback_template=(
                    "Merge these two BINDING modeling conventions into ONE, "
                    "preserving EVERY constraint from both (never drop, soften, "
                    "or generalize; if they conflict keep both as separate "
                    "clauses):\n\nExisting: {{existing_convention}}\n"
                    "New: {{new_convention}}\n\nMerged convention:"
                ),
            )
        return self._convention_action

    # Verdicts the merge classifier may return. CONTRADICTORY is the one that
    # matters: it is the case a similarity score cannot detect, because
    # "always X" and "never X" embed close together.
    VERDICTS = ("SAME", "COMPLEMENTARY", "CONTRADICTORY")

    # Returned when the reply carries no usable verdict. This is NOT a verdict -
    # it means the classifier did not answer, so the caller must take the action
    # that changes nothing (keep both items, on their own rows).
    UNPARSED = "UNPARSED"

    @classmethod
    def parse_lesson_merge(cls, response: str) -> tuple:
        """
        Parse a `VERDICT:`/`MERGED:` reply into (verdict, merged_text).

        Returns (UNPARSED, <whole reply>) when the reply carries no verdict line
        - an older prompt, or a model that ignored the format. This deliberately
        does NOT default to COMPLEMENTARY: merging is the destructive branch (it
        rewrites the surviving row), and defaulting to it meant a malformed reply
        could fold a binding convention into the rule that replaced it. Doing
        nothing loses no guidance - the new item is simply stored on its own row.
        """
        import re

        text = (response or "").strip()
        if not text:
            return cls.UNPARSED, ""

        verdict = None
        merged_lines = []
        seen_merged = False
        for line in text.splitlines():
            stripped = line.strip()
            # Models decorate labels ("**VERDICT**:", "`MERGED`:"); match against
            # a copy with that markup removed so the label is still recognised.
            plain = stripped.replace('*', '').replace('`', '').strip()

            match = re.match(r"(?i)^verdict\s*:\s*(.+)$", plain)
            if match and verdict is None:
                token = match.group(1).strip().strip('.').upper()
                verdict = token if token in cls.VERDICTS else None
                continue
            match = re.match(r"(?i)^merged\s*:\s*(.*)$", plain)
            if match:
                seen_merged = True
                if match.group(1).strip():
                    merged_lines.append(match.group(1).strip())
                continue
            if seen_merged and stripped:
                merged_lines.append(stripped)

        if verdict is None:
            return cls.UNPARSED, text

        merged = " ".join(merged_lines).strip()
        if merged.upper() in ("NONE", "N/A", ""):
            merged = ""
        return verdict, merged

    async def merge_lessons(self, existing: str, new: str) -> str:
        """Merge two similar lessons into one brief sentence."""
        _verdict, merged = await self.merge_lessons_classified(existing, new)
        return merged

    async def merge_lessons_classified(self, existing: str, new: str) -> tuple:
        """
        Classify the relationship between two lessons, and merge when they are
        compatible.

        Returns (verdict, merged_text). On CONTRADICTORY the merged text is
        empty: the two lessons must not be reconciled into one sentence, since
        whichever side the wording favours becomes the one the agent follows.
        """
        raw = await self.action.run(existing, new)
        return self.parse_lesson_merge(raw)

    async def merge_conventions(self, existing: str, new: str) -> str:
        """Merge two similar modeling conventions, preserving every constraint."""
        _verdict, merged = await self.merge_conventions_classified(existing, new)
        return merged

    async def merge_conventions_classified(self, existing: str, new: str) -> tuple:
        """
        Classify the relationship between two conventions, and merge when they
        are compatible.

        Conventions get the same treatment lessons do, for a sharper reason: a
        convention is BINDING on the model builder, and a convention sits closest
        in embedding space to the convention that REPLACES it - both describe the
        same corner of the model. Folding those two into one sentence hands the
        builder a rule and its own replacement at once.

        Returns (verdict, merged_text); the text is empty on CONTRADICTORY.
        """
        raw = await self.convention_action.run(existing, new)
        return self.parse_lesson_merge(raw)

    async def merge(self, item_type: str, existing: str, new: str) -> str:
        """Dispatch to the merge appropriate for the collection type."""
        if item_type == "convention":
            return await self.merge_conventions(existing, new)
        return await self.merge_lessons(existing, new)
