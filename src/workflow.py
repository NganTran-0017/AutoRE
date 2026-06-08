"""
AutoRE Workflow (V2) - Using SharedRuntimeContext.

Simplified workflow that directly calls actions instead of message passing.
"""
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

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
    GenerateSemanticFeedback,
    GenerateSyntaxRepairInstruction,
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

        # Create SharedRuntimeContext with logger and config
        self.context = SharedRuntimeContext(
            project_name=project_name,
            logger=self.logger,
            config=self.config_loader.config
        )

        # Create actions (no agents needed - direct action calls)
        self.analyze_requirements = AnalyzeRequirements(self.context, agent_name="RE")
        self.incorporate_clarifications = IncorporateClarifications(self.context, agent_name="RE")
        self.build_model = BuildAlloyModel(self.context, agent_name="RE")
        self.update_model = UpdateAlloyModel(self.context, agent_name="RE")

        self.run_analyzer = RunAlloyAnalyzer(self.context, agent_name="Evaluator")
        self.interpret_results = InterpretResults(self.context, agent_name="Evaluator")
        self.generate_semantic_feedback = GenerateSemanticFeedback(self.context, agent_name="Evaluator")
        self.generate_syntax_repair = GenerateSyntaxRepairInstruction(self.context, agent_name="Evaluator")
        self.update_requirements = UpdateRequirements(self.context, agent_name="Evaluator")
        self.refine_feedback = RefineFeedback(self.context, agent_name="Evaluator")

        # Configure LLM for all actions
        self._configure_action_llms()

        print("✓ AutoRE Workflow initialized (V2)")
        print(f"  - Project: {project_name}")
        print(f"  - Max iterations: {max_iterations}")
        print(f"  - Input: {input_file}")

    def _debug(self, message: str):
        """Log debug message to both console and log file."""
        self.logger.log(message)

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
            self.generate_semantic_feedback,
            self.generate_syntax_repair,
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
                
                # Repair regression log entries from previous runs with buggy code
                await self._repair_regression_log_issues()
                
                # In resume mode, max_iterations is additional iterations from current
                # e.g., resume at 7 with max_iterations=10 means run 7 to 17 (inclusive)
                effective_max = self.context.iteration.current + self.max_iterations + 1
            else:
                # Clear regression log for fresh start from iteration 0
                self.context.regression_log.clear()

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

                # Step 4: Evaluate model - check HARD METRICS
                hard_metrics_pass = await self._step4_evaluate_model()

                # Check if model file was found
                if hard_metrics_pass is None:
                    self.logger.log("\n❌ Workflow terminated: Model file not found")
                    break

                # Step 5-6: Generate feedback and get user input (includes agent assessment)
                feedback_result = await self._step5_6_generate_feedback_and_get_user_input()

                # HYBRID CONVERGENCE DECISION: Hard Metrics AND Agent Assessment
                if hard_metrics_pass and feedback_result["final_convergence"]:
                    self.logger.log("\n✅ Verification complete! All criteria met.")
                    self.logger.log("  Hard Metrics: ✓ Passed")
                    self.logger.log("  Agent Assessment: ✓ Converged")
                    break

                # Convergence not met - continue refinement
                if not hard_metrics_pass:
                    self.logger.log("\n⚠ Hard metrics not satisfied - continuing refinement")
                elif not feedback_result["final_convergence"]:
                    self.logger.log("\n⚠ Agent assessment: further refinement needed")

                # Increment iteration counter before updating requirements and model
                self.context.next_iteration()

                # Step 7: Update requirements (saves with new iteration number)
                await self._step7_update_requirements()

                # Step 8: Update model (saves with new iteration number)
                await self._step8_update_model()

            # Save final state
            self.context.save_state()

            # Save copy of regression log to Output/RegressionLog/
            self.context.regression_log.save_copy_to_output()

            self.logger.log("\n" + "=" * 80)
            self.logger.log("Workflow Complete")
            self.logger.log("=" * 80)
            self._print_summary()

        except Exception as e:
            # Save copy of regression log even on failure
            self.context.regression_log.save_copy_to_output()
            
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
            # Find the latest model (since models are created every iteration)
            if not model_versions:
                raise ValueError("No model versions found. Cannot resume.")
            target_iteration = model_versions[-1]  # Latest model
            print(f"  Target iteration: {target_iteration} (latest available)")
        
        # Validate target model iteration exists
        if target_iteration not in model_versions:
            raise ValueError(
                f"Model for iteration {target_iteration} not found.\n"
                f"  Available: {model_versions}"
            )
        
        # Find latest requirements file up to target iteration
        # (requirements are only created when updated, not every iteration)
        req_iteration = self.context.file_manager.get_latest_requirements_up_to(target_iteration)
        if req_iteration is None:
            raise ValueError(
                f"No requirements found up to iteration {target_iteration}.\n"
                f"  Available requirements: {req_versions}"
            )
        
        # Load requirements (from the latest available up to target iteration)
        requirements = self.context.file_manager.load_requirements(req_iteration)
        if not requirements:
            raise ValueError(f"Failed to load requirements for iteration {req_iteration}")
        if req_iteration != target_iteration:
            print(f"✓ Loaded requirements from iteration {req_iteration} (latest available for iteration {target_iteration})")
        else:
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

        # Keep regression log as-is when resuming (don't trim)
        # The historical log is preserved for context
        print(f"✓ Regression log preserved with {len(self.context.regression_log.entries)} entries")

        # Try to load existing feedback (optional - may not exist)
        try:
            feedback = self.context.file_manager.load_feedback(target_iteration)
            if feedback:
                self.context.artifacts.store_feedback(target_iteration, feedback)
                print(f"✓ Loaded existing feedback from iteration {target_iteration}")
        except:
            print(f"  (No feedback found for iteration {target_iteration} - will generate fresh)")
        
        print(f"\n✓ Resume complete - starting from Step 4 (Evaluate Model) at iteration {target_iteration}")

    async def _repair_regression_log_issues(self):
        """
        Repair issue fields in regression log entries by re-analyzing old model files.
        
        This is needed when resuming from a previous run where entries were created with buggy code
        that didn't properly extract issues. We re-run the analyzer on old models to get correct issues.
        """
        from .utils.regression_log import extract_issue_description, check_issue_resolved
        
        print("\n🔧 Repairing regression log entries by re-analyzing models...")
        repaired_count = 0
        
        for entry in self.context.regression_log.entries:
            # Skip if issue is already properly extracted (not "No issues")
            if entry.issue and entry.issue != "No issues":
                continue
            
            # Get the model file for this iteration
            model_file = self.context.file_manager.get_alloy_model_path(entry.iteration_id)
            if not model_file.exists():
                print(f"  ⚠ Iteration {entry.iteration_id}: Model file not found, skipping")
                continue
            
            # Re-run analyzer on this model
            try:
                results = await self.run_analyzer.run(model_file)
                analysis = results.get('analysis', {})
                
                # Re-extract issue
                new_issue = extract_issue_description(analysis)
                
                if new_issue != entry.issue:
                    print(f"  Iteration {entry.iteration_id}: '{entry.issue}' → '{new_issue}'")
                    entry.issue = new_issue
                    repaired_count += 1
                    
                    # Also re-check resolved_target_issue for this entry
                    if entry.iteration_id > 0:
                        prev_entry = self.context.regression_log.get_entry(entry.iteration_id - 1)
                        if prev_entry:
                            # Get previous results by re-analyzing previous model
                            prev_model_file = self.context.file_manager.get_alloy_model_path(entry.iteration_id - 1)
                            if prev_model_file.exists():
                                prev_results = await self.run_analyzer.run(prev_model_file)
                                prev_analysis = prev_results.get('analysis', {})
                                
                                entry.resolved_target_issue = check_issue_resolved(
                                    current_analysis=analysis,
                                    previous_analysis=prev_analysis,
                                    current_entry=entry,
                                    previous_entry=prev_entry
                                )
                
            except Exception as e:
                print(f"  ⚠ Iteration {entry.iteration_id}: Failed to re-analyze - {e}")
                continue
        
        if repaired_count > 0:
            self.context.regression_log._save_to_file()
            print(f"✓ Repaired {repaired_count} regression log entries")
        else:
            print("✓ No repairs needed")

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

        # Update regression log with verification result and calculate actual impact
        current_verification = self._create_verification_snapshot(results)
        entry = self.context.regression_log.get_entry(self.context.iteration.current)
        
        self._debug(f"[DEBUG] Step 4 - Looking for entry at iteration {self.context.iteration.current}")
        self._debug(f"[DEBUG] Entry found: {entry is not None}")
        
        # If no entry exists for current iteration (e.g., iteration 0), create one
        if not entry:
            from .utils.regression_log import RegressionLogEntry, VerificationResult, ImpactAnalysis
            self._debug(f"[DEBUG] Creating entry for iteration {self.context.iteration.current} (first time evaluation)")
            
            model_file = self.context.file_manager.get_alloy_model_path(self.context.iteration.current)
            entry = RegressionLogEntry(
                iteration_id=self.context.iteration.current,
                model_file_location=str(model_file),
                fix_intent="Initial model creation" if self.context.iteration.current == 0 else "Model update",
                source_ref="Initial build" if self.context.iteration.current == 0 else "RE Agent",
                current_result=VerificationResult(syntax="Pending"),
                previous_result=None,
                updated_lines="",
                expected_impact=ImpactAnalysis()
            )
            self.context.regression_log.add_entry(entry)
        
        # Now update the entry with current verification results
        entry.current_result = current_verification

        # Calculate actual impact by comparing with previous results
        prev_entry = self.context.regression_log.get_entry(self.context.iteration.current - 1)
        prev_results = None
        if prev_entry:
            # Get previous analyzer results from artifacts
            prev_results = self.context.artifacts.analyzer_results.get(self.context.iteration.current - 1, {})
            if prev_results:
                actual_impact = self._calculate_actual_impact(results, prev_results)
                entry.actual_impact = actual_impact

        # Extract issue description from current analysis
        from .utils.regression_log import extract_issue_description, check_issue_resolved, detect_fix_pattern
        
        # Get the analysis sub-dict from results
        current_analysis = results.get('analysis', {})
        prev_analysis = prev_results.get('analysis', {}) if prev_results else None
        
        # Debug: Check what's in results
        self._debug(f"[DEBUG] Results structure check:")
        self._debug(f"  has_syntax_errors in analysis: {current_analysis.get('has_syntax_errors', 'NOT FOUND')}")
        self._debug(f"  syntax_errors count: {len(current_analysis.get('syntax_errors', []))}")
        if current_analysis.get('syntax_errors'):
            self._debug(f"  first error line: {current_analysis['syntax_errors'][0].get('line', 'NO LINE')}")
        
        entry.issue = extract_issue_description(current_analysis)
        
        # Extract syntax error context for comparison
        syntax_errors = current_analysis.get('syntax_errors', [])
        if syntax_errors and isinstance(syntax_errors[0], dict):
            entry.syntax_error_context = syntax_errors[0].get('context', None)
        else:
            entry.syntax_error_context = None

        # Debug logging
        self._debug(f"[DEBUG] Step 4 - Iteration: {self.context.iteration.current}")
        self._debug(f"[DEBUG] Entry found/created for iteration {self.context.iteration.current}: True")
        self._debug(f"[DEBUG] Extracted issue: {entry.issue}")

        # Check if target issue from previous iteration is resolved
        entry.resolved_target_issue = check_issue_resolved(
            current_analysis=current_analysis,
            previous_analysis=prev_analysis,
            current_entry=entry,
            previous_entry=prev_entry
        )

        self._debug(f"[DEBUG] Resolved target issue: {entry.resolved_target_issue}")

        # Detect if same fix approach has been tried multiple times for this issue
        if entry.issue and entry.resolved_target_issue is False:
            entry.fix_pattern_detected = detect_fix_pattern(
                current_issue=entry.issue,
                regression_log_entries=self.context.regression_log.entries
            )
            self._debug(f"[DEBUG] Pattern detected: {entry.fix_pattern_detected}")

        self.context.regression_log._save_to_file()
        self._debug(f"[DEBUG] Regression log saved with {len(self.context.regression_log.entries)} entries")

        # Check for syntax errors to decide whether to call InterpretResults
        analysis = results.get('analysis', {})
        has_syntax_errors = analysis.get('has_syntax_errors', False)

        requirements = self.context.artifacts.get_latest_requirements()
        alloy_model = self.context.artifacts.get_latest_alloy_model()

        # Only call InterpretResults if there are NO syntax errors
        interpretation = None
        if has_syntax_errors:
            print("  ⚠️  Syntax errors detected - skipping InterpretResults")
            # Store empty interpretation for consistency
            self.context.artifacts.store_evaluation(
                self.context.iteration.current,
                "(Skipped - syntax errors present)"
            )
        else:
            # Interpret results
            print("  Interpreting results...")
            interpretation = await self.interpret_results.run(
                analyzer_results=results,
                requirements_document=requirements,
                alloy_model=alloy_model
            )

            # Step 4: Parse questions from InterpretResults and store as pending_questions
            from src.utils.qa_parser import parse_user_questions

            questions_from_interpretation = parse_user_questions(
                interpretation,
                section_name="USER QUESTIONS"
            )

            if questions_from_interpretation:
                self.context.artifacts.store_pending_questions(
                    self.context.iteration.current,
                    questions_from_interpretation
                )
                print(f"  📋 {len(questions_from_interpretation)} question(s) identified for user")

        print("✓ Evaluation complete")

        # Check HARD METRICS - analysis results are nested under 'analysis' key
        analysis = results.get('analysis', {})
        no_syntax_errors = not analysis.get('has_syntax_errors', False)
        no_counterexamples = not analysis.get('has_counterexamples', False)

        # NEW: Check all positive runs satisfied (exclude "negative" test cases)
        positive_runs = analysis.get('positive_run_commands', 0)
        satisfied_positive = analysis.get('satisfied_positive_runs', 0)
        all_positive_runs_satisfied = (positive_runs > 0 and positive_runs == satisfied_positive)

        print(f"  Syntax: {'✓ OK' if no_syntax_errors else '✗ Errors'}")
        print(f"  Counterexamples: {'✓ None' if no_counterexamples else '✗ Found'}")
        print(f"  Positive Runs: {satisfied_positive}/{positive_runs} satisfied")

        # Show syntax error details if present
        if not no_syntax_errors:
            syntax_errors = analysis.get('syntax_errors', [])
            print(f"  ⚠ Found {len(syntax_errors)} syntax error(s)")
            for err in syntax_errors[:3]:  # Show first 3
                if isinstance(err, dict):
                    print(f"    - Line {err.get('line', '?')}: {err.get('message', 'Unknown error')}")
                else:
                    print(f"    - {err}")

        # Hard metrics check (agent assessment happens later in workflow)
        hard_metrics_pass = no_syntax_errors and no_counterexamples and all_positive_runs_satisfied

        return hard_metrics_pass

    async def _step5_6_generate_feedback_and_get_user_input(self) -> dict:
        """
        Steps 5-6: Generate feedback and get user review.

        Returns:
            dict with 'user_provided_feedback': bool, 'final_convergence': bool
        """
        import re

        print("\n📝 Step 5-6: Generating feedback...")

        interpretation = self.context.artifacts.get_latest_evaluation()
        requirements = self.context.artifacts.get_latest_requirements()
        alloy_model = self.context.artifacts.get_latest_alloy_model()

        # Check for syntax errors and route accordingly
        analyzer_results = self.context.artifacts.get_analyzer_results(
            self.context.iteration.current
        )
        analysis = analyzer_results.get('analysis', {}) if analyzer_results else {}
        has_syntax_errors = analysis.get('has_syntax_errors', False)

        # SYNTAX ERROR PATH - Use specialized syntax repair instruction
        if has_syntax_errors:
            print("  🔧 Syntax errors detected - using syntax repair path")

            # Extract syntax error details
            syntax_errors = analysis.get('syntax_errors', [])
            if not syntax_errors:
                print("  ⚠️  Warning: has_syntax_errors=True but no syntax_errors list found")
                # Fallback to semantic feedback
                has_syntax_errors = False
            else:
                # Extract error message and code snippet from first error
                first_error = syntax_errors[0]
                if isinstance(first_error, dict):
                    # Get basic location message
                    location_msg = first_error.get('message', 'Unknown syntax error')
                    
                    # Get context field with detailed error information
                    context = first_error.get('context', '')
                    
                    # Extract the error description from context (before file location)
                    if context:
                        from src.utils.regression_log import _extract_error_message_from_context
                        error_details = _extract_error_message_from_context(context)
                        
                        # Combine location and details
                        if error_details:
                            error_message = f"{location_msg}\n\n{error_details}"
                        else:
                            error_message = location_msg
                    else:
                        error_message = location_msg
                    
                    code_snippet = first_error.get('code_snippet', 'No code snippet available')
                else:
                    error_message = str(first_error)
                    code_snippet = 'No code snippet available'

                # Check if we've had too many consecutive iterations with THE SAME syntax error
                from src.utils.regression_log import count_consecutive_same_syntax_errors

                # Get current issue from regression log entry
                current_entry = self.context.regression_log.get_entry(self.context.iteration.current)
                current_issue = current_entry.issue if current_entry else ""
                
                # Pass the full syntax_error dictionary for context comparison
                current_syntax_error = first_error if isinstance(first_error, dict) else None

                consecutive_same_errors = count_consecutive_same_syntax_errors(
                    self.context.regression_log.entries,
                    self.context.iteration.current,
                    current_issue,
                    current_syntax_error
                )

                max_failed_fixes = 5
                if consecutive_same_errors >= max_failed_fixes:
                    print(f"\n{'='*80}")
                    print(f"❌ SYNTAX ERROR LIMIT REACHED")
                    print(f"{'='*80}")
                    print(f"The system has attempted to fix THE SAME syntax error {consecutive_same_errors} times")
                    print(f"but the errors persist. This may indicate:")
                    print(f"  - Misdiagnosis of the root cause")
                    print(f"  - Alloy 6 syntax complexity beyond current capabilities")
                    print(f"  - Model structure issues requiring redesign")
                    print(f"\nCurrent syntax error:")
                    print(f"  {error_message}")
                    print(f"{'='*80}\n")

                    user_input = self.cli.request_input(
                        prompt="Please provide guidance on how to fix the syntax error (or 'skip' to continue anyway):",
                        multiline=True
                    )

                    if user_input and user_input.strip().lower() != 'skip':
                        # User provided feedback - use it as the draft feedback
                        draft_feedback = f"USER GUIDANCE (after {consecutive_same_errors} failed attempts):\n{user_input}"
                        print("  ✓ User feedback received - will use for model update")
                    else:
                        # User skipped or no input - generate one more attempt
                        print("  ⚠️  Proceeding with automated repair (may fail again)")
                        draft_feedback = None  # Will generate below
                else:
                    draft_feedback = None  # Will generate below

                # Only run retry loop if we don't have user feedback yet
                if draft_feedback is None:
                    # Implement retry loop for syntax repair (max 3 rejected attempts)
                    max_retries = 3
                    retry_count = 0
                    previous_failed_attempts = []  # List of {feedback, changes} dicts

                    while retry_count < max_retries:
                        # Show cross-iteration counter (how many iterations for this same error)
                        if consecutive_same_errors > 1:
                            print(f"  🔄 Cross-iteration fix attempt: {consecutive_same_errors}/{max_failed_fixes} for this error")
                        
                        # Show per-iteration retry counter (rejected attempts in this iteration)
                        if retry_count > 0:
                            print(f"  🔄 Rejected attempts in this iteration: {retry_count}/{max_retries}")
                        
                        print(f"  🔄 Generating syntax repair...")

                        # Generate syntax repair instructions
                        feedback = await self.generate_syntax_repair.run(
                            code_snippet=code_snippet,
                            error_message=error_message,
                            alloy_model=alloy_model,
                            previous_failed_attempts=previous_failed_attempts
                        )

                        # Check if feedback is too similar to previous attempts
                        if previous_failed_attempts:
                            from src.utils.regression_log import is_feedback_too_similar, save_rejected_feedback, extract_repair_instructions

                            # Extract REPAIR INSTRUCTIONS section from current feedback
                            current_instructions = extract_repair_instructions(feedback)

                            # Extract REPAIR INSTRUCTIONS from previous feedback texts
                            previous_feedbacks = [attempt['feedback'] for attempt in previous_failed_attempts]
                            previous_instructions = [extract_repair_instructions(fb) for fb in previous_feedbacks]

                            # Check similarity based on REPAIR INSTRUCTIONS only
                            is_similar, similar_index, similarity_score = is_feedback_too_similar(
                                new_feedback=current_instructions,
                                previous_feedbacks=previous_instructions,
                                threshold=0.80
                            )

                            if is_similar:
                                print(f"  ⚠️  Feedback too similar to attempt {similar_index + 1} (score: {similarity_score:.4f})")
                            
                                # Save rejected feedback
                                save_rejected_feedback(
                                    feedback=feedback,
                                    iteration=self.context.iteration.current,
                                    reason=f"Too similar to previous attempt {similar_index + 1}",
                                    similarity_score=similarity_score,
                                    similar_to_attempt=similar_index + 1
                                )

                                # Add to failed attempts (for next iteration)
                                previous_failed_attempts.append({
                                    'feedback': feedback,
                                    'changes': '(Rejected before execution - too similar)'
                                })

                                retry_count += 1

                                # Check if we've exhausted retries
                                if retry_count >= max_retries:
                                    print(f"  ❌ Maximum retries ({max_retries}) reached - asking user for help")
                                    print("\n" + "=" * 80)
                                    print("The Evaluator has attempted to fix the syntax error 3 times,")
                                    print("but all attempts were too similar to previous failed approaches.")
                                    print("=" * 80)
                                    print(f"\nLatest rejected feedback:\n{feedback}\n")
                                    print("=" * 80 + "\n")
                                
                                    user_input = self.cli.request_input(
                                        prompt="Please provide guidance on how to fix the syntax error:",
                                        multiline=True
                                    )

                                    if user_input and user_input.strip():
                                        # User provided feedback - use it as the draft feedback
                                        draft_feedback = f"USER GUIDANCE:\n{user_input}\n\nEvaluator's last attempt:\n{feedback}"
                                        print("  ✓ User feedback received - will use for model update")
                                    else:
                                        # User didn't provide feedback - use the last attempt anyway
                                        draft_feedback = feedback
                                        print("  ⚠️  No user feedback - using last attempt")
                                
                                    break
                                else:
                                    # Continue retry loop
                                    print(f"  🔄 Retrying with different approach...")
                                    continue
                    
                        # Feedback is different (or first attempt) - accept it
                        print(f"  ✓ Feedback accepted (unique approach)")
                        draft_feedback = feedback
                        break

                    # End of retry loop
                    print("✓ Syntax repair instructions generated")

                # For syntax repair, skip Q&A and user review - store feedback directly
                # Store feedback
                self.context.artifacts.store_feedback(
                    self.context.iteration.current,
                    draft_feedback
                )

                # Save feedback to disk
                self.context.file_manager.save_feedback(
                    {"feedback": draft_feedback, "final_convergence": False},  # Syntax repairs don't have convergence
                    iteration=self.context.iteration.current
                )

                print("✓ Syntax repair instructions stored")

                # Return early - skip semantic feedback flow
                return {
                    "user_provided_feedback": False,  # No user review for syntax repair (unless max retries hit)
                    "final_convergence": False  # Syntax repairs never trigger convergence
                }

        # SEMANTIC FEEDBACK PATH - Use existing semantic feedback flow
        else:
            print("  ✅ No syntax errors - using semantic feedback path")
            
            # Retrieve pending questions from InterpretResults
            pending_questions = self.context.artifacts.get_pending_questions(
                self.context.iteration.current
            )

            # Retrieve relevant Q&A from database (if we have questions)
            relevant_qa_str = "No relevant prior Q&A pairs found."
            if pending_questions:
                print(f"  📋 Found {len(pending_questions)} pending question(s) from InterpretResults")
                relevant_qa_records = self.context.qa_database.retrieve_relevant(
                    questions=pending_questions,
                    current_iteration=self.context.iteration.current,
                    max_results=3,
                    similarity_threshold=0.3
                )

                if relevant_qa_records:
                    relevant_qa_str = self.context.qa_database.format_for_prompt(relevant_qa_records)
                    print(f"  📚 Retrieved {len(relevant_qa_records)} relevant Q&A record(s)")
                else:
                    print(f"  ℹ️  No relevant Q&A found (database may be empty or similarity below threshold)")
            else:
                print(f"  ℹ️  No pending questions from InterpretResults")

            # Generate draft feedback
            draft_feedback = await self.generate_semantic_feedback.run(
                interpretation=interpretation,
                requirements_document=requirements,
                alloy_model=alloy_model,
                relevant_qa=relevant_qa_str
            )

            print("✓ Draft feedback generated")

            # Parse new questions from draft feedback
            from src.utils.qa_parser import (
                parse_user_questions,
                parse_qa_updates,
                parse_reused_qids
            )

            new_questions = parse_user_questions(draft_feedback, section_name="UPDATED USER QUESTIONS")

            # Parse and apply Q&A status updates
            qa_updates = parse_qa_updates(draft_feedback)
            if qa_updates:
                for qa_id, new_status in qa_updates.items():
                    if self.context.qa_database.update_status(qa_id, new_status):
                        print(f"  ✓ Updated {qa_id}: {new_status}")

            # Parse and track reused Q&A IDs
            reused_qids = parse_reused_qids(draft_feedback)
            if reused_qids:
                for qa_id in reused_qids:
                    if self.context.qa_database.increment_reuse_count(qa_id):
                        print(f"  ♻️  Reused {qa_id}")

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

                # Parse final convergence from refined feedback
                convergence_match = re.search(
                    r'===\s*CONVERGENCE_RECOMMENDATION\s*===.*?Status:\s*(TRUE|FALSE)',
                    final_feedback,
                    re.IGNORECASE | re.DOTALL
                )
                final_convergence = convergence_match.group(1).upper() == "TRUE" if convergence_match else False

                # Update artifacts
                self.context.artifacts.store_feedback(
                    self.context.iteration.current,
                    final_feedback
                )

                # Save feedback to disk
                self.context.file_manager.save_feedback(
                    {"feedback": final_feedback, "final_convergence": final_convergence},
                    iteration=self.context.iteration.current
                )

                # Record user preference
                self.context.user_preferences.add_preference(
                    preference=f"User review feedback: {user_review}",
                    iteration=self.context.iteration.current,
                    context="Feedback refinement"
                )

                # Create Q&A records if user answered questions
                if new_questions:
                    from src.utils.qa_parser import extract_question_context
                    from src.utils.qa_database import QARecord, create_qa_id

                    print(f"  💾 Storing {len(new_questions)} Q&A record(s)...")

                    for idx, question in enumerate(new_questions, start=1):
                        context = extract_question_context(question)
                        qa_id = create_qa_id(self.context.iteration.current, idx)

                        # User answered - mark as confirmed
                        record = QARecord(
                            id=qa_id,
                            iteration=self.context.iteration.current,
                            question=question,
                            answer=user_review,  # Full user feedback
                            source="user",
                            context=context,
                            status="confirmed"
                        )

                        self.context.qa_database.add_record(record)
                        print(f"    ✓ Stored {qa_id} (confirmed)")

                print("✓ Feedback refined based on user input")

                return {
                    "user_provided_feedback": True,
                    "final_convergence": final_convergence
                }
            else:
                # No user feedback - skip RefineFeedback, use preliminary recommendation from draft
                if user_review is None:
                    print("✓ No user feedback provided (timeout) - using draft feedback")
                else:
                    print("✓ No user feedback provided - using draft feedback")

                # Parse preliminary convergence from draft feedback
                convergence_match = re.search(
                    r'===\s*CONVERGENCE_RECOMMENDATION\s*===.*?Status:\s*(TRUE|FALSE)',
                    draft_feedback,
                    re.IGNORECASE | re.DOTALL
                )
                preliminary_convergence = convergence_match.group(1).upper() == "TRUE" if convergence_match else False

                # Store draft as final feedback
                self.context.artifacts.store_feedback(
                    self.context.iteration.current,
                    draft_feedback
                )

                # Save feedback to disk
                self.context.file_manager.save_feedback(
                    {"feedback": draft_feedback, "final_convergence": preliminary_convergence},
                    iteration=self.context.iteration.current
                )

                # If Evaluator asked questions but user didn't answer, check for agent assumptions
                # IMPORTANT: Only capture assumptions made in response to unanswered user questions,
                # not assumptions from ASSUMPTIONS REVIEW or other modeling decisions.
                # This is achieved by only creating Q&A records when new_questions exist.
                if new_questions:
                    from src.utils.qa_parser import extract_question_context
                    from src.utils.qa_database import QARecord, create_qa_id

                    print(f"  ⚠️  {len(new_questions)} unanswered question(s)")

                    # Check if Evaluator made assumptions in the feedback
                    # Look for assumption language: "Assuming...", "Proceeding with assumption...", etc.
                    # These patterns will match assumptions from any section, but we only create Q&A
                    # records for the questions in new_questions (from UPDATED USER QUESTIONS section)
                    assumption_patterns = [
                        r'Assuming\s+(.+?)(?:\.|$)',
                        r'Proceeding with\s+(?:the\s+)?assumption[:\s]+(.+?)(?:\.|$)',
                        r'Default assumption:\s*(.+?)(?:\.|$)'
                    ]

                    for idx, question in enumerate(new_questions, start=1):
                        # Try to find assumption related to this question
                        assumption_found = False

                        for pattern in assumption_patterns:
                            matches = re.finditer(pattern, draft_feedback, re.IGNORECASE | re.MULTILINE)
                            for match in matches:
                                assumption_text = match.group(1).strip()

                                # Create provisional Q&A record
                                context = extract_question_context(question)
                                qa_id = create_qa_id(self.context.iteration.current, idx)

                                record = QARecord(
                                    id=qa_id,
                                    iteration=self.context.iteration.current,
                                    question=question,
                                    answer=f"Agent assumption: {assumption_text}",
                                    source="agent_assumption",
                                    context=context,
                                    status="provisional"
                                )

                                self.context.qa_database.add_record(record)
                                print(f"    ~ Stored {qa_id} (provisional - agent assumption)")
                                assumption_found = True
                                break

                            if assumption_found:
                                break

                return {
                    "user_provided_feedback": False,
                    "final_convergence": preliminary_convergence
                }

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

        # Skip if no requirement updates found - reuse existing requirements file
        if requirements_feedback is None:
            print("✓ No requirement updates needed - using existing requirements")
            latest_reqs_file = self.context.file_manager.get_latest_requirements_file()
            if latest_reqs_file:
                print(f"  Using: {latest_reqs_file}")
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

        # Get previous model for diff calculation
        previous_iteration = self.context.iteration.current - 1
        previous_model = ""
        if previous_iteration > 0:
            previous_model = self.context.artifacts.alloy_models.get(previous_iteration, "")

        # Check if this is a syntax repair - if so, add delay for user review
        import time
        if feedback and "REPAIR INSTRUCTIONS" in feedback:
            print("  ⏱️  Waiting 30 seconds for feedback review...")
            time.sleep(30)
            print("  ✓ Proceeding with model update")

        updated_model_response = await self.update_model.run(
            current_model=current_model,
            evaluation_feedback=feedback,
            requirements_document=requirements
        )

        print("✓ Alloy model updated")

        # Parse regression tracking fields from RE response
        from .utils.regression_log import parse_re_response_for_regression, RegressionLogEntry, VerificationResult

        regression_fields = parse_re_response_for_regression(updated_model_response)

        # Extract the actual model code (after the regression fields)
        # The model code is in the ```alloy code block
        import re
        model_match = re.search(r'```alloy\s*\n(.*?)\n```', updated_model_response, re.DOTALL)
        if model_match:
            updated_model = model_match.group(1)
        else:
            # Fallback: use the whole response if no code block found
            updated_model = updated_model_response

        # Save to file
        model_file = self.context.file_manager.save_alloy_model(
            updated_model,
            iteration=self.context.iteration.current
        )
        print(f"  Saved to: {model_file}")

        # Compute diff using Linux diff command on actual files
        updated_lines = ""
        if previous_iteration > 0:
            previous_model_file = self.context.file_manager.models_dir / f"AlloyModel__{previous_iteration}.als"
            if previous_model_file.exists():
                import subprocess
                try:
                    result = subprocess.run(
                        ['diff', '-u', str(previous_model_file), str(model_file)],
                        capture_output=True,
                        text=True
                    )
                    # diff returns non-zero exit code when files differ (this is normal)
                    # Filter out comment lines (lines with // after diff prefix)
                    filtered_lines = []
                    for line in result.stdout.split('\n'):
                        # Keep diff metadata lines (---, +++, @@)
                        if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
                            filtered_lines.append(line)
                        # For content lines (start with -, +, or space), check if content is a comment
                        elif len(line) > 0:
                            # Get content after diff prefix (first character)
                            content = line[1:] if len(line) > 1 else ""
                            # Keep if not a comment line
                            if not content.lstrip().startswith('//'):
                                filtered_lines.append(line)
                        else:
                            # Empty line - keep it
                            filtered_lines.append(line)
                    updated_lines = '\n'.join(filtered_lines)
                except Exception as e:
                    print(f"Warning: Failed to compute diff: {e}")
                    updated_lines = "Error computing diff"
        else:
            # First iteration - no previous model to compare
            updated_lines = "Initial model (no previous version to compare)"

        # Get previous verification result if available
        previous_result = None
        prev_entry = self.context.regression_log.get_entry(previous_iteration)
        if prev_entry:
            previous_result = prev_entry.current_result

        # Create regression log entry (current_result will be filled after next verification)
        # For now, use a placeholder
        entry = RegressionLogEntry(
            iteration_id=self.context.iteration.current,
            model_file_location=str(model_file),
            fix_intent=regression_fields.get("fix_intent", "No fix intent provided"),
            source_ref=regression_fields.get("source_ref", "No source reference provided"),
            current_result=VerificationResult(
                syntax="Pending",
                satisfied_predicates=[],
                unsatisfied_predicates=[],
                counterexamples=[],
                no_counterexample=[]
            ),
            previous_result=previous_result,
            updated_lines=updated_lines,
            expected_impact=regression_fields.get("expected_impact")
        )

        self.context.regression_log.add_entry(entry)
        print(f"  Regression log entry created for iteration {self.context.iteration.current}")
        self._debug(f"[DEBUG] Step 8 - Created entry for iteration {self.context.iteration.current}")
        self._debug(f"[DEBUG] Total entries in log: {len(self.context.regression_log.entries)}")

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
        self.logger.log(f"  Regression log entries: {len(self.context.regression_log.entries)}")

    def _create_verification_snapshot(self, analyzer_results: Dict[str, Any]):
        """
        Create a verification result snapshot from analyzer results.

        Args:
            analyzer_results: Results from AlloyExecutor

        Returns:
            VerificationResult snapshot
        """
        from .utils.regression_log import VerificationResult

        analysis = analyzer_results.get('analysis', {})

        # Syntax status
        has_syntax_errors = analysis.get('has_syntax_errors', False)
        syntax_status = "Error" if has_syntax_errors else "OK"

        # Error message (only if syntax errors exist)
        error_message = None
        if has_syntax_errors:
            syntax_errors = analysis.get('syntax_errors', [])
            if syntax_errors:
                # Extract context field from syntax errors
                error_parts = []
                for err in syntax_errors:
                    if isinstance(err, dict) and err.get('context'):
                        error_parts.append(err['context'])
                if error_parts:
                    error_message = "\n---\n".join(error_parts)

        # Satisfied predicates (list of successful run command names)
        instances = analysis.get('instances', [])
        satisfied_predicates = [inst['command_name'] for inst in instances]

        # Unsatisfied predicates (list of unsuccessful run command names)
        unsat_run_commands = analysis.get('unsat_run_commands', [])
        unsatisfied_predicates = [cmd['name'] for cmd in unsat_run_commands]

        # Counterexamples (list of assert command names that generated SAT instances)
        counterexamples_list = analysis.get('counterexamples', [])
        counterexamples = [ce['command_name'] for ce in counterexamples_list]

        # No counterexample (list of assert command names with no counterexamples)
        unsat_check_commands = analysis.get('unsat_check_commands', [])
        no_counterexample = [cmd['name'] for cmd in unsat_check_commands]

        return VerificationResult(
            syntax=syntax_status,
            error_message=error_message,
            satisfied_predicates=satisfied_predicates,
            unsatisfied_predicates=unsatisfied_predicates,
            counterexamples=counterexamples,
            no_counterexample=no_counterexample
        )


    def _calculate_actual_impact(self, current_results: Dict[str, Any], previous_results: Dict[str, Any]):
        """
        Calculate actual impact by comparing current and previous analyzer results.

        Args:
            current_results: Current analyzer results
            previous_results: Previous analyzer results

        Returns:
            ImpactAnalysis object
        """
        from .utils.regression_log import ImpactAnalysis

        current_analysis = current_results.get('analysis', {})
        previous_analysis = previous_results.get('analysis', {})

        impact = ImpactAnalysis()

        # Get current and previous command states
        curr_instances = {inst['command_name'] for inst in current_analysis.get('instances', [])}
        curr_unsat_runs = {cmd['name'] for cmd in current_analysis.get('unsat_run_commands', [])}
        curr_counterexamples = {ce['command_name'] for ce in current_analysis.get('counterexamples', [])}
        curr_passing_assertions = {cmd['name'] for cmd in current_analysis.get('unsat_check_commands', [])}

        prev_instances = {inst['command_name'] for inst in previous_analysis.get('instances', [])}
        prev_unsat_runs = {cmd['name'] for cmd in previous_analysis.get('unsat_run_commands', [])}
        prev_counterexamples = {ce['command_name'] for ce in previous_analysis.get('counterexamples', [])}
        prev_passing_assertions = {cmd['name'] for cmd in previous_analysis.get('unsat_check_commands', [])}

        # Calculate changes
        # SAT → UNSAT: was satisfying instance, now unsatisfiable
        impact.sat_to_unsat = list(prev_instances & curr_unsat_runs)

        # UNSAT → SAT: was unsatisfiable, now has satisfying instance
        impact.unsat_to_sat = list(prev_unsat_runs & curr_instances)

        # PASS → FAIL: was passing (check UNSAT), now failing (has counterexample)
        impact.pass_to_fail = list(prev_passing_assertions - curr_passing_assertions)

        # FAIL → PASS: was failing (had counterexample), now passing (check UNSAT)
        impact.fail_to_pass = list(curr_passing_assertions - prev_passing_assertions)

        return impact
