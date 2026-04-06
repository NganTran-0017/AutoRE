"""Evaluator agent implementation."""
from metagpt.roles import Role
from metagpt.actions import Action
from metagpt.schema import Message
from typing import Dict, Any, Optional, List
import json

from ..utils import AgentMemory, FileManager, AlloyExecutor


class RunAlloyAnalyzer(Action):
    """Action to run Alloy Analyzer on a model."""

    name: str = "RunAlloyAnalyzer"

    def __init__(self, alloy_executor: AlloyExecutor, file_manager: FileManager):
        super().__init__()
        self.alloy_executor = alloy_executor
        self.file_manager = file_manager

    async def run(self, iteration: int) -> Dict[str, Any]:
        """
        Run Alloy Analyzer on the model for given iteration.

        Args:
            iteration: Iteration number

        Returns:
            Execution results
        """
        model_path = self.file_manager.get_alloy_model_path(iteration)
        output_dir = self.file_manager.create_analyzer_output_dir(iteration)

        if not model_path.exists():
            return {
                "success": False,
                "error": f"Model file not found: {model_path}"
            }

        # Execute Alloy
        result = self.alloy_executor.execute(model_path, output_dir)
        return result


class InterpretResults(Action):
    """Action to interpret Alloy Analyzer results."""

    name: str = "InterpretResults"

    async def run(self, execution_result: Dict[str, Any], requirements: str,
                  previous_feedback_summary: Optional[str] = None) -> str:
        """
        Interpret Alloy Analyzer results.

        Args:
            execution_result: Results from Alloy execution
            requirements: Current requirements
            previous_feedback_summary: Summary of previous feedback

        Returns:
            Interpretation and analysis
        """
        analysis = execution_result.get("analysis", {})

        context_parts = [
            "You are an Evaluator analyzing Alloy Analyzer results.",
            "",
            "Requirements:",
            requirements,
            ""
        ]

        if previous_feedback_summary:
            context_parts.extend([
                "Previous feedback summary (avoid repeating):",
                previous_feedback_summary,
                ""
            ])

        context_parts.extend([
            "Execution Summary:",
            f"Success: {execution_result.get('success', False)}",
            f"Syntax Errors: {analysis.get('has_syntax_errors', False)}",
            f"Counterexamples: {analysis.get('has_counterexamples', False)}",
            f"Satisfying Instances: {analysis.get('has_satisfying_instances', False)}",
            ""
        ])

        # Add details about errors
        if analysis.get("syntax_errors"):
            context_parts.append("Syntax Errors Details:")
            for err in analysis["syntax_errors"]:
                context_parts.append(f"  File: {err['file']}")
                context_parts.append(f"  Data: {json.dumps(err['data'], indent=2)}")

        # Add details about counterexamples
        if analysis.get("counterexamples"):
            context_parts.append("Counterexamples Details:")
            for ce in analysis["counterexamples"]:
                context_parts.append(f"  File: {ce['file']}")

        # Add details about instances
        if analysis.get("instances"):
            context_parts.append(f"Satisfying Instances: {len(analysis['instances'])}")

        context_parts.extend([
            "",
            "Provide a detailed interpretation including:",
            "1. What the results mean for the requirements",
            "2. Whether the model correctly captures the requirements",
            "3. Whether any issues need to be addressed",
            "4. Specific observations about the model behavior"
        ])

        prompt = "\n".join(context_parts)
        response = await self._aask(prompt)
        return response


