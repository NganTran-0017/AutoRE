"""Main workflow orchestrator for AutoRE system."""
import asyncio
from pathlib import Path

from .agents import RequirementEngineer, Evaluator
from .utils import CLIInteraction, FileManager, AutoRELogger


class AutoREWorkflow:
    """
    Orchestrates the multi-agent requirement engineering workflow.

    Workflow steps:
    1. RE analyzes initial requirements and asks for clarification
    2. User provides clarification
    3. RE builds initial Alloy model
    4. Evaluator runs Alloy Analyzer and interprets results
    5. Evaluator generates feedback and asks user for review
    6. User provides feedback and additional scenarios
    7. Evaluator updates requirements based on feedback
    8. RE updates Alloy model based on feedback
    9. Steps 4-8 repeat until convergence
    """

    def __init__(self, base_dir: str = ".", timeout: int = 300):
        """
        Initialize workflow.

        Args:
            base_dir: Base directory for the project
            timeout: User input timeout in seconds (default: 300 = 5 minutes)
        """
        self.base_dir = Path(base_dir)
        self.logger = AutoRELogger(log_dir=str(self.base_dir / "outputlog"))
        self.re_agent = RequirementEngineer()
        self.evaluator = Evaluator()
        self.cli = CLIInteraction(self.logger, timeout=timeout)
        self.file_manager = FileManager(base_dir)

        self.current_iteration = 0
        self.requirements = None
        self.alloy_model = None

    async def run(self, input_file: str, max_iterations: int = 10):
        """
        Run the complete workflow.

        Args:
            input_file: Path to initial requirements file
            max_iterations: Maximum number of iterations
        """
        self.logger.log_section("AutoRE - Automated Requirement Engineering System")

        try:
            # Step 1: Initial requirement analysis
            await self._step1_analyze_requirements(input_file)

            # Step 2: User clarification
            await self._step2_user_clarification()

            # Step 3: Build initial model
            await self._step3_build_initial_model()

            # Iterative refinement (steps 4-8)
            converged = False
            iteration = 0

            while not converged and iteration < max_iterations:
                iteration += 1
                self.logger.log_section(f"ITERATION {iteration}")

                # Step 4: Run Alloy Analyzer
                evaluation = await self._step4_run_analyzer()

                # Check if converged
                if evaluation['complete']:
                    # Step 5-6: Even if complete, ask user for confirmation
                    user_satisfied = await self._step5_6_evaluation_and_user_feedback(evaluation)

                    if user_satisfied:
                        converged = True
                        self.logger.log_section("WORKFLOW COMPLETED SUCCESSFULLY!")
                        self._print_summary()
                        break

                else:
                    # Step 5-6: Get evaluation feedback and user input
                    await self._step5_6_evaluation_and_user_feedback(evaluation)

                # Step 7: Update requirements
                await self._step7_update_requirements(evaluation)

                # Step 8: Update Alloy model
                await self._step8_update_model(evaluation)

            if not converged:
                self.logger.log_separator()
                self.logger.log(f"Maximum iterations ({max_iterations}) reached.")
                self.logger.log("Workflow incomplete. Review results and continue if needed.")
                self.logger.log_separator()
                self._print_summary()

        finally:
            # Close logger
            self.logger.close()

    async def _step1_analyze_requirements(self, input_file: str):
        """Step 1: Analyze initial requirements."""
        self.logger.log("\nStep 1: Analyzing initial requirements...")
        self.requirements = await self.re_agent.analyze_initial_requirements(input_file)
        self.cli.show_file_update(f"ReqsDoc/Reqs_{self.current_iteration}.txt", "Requirements document created")

    async def _step2_user_clarification(self):
        """Step 2: Request user clarification."""
        self.logger.log("\nStep 2: Requesting user clarification...")

        # Create prompt
        reqs_file = f"ReqsDoc/Reqs_{self.current_iteration}.txt"
        full_prompt, concise_prompt = self.cli.create_clarification_request(
            iteration=self.current_iteration,
            requirements_file=reqs_file
        )

        # Request clarification via CLI
        clarification = self.cli.request_input(
            prompt=full_prompt,
            concise_prompt=concise_prompt,
            multiline=True
        )

        if clarification:
            self.logger.log("User clarification received!")
            # Store clarification for RE agent
            self.re_agent.memory_manager.set_current_iteration_data(
                "user_clarification",
                clarification
            )
        else:
            self.logger.log_separator()
            self.logger.log("No user clarification provided (timeout)")
            self.logger.log("Proceeding with current understanding of requirements")
            self.logger.log_separator()
            # Store empty clarification
            self.re_agent.memory_manager.set_current_iteration_data(
                "user_clarification",
                "No clarification provided - proceeding with current requirements"
            )

    async def _step3_build_initial_model(self):
        """Step 3: Build initial Alloy model."""
        self.logger.log("\nStep 3: Building initial Alloy model...")

        self.alloy_model = await self.re_agent.create_alloy_model(
            requirements=self.requirements
        )
        self.cli.show_file_update(f"AlloyModels/AlloyModel__{self.current_iteration}.als", "Alloy model created")

    async def _step4_run_analyzer(self) -> dict:
        """Step 4: Run Alloy Analyzer."""
        self.logger.log("\nStep 4: Running Alloy Analyzer...")

        evaluation = await self.evaluator.evaluate_model(
            iteration=self.current_iteration,
            requirements=self.requirements,
            alloy_model=self.alloy_model
        )

        if not evaluation['success']:
            self.logger.log_error(f"Alloy Analyzer: {evaluation.get('error', 'Unknown')}")
            return evaluation

        # Log summary
        analysis = evaluation['execution_result']['analysis']
        self.logger.log("\nAnalysis Results:")
        self.logger.log(f"  Syntax Errors: {'YES' if analysis['has_syntax_errors'] else 'NO'}")
        self.logger.log(f"  Counterexamples: {'YES' if analysis['has_counterexamples'] else 'NO'}")
        self.logger.log(f"  Satisfying Instances: {'YES' if analysis['has_satisfying_instances'] else 'NO'}")
        self.logger.log(f"  Complete: {'YES' if evaluation['complete'] else 'NO'}")
        self.cli.show_file_update(f"AnalyzerOutput/{self.current_iteration}/", "Analysis results saved to")

        return evaluation

    async def _step5_6_evaluation_and_user_feedback(self, evaluation: dict) -> bool:
        """
        Steps 5-6: Generate evaluation feedback and get user input.

        Returns:
            True if user is satisfied, False otherwise
        """
        self.logger.log("\nSteps 5-6: Evaluation and user feedback...")

        # Create current state summary
        current_state = self._get_current_state_summary(evaluation)
        analysis = evaluation['execution_result']['analysis']

        # Create prompt for user
        full_prompt, concise_prompt = self.cli.create_evaluation_request(
            iteration=self.current_iteration,
            current_state=current_state,
            has_errors=analysis['has_syntax_errors'],
            has_counterexamples=analysis['has_counterexamples'],
            has_instances=analysis['has_satisfying_instances']
        )

        # Get user feedback via CLI
        user_feedback = self.cli.request_input(
            prompt=full_prompt,
            concise_prompt=concise_prompt,
            multiline=True
        )

        if not user_feedback:
            self.logger.log_separator()
            self.logger.log("No user feedback provided (timeout)")
            self.logger.log("Proceeding to next iteration with agent-suggested improvements only")
            self.logger.log_separator()
            # Store that no feedback was provided
            self.evaluator.memory_manager.set_current_iteration_data(
                "user_feedback",
                "No feedback provided - using agent suggestions only"
            )
            return False

        # Check if user is satisfied
        if "SATISFIED" in user_feedback.upper():
            self.logger.log_separator()
            self.logger.log("User is satisfied with results!")
            self.logger.log_separator()
            return True

        # Store user feedback
        self.evaluator.memory_manager.set_current_iteration_data(
            "user_feedback",
            user_feedback
        )

        return False

    async def _step7_update_requirements(self, evaluation: dict):
        """Step 7: Update requirements based on feedback."""
        self.logger.log("\nStep 7: Updating requirements...")

        feedback = evaluation.get('feedback', {})
        user_feedback = self.evaluator.memory_manager.get_current_iteration_data(
            "user_feedback"
        )

        suggested_updates = feedback.get('requirement_updates', '')

        if suggested_updates or user_feedback:
            self.requirements = await self.evaluator.update_requirements_with_feedback(
                current_requirements=self.requirements,
                suggested_updates=suggested_updates,
                user_feedback=user_feedback
            )
            new_iter = self.evaluator.memory_manager.get_iteration()
            self.cli.show_file_update(f"ReqsDoc/Reqs_{new_iter}.txt", "Requirements updated")
        else:
            self.logger.log("No requirement updates needed")

    async def _step8_update_model(self, evaluation: dict):
        """Step 8: Update Alloy model based on feedback."""
        self.logger.log("\nStep 8: Updating Alloy model...")

        feedback = evaluation.get('feedback', {})
        alloy_feedback = feedback.get('alloy_improvements', '')

        if alloy_feedback:
            self.alloy_model = await self.re_agent.update_model(
                feedback=alloy_feedback,
                requirements=self.requirements
            )

            # Update current iteration
            self.current_iteration = self.re_agent.memory_manager.get_iteration()

            self.cli.show_file_update(f"AlloyModels/AlloyModel__{self.current_iteration}.als", "Alloy model updated")

            # Learn from the update
            if evaluation['execution_result']['analysis'].get('has_syntax_errors'):
                self.re_agent.add_lesson(
                    "Fixed syntax errors in model",
                    category="modeling"
                )
        else:
            self.logger.log("No model updates needed")

    def _get_current_state_summary(self, evaluation: dict) -> str:
        """Get summary of current state."""
        analysis = evaluation['execution_result']['analysis']
        parts = [
            f"Iteration: {self.current_iteration}",
            f"Syntax Errors: {'YES' if analysis['has_syntax_errors'] else 'NO'}",
            f"Counterexamples: {'YES' if analysis['has_counterexamples'] else 'NO'}",
            f"Satisfying Instances: {'YES' if analysis['has_satisfying_instances'] else 'NO'}",
        ]
        return "\n".join(parts)

    def _print_summary(self):
        """Print final summary."""
        self.logger.log_section("FINAL SUMMARY")

        self.logger.log(f"\nFinal Iteration: {self.current_iteration}")

        self.logger.log(f"\nRequirement Engineer Memory:")
        self.logger.log(self.re_agent.get_memory_summary())

        self.logger.log(f"\nEvaluator Memory:")
        self.logger.log(self.evaluator.get_memory_summary())

        self.logger.log(f"\nEvaluation History:")
        self.logger.log(self.evaluator.get_evaluation_summary())

        self.logger.log(f"\nOutput Files:")
        self.logger.log(f"  Requirements: ReqsDoc/Reqs_*.txt")
        self.logger.log(f"  Alloy Models: AlloyModels/AlloyModel__*.als")
        self.logger.log(f"  Analyzer Output: AnalyzerOutput/*/")
        self.logger.log(f"  Session Log: {self.logger.log_file}")

        self.logger.log_separator()


async def main(input_file: str, max_iterations: int = 10):
    """
    Main entry point for the workflow.

    Args:
        input_file: Path to initial requirements file
        max_iterations: Maximum number of iterations
    """
    workflow = AutoREWorkflow()
    await workflow.run(input_file, max_iterations)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.workflow <input_file> [max_iterations]")
        sys.exit(1)

    input_file = sys.argv[1]
    max_iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    asyncio.run(main(input_file, max_iterations))