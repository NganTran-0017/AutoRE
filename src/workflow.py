"""
AutoRE Workflow (V2) - Using SharedRuntimeContext.

Simplified workflow that directly calls actions instead of message passing.
"""
import asyncio
from pathlib import Path
from typing import Optional

from .utils.runtime_context import SharedRuntimeContext
from .utils.config_loader import ConfigLoader
from .utils.logger import AutoRELogger
from .utils.cli_interaction import CLIInteraction

from .actions.requirement_actions import (
    AnalyzeRequirements,
    IncorporateClarifications,
    BuildAlloyModel,
    UpdateAlloyModel
)
from .actions.evaluation_actions import (
    RunAlloyAnalyzer,
    InterpretResults,
    GenerateFeedback,
    UpdateRequirements,
    RefineFeedback
)


class AutoREWorkflow:
    """
    Orchestrates the multi-agent requirement engineering workflow.

    Uses SharedRuntimeContext for state management and direct action calls
    for simplicity.
    """

    def __init__(
        self,
        input_file: str,
        base_dir: str = ".",
        max_iterations: int = 10,
        timeout: int = 300,
        project_name: str = "default"
    ):
        """
        Initialize workflow.

        Args:
            input_file: Path to input requirements file
            base_dir: Base directory for the project
            max_iterations: Maximum refinement iterations
            timeout: CLI timeout in seconds
            project_name: Project name for memory isolation
        """
        self.base_dir = Path(base_dir)
        self.input_file = input_file
        self.max_iterations = max_iterations
        self.timeout = timeout

        # Load configuration
        config_path = self.base_dir / "config.yaml"
        try:
            self.config_loader = ConfigLoader(str(config_path))
            llm_config = self.config_loader.get_llm_config()
            self._setup_llm(llm_config)
        except FileNotFoundError as e:
            print(f"Error: {e}")
            raise
        except ValueError as e:
            print(f"Error: {e}")
            raise

        # Setup logging
        self._setup_logging()

        # Initialize utilities
        self.logger = AutoRELogger()
        self.cli = CLIInteraction(self.logger, timeout=timeout)

        # Create SharedRuntimeContext with logger
        self.context = SharedRuntimeContext(project_name=project_name, logger=self.logger)

        # Create actions (no agents needed - direct action calls)
        self.analyze_requirements = AnalyzeRequirements(self.context, agent_name="RE")
        self.incorporate_clarifications = IncorporateClarifications(self.context, agent_name="RE")
        self.build_model = BuildAlloyModel(self.context, agent_name="RE")
        self.update_model = UpdateAlloyModel(self.context, agent_name="RE")

        self.run_analyzer = RunAlloyAnalyzer(self.context, agent_name="Evaluator")
        self.interpret_results = InterpretResults(self.context, agent_name="Evaluator")
        self.generate_feedback = GenerateFeedback(self.context, agent_name="Evaluator")
        self.update_requirements = UpdateRequirements(self.context, agent_name="Evaluator")
        self.refine_feedback = RefineFeedback(self.context, agent_name="Evaluator")

        # Configure LLM for all actions
        self._configure_action_llms()

        print("✓ AutoRE Workflow initialized (V2)")
        print(f"  - Project: {project_name}")
        print(f"  - Max iterations: {max_iterations}")
        print(f"  - Input: {input_file}")

    def _setup_llm(self, llm_config: dict):
        """Configure LLM settings."""
        import os
        os.environ['OPENAI_API_KEY'] = llm_config['api_key']
        os.environ['OPENAI_API_MODEL'] = llm_config['model']

        if llm_config.get('api_base'):
            os.environ['OPENAI_API_BASE'] = llm_config['api_base']

        from metagpt.config2 import Config
        self.metagpt_config = Config.default()
        self.metagpt_config.llm.api_key = llm_config['api_key']
        self.metagpt_config.llm.model = llm_config['model']
        self.metagpt_config.llm.temperature = llm_config.get('temperature', 0.7)
        self.metagpt_config.llm.max_token = llm_config.get('max_tokens', 16000)

    def _configure_action_llms(self):
        """Configure LLM for all actions."""
        from metagpt.provider.openai_api import OpenAILLM

        # Create LLM instance for actions
        llm = OpenAILLM(self.metagpt_config.llm)

        # Set LLM for all actions
        actions = [
            self.analyze_requirements,
            self.incorporate_clarifications,
            self.build_model,
            self.update_model,
            self.run_analyzer,
            self.interpret_results,
            self.generate_feedback,
            self.update_requirements,
            self.refine_feedback
        ]

        for action in actions:
            action.set_llm(llm)

    def _setup_logging(self):
        """Configure MetaGPT logging."""
        import logging
        from pathlib import Path

        # Create log directory
        log_dir = Path("Output/outputlog")
        log_dir.mkdir(parents=True, exist_ok=True)
        metagpt_log_file = log_dir / "metagpt.log"

        # Configure MetaGPT logger
        metagpt_logger = logging.getLogger("metagpt")
        metagpt_logger.setLevel(logging.DEBUG)

        # Clear existing handlers
        metagpt_logger.handlers.clear()

        # Add file handler
        file_handler = logging.FileHandler(metagpt_log_file, mode='a')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        metagpt_logger.addHandler(file_handler)

        # Also log to console for errors
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        metagpt_logger.addHandler(console_handler)

    async def run(self, resume_mode: bool = False, resume_iteration: Optional[int] = None):
        """Run the complete workflow.
        
        Args:
            resume_mode: If True, resume from existing model/requirements
            resume_iteration: Specific iteration to resume from (None = latest)
        """
        try:
            self.logger.log("\n" + "=" * 80)
            self.logger.log("AutoRE - Automated Requirements Engineering")
            self.logger.log("=" * 80)
            self.logger.log("")

            if resume_mode:
                # Resume from existing files
                await self._resume_from_analyzer(resume_iteration)
                # In resume mode, max_iterations is additional iterations from current
                # e.g., resume at 7 with max_iterations=10 means run 7 to 17 (inclusive)
                effective_max = self.context.iteration.current + self.max_iterations + 1
            else:
                # Read input requirements
                raw_requirements = self._read_input()

                # Step 1: Analyze initial requirements
                await self._step1_analyze_requirements(raw_requirements)

                # Step 2: User clarification
                await self._step2_user_clarification()

                # Step 3: Build initial model
                await self._step3_build_initial_model()
                
                # In normal mode, max_iterations is the total iteration limit
                effective_max = self.max_iterations + 1

            # Iterative refinement loop
            for iteration in range(self.context.iteration.current, effective_max):
                self.logger.log(f"\n{'=' * 80}")
                self.logger.log(f"Iteration {iteration}/{effective_max}")
                self.logger.log(f"{'=' * 80}\n")

                # Step 4: Evaluate model (evaluates model from current iteration)
                evaluation_result = await self._step4_evaluate_model()

                # Check if model file was found
                if evaluation_result is None:
                    self.logger.log("\n❌ Workflow terminated: Model file not found")
                    break

                # Check if verification is complete
                if evaluation_result:
                    self.logger.log("\n✅ Verification complete! All criteria met.")
                    break

                # Step 5-6: Generate feedback and get user input
                await self._step5_6_generate_feedback_and_get_user_input()

                # Increment iteration counter before updating requirements and model
                self.context.next_iteration()

                # Step 7: Update requirements (saves with new iteration number)
                await self._step7_update_requirements()

                # Step 8: Update model (saves with new iteration number)
                await self._step8_update_model()

            # Save final state
            self.context.save_state()

            self.logger.log("\n" + "=" * 80)
            self.logger.log("Workflow Complete")
            self.logger.log("=" * 80)
            self._print_summary()

        except Exception as e:
            self.logger.log(f"\n❌ Workflow failed with error: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _read_input(self) -> str:
        """Read input requirements file."""
        print("📋 Reading input requirements...")
        try:
            with open(self.input_file, 'r') as f:
                content = f.read()
            print(f"✓ Read {len(content)} characters from {self.input_file}")
            return content
        except FileNotFoundError:
            print(f"❌ Input file not found: {self.input_file}")
            raise

    async def _resume_from_analyzer(self, resume_iteration: Optional[int] = None):
        """Resume workflow from existing model and requirements.
        
        Args:
            resume_iteration: Specific iteration to resume from (None = latest)
        """
        print("\n🔄 Resuming workflow from existing files...")
        
        # Get available versions
        req_versions = self.context.file_manager.get_all_requirement_versions()
        model_versions = self.context.file_manager.get_all_model_versions()
        
        if not req_versions:
            raise ValueError("No requirement versions found. Cannot resume.")
        if not model_versions:
            raise ValueError("No model versions found. Cannot resume.")
        
        # Determine which iteration to resume from
        if resume_iteration is not None:
            target_iteration = resume_iteration
            print(f"  Target iteration: {target_iteration} (user-specified)")
        else:
            # Find the latest common iteration between requirements and models
            common_iterations = sorted(set(req_versions) & set(model_versions), reverse=True)
            if not common_iterations:
                raise ValueError(
                    f"No matching iteration found.\n"
                    f"  Requirements available: {req_versions}\n"
                    f"  Models available: {model_versions}"
                )
            target_iteration = common_iterations[0]
            print(f"  Target iteration: {target_iteration} (latest available)")
        
        # Validate target iteration exists
        if target_iteration not in req_versions:
            raise ValueError(
                f"Requirements for iteration {target_iteration} not found.\n"
                f"  Available: {req_versions}"
            )
        if target_iteration not in model_versions:
            raise ValueError(
                f"Model for iteration {target_iteration} not found.\n"
                f"  Available: {model_versions}"
            )
        
        # Load requirements
        requirements = self.context.file_manager.load_requirements(target_iteration)
        if not requirements:
            raise ValueError(f"Failed to load requirements for iteration {target_iteration}")
        print(f"✓ Loaded requirements from iteration {target_iteration}")
        
        # Load model
        model = self.context.file_manager.load_alloy_model(target_iteration)
        if not model:
            raise ValueError(f"Failed to load model for iteration {target_iteration}")
        print(f"✓ Loaded Alloy model from iteration {target_iteration}")
        
        # Store in artifacts (as current iteration artifacts)
        self.context.artifacts.store_requirements(target_iteration, requirements)
        self.context.artifacts.store_alloy_model(target_iteration, model)
        
        # Set iteration to continue from target_iteration + 1
        # This way, the next iteration will be target_iteration + 1
        self.context.iteration.set(target_iteration)
        print(f"✓ Iteration counter set to {target_iteration}")
        print(f"  → Next iteration will be {target_iteration + 1}")
        
        # Try to load existing feedback (optional - may not exist)
        try:
            feedback = self.context.file_manager.load_feedback(target_iteration)
            if feedback:
                self.context.artifacts.store_feedback(target_iteration, feedback)
                print(f"✓ Loaded existing feedback from iteration {target_iteration}")
        except:
            print(f"  (No feedback found for iteration {target_iteration} - will generate fresh)")
        
        print(f"\n✓ Resume complete - starting from Step 4 (Evaluate Model) at iteration {target_iteration}")

    async def _step1_analyze_requirements(self, raw_requirements: str):
        """Step 1: Analyze initial requirements."""
        print("\n📋 Step 1: Analyzing initial requirements...")

        requirements_doc = await self.analyze_requirements.run(raw_requirements)

        print("✓ Requirements analyzed")
        print(f"  Output: {len(requirements_doc)} characters")

        # Save to file
        reqs_file = self.context.file_manager.save_requirements(
            requirements_doc,
            iteration=self.context.iteration.current
        )
        print(f"  Saved to: {reqs_file}")

    async def _step2_user_clarification(self):
        """Step 2: Get user clarifications."""
        print("\n💬 Step 2: User clarification...")

        requirements = self.context.artifacts.get_latest_requirements()

        if not requirements:
            print("⚠ No requirements found")
            return

        # Check if there are questions in the requirements
        if "ASSUMPTIONS REQUIRING CLARIFICATION" in requirements:
            print("\n" + "-" * 80)
            print(requirements)
            print("-" * 80 + "\n")

            print("Please provide clarifications (or press Enter to skip):")
            user_input = self.cli.request_input(
                prompt="Please provide clarifications on the requirements:",
                multiline=True
            )

            if user_input and user_input.strip():
                # Incorporate clarifications into requirements document
                print("  Updating requirements with clarifications...")
                updated_requirements = await self.incorporate_clarifications.run(
                    requirements_document=requirements,
                    user_clarifications=user_input
                )

                # Save updated requirements to file
                reqs_file = self.context.file_manager.save_requirements(
                    updated_requirements,
                    iteration=self.context.iteration.current
                )
                print(f"✓ Requirements updated with clarifications")
                print(f"  Saved to: {reqs_file}")

                # Also record as user preference for additional context
                self.context.user_preferences.add_preference(
                    preference=f"User clarification: {user_input}",
                    iteration=self.context.iteration.current,
                    context="Step 2 clarification"
                )
            else:
                print("✓ No clarifications provided")
        else:
            print("✓ No clarifications needed")

    async def _step3_build_initial_model(self):
        """Step 3: Build initial Alloy model."""
        print("\n🔨 Step 3: Building initial Alloy model...")

        # Get latest requirements (includes any clarifications from Step 2)
        requirements = self.context.artifacts.get_latest_requirements()
        user_prefs = self.context.user_preferences.format_for_prompt()

        # Build model from updated requirements
        alloy_model = await self.build_model.run(
            requirements_document=requirements,
            user_feedback=user_prefs if user_prefs else ""
        )

        print("✓ Alloy model created")
        print(f"  Output: {len(alloy_model)} characters")

        # Save to file
        model_file = self.context.file_manager.save_alloy_model(
            alloy_model,
            iteration=self.context.iteration.current
        )
        print(f"  Saved to: {model_file}")

    async def _step4_evaluate_model(self) -> Optional[bool]:
        """
        Step 4: Evaluate Alloy model.

        Returns:
            True if evaluation is complete (convergence)
            False if evaluation done but not converged
            None if model not found (error case)
        """
        print("\n🔍 Step 4: Evaluating Alloy model...")

        # Get model file path for current iteration
        model_file = self.context.file_manager.get_alloy_model_path(
            self.context.iteration.current
        )

        if not model_file.exists():
            print("❌ ERROR: No Alloy model found to evaluate")
            print(f"   Expected file: {model_file}")
            print("   Workflow cannot continue without a model.")
            return None

        # Run Alloy Analyzer
        print("  Running Alloy Analyzer...")
        results = await self.run_analyzer.run(model_file)

        # Interpret results
        print("  Interpreting results...")
        requirements = self.context.artifacts.get_latest_requirements()
        alloy_model = self.context.artifacts.get_latest_alloy_model()

        interpretation = await self.interpret_results.run(
            analyzer_results=results,
            requirements_document=requirements,
            alloy_model=alloy_model
        )

        print("✓ Evaluation complete")

        # Check convergence - analysis results are nested under 'analysis' key
        analysis = results.get('analysis', {})
        no_syntax_errors = not analysis.get('has_syntax_errors', False)
        no_counterexamples = not analysis.get('has_counterexamples', False)
        has_instances = analysis.get('has_satisfying_instances', False)

        print(f"  Syntax: {'✓ OK' if no_syntax_errors else '✗ Errors'}")
        print(f"  Counterexamples: {'✓ None' if no_counterexamples else '✗ Found'}")
        print(f"  Instances: {'✓ Found' if has_instances else '✗ None'}")

        # Show syntax error details if present
        if not no_syntax_errors:
            syntax_errors = analysis.get('syntax_errors', [])
            print(f"  ⚠ Found {len(syntax_errors)} syntax error(s)")
            for err in syntax_errors[:3]:  # Show first 3
                if isinstance(err, dict):
                    print(f"    - Line {err.get('line', '?')}: {err.get('message', 'Unknown error')}")
                else:
                    print(f"    - {err}")

        # Convergence requires user satisfaction too
        return no_syntax_errors and no_counterexamples and has_instances

    async def _step5_6_generate_feedback_and_get_user_input(self):
        """Steps 5-6: Generate feedback and get user review."""
        print("\n📝 Step 5-6: Generating feedback...")

        interpretation = self.context.artifacts.get_latest_evaluation()
        requirements = self.context.artifacts.get_latest_requirements()
        alloy_model = self.context.artifacts.get_latest_alloy_model()

        # Generate draft feedback
        draft_feedback = await self.generate_feedback.run(
            interpretation=interpretation,
            requirements_document=requirements,
            alloy_model=alloy_model
        )

        print("✓ Draft feedback generated")

        # Show to user
        print("\n" + "-" * 80)
        print(draft_feedback[:1000])  # Show first 1000 chars
        if len(draft_feedback) > 1000:
            print(f"\n... ({len(draft_feedback) - 1000} more characters)")
        print("-" * 80 + "\n")

        # Get user review
        print("Review the feedback above. Provide comments or press Enter to continue:")
        user_review = self.cli.request_input(
            prompt="Provide your review or comments on the feedback:",
            multiline=True
        )

        # Check if user provided meaningful feedback
        if user_review and user_review.strip():
            # Refine feedback based on user review
            print("  Refining feedback based on your input...")
            final_feedback = await self.refine_feedback.run(
                draft_feedback=draft_feedback,
                user_review=user_review
            )

            # Update artifacts
            self.context.artifacts.store_feedback(
                self.context.iteration.current,
                final_feedback
            )

            # Save feedback to disk
            self.context.file_manager.save_feedback(
                {"feedback": final_feedback},
                iteration=self.context.iteration.current
            )

            # Record user preference
            self.context.user_preferences.add_preference(
                preference=f"User review feedback: {user_review}",
                iteration=self.context.iteration.current,
                context="Feedback refinement"
            )

            print("✓ Feedback refined based on user input")
        else:
            # No user feedback - skip RefineFeedback action and use draft as final
            if user_review is None:
                print("✓ No user feedback provided (timeout) - using draft feedback")
            else:
                print("✓ No user feedback provided - using draft feedback")

            # Store draft as final feedback
            self.context.artifacts.store_feedback(
                self.context.iteration.current,
                draft_feedback
            )

            # Save feedback to disk
            self.context.file_manager.save_feedback(
                {"feedback": draft_feedback},
                iteration=self.context.iteration.current
            )

    def _extract_requirement_updates(self, feedback: str) -> Optional[str]:
        """
        Extract only the REQUIREMENT_UPDATES section from feedback.

        Args:
            feedback: Full feedback with all sections

        Returns:
            Only the REQUIREMENT_UPDATES section content, or None if empty/not found
        """
        import re

        # Pattern to extract REQUIREMENT_UPDATES section
        # Match from === REQUIREMENT_UPDATES === to the next === at start of line or end of string
        pattern = r'===\s*REQUIREMENT_UPDATES\s*===\s*\n(.*?)(?=^===|\Z)'
        match = re.search(pattern, feedback, re.DOTALL | re.MULTILINE)

        if match:
            content = match.group(1).strip()
            # Check if content is meaningful (not just empty, placeholder, or "None")
            if content and content.lower() not in ['none', 'n/a', 'not applicable', '[ambiguities/inconsistencies/missing items]']:
                return content

        return None

    async def _step7_update_requirements(self):
        """Step 7: Update requirements based on feedback."""
        print("\n📝 Step 7: Updating requirements...")

        full_feedback = self.context.artifacts.get_latest_feedback()
        requirements = self.context.artifacts.get_latest_requirements()

        # Extract only REQUIREMENT_UPDATES section from feedback
        requirements_feedback = self._extract_requirement_updates(full_feedback)

        # Skip if no requirement updates found - but still create a copy for this iteration
        if requirements_feedback is None:
            print("✓ No requirement updates needed - copying current requirements to this iteration")

            # Save unchanged requirements to file for current iteration
            reqs_file = self.context.file_manager.save_requirements(
                requirements,
                iteration=self.context.iteration.current
            )
            print(f"  Saved to: {reqs_file}")
            return

        user_prefs = self.context.user_preferences.format_for_prompt()

        updated_requirements = await self.update_requirements.run(
            requirements_document=requirements,
            feedback=requirements_feedback,
            user_feedback=user_prefs
        )

        print("✓ Requirements updated")

        # Save to file
        reqs_file = self.context.file_manager.save_requirements(
            updated_requirements,
            iteration=self.context.iteration.current
        )
        print(f"  Saved to: {reqs_file}")

    async def _step8_update_model(self):
        """Step 8: Update Alloy model based on feedback."""
        print("\n🔨 Step 8: Updating Alloy model...")

        current_model = self.context.artifacts.get_latest_alloy_model()
        feedback = self.context.artifacts.get_latest_feedback()
        requirements = self.context.artifacts.get_latest_requirements()

        updated_model = await self.update_model.run(
            current_model=current_model,
            evaluation_feedback=feedback,
            requirements_document=requirements
        )

        print("✓ Alloy model updated")

        # Save to file
        model_file = self.context.file_manager.save_alloy_model(
            updated_model,
            iteration=self.context.iteration.current
        )
        print(f"  Saved to: {model_file}")

    def _print_summary(self):
        """Print workflow summary to console and log file."""
        stats = self.context.memory.get_stats()

        self.logger.log("\nWorkflow Summary:")
        self.logger.log(f"  Iterations completed: {self.context.iteration.current}")
        self.logger.log(f"  Requirements versions: {len(self.context.artifacts.requirements)}")
        self.logger.log(f"  Alloy model versions: {len(self.context.artifacts.alloy_models)}")
        self.logger.log(f"  Lessons learned: {stats['by_type'].get('lesson', 0)}")
        self.logger.log(f"  Patterns identified: {stats['by_type'].get('pattern', 0)}")
        self.logger.log(f"  Events recorded: {stats['by_type'].get('event', 0)}")
        self.logger.log(f"  User preferences: {len(self.context.user_preferences.preferences)}")
