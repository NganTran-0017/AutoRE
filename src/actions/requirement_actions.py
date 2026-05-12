"""
Actions for Requirement Engineer agent (v2 - with LessonAwareAction).

These actions handle requirement analysis and Alloy model creation/updating.
"""
from .lesson_aware_action import LessonAwareAction
from typing import Dict, Any


class AnalyzeRequirements(LessonAwareAction):
    """
    Action to analyze initial requirements and produce requirements document.

    Uses SharedRuntimeContext for:
    - Memory access (lessons learned)
    - Prompt rendering
    - User preference tracking
    - Artifact storage
    """

    name: str = "AnalyzeRequirements"

    async def run(self, raw_requirements: str) -> str:
        """
        Analyze requirements from raw input.

        Args:
            raw_requirements: Raw requirement text from input file

        Returns:
            Structured requirements document
        """
        # Get lessons from memory
        lessons = self.get_lessons(limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        # Render prompt using PromptManager
        prompt = self.render_prompt(
            raw_requirements=raw_requirements,
            lessons=lessons_str,
            user_preferences=user_prefs
        )

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning, get cleaned output
        cleaned_response = self.parse_and_record_learning(response)

        # Store cleaned output in artifacts
        iteration = self.get_current_iteration()
        self.get_artifacts().store_requirements(iteration, cleaned_response)

        return cleaned_response


class IncorporateClarifications(LessonAwareAction):
    """
    Action to incorporate user clarifications into requirements document.
    """

    name: str = "IncorporateClarifications"

    async def run(
        self,
        requirements_document: str,
        user_clarifications: str
    ) -> str:
        """
        Update requirements document with user clarifications.

        Args:
            requirements_document: Current requirements document
            user_clarifications: User's clarifications

        Returns:
            Updated requirements document
        """
        # Get lessons
        lessons = self.get_lessons(limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Render prompt
        prompt = self.render_prompt(
            requirements_document=requirements_document,
            user_clarifications=user_clarifications,
            lessons=lessons_str
        )

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning, get cleaned output
        cleaned_response = self.parse_and_record_learning(response)

        # Store cleaned output in artifacts
        iteration = self.get_current_iteration()
        self.get_artifacts().store_requirements(iteration, cleaned_response)

        return cleaned_response


class BuildAlloyModel(LessonAwareAction):
    """
    Action to build initial Alloy model from requirements.
    """

    name: str = "BuildAlloyModel"

    async def run(
        self,
        requirements_document: str,
        user_feedback: str = ""
    ) -> str:
        """
        Build Alloy model from requirements.

        Args:
            requirements_document: Structured requirements
            user_feedback: User clarifications (if any)

        Returns:
            Alloy model code
        """
        # Get lessons
        lessons = self.get_lessons(limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        # Render prompt
        prompt = self.render_prompt(
            requirements_document=requirements_document,
            user_feedback=user_feedback if user_feedback else "No user feedback yet.",
            lessons=lessons_str,
            user_preferences=user_prefs
        )

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning, get cleaned output
        cleaned_response = self.parse_and_record_learning(response)

        # Store cleaned output in artifacts
        iteration = self.get_current_iteration()
        self.get_artifacts().store_alloy_model(iteration, cleaned_response)

        return cleaned_response


class UpdateAlloyModel(LessonAwareAction):
    """
    Action to update Alloy model based on feedback.
    """

    name: str = "UpdateAlloyModel"

    async def run(
        self,
        current_model: str,
        evaluation_feedback: str,
        requirements_document: str
    ) -> str:
        """
        Update Alloy model based on evaluator feedback.

        Args:
            current_model: Current Alloy model code
            evaluation_feedback: Feedback from Evaluator
            requirements_document: Latest requirements

        Returns:
            Updated Alloy model code
        """
        # Get lessons
        lessons = self.get_lessons(limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        # Render prompt
        prompt = self.render_prompt(
            current_model=current_model,
            evaluation_feedback=evaluation_feedback,
            requirements_document=requirements_document,
            lessons=lessons_str,
            user_preferences=user_prefs
        )

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning, get cleaned output
        cleaned_response = self.parse_and_record_learning(response)

        # Store cleaned output in artifacts
        iteration = self.get_current_iteration()
        self.get_artifacts().store_alloy_model(iteration, cleaned_response)

        return cleaned_response
