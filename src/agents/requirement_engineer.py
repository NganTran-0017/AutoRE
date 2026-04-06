"""Requirement Engineer agent implementation."""
from metagpt.roles import Role
from metagpt.actions import Action
from metagpt.schema import Message
from typing import Optional
from pathlib import Path

from ..utils import AgentMemory, FileManager


class AnalyzeRequirements(Action):
    """Action to analyze initial requirements and produce requirements document."""

    name: str = "AnalyzeRequirements"

    async def run(self, input_file: str) -> str:
        """
        Analyze requirements from input file.

        Args:
            input_file: Path to input requirements file

        Returns:
            Requirements document with assumptions
        """
        with open(input_file, 'r') as f:
            raw_requirements = f.read()

        # Analyze and structure requirements
        prompt = f"""You are a Requirement Engineer. Analyze the following system description and requirements:

{raw_requirements}

Your tasks:
1. Restate the requirements clearly and unambiguously
2. Identify key concepts and entities in the system
3. List assumptions that need clarification for modeling
4. Structure the requirements in a clear format

Provide a comprehensive requirements document with the following sections:
- SYSTEM OVERVIEW
- FUNCTIONAL REQUIREMENTS
- KEY CONCEPTS AND ENTITIES
- ASSUMPTIONS REQUIRING CLARIFICATION
- CONSTRAINTS

Be thorough and precise."""

        # This would call the LLM in actual MetaGPT usage
        # For now, we'll use a structured format
        response = await self._aask(prompt)
        return response


class BuildAlloyModel(Action):
    """Action to build Alloy model from requirements."""

    name: str = "BuildAlloyModel"

    async def run(self, requirements: str, previous_models: Optional[str] = None,
                  feedback: Optional[str] = None, lessons: Optional[str] = None) -> str:
        """
        Build Alloy model from requirements.

        Args:
            requirements: Requirements document
            previous_models: Previous Alloy models (if updating)
            feedback: Feedback from Evaluator
            lessons: Lessons learned from memory

        Returns:
            Alloy model code
        """
        context_parts = [
            "You are a Requirement Engineer creating an Alloy model.",
            "",
            "Requirements:",
            requirements,
        ]

        if lessons:
            context_parts.extend([
                "",
                "Important lessons from previous iterations (avoid these mistakes):",
                lessons
            ])

        if previous_models:
            context_parts.extend([
                "",
                "Previous model version:",
                previous_models
            ])

        if feedback:
            context_parts.extend([
                "",
                "Feedback to address:",
                feedback
            ])

        context_parts.extend([
            "",
            "Create a formal Alloy model that:",
            "1. Captures all key concepts and entities",
            "2. Defines appropriate signatures and relations",
            "3. Includes facts for constraints",
            "4. Includes predicates for scenarios to check",
            "5. Includes assertions to verify properties",
            "6. Is syntactically correct",
            "",
            "Provide only the Alloy code without explanations."
        ])

        prompt = "\n".join(context_parts)
        response = await self._aask(prompt)
        return response


class UpdateAlloyModel(Action):
    """Action to update Alloy model based on feedback."""

    name: str = "UpdateAlloyModel"

    async def run(self, current_model: str, feedback: str, requirements: str,
                  lessons: Optional[str] = None) -> str:
        """
        Update Alloy model based on feedback.

        Args:
            current_model: Current Alloy model
            feedback: Feedback from Evaluator
            requirements: Updated requirements
            lessons: Lessons learned

        Returns:
            Updated Alloy model
        """
        context_parts = [
            "You are a Requirement Engineer updating an Alloy model.",
            "",
            "Current model:",
            current_model,
            "",
            "Current requirements:",
            requirements,
            "",
            "Feedback to address:",
            feedback
        ]

        if lessons:
            context_parts.extend([
                "",
                "Important lessons (avoid repeating these mistakes):",
                lessons
            ])

        context_parts.extend([
            "",
            "Update the model to:",
            "1. Address all feedback points",
            "2. Fix any syntax errors",
            "3. Eliminate counterexamples if appropriate",
            "4. Maintain consistency with requirements",
            "5. Apply lessons learned",
            "",
            "Provide only the updated Alloy code."
        ])

        prompt = "\n".join(context_parts)
        response = await self._aask(prompt)
        return response