class GenerateFeedback(Action):
    """Action to generate feedback for improving the model and requirements."""

    name: str = "GenerateFeedback"

    async def run(self, interpretation: str, execution_result: Dict[str, Any],
                  requirements: str, alloy_model: str,
                  previous_feedbacks: Optional[str] = None) -> Dict[str, str]:
        """
        Generate comprehensive feedback.

        Args:
            interpretation: Result interpretation
            execution_result: Alloy execution results
            requirements: Current requirements
            alloy_model: Current Alloy model
            previous_feedbacks: Summary of previous feedbacks

        Returns:
            Dictionary with feedback for different aspects
        """
        analysis = execution_result.get("analysis", {})

        context_parts = [
            "You are an Evaluator providing feedback to improve the system.",
            "",
            "Current Requirements:",
            requirements,
            "",
            "Current Alloy Model:",
            alloy_model,
            "",
            "Analysis Results:",
            interpretation,
            ""
        ]

        if previous_feedbacks:
            context_parts.extend([
                "Previous Feedbacks (for context, don't repeat):",
                previous_feedbacks,
                ""
            ])

        context_parts.extend([
            "Provide specific, actionable feedback for:",
            "1. ALLOY_MODEL_IMPROVEMENTS: How to fix/improve the Alloy model",
            "2. REQUIREMENT_UPDATES: Suggested updates to English requirements",
            "3. ASSUMPTIONS_TO_CLARIFY: New assumptions that need user clarification",
            "",
            "Format your response as:",
            "=== ALLOY_MODEL_IMPROVEMENTS ===",
            "[your feedback]",
            "",
            "=== REQUIREMENT_UPDATES ===",
            "[your feedback]",
            "",
            "=== ASSUMPTIONS_TO_CLARIFY ===",
            "[your feedback]"
        ])

        # Add specific guidance based on results
        if analysis.get("has_syntax_errors"):
            context_parts.append("\nPriority: Fix syntax errors first!")
        elif analysis.get("has_counterexamples"):
            context_parts.append("\nPriority: Address counterexamples!")
        elif not analysis.get("has_satisfying_instances"):
            context_parts.append("\nPriority: Model may be over-constrained!")

        prompt = "\n".join(context_parts)
        response = await self._aask(prompt)

        # Parse response into sections
        feedback = self._parse_feedback(response)
        return feedback

    def _parse_feedback(self, response: str) -> Dict[str, str]:
        """Parse feedback response into sections."""
        sections = {
            "alloy_improvements": "",
            "requirement_updates": "",
            "assumptions": ""
        }

        current_section = None
        lines = []

        for line in response.split('\n'):
            if '=== ALLOY_MODEL_IMPROVEMENTS ===' in line:
                if current_section and lines:
                    sections[current_section] = '\n'.join(lines).strip()
                current_section = 'alloy_improvements'
                lines = []
            elif '=== REQUIREMENT_UPDATES ===' in line:
                if current_section and lines:
                    sections[current_section] = '\n'.join(lines).strip()
                current_section = 'requirement_updates'
                lines = []
            elif '=== ASSUMPTIONS_TO_CLARIFY ===' in line:
                if current_section and lines:
                    sections[current_section] = '\n'.join(lines).strip()
                current_section = 'assumptions'
                lines = []
            elif current_section:
                lines.append(line)

        if current_section and lines:
            sections[current_section] = '\n'.join(lines).strip()

        return sections


class UpdateRequirements(Action):
    """Action to update English requirements based on findings."""

    name: str = "UpdateRequirements"

    async def run(self, current_requirements: str, suggested_updates: str,
                  user_feedback: Optional[str] = None) -> str:
        """
        Update requirements document.

        Args:
            current_requirements: Current requirements
            suggested_updates: Suggested updates from analysis
            user_feedback: User feedback

        Returns:
            Updated requirements
        """
        context_parts = [
            "You are an Evaluator updating the requirements document.",
            "",
            "Current Requirements:",
            current_requirements,
            "",
            "Suggested Updates:",
            suggested_updates
        ]

        if user_feedback:
            context_parts.extend([
                "",
                "User Feedback:",
                user_feedback
            ])

        context_parts.extend([
            "",
            "Update the requirements to:",
            "1. Incorporate suggested improvements",
            "2. Address user feedback if provided",
            "3. Maintain clarity and precision",
            "4. Preserve all relevant information",
            "",
            "Provide the complete updated requirements document."
        ])

        prompt = "\n".join(context_parts)
        response = await self._aask(prompt)
        return response