class RequirementEngineer(Role):
    """
    Requirement Engineer agent.

    Responsibilities:
    - Analyze raw requirements
    - Create requirements documents
    - Build Alloy models
    - Update models based on feedback
    - Maintain memory of past updates
    """

    name: str = "RequirementEngineer"
    profile: str = "Requirement Engineer"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_actions([AnalyzeRequirements, BuildAlloyModel, UpdateAlloyModel])
        self.memory_manager = AgentMemory("RE")
        self.file_manager = FileManager()

    async def analyze_initial_requirements(self, input_file: str) -> str:
        """
        Analyze initial requirements and create requirements document.

        Args:
            input_file: Path to input file

        Returns:
            Requirements document
        """
        action = AnalyzeRequirements()
        requirements = await action.run(input_file)

        # Save to file
        iteration = self.memory_manager.get_iteration()
        self.file_manager.save_requirements(requirements, iteration)

        # Update memory
        self.memory_manager.add_high_level_entry(
            "Analyzed initial requirements and created requirements document"
        )
        self.memory_manager.add_detailed_entry({
            "action": "analyze_requirements",
            "input_file": input_file,
            "output_file": f"ReqsDoc/Reqs_{iteration}.txt"
        })

        return requirements

    async def create_alloy_model(self, requirements: str, previous_feedback: Optional[str] = None) -> str:
        """
        Create Alloy model from requirements.

        Args:
            requirements: Requirements document
            previous_feedback: Optional feedback from previous iteration

        Returns:
            Alloy model code
        """
        iteration = self.memory_manager.get_iteration()

        # Get lessons learned
        lessons = self._format_lessons()

        # Get previous model if updating
        previous_model = None
        if iteration > 0:
            previous_model = self.file_manager.load_alloy_model(iteration - 1)

        action = BuildAlloyModel()
        model = await action.run(
            requirements=requirements,
            previous_models=previous_model,
            feedback=previous_feedback,
            lessons=lessons
        )

        # Save model
        self.file_manager.save_alloy_model(model, iteration)

        # Update memory
        self.memory_manager.add_high_level_entry(
            f"Created Alloy model (iteration {iteration})"
        )
        self.memory_manager.add_detailed_entry({
            "action": "create_model",
            "iteration": iteration,
            "has_previous": previous_model is not None,
            "has_feedback": previous_feedback is not None
        })

        return model

    async def update_model(self, feedback: str, requirements: str) -> str:
        """
        Update Alloy model based on feedback.

        Args:
            feedback: Feedback from Evaluator
            requirements: Current requirements

        Returns:
            Updated Alloy model
        """
        iteration = self.memory_manager.get_iteration()
        current_model = self.file_manager.load_alloy_model(iteration)

        if not current_model:
            raise ValueError(f"No model found for iteration {iteration}")

        lessons = self._format_lessons()

        action = UpdateAlloyModel()
        updated_model = await action.run(
            current_model=current_model,
            feedback=feedback,
            requirements=requirements,
            lessons=lessons
        )

        # Increment iteration and save
        self.memory_manager.increment_iteration()
        new_iteration = self.memory_manager.get_iteration()
        self.file_manager.save_alloy_model(updated_model, new_iteration)

        # Update memory
        self.memory_manager.add_high_level_entry(
            f"Updated Alloy model based on feedback (iteration {new_iteration})"
        )

        return updated_model

    def _format_lessons(self) -> str:
        """Format lessons learned for prompt."""
        lessons = self.memory_manager.get_lessons(category="modeling")
        if not lessons:
            return ""

        formatted = ["Lessons learned:"]
        for lesson in lessons[-5:]:  # Last 5 lessons
            formatted.append(f"- {lesson['lesson']}")

        return "\n".join(formatted)

    def add_lesson(self, lesson: str, category: str = "modeling"):
        """
        Add a lesson learned.

        Args:
            lesson: Lesson description
            category: Lesson category
        """
        self.memory_manager.add_lesson(lesson, category)

    def get_memory_summary(self) -> str:
        """Get memory summary."""
        return self.memory_manager.get_summary()