class Evaluator(Role):
    """
    Evaluator agent.

    Responsibilities:
    - Run Alloy Analyzer on models
    - Interpret analyzer results
    - Generate feedback for improvements
    - Update requirements
    - Maintain memory of feedback history
    """

    name: str = "Evaluator"
    profile: str = "Requirements Evaluator"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_actions([RunAlloyAnalyzer, InterpretResults, GenerateFeedback, UpdateRequirements])
        self.memory_manager = AgentMemory("Evaluator")
        self.file_manager = FileManager()
        self.alloy_executor = AlloyExecutor()

        # Store feedback history
        self.feedback_history: List[Dict[str, Any]] = []

    async def evaluate_model(self, iteration: int, requirements: str,
                           alloy_model: str) -> Dict[str, Any]:
        """
        Evaluate Alloy model for given iteration.

        Args:
            iteration: Iteration number
            requirements: Current requirements
            alloy_model: Current Alloy model

        Returns:
            Evaluation results with feedback
        """
        # Run Alloy Analyzer
        run_action = RunAlloyAnalyzer(self.alloy_executor, self.file_manager)
        execution_result = await run_action.run(iteration)

        if not execution_result.get("success", False):
            return {
                "success": False,
                "error": execution_result.get("error", "Unknown error"),
                "execution_result": execution_result
            }

        # Interpret results
        interpret_action = InterpretResults()
        previous_summary = self._get_previous_feedback_summary()
        interpretation = await interpret_action.run(
            execution_result,
            requirements,
            previous_summary
        )

        # Generate feedback
        feedback_action = GenerateFeedback()
        feedback = await feedback_action.run(
            interpretation,
            execution_result,
            requirements,
            alloy_model,
            previous_summary
        )

        # Store feedback in memory
        feedback_entry = {
            "iteration": iteration,
            "interpretation": interpretation,
            "feedback": feedback,
            "execution_summary": {
                "has_syntax_errors": execution_result["analysis"]["has_syntax_errors"],
                "has_counterexamples": execution_result["analysis"]["has_counterexamples"],
                "has_satisfying_instances": execution_result["analysis"]["has_satisfying_instances"]
            }
        }
        self.feedback_history.append(feedback_entry)

        self.memory_manager.add_high_level_entry(
            f"Evaluated model iteration {iteration}: " +
            f"Syntax OK: {not execution_result['analysis']['has_syntax_errors']}, " +
            f"No counterexamples: {not execution_result['analysis']['has_counterexamples']}, " +
            f"Has instances: {execution_result['analysis']['has_satisfying_instances']}"
        )

        self.memory_manager.add_detailed_entry({
            "action": "evaluate_model",
            "iteration": iteration,
            "results": execution_result["analysis"]
        })

        # Learn from errors
        if execution_result["analysis"]["has_syntax_errors"]:
            self.memory_manager.add_lesson(
                "Syntax errors found - provide specific fixes",
                category="feedback"
            )

        return {
            "success": True,
            "execution_result": execution_result,
            "interpretation": interpretation,
            "feedback": feedback,
            "complete": self._is_complete(execution_result)
        }

    async def update_requirements_with_feedback(self, current_requirements: str,
                                               suggested_updates: str,
                                               user_feedback: Optional[str] = None) -> str:
        """
        Update requirements based on feedback.

        Args:
            current_requirements: Current requirements
            suggested_updates: Suggested updates
            user_feedback: Optional user feedback

        Returns:
            Updated requirements
        """
        update_action = UpdateRequirements()
        updated = await update_action.run(
            current_requirements,
            suggested_updates,
            user_feedback
        )

        iteration = self.memory_manager.get_iteration()
        self.memory_manager.increment_iteration()
        new_iteration = self.memory_manager.get_iteration()

        self.file_manager.save_requirements(updated, new_iteration)

        self.memory_manager.add_high_level_entry(
            f"Updated requirements (iteration {new_iteration})"
        )

        return updated

    def _get_previous_feedback_summary(self) -> str:
        """Get summary of previous feedback."""
        if len(self.feedback_history) == 0:
            return ""

        recent = self.feedback_history[-3:]  # Last 3 feedbacks
        summary_parts = ["Recent feedback summary:"]

        for entry in recent:
            iter_num = entry["iteration"]
            exec_sum = entry["execution_summary"]
            summary_parts.append(
                f"Iteration {iter_num}: " +
                f"Syntax: {'OK' if not exec_sum['has_syntax_errors'] else 'ERRORS'}, " +
                f"Counterexamples: {'YES' if exec_sum['has_counterexamples'] else 'NO'}, " +
                f"Instances: {'YES' if exec_sum['has_satisfying_instances'] else 'NO'}"
            )

        return "\n".join(summary_parts)

    def _is_complete(self, execution_result: Dict[str, Any]) -> bool:
        """
        Check if the verification is complete.

        Args:
            execution_result: Alloy execution results

        Returns:
            True if no issues found
        """
        analysis = execution_result.get("analysis", {})
        return (
            not analysis.get("has_syntax_errors", True) and
            not analysis.get("has_counterexamples", True) and
            analysis.get("has_satisfying_instances", False)
        )

    def get_memory_summary(self) -> str:
        """Get memory summary."""
        return self.memory_manager.get_summary()

    def get_evaluation_summary(self) -> str:
        """Get summary of all evaluations."""
        if not self.feedback_history:
            return "No evaluations performed yet."

        summary_parts = [
            f"Total Evaluations: {len(self.feedback_history)}",
            ""
        ]

        for entry in self.feedback_history:
            exec_sum = entry["execution_summary"]
            summary_parts.append(
                f"Iteration {entry['iteration']}: " +
                f"Syntax: {'✓' if not exec_sum['has_syntax_errors'] else '✗'}, " +
                f"Counterexamples: {'✗' if exec_sum['has_counterexamples'] else '✓'}, " +
                f"Instances: {'✓' if exec_sum['has_satisfying_instances'] else '✗'}"
            )

        return "\n".join(summary_parts)