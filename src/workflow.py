"""
AutoRE Workflow (V2) - Using SharedRuntimeContext.

Simplified workflow that directly calls actions instead of message passing.
"""
import asyncio
import signal
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
        timeout: Optional[int] = None,
        project_name: str = "default"
    ):
        """
        Initialize workflow.

        Args:
            input_file: Path to input requirements file
            base_dir: Base directory for the project
            max_iterations: Maximum refinement iterations
            timeout: CLI timeout in seconds. If None, falls back to
                config.yaml's user_interaction.response_timeout (or 300 if
                that is also unset).
            project_name: Project name for memory isolation
        """
        self.base_dir = Path(base_dir)
        self.input_file = input_file
        self.max_iterations = max_iterations

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

        if timeout is None:
            timeout = self.config_loader.get_user_interaction_config().get(
                'response_timeout', 300)
        self.timeout = timeout

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

        # Post-analysis chain (deterministic): ErrorNormalizer -> IssuePatternTracker
        # -> SemanticIssueTracker -> RepairPlateauDetector (escalation builders)
        from .utils.error_normalizer import ErrorNormalizer
        from .utils.issue_pattern_tracker import IssuePatternTracker
        from .utils.semantic_issue_tracker import SemanticIssueTracker
        self.error_normalizer = ErrorNormalizer(logger=self.logger)
        self.issue_pattern_tracker = IssuePatternTracker(logger=self.logger)
        self.semantic_issue_tracker = SemanticIssueTracker(logger=self.logger)

        # Lessons are confirmed only after their target issue stays resolved
        # for several consecutive iterations (guards against oscillating errors)
        from .utils.learning_system import LessonProbation
        self.lesson_probation = LessonProbation(required_clean_iterations=3, logger=self.logger)

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

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown on Ctrl+C and SIGTERM."""
        def signal_handler(signum, frame):
            raise KeyboardInterrupt()

        signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # Graceful termination
        print("  ⚙️  Signal handlers registered (Ctrl+C will save state before exit)")

    async def run(self, resume_mode: bool = False, resume_iteration: Optional[int] = None):
        """Run the complete workflow.

        Args:
            resume_mode: If True, resume from existing model/requirements
            resume_iteration: Specific iteration to resume from (None = latest)
        """
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()

        try:
            self.logger.log("\n" + "=" * 80)
            self.logger.log("AutoRE - Automated Requirements Engineering")
            self.logger.log("=" * 80)
            self.logger.log("")

            if resume_mode:
                # Resume from existing files
                await self._resume_from_analyzer(resume_iteration)

                # Restore the immutable original input (ground truth for
                # requirement-drift protection) if a prior run preserved it.
                original = self.context.file_manager.load_original_requirements()
                if original:
                    self.context.artifacts.store_original_requirements(original)
                
                # [TEMPORARY] Repair regression log entries from previous runs with buggy code
                # TODO: Remove this call when _repair_regression_log_issues() is removed
                await self._repair_regression_log_issues()
                
                # In resume mode, max_iterations is additional iterations from current
                # e.g., resume at 7 with max_iterations=10 means run 7 to 17 (inclusive)
                effective_max = self.context.iteration.current + self.max_iterations + 1
            else:
                # Clear regression log for fresh start from iteration 0
                self.context.regression_log.clear()
                self.context.requirement_patch_log.clear()

                # Read input requirements and preserve them as the immutable
                # ground truth every future requirement update is checked
                # against (anti-drift anchor).
                raw_requirements = self._read_input()
                self.context.artifacts.store_original_requirements(raw_requirements)
                self.context.file_manager.save_original_requirements(raw_requirements)

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
                    # Convergence (hard metrics passed) proves no issues remain:
                    # confirm any lessons still on probation
                    self._store_confirmed_lessons(self.lesson_probation.flush())
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

            # Save error symbol index to Output/RegressionLog/
            self.context.regression_log.save_error_symbol_index()

            # Save copy of requirement patch log to Output/RequirementPatchLog/
            self.context.requirement_patch_log.save_copy_to_output()

            self.logger.log("\n" + "=" * 80)
            self.logger.log("Workflow Complete")
            self.logger.log("=" * 80)
            self._print_summary()

        except KeyboardInterrupt:
            # Handle manual interruption (Ctrl+C)
            print("\n\n⚠️  Workflow interrupted by user")
            self.logger.log("\n" + "=" * 80)
            self.logger.log("Workflow Interrupted by User")
            self.logger.log("=" * 80)

            # Save state before exiting
            self.context.save_state()
            self.context.regression_log.save_copy_to_output()
            self.context.regression_log.save_error_symbol_index()
            self.context.requirement_patch_log.save_copy_to_output()

            print("  ✓ State saved - you can resume from where you left off")
            self.logger.log("State saved successfully")
            raise

        except Exception as e:
            # Save copy of regression log even on failure
            self.context.regression_log.save_copy_to_output()

            # Save error symbol index even on failure
            self.context.regression_log.save_error_symbol_index()

            # Save copy of requirement patch log even on failure
            self.context.requirement_patch_log.save_copy_to_output()

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
                # Determine action type based on analyzer results from regression log
                # Check if there were syntax errors in the target iteration
                action_type = "GenerateSemanticFeedback"  # Default

                entry = self.context.regression_log.get_entry(target_iteration)
                if entry and entry.current_result:
                    # Check error_message field to determine if there were syntax errors
                    # (syntax field may be "Pending" if entry was just created)
                    if entry.current_result.error_message:
                        action_type = "GenerateSyntaxRepairInstruction"
                        print(f"✓ Loaded existing feedback from iteration {target_iteration} (syntax repair mode - had syntax errors)")
                    else:
                        print(f"✓ Loaded existing feedback from iteration {target_iteration} (semantic repair mode - no syntax errors)")
                else:
                    print(f"✓ Loaded existing feedback from iteration {target_iteration} (defaulting to semantic mode)")

                self.context.artifacts.store_feedback(target_iteration, feedback, action_type=action_type)
        except:
            print(f"  (No feedback found for iteration {target_iteration} - will generate fresh)")
        
        print(f"\n✓ Resume complete - starting from Step 4 (Evaluate Model) at iteration {target_iteration}")

    async def _repair_regression_log_issues(self):
        """
        [TEMPORARY - REMOVE IN FUTURE] Repair issue fields in regression log entries by re-analyzing old model files.

        This is needed when resuming from a previous run where entries were created with buggy code
        that didn't properly extract issues. We re-run the analyzer on old models to get correct issues.

        TODO: Remove this function once all regression logs from old buggy runs have been migrated/discarded.
        Issues fixed by this repair:
        - Empty or "No issues" when there were actually issues
        - "counterexample: unknown" due to 'command' vs 'command_name' key mismatch

        Once all users run fresh workflows with corrected code, this repair is unnecessary.
        Target removal: After all active projects have been re-initialized or completed.
        """
        from .utils.regression_log import extract_issue_description, check_issue_resolved

        self.logger.log("\n🔧 Repairing previous regression log entries before resuming")
        repaired_count = 0

        # Cache analysis results to avoid re-analyzing the same model multiple times
        analysis_cache = {}  # iteration_id -> analysis_dict

        async def get_cached_analysis(iteration_id: int):
            """Get analysis from cache or run analyzer and cache result."""
            if iteration_id in analysis_cache:
                return analysis_cache[iteration_id]

            model_file = self.context.file_manager.get_alloy_model_path(iteration_id)
            if not model_file.exists():
                analysis_cache[iteration_id] = None
                return None

            try:
                results = await self.run_analyzer.run(model_file)
                analysis = results.get('analysis', {})
                analysis_cache[iteration_id] = analysis
                return analysis
            except Exception:
                analysis_cache[iteration_id] = None
                return None

        for entry in self.context.regression_log.entries:
            # Skip if issue is already properly extracted (not "No issues" and no "unknown" counterexamples)
            needs_repair = False
            if not entry.issue or entry.issue == "No issues":
                needs_repair = True
            elif "counterexample: unknown" in entry.issue:
                # Fix old entries with "unknown" counterexample names (from command vs command_name bug)
                needs_repair = True

            if not needs_repair:
                continue

            # Get analysis (cached or fresh)
            analysis = await get_cached_analysis(entry.iteration_id)
            if analysis is None:
                continue

            # Re-extract issue
            new_issue = extract_issue_description(analysis)

            if new_issue != entry.issue:
                old_issue = entry.issue
                entry.issue = new_issue
                repaired_count += 1
                self.logger.log(f"[REPAIR] Iteration {entry.iteration_id}: '{old_issue}' → '{new_issue}'")

                # Also re-check resolved_target_issue for this entry
                if entry.iteration_id > 0:
                    prev_entry = self.context.regression_log.get_entry(entry.iteration_id - 1)
                    if prev_entry:
                        # Get previous analysis (cached or fresh)
                        prev_analysis = await get_cached_analysis(entry.iteration_id - 1)
                        if prev_analysis is not None:
                            entry.resolved_target_issue = check_issue_resolved(
                                current_analysis=analysis,
                                previous_analysis=prev_analysis,
                                current_entry=entry,
                                previous_entry=prev_entry
                            )

        if repaired_count > 0:
            self.context.regression_log._save_to_file()
            self.logger.log(f"✓ Repaired {repaired_count} regression log entries")

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
                # Log user input
                self.logger.log("\n" + "=" * 80)
                self.logger.log("USER INPUT - Step 2 Clarifications")
                self.logger.log("=" * 80)
                self.logger.log(user_input)
                self.logger.log("=" * 80 + "\n")

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
                self.logger.log("✓ No clarifications provided (Step 2)")
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
        
        self.logger.log(f"[DEBUG] Step 4 - Looking for entry at iteration {self.context.iteration.current}")
        self.logger.log(f"[DEBUG] Entry found: {entry is not None}")
        
        # If no entry exists for current iteration (e.g., iteration 0), create one
        if not entry:
            from .utils.regression_log import RegressionLogEntry, VerificationResult, ImpactAnalysis
            self.logger.log(f"[DEBUG] Creating entry for iteration {self.context.iteration.current} (first time evaluation)")
            
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
        self.logger.log(f"[DEBUG] Results structure check:")
        self.logger.log(f"  has_syntax_errors in analysis: {current_analysis.get('has_syntax_errors', 'NOT FOUND')}")
        self.logger.log(f"  syntax_errors count: {len(current_analysis.get('syntax_errors', []))}")
        if current_analysis.get('syntax_errors'):
            self.logger.log(f"  first error line: {current_analysis['syntax_errors'][0].get('line', 'NO LINE')}")
        
        entry.issue = extract_issue_description(current_analysis)
        
        # Extract syntax error context for comparison
        syntax_errors = current_analysis.get('syntax_errors', [])
        if syntax_errors and isinstance(syntax_errors[0], dict):
            entry.syntax_error_context = syntax_errors[0].get('context', None)
        else:
            entry.syntax_error_context = None

        # Post-analysis chain, step 1 of 4: ErrorNormalizer.
        # Convert the raw Alloy error into a stable, location-independent
        # signature and store it on this iteration's regression-log entry.
        entry.error_signature = self.error_normalizer.run(
            analysis=current_analysis,
            model_path=str(model_file)
        )
        if entry.error_signature:
            self.logger.log(
                f"[DEBUG] ErrorNormalizer signature: {entry.error_signature.get('normalized_signature')}"
            )

        # A syntax error must always yield a normalized signature - resolution and
        # lesson tracking depend on it (a missing signature forces the conservative
        # "not resolved" fallback in check_issue_resolved / issues_match). Flag it
        # loudly if the normalizer produced nothing, but keep the run going.
        has_syntax_error = (entry.current_result is not None
                            and entry.current_result.syntax == "Error")
        normalized_sig = (entry.error_signature or {}).get('normalized_signature')
        if has_syntax_error and not normalized_sig:
            self.logger.log(
                f"❌ [ERROR] ErrorNormalizer produced no signature for a syntax error "
                f"at iteration {self.context.iteration.current} (issue: {entry.issue!r}). "
                f"Resolution/lesson tracking falls back to conservative 'not resolved'."
            )

        # Post-analysis chain, step 2 of 4: IssuePatternTracker.
        # Classify the current error against recent iterations and store it.
        entry.issue_pattern = self.issue_pattern_tracker.run(
            current_iteration=self.context.iteration.current,
            current_signature=entry.error_signature,
            regression_log_entries=self.context.regression_log.entries
        )
        self.logger.log(
            f"[DEBUG] IssuePatternTracker: pattern_type={entry.issue_pattern.get('pattern_type')}, "
            f"repeat_exact={entry.issue_pattern.get('repeat_count_exact')}, "
            f"repeat_root_family={entry.issue_pattern.get('repeat_count_root_family')}"
        )

        # Post-analysis chain, step 3 of 4: SemanticIssueTracker.
        # Track persistence of unsat predicates and assertion counterexamples
        # across syntactically-valid iterations; flags issues that require
        # escalation to requirements diagnosis instead of more model repair.
        entry.semantic_issue_persistence = self.semantic_issue_tracker.run(
            current_iteration=self.context.iteration.current,
            current_result=entry.current_result,
            regression_log_entries=self.context.regression_log.entries
        )
        if entry.semantic_issue_persistence.get('issues'):
            self.logger.log(
                f"[DEBUG] SemanticIssueTracker: "
                f"{len(entry.semantic_issue_persistence['issues'])} tracked issue(s), "
                f"escalation_required={entry.semantic_issue_persistence.get('escalation_required')}, "
                f"escalated={entry.semantic_issue_persistence.get('escalated_issues')}"
            )

        # Debug logging
        self.logger.log(f"[DEBUG] Step 4 - Iteration: {self.context.iteration.current}")
        self.logger.log(f"[DEBUG] Entry found/created for iteration {self.context.iteration.current}: True")
        self.logger.log(f"[DEBUG] Extracted issue: {entry.issue}")

        # Check if target issue from previous iteration is resolved
        entry.resolved_target_issue = check_issue_resolved(
            current_analysis=current_analysis,
            previous_analysis=prev_analysis,
            current_entry=entry,
            previous_entry=prev_entry
        )

        self.logger.log(f"[DEBUG] Resolved target issue: {entry.resolved_target_issue}")

        # A syntax error fixed into a compilable model is a DEFINITIVE
        # resolution. Alloy could not compile the previous model, so the syntax
        # error genuinely disappears the moment the model compiles - unlike
        # semantic issues (unsat predicates / counterexamples), which oscillate
        # across iterations. Such a resolution needs no probation window:
        # confirm it immediately and store the fix's lesson right away (below).
        prev_had_syntax_error = bool(prev_analysis and prev_analysis.get('syntax_errors'))
        curr_compiles = (entry.current_result is not None
                         and entry.current_result.syntax == "OK")
        syntax_definitively_resolved = (
            entry.resolved_target_issue is True
            and prev_had_syntax_error
            and curr_compiles
        )

        # A single absent iteration only proves TEMPORARY absence (oscillating
        # errors come back): mark the resolution provisional. It is confirmed
        # or reverted by update_resolution_statuses() over later iterations.
        # The one exception is a syntax error that now compiles - that is
        # confirmed on the spot (see above).
        if entry.resolved_target_issue is True and prev_entry and prev_entry.issue:
            if syntax_definitively_resolved:
                entry.resolution_status = {
                    'status': 'resolved_confirmed',
                    'target_issue': prev_entry.issue,
                    'target_signature': (prev_entry.error_signature or {}).get('normalized_signature'),
                    'target_fingerprint': (prev_entry.error_signature or {}).get('detail_fingerprint'),
                    'confirmed_at': self.context.iteration.current,
                }
                self.logger.log(
                    f"[DEBUG] Syntax error fixed - resolution CONFIRMED immediately "
                    f"(model compiles; target: '{prev_entry.issue[:80]}')"
                )
            else:
                entry.resolution_status = {
                    'status': 'temporarily_absent',
                    'target_issue': prev_entry.issue,
                    'target_signature': (prev_entry.error_signature or {}).get('normalized_signature'),
                    'target_fingerprint': (prev_entry.error_signature or {}).get('detail_fingerprint'),
                }
                self.logger.log(
                    f"[DEBUG] Resolution marked temporarily_absent "
                    f"(target: '{prev_entry.issue[:80]}')"
                )

        # Advance provisional resolutions from earlier iterations: confirm
        # those whose target stayed absent long enough, revert (and return to
        # failed-fix history) those whose target issue recurred.
        from .utils.regression_log import update_resolution_statuses
        update_resolution_statuses(
            entries=self.context.regression_log.entries,
            current_iteration=self.context.iteration.current,
            required_clean_iterations=3,
            logger=self.logger
        )

        # Confirm or discard any staged lessons from the previous iteration's
        # feedback/fix, now that we know whether the issue they targeted was resolved
        # First advance lessons already on probation: discard any whose target
        # issue recurred (oscillation), store those that stayed resolved for
        # the required number of consecutive iterations.
        confirmed_items, _discarded_items = self.lesson_probation.evaluate(
            current_iteration=self.context.iteration.current,
            current_issue=entry.issue,
            current_signature=(entry.error_signature or {}).get('normalized_signature'),
            current_fingerprint=(entry.error_signature or {}).get('detail_fingerprint'),
            syntax_ok=(entry.current_result.syntax == "OK")
        )
        self._store_confirmed_lessons(confirmed_items)

        # Then move newly-resolved pending lessons onto probation (instead of
        # storing them immediately - a single resolved iteration is not enough
        # evidence when errors oscillate A,B,A,B across iterations).
        for pending_attr in ('pending_evaluator_feedback_lesson', 'pending_re_fix_lesson'):
            pending = getattr(self.context, pending_attr)
            if pending is None:
                continue
            if entry.resolved_target_issue is True:
                src_entry = self.context.regression_log.get_entry(pending['source_iteration'])
                if syntax_definitively_resolved:
                    # The fix turned a non-compiling model into a compilable
                    # one - a definitive syntax resolution. Store the lesson
                    # from the iteration that generated the fix and correct
                    # feedback immediately; no probation window is needed.
                    self._store_confirmed_lessons([{'pending': pending}])
                    self.logger.log(
                        f"✅ Lesson from {pending['agent_name']}/{pending['action_name']} "
                        f"(iteration {pending['source_iteration']}) stored immediately - "
                        f"syntax error fixed, model now compiles"
                    )
                else:
                    self.lesson_probation.add(
                        pending=pending,
                        target_issue=src_entry.issue if src_entry else '',
                        target_signature=((src_entry.error_signature or {}).get('normalized_signature')
                                          if src_entry else None),
                        target_fingerprint=((src_entry.error_signature or {}).get('detail_fingerprint')
                                            if src_entry else None),
                        resolved_at_iteration=self.context.iteration.current
                    )
                    self.logger.log(
                        f"⏳ Lesson from {pending['agent_name']}/{pending['action_name']} "
                        f"(iteration {pending['source_iteration']}) placed on probation - stored only if "
                        f"the issue stays resolved for {self.lesson_probation.required_clean_iterations} "
                        f"consecutive iterations"
                    )
            else:
                self.logger.log(
                    f"🗑️ Discarding unconfirmed lesson from {pending['agent_name']}/{pending['action_name']} "
                    f"(iteration {pending['source_iteration']})"
                )
            setattr(self.context, pending_attr, None)

        # Detect if same fix approach has been tried multiple times for this issue
        if entry.issue and entry.resolved_target_issue is False:
            entry.fix_pattern_detected = detect_fix_pattern(
                current_issue=entry.issue,
                regression_log_entries=self.context.regression_log.entries
            )
            self.logger.log(f"[DEBUG] Pattern detected: {entry.fix_pattern_detected}")

        # Guarantee an outcome classification: InterpretResults is skipped on
        # syntax-error iterations (and can fail to produce one on semantic
        # iterations), which previously left entries stuck at "pending".
        # Derive a deterministic classification now; the LLM classification
        # from InterpretResults overwrites it later when available.
        if entry.outcome_classification == "pending":
            from .utils.regression_log import derive_outcome_classification
            entry.outcome_classification = derive_outcome_classification(
                has_syntax_errors=current_analysis.get('has_syntax_errors', False),
                resolved_target_issue=entry.resolved_target_issue,
                has_previous_iteration=prev_entry is not None,
                current_issue=entry.issue
            )
            self.logger.log(
                f"[DEBUG] Outcome classification (deterministic): {entry.outcome_classification}"
            )

        self.context.regression_log._save_to_file()
        self.logger.log(f"[DEBUG] Regression log saved with {len(self.context.regression_log.entries)} entries")

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
                section_name="BLOCKING QUESTIONS"
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

    def _run_semantic_diagnostics(
        self,
        semantic_escalation: dict,
        semantic_persistence: Optional[dict],
        model_text: Optional[str],
    ) -> None:
        """
        Rungs 2-3 of the semantic escalation ladder (deterministic, LLM-free).

        For each escalated UNSAT predicate, re-run it alone at enlarged bounds
        (rung 2: bounded-search artifact?) and, if still UNSAT, delta-debug the
        fact set to the minimal blocking facts / implicated requirement IDs
        (rung 3). The measured evidence is appended to the escalation
        directive; the interpretation rules live in the
        PersistentIssueEscalation prompt section. Best-effort: any failure
        leaves the escalation unchanged.
        """
        try:
            escalated = set(semantic_escalation.get('escalated_issues') or [])
            unsat_predicates = [
                issue.get('name')
                for issue in ((semantic_persistence or {}).get('issues') or [])
                if issue.get('name') in escalated
                and issue.get('kind') == 'unsat_predicate'
            ]
            if not unsat_predicates or not model_text:
                return

            from src.utils.alloy_executor import AlloyExecutor
            from src.utils.semantic_diagnostics import (
                diagnose_unsat_predicates,
                make_alloy_sat_checker,
            )
            diag_dir = Path(
                f"Output/AnalyzerOutput/{self.context.iteration.current}/diagnostics"
            )
            check = make_alloy_sat_checker(
                AlloyExecutor(), diag_dir, logger=self.logger
            )
            print(
                f"  🔬 Deterministic diagnosis (scope sweep + fact localization) "
                f"for: {', '.join(unsat_predicates)}"
            )
            diagnosis = diagnose_unsat_predicates(
                model_text, unsat_predicates, check, logger=self.logger
            )
            if diagnosis['directive_text']:
                semantic_escalation['directive'] += "\n" + diagnosis['directive_text']
                semantic_escalation['diagnostics'] = diagnosis['results']
        except Exception as e:
            self.logger.log(f"[SEMANTIC_DIAGNOSTICS] skipped: {e}")

    def _apply_requirement_gate(
        self,
        feedback: str,
        gate_decision: Optional[str],
        proposed_updates: Optional[str],
        semantic_escalation: dict,
        current_entry,
        qa_index: int,
    ) -> str:
        """
        Rung 5 of the semantic escalation ladder: enforce the user's decision
        on the requirement updates proposed for persistent semantic issues.

        rejected              -> strip REQUIREMENT UPDATES deterministically so
                                 _step7 cannot apply them; record the rejection
                                 as a confirmed Q&A record.
        accepted / edited     -> record the decision (confirmed) and store a
                                 REGENERATE_PREDICATES escalation on the entry
                                 so _step8 directs the RE agent to rebuild the
                                 affected constructs from the updated
                                 requirements instead of patching.
        provisional (timeout) -> like accepted, but recorded as a provisional
                                 agent assumption in the Q&A database.

        Returns the (possibly stripped) feedback text.
        """
        if not gate_decision:
            return feedback
        try:
            from src.utils.qa_database import QARecord, create_qa_id
            from src.utils.repair_plateau_detector import (
                build_regeneration_escalation,
                remove_requirement_updates,
            )

            escalated_names = ', '.join(
                semantic_escalation.get('escalated_issues') or [])
            question = (
                f"Confirm the requirement update(s) proposed for persistent "
                f"issue(s) {escalated_names}:\n{(proposed_updates or '').strip()}"
            )

            if gate_decision == 'rejected':
                self.context.qa_database.add_record(QARecord(
                    id=create_qa_id(self.context.iteration.current, qa_index),
                    iteration=self.context.iteration.current,
                    question=question,
                    answer="User REJECTED the proposed requirement update(s); "
                           "the requirements remain unchanged.",
                    source="user",
                    context="requirement-change decision gate",
                    status="confirmed",
                ))
                self.logger.log(
                    "[REQUIREMENT_GATE] rejected - REQUIREMENT UPDATES section "
                    "stripped from feedback"
                )
                print("  🚫 Updates rejected - requirements stay unchanged")
                return remove_requirement_updates(feedback)

            # accepted / edited / provisional -> targeted regeneration
            answer = {
                'accepted': "User ACCEPTED the proposed requirement update(s).",
                'edited': "User ACCEPTED the requirement update(s) with edits "
                          "(see the refined feedback's REQUIREMENT UPDATES).",
                'provisional': "No user response - requirement update(s) applied "
                               "as a PROVISIONAL assumption pending confirmation.",
            }.get(gate_decision, gate_decision)
            self.context.qa_database.add_record(QARecord(
                id=create_qa_id(self.context.iteration.current, qa_index),
                iteration=self.context.iteration.current,
                question=question,
                answer=answer,
                source="user" if gate_decision in ('accepted', 'edited') else "agent_assumption",
                context="requirement-change decision gate",
                status="provisional" if gate_decision == 'provisional' else "confirmed",
            ))

            regeneration = build_regeneration_escalation(
                current_iteration=self.context.iteration.current,
                semantic_escalation=semantic_escalation,
                user_decision=gate_decision,
                proposed_updates=proposed_updates,
            )
            if current_entry:
                current_entry.repair_escalation = regeneration
                self.context.regression_log._save_to_file()
            self.logger.log(
                f"[REQUIREMENT_GATE] {gate_decision} -> REGENERATE_PREDICATES "
                f"for {regeneration['regenerate_targets']}"
            )
            print(
                f"  ♻️  Regeneration escalation stored for: "
                f"{', '.join(regeneration['regenerate_targets'])}"
            )
        except Exception as e:
            self.logger.log(f"[REQUIREMENT_GATE] skipped: {e}")
        return feedback

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

                # Post-analysis chain, step 4 of 4: RepairPlateauDetector.
                # Turn the cross-iteration pattern classification into an
                # escalation decision + evidence block for the Evaluator/RE prompts.
                from src.utils.repair_plateau_detector import build_syntax_escalation
                syntax_escalation = build_syntax_escalation(
                    current_iteration=self.context.iteration.current,
                    issue_pattern=current_entry.issue_pattern if current_entry else None,
                    error_signature=current_entry.error_signature if current_entry else None,
                    regression_log_entries=self.context.regression_log.entries
                )
                pattern_status = syntax_escalation['directive'] or (
                    "No cross-iteration error pattern detected - this is the first "
                    "occurrence of this error."
                )
                if current_entry:
                    current_entry.repair_escalation = syntax_escalation
                    self.context.regression_log._save_to_file()
                if syntax_escalation['escalation_level'] > 0:
                    self.logger.log(
                        f"  🚨 Repair escalation: level {syntax_escalation['escalation_level']} "
                        f"({syntax_escalation['strategy']})"
                    )

                error_counts = count_consecutive_same_syntax_errors(
                    self.context.regression_log.entries,
                    self.context.iteration.current,
                    current_issue,
                    current_syntax_error,
                    window=7
                )

                consecutive_count = error_counts['consecutive']
                total_count = error_counts['total']

                # Trigger user feedback if: 3 consecutive OR 4 total within the last 7 iterations
                threshold_consecutive = 3
                threshold_total = 4

                if consecutive_count >= threshold_consecutive or total_count >= threshold_total:
                    self.logger.log(f"\n{'='*80}")
                    self.logger.log(f"❌ SYNTAX ERROR LIMIT REACHED")
                    self.logger.log(f"{'='*80}")
                    
                    if consecutive_count >= threshold_consecutive:
                        self.logger.log(f"The same syntax error has occurred {consecutive_count} times consecutively.")
                    else:
                        self.logger.log(f"The same syntax error has occurred {total_count} times within the last 7 iterations.")
                    
                    self.logger.log(f"Occurrences: {consecutive_count} consecutive, {total_count} total")
                    self.logger.log(f"This may indicate:")
                    self.logger.log(f"  - Misdiagnosis of the root cause")
                    self.logger.log(f"  - Alloy 6 syntax complexity beyond current capabilities")
                    self.logger.log(f"  - Model structure issues requiring redesign")
                    self.logger.log(f"\nCurrent syntax error:")
                    self.logger.log(f"  {error_message}")
                    self.logger.log(f"{'='*80}\n")

                    user_input = self.cli.request_input(
                        prompt="Please provide guidance on how to fix the syntax error (or 'skip' to continue anyway):",
                        multiline=True
                    )

                    # Log user input request and response
                    trigger_reason = f"{consecutive_count} consecutive" if consecutive_count >= threshold_consecutive else f"{total_count} total"
                    self.logger.log(f"\n⚠️  USER INPUT REQUESTED: Syntax error limit reached ({trigger_reason})")
                    
                    if user_input and user_input.strip().lower() != 'skip':
                        # User provided feedback - refine with Evaluator
                        self.logger.log("  ✓ User feedback received - refining with Evaluator...")

                        # Call GenerateSyntaxRepairInstruction with user guidance
                        draft_feedback = await self.generate_syntax_repair.run(
                            code_snippet=code_snippet,
                            error_message=error_message,
                            alloy_model=alloy_model,
                            user_guidance=user_input,
                            pattern_status=pattern_status
                        )

                        self.logger.log("  ✓ Feedback refined based on user guidance")
                        
                        # Log the user's guidance (just to file, not console since user already knows what they typed)
                        self.logger.log("USER PROVIDED GUIDANCE:")
                        self.logger.log("-" * 80)
                        self.logger.log(user_input)
                        self.logger.log("-" * 80)
                    else:
                        # User skipped or no input - generate one more attempt
                        self.logger.log("  ⚠️  Proceeding with automated repair (may fail again)")
                        self.logger.log("USER RESPONSE: Skipped (no guidance provided)")
                        draft_feedback = None  # Will generate below
                else:
                    draft_feedback = None  # Will generate below

                # Only run retry loop if we don't have user feedback yet
                if draft_feedback is None:
                    # Implement retry loop for syntax repair (max 3 rejected attempts)
                    max_retries = 3
                    retry_count = 0
                    
                    # Fetch failed syntax repair attempts from previous iterations
                    # This prevents repeating the same repair across iterations
                    # IMPORTANT: Only include attempts for the SAME error (same symbol)
                    previous_failed_attempts = []  # Genuinely failed/unconfirmed prior repairs -> reject pool ("don't repeat")
                    previous_successful_attempts = []  # Prior repairs that RESOLVED their target issue -> surfaced to LLM as known-good approaches

                    # Track rejected attempts in THIS iteration (for debugging)
                    current_iteration_rejected = []  # List of {feedback, reason, similarity_score, similar_to_attempt}

                    # Extract current error's symbol for matching
                    current_symbol = ""
                    if current_entry and current_entry.issue and " in " in current_entry.issue:
                        current_symbol = current_entry.issue.split(" in ", 1)[1].strip()

                    # Use index to quickly find iterations with the same symbol,
                    # merged with the IssuePatternTracker's signature matches
                    # (location-independent, so it catches the same error even
                    # when the issue string / symbol extraction differs).
                    matching_iterations = set()
                    if current_symbol:
                        matching_iterations.update(
                            self.context.regression_log.get_iterations_for_symbol(current_symbol)
                        )
                    if current_entry and current_entry.issue_pattern:
                        matching_iterations.update(
                            current_entry.issue_pattern.get('matched_exact_iterations', []) or []
                        )
                        matching_iterations.update(
                            current_entry.issue_pattern.get('matched_root_family_iterations', []) or []
                        )

                    if matching_iterations:
                        # Look through matching iterations (excluding current)
                        for prev_iter in sorted(matching_iterations):
                            if prev_iter >= self.context.iteration.current:
                                continue  # Skip current and future iterations

                            # Get the feedback from that iteration
                            prev_feedback = self.context.artifacts.get_feedback(prev_iter)

                            if prev_feedback and "[REPAIR INSTRUCTIONS]" in prev_feedback:
                                # Get timestamp + resolution status for this iteration from regression log
                                prev_timestamp = None
                                prev_entry = next((e for e in self.context.regression_log.entries if e.iteration_id == prev_iter), None)
                                if prev_entry and hasattr(prev_entry, 'timestamp'):
                                    prev_timestamp = prev_entry.timestamp

                                attempt_record = {
                                    'feedback': prev_feedback,
                                    'changes': f'(From iteration {prev_iter})',
                                    'iteration': prev_iter,
                                    'timestamp': prev_timestamp
                                }

                                # A repair whose target issue was RESOLVED is a known-good
                                # approach, NOT a failure - it must not populate the reject
                                # pool that drives dedup rejection. The same error family can
                                # recur in a different block (a new site, not the same fix
                                # failing), so a proven fix should be re-offered to the LLM,
                                # not forbidden. Only genuinely failed or unconfirmed attempts
                                # (resolved_target_issue is False or None) are "don't repeat".
                                if prev_entry is not None and prev_entry.resolved_target_issue is True:
                                    previous_successful_attempts.append(attempt_record)
                                else:
                                    previous_failed_attempts.append(attempt_record)

                    if previous_failed_attempts:
                        self.logger.log(f"  📋 Loaded {len(previous_failed_attempts)} previously FAILED syntax repair attempt(s) for '{current_symbol}' (reject pool - do not repeat)")
                    if previous_successful_attempts:
                        self.logger.log(f"  ✅ Loaded {len(previous_successful_attempts)} previously RESOLVED syntax repair attempt(s) for '{current_symbol}' (known-good - surfaced to LLM)")

                    while retry_count < max_retries:
                        # Show cross-iteration counter (how many iterations for this same error)
                        if consecutive_count > 1 or total_count > 1:
                            self.logger.log(f"  🔄 Cross-iteration fix attempt: {consecutive_count} consecutive, {total_count} total for this error")
                        
                        # Show per-iteration retry counter (rejected attempts in this iteration)
                        if retry_count > 0:
                            self.logger.log(f"  🔄 Rejected attempts in this iteration: {retry_count}/{max_retries}")
                        
                        self.logger.log(f"  🔄 Generating syntax repair...")

                        # Generate syntax repair instructions
                        feedback = await self.generate_syntax_repair.run(
                            code_snippet=code_snippet,
                            error_message=error_message,
                            alloy_model=alloy_model,
                            previous_failed_attempts=previous_failed_attempts,
                            known_good_attempts=previous_successful_attempts,
                            pattern_status=pattern_status
                        )

                        # Check if feedback is too similar to previous attempts
                        if previous_failed_attempts:
                            from src.utils.regression_log import is_feedback_too_similar, save_rejected_feedback, extract_fix_intent_and_repair_instructions

                            # Extract FIX INTENT + REPAIR INSTRUCTIONS from current feedback
                            current_instructions = extract_fix_intent_and_repair_instructions(feedback)

                            # Extract FIX INTENT + REPAIR INSTRUCTIONS from previous feedback texts
                            previous_feedbacks = [attempt['feedback'] for attempt in previous_failed_attempts]
                            previous_instructions = [extract_fix_intent_and_repair_instructions(fb) for fb in previous_feedbacks]

                            # Check similarity based on FIX INTENT + REPAIR INSTRUCTIONS
                            is_similar, similar_index, similarity_score = is_feedback_too_similar(
                                new_feedback=current_instructions,
                                previous_feedbacks=previous_instructions,
                                threshold=0.85  # Raised from 0.75 to reduce false positives on genuinely different fixes sharing domain vocabulary
                            )

                            # Deterministic guard on top of text similarity:
                            # reject a repair whose NORMALIZED signature (same
                            # operation family on the same target) matches a
                            # previously failed attempt - catches rephrased
                            # repeats that slip under the text threshold
                            if not is_similar:
                                from src.utils.repair_plateau_detector import normalize_repair
                                err_sig = current_entry.error_signature if current_entry else None
                                candidate_sig = normalize_repair(feedback, error_signature=err_sig)['normalized_signature']
                                for prev_idx, prev_fb in enumerate(previous_feedbacks):
                                    prev_sig = normalize_repair(prev_fb, error_signature=err_sig)['normalized_signature']
                                    if prev_sig == candidate_sig:
                                        is_similar, similar_index, similarity_score = True, prev_idx, 1.0
                                        self.logger.log(
                                            f"  ⚠️  Repair signature '{candidate_sig}' matches a "
                                            f"previously failed attempt - rejecting"
                                        )
                                        break

                            if is_similar:
                                # Get metadata about the similar feedback
                                similar_attempt = previous_failed_attempts[similar_index]
                                similar_source = ""
                                similar_timestamp_str = ""
                                
                                if 'iteration' in similar_attempt:
                                    # Similar to feedback from a previous iteration
                                    similar_iteration = similar_attempt['iteration']
                                    if similar_iteration < self.context.iteration.current:
                                        similar_source = f"iteration {similar_iteration}"
                                    else:
                                        similar_source = f"current iteration attempt {similar_index + 1}"
                                    
                                    # Get timestamp of the similar feedback
                                    if 'timestamp' in similar_attempt and similar_attempt['timestamp']:
                                        similar_timestamp_str = similar_attempt['timestamp']
                                elif 'attempt_number' in similar_attempt:
                                    # Similar to feedback from current iteration retry
                                    similar_source = f"current iteration attempt {similar_attempt['attempt_number']}"
                                    
                                    # Get timestamp of the similar feedback
                                    if 'timestamp' in similar_attempt and similar_attempt['timestamp']:
                                        similar_timestamp_str = similar_attempt['timestamp']
                                else:
                                    # Fallback
                                    similar_source = f"previous attempt {similar_index + 1}"
                                
                                # Import datetime for current timestamp
                                from datetime import datetime
                                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                
                                # Build detailed reason with timestamp of the similar feedback and similarity score
                                score_str = f"{similarity_score:.4f}" if similarity_score is not None else "N/A"
                                if similar_timestamp_str:
                                    detailed_reason = f"Too similar to feedback from {similar_source} (created: {similar_timestamp_str}, similarity: {score_str})"
                                else:
                                    detailed_reason = f"Too similar to feedback from {similar_source} (similarity: {score_str})"
                                
                                self.logger.log(f"  ⚠️  {detailed_reason}")
                            
                                # Save rejected feedback
                                save_rejected_feedback(
                                    feedback=feedback,
                                    iteration=self.context.iteration.current,
                                    reason=detailed_reason,
                                    similarity_score=similarity_score,
                                    similar_to_attempt=similar_index + 1
                                )

                                # Track rejected attempt in current iteration
                                current_iteration_rejected.append({
                                    'feedback': feedback,
                                    'reason': detailed_reason,
                                    'similarity_score': similarity_score,
                                    'similar_to_attempt': similar_index + 1,
                                    'similar_source': similar_source,
                                    'similar_timestamp': similar_timestamp_str,
                                    'attempt_number': retry_count + 1,
                                    'timestamp': timestamp
                                })

                                # Add to failed attempts (for next iteration)
                                previous_failed_attempts.append({
                                    'feedback': feedback,
                                    'changes': '(Rejected before execution - too similar)',
                                    'attempt_number': retry_count + 1,
                                    'timestamp': timestamp
                                })

                                retry_count += 1

                                # Check if we've exhausted retries
                                if retry_count >= max_retries:
                                    self.logger.log(f"  ❌ Maximum retries ({max_retries}) reached - asking user for help")
                                    self.logger.log("\n" + "=" * 80)
                                    self.logger.log("The Evaluator has attempted to fix the syntax error 3 times,")
                                    self.logger.log("but all attempts were too similar to previous failed approaches.")
                                    self.logger.log("=" * 80)
                                    
                                    # Display ALL rejected attempts from this iteration
                                    self.logger.log(f"\nAll {len(current_iteration_rejected)} rejected feedback attempts:\n")
                                    for idx, rejected in enumerate(current_iteration_rejected, 1):
                                        self.logger.log(f"\n--- REJECTED ATTEMPT {idx} ---")
                                        self.logger.log(f"Reason: {rejected['reason']}")
                                        self.logger.log(f"\nFeedback:\n{rejected['feedback']}\n")
                                        self.logger.log("-" * 80)
                                    
                                    self.logger.log("=" * 80 + "\n")
                                
                                    user_input = self.cli.request_input(
                                        prompt="Please provide guidance on how to fix the syntax error:",
                                        multiline=True
                                    )

                                    # Log user input request and response
                                    self.logger.log(f"\n⚠️  USER INPUT REQUESTED: All {max_retries} syntax repair attempts rejected (too similar)")
                                    
                                    if user_input and user_input.strip():
                                        # User provided feedback - refine with Evaluator
                                        self.logger.log("  ✓ User feedback received - refining with Evaluator...")

                                        # Log the user's guidance
                                        self.logger.log("USER PROVIDED GUIDANCE:")
                                        self.logger.log("-" * 80)
                                        self.logger.log(user_input)
                                        self.logger.log("-" * 80)

                                        # Call GenerateSyntaxRepairInstruction again with user guidance
                                        draft_feedback = await self.generate_syntax_repair.run(
                                            code_snippet=code_snippet,
                                            error_message=error_message,
                                            alloy_model=alloy_model,
                                            previous_failed_attempts=previous_failed_attempts,
                                            known_good_attempts=previous_successful_attempts,
                                            user_guidance=user_input,
                                            pattern_status=pattern_status
                                        )

                                        self.logger.log("  ✓ Feedback refined based on user guidance")
                                    else:
                                        # User didn't provide feedback - use the last attempt anyway
                                        draft_feedback = feedback
                                        self.logger.log("  ⚠️  No user feedback - using last attempt")
                                        self.logger.log("USER RESPONSE: No guidance provided (using Evaluator's last attempt)")
                                
                                    break
                                else:
                                    # Continue retry loop
                                    self.logger.log(f"  🔄 Retrying with different approach...")
                                    continue

                        # Feedback is different (or first attempt) - accept it
                        self.logger.log(f"  ✓ Feedback accepted (unique approach)")
                        draft_feedback = feedback
                        break

                    # End of retry loop (feedback accepted or max retries hit with user input)

                # For syntax repair, skip Q&A and user review - store feedback directly
                # Store feedback as official
                official_feedback = draft_feedback

                # Record the normalized signature of the prescribed repair so
                # later iterations can detect "same operation on the same
                # target" deterministically (see repair_plateau_detector)
                if current_entry:
                    from src.utils.repair_plateau_detector import normalize_repair
                    current_entry.repair_signature = normalize_repair(
                        official_feedback,
                        error_signature=current_entry.error_signature,
                        strategy=syntax_escalation['strategy']
                    )
                    self.logger.log(
                        f"[DEBUG] Repair signature: "
                        f"{current_entry.repair_signature.get('normalized_signature')}"
                    )

                # Syntax repairs never trigger convergence
                self._store_final_feedback(official_feedback, False, "GenerateSyntaxRepairInstruction")

                self.logger.log("✓ Syntax repair instructions stored")

                # Return early - skip semantic feedback flow
                return {
                    "user_provided_feedback": False,  # No user review for syntax repair (unless max retries hit)
                    "final_convergence": False  # Syntax repairs never trigger convergence
                }

        # SEMANTIC FEEDBACK PATH - Use existing semantic feedback flow
        else:
            print("  ✅ No syntax errors - using semantic feedback path")

            # Deterministically extract diagnostic experiments from InterpretResults
            # up front, so it can be spliced into the final feedback's REPAIR
            # INSTRUCTIONS section regardless of whether GenerateSemanticFeedback or
            # RefineFeedback happen to carry it over on their own.
            diagnostic_text = self._extract_diagnostic_experiments(interpretation)

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

            # Post-analysis chain, step 4 of 4: RepairPlateauDetector (semantic).
            # If unsat predicates / counterexamples have persisted past the
            # SemanticIssueTracker thresholds, force the Evaluator into
            # requirements diagnosis instead of another round of model repair.
            from src.utils.repair_plateau_detector import build_semantic_escalation
            current_entry = self.context.regression_log.get_entry(self.context.iteration.current)
            semantic_escalation = build_semantic_escalation(
                current_iteration=self.context.iteration.current,
                semantic_persistence=current_entry.semantic_issue_persistence if current_entry else None,
                regression_log_entries=self.context.regression_log.entries
            )
            if semantic_escalation['escalation_level'] > 0:
                self.logger.log(
                    f"  🚨 Persistent semantic issue(s) "
                    f"{semantic_escalation['escalated_issues']} - escalation "
                    f"level 3 triggered (strategy decided by evidence alignment below)"
                )
                print(
                    f"  🚨 Persistent issue(s) {semantic_escalation['escalated_issues']} "
                    f"- escalated; running deterministic diagnosis + evidence alignment"
                )
                # Rungs 2-3 of the semantic ladder: before the Evaluator is
                # forced into requirements diagnosis, let the Analyzer answer
                # empirically (scope sweep + fact localization). Appends the
                # measured evidence to the escalation directive.
                self._run_semantic_diagnostics(
                    semantic_escalation,
                    current_entry.semantic_issue_persistence if current_entry else None,
                    alloy_model,
                )
                # Two-key evidence gate: requirements diagnosis stays mandated
                # only when BOTH the InterpretResults causal analysis and the
                # deterministic diagnostics support a requirement-level cause;
                # otherwise the directive is redirected to targeted model
                # repair (MODEL_OVERCONSTRAINT_REPAIR). The alignment verdict
                # is appended to the directive so GenerateSemanticFeedback
                # sees both evidence streams and the binding conclusion.
                from src.utils.repair_plateau_detector import apply_evidence_alignment
                alignment = apply_evidence_alignment(semantic_escalation, interpretation)
                if alignment.get('applied'):
                    self.logger.log(
                        f"[EVIDENCE_ALIGNMENT] strategy={semantic_escalation['strategy']} "
                        f"(interpretation cause: {alignment.get('interpretation_cause')}, "
                        f"diagnostics: {alignment.get('diagnostics_per_issue') or 'not run'}) "
                        f"- {alignment.get('reason')}"
                    )
                    print(
                        f"  ⚖️  Evidence alignment -> {semantic_escalation['strategy']}: "
                        f"{alignment.get('reason')}"
                    )
            if current_entry:
                current_entry.repair_escalation = semantic_escalation
                self.context.regression_log._save_to_file()

            # Generate draft feedback
            draft_feedback = await self.generate_semantic_feedback.run(
                interpretation=interpretation,
                requirements_document=requirements,
                alloy_model=alloy_model,
                relevant_qa=relevant_qa_str,
                persistence_status=semantic_escalation['directive']
            )

            print("✓ Draft feedback generated")

            # Parse new questions from draft feedback
            from src.utils.qa_parser import (
                parse_user_questions,
                parse_qa_updates,
                parse_reused_qids
            )

            new_questions = parse_user_questions(draft_feedback, section_name="UPDATED USER QUESTIONS")

            # Store questions from GenerateSemanticFeedback as pending questions
            if new_questions:
                # Merge with any existing pending questions from InterpretResults
                existing_pending = self.context.artifacts.get_pending_questions(
                    self.context.iteration.current
                ) or []
                all_questions = existing_pending + new_questions
                # Remove duplicates while preserving order
                seen = set()
                unique_questions = []
                for q in all_questions:
                    if q not in seen:
                        seen.add(q)
                        unique_questions.append(q)
                self.context.artifacts.store_pending_questions(
                    self.context.iteration.current,
                    unique_questions
                )
                print(f"  📋 {len(new_questions)} question(s) from semantic feedback added to pending")

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

            # Rung 5 decision gate: escalated semantic issues whose feedback
            # proposes requirement updates need an explicit user decision.
            # The existing review interaction doubles as the gate.
            gate_active = False
            proposed_updates = None
            if semantic_escalation['escalation_level'] > 0:
                proposed_updates = self._extract_requirement_updates(draft_feedback)
                if proposed_updates:
                    gate_active = True
                    print("🚧 REQUIREMENT-CHANGE DECISION GATE (persistent issue escalation)")
                    print("The Evaluator proposes these requirement update(s):\n")
                    print(proposed_updates.strip())
                    print(
                        "\nYour review doubles as the decision: type 'accept' or 'reject', "
                        "provide corrected wording, or press Enter to accept provisionally."
                    )

            # Get user review
            print("Review the feedback above. Provide comments or press Enter to continue:")
            user_review = self.cli.request_input(
                prompt="Provide your review or comments on the feedback:",
                multiline=True
            )

            gate_decision = None
            if gate_active:
                from src.utils.repair_plateau_detector import classify_gate_decision
                gate_decision = classify_gate_decision(user_review)
                self.logger.log(
                    f"[REQUIREMENT_GATE] iter={self.context.iteration.current} "
                    f"decision={gate_decision}"
                )
                print(f"  🚧 Requirement-change decision: {gate_decision}")
                if gate_decision in ('accepted', 'rejected'):
                    # A bare keyword is a gate decision, not review content
                    # for RefineFeedback.
                    user_review = ""

            # Check if user provided meaningful feedback
            if user_review and user_review.strip():
                # Log user review
                self.logger.log("\n" + "=" * 80)
                self.logger.log("USER INPUT - Step 5-6 Feedback Review")
                self.logger.log("=" * 80)
                self.logger.log(user_review)
                self.logger.log("=" * 80 + "\n")

                # Refine feedback based on user review
                print("  Refining feedback based on your input...")
                final_feedback = await self.refine_feedback.run(
                    draft_feedback=draft_feedback,
                    user_review=user_review
                )

                # Safety net: RefineFeedback only guarantees preserving the
                # CONVERGENCE_RECOMMENDATION section, so re-inject diagnostic
                # experiments here in case its rewrite dropped them.
                final_feedback = self._inject_diagnostic_experiments(final_feedback, diagnostic_text)

                # Rung 5: enforce the user's requirement-change decision
                final_feedback = self._apply_requirement_gate(
                    final_feedback, gate_decision, proposed_updates,
                    semantic_escalation, current_entry,
                    qa_index=len(new_questions or []) + 1,
                )

                # Parse final convergence from refined feedback and persist it
                final_convergence = self._parse_convergence(final_feedback)
                if current_entry:
                    from src.utils.repair_plateau_detector import normalize_repair
                    current_entry.repair_signature = normalize_repair(
                        final_feedback,
                        error_signature=current_entry.error_signature,
                        strategy=semantic_escalation['strategy']
                    )
                self._store_final_feedback(final_feedback, final_convergence, "GenerateSemanticFeedback")

                # Record user preference
                self.context.user_preferences.add_preference(
                    preference=f"User review feedback: {user_review}",
                    iteration=self.context.iteration.current,
                    context="Feedback refinement"
                )

                # Create Q&A records if user answered questions
                if new_questions:
                    from src.utils.qa_parser import extract_question_context, parse_user_feedback_for_answers
                    from src.utils.qa_database import QARecord, create_qa_id

                    print(f"  💾 Storing {len(new_questions)} Q&A record(s)...")

                    # Parse user feedback to extract individual answers for each question
                    answer_map = parse_user_feedback_for_answers(user_review, new_questions)

                    for idx, question in enumerate(new_questions, start=1):
                        context = extract_question_context(question)
                        qa_id = create_qa_id(self.context.iteration.current, idx)

                        # Extract individual answer for this question (0-indexed)
                        individual_answer = answer_map.get(idx - 1, user_review)

                        # User answered - mark as confirmed
                        record = QARecord(
                            id=qa_id,
                            iteration=self.context.iteration.current,
                            question=question,
                            answer=individual_answer,  # Individual answer for this question
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
                    self.logger.log("✓ No user feedback provided (timeout) - using draft feedback (Step 5-6)")
                    print("✓ No user feedback provided (timeout) - using draft feedback")
                else:
                    self.logger.log("✓ No user feedback provided - using draft feedback (Step 5-6)")
                    print("✓ No user feedback provided - using draft feedback")

                # Parse preliminary convergence from draft feedback
                preliminary_convergence = self._parse_convergence(draft_feedback)

                # Store draft as official final feedback (no user refinement)
                official_feedback = draft_feedback

                # Safety net: ensure diagnostic experiments from InterpretResults
                # reached REPAIR INSTRUCTIONS even if GenerateSemanticFeedback dropped them.
                official_feedback = self._inject_diagnostic_experiments(official_feedback, diagnostic_text)

                # Rung 5: no user response -> proceed under a provisional
                # assumption (recorded in the Q&A database) or, on a bare
                # 'reject', strip the proposed updates deterministically.
                official_feedback = self._apply_requirement_gate(
                    official_feedback, gate_decision, proposed_updates,
                    semantic_escalation, current_entry,
                    qa_index=len(new_questions or []) + 1,
                )

                if current_entry:
                    from src.utils.repair_plateau_detector import normalize_repair
                    current_entry.repair_signature = normalize_repair(
                        official_feedback,
                        error_signature=current_entry.error_signature,
                        strategy=semantic_escalation['strategy']
                    )
                self._store_final_feedback(official_feedback, preliminary_convergence, "GenerateSemanticFeedback")

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

    def _parse_convergence(self, feedback: str) -> bool:
        """Parse the CONVERGENCE_RECOMMENDATION Status (TRUE/FALSE) from feedback text."""
        import re
        match = re.search(
            r'===\s*CONVERGENCE_RECOMMENDATION\s*===.*?Status:\s*(TRUE|FALSE)',
            feedback,
            re.IGNORECASE | re.DOTALL
        )
        return match.group(1).upper() == "TRUE" if match else False

    def _store_final_feedback(self, feedback: str, final_convergence: bool, action_type: str) -> None:
        """Persist official feedback to artifacts, disk, and the regression log."""
        self.context.artifacts.store_feedback(
            self.context.iteration.current,
            feedback,
            action_type=action_type
        )
        self.context.file_manager.save_feedback(
            {"feedback": feedback, "final_convergence": final_convergence},
            iteration=self.context.iteration.current
        )
        entry = self.context.regression_log.get_entry(self.context.iteration.current)
        if entry:
            entry.evaluator_feedback = feedback
            self.context.regression_log._save_to_file()

    def _store_confirmed_lessons(self, probation_items) -> None:
        """Store lessons whose probation completed (target issue stayed resolved)."""
        for item in probation_items:
            pending = item['pending']
            for lesson_content in pending['lessons']:
                self.context.memory.store(
                    content=lesson_content,
                    item_type='lesson',
                    agent=pending['agent_name'],
                    action=pending['action_name'],
                    iteration=pending['source_iteration']
                )
            self.logger.log(
                f"✅ Lesson from {pending['agent_name']}/{pending['action_name']} "
                f"(iteration {pending['source_iteration']}) confirmed and recorded"
            )

    def _extract_section(
        self,
        text: str,
        section_keywords: str,
        filter_placeholders: bool = True,
    ) -> Optional[str]:
        """
        Extract a named "=== SECTION ===" (or ##/**/numeric variant) block's content
        from LLM-generated text. Supports multiple header formats: ===, ##, **, and
        numeric (N.).

        Args:
            text: Full text containing one or more section blocks
            section_keywords: Regex fragment identifying the section name, e.g.
                r'REQUIREMENT[S]?\s+UPDATE[S]?' or r'Diagnostic\s+experiments\s+recommended'
            filter_placeholders: if True, reject placeholder-only content ("None - ...",
                "N/A", "Not applicable", "No ... needed/required") and require a positive
                content indicator (bullets, numbers, or action verbs + multiple lines)

        Returns:
            The section content, or None if empty/not found/placeholder-only
        """
        import re

        # Pattern to detect the section header in various formats:
        # - === SECTION NAME ===
        # - ## 4. SECTION NAME
        # - **SECTION NAME**
        # - 4. SECTION NAME
        header_pattern = rf'^(?:===|##|\*\*|\d+\.)\s*.*?{section_keywords}.*?(?:===|\*\*)?$'

        lines = text.split('\n')
        header_index = None

        # Find the header line
        for i, line in enumerate(lines):
            if re.match(header_pattern, line.strip(), re.IGNORECASE):
                header_index = i
                break

        if header_index is None:
            return None

        # Extract content from header+1 until next section header
        content_lines = []
        for i in range(header_index + 1, len(lines)):
            line = lines[i]

            # Stop at next section header (starts with ===, ##, **, or "--- ")
            if re.match(r'^(===|##|\*\*|---)\s', line):
                break

            content_lines.append(line)

        content = '\n'.join(content_lines).strip()

        if not content:
            return None

        if not filter_placeholders:
            return content

        # Filter known placeholders using regex patterns
        placeholder_patterns = [
            r'^none\s*[-:–]',           # "None - requirements are clear"
            r'^no\s+.*?\b(needed|required|necessary|applicable|updates?|experiments?|changes?)\b',  # "No requirement updates needed", "No diagnostic experiments necessary"
            r'^n/?a\s*[-:–]',          # "N/A - ..." or "N/A: ..."
            r'^not\s+applicable',       # "Not applicable"
        ]

        content_lower = content.lower()
        for pattern in placeholder_patterns:
            if re.match(pattern, content_lower):
                return None

        # Check for positive indicators of real content
        has_bullets = bool(re.search(r'^\s*[-•*]\s', content, re.MULTILINE))
        has_numbers = bool(re.search(r'^\s*\d+\.', content, re.MULTILINE))
        has_action_verbs = bool(re.search(
            r'\b(Clarify|Add|Update|Remove|Specify|Modify|Define|Include|Test|Relax|Increase|Separate|Simplify)\b',
            content, re.IGNORECASE
        ))
        has_multiple_lines = len([l for l in content.split('\n') if l.strip()]) > 2

        # Return if it has strong indicators of real content
        if has_bullets or has_numbers or (has_action_verbs and has_multiple_lines):
            return content

        # If unsure, return None (conservative - won't create spurious content)
        return None

    def _extract_requirement_updates(self, feedback: str) -> Optional[str]:
        """
        Extract only the REQUIREMENT_UPDATES section from feedback.

        Args:
            feedback: Full feedback with all sections

        Returns:
            Only the REQUIREMENT_UPDATES section content, or None if empty/not found
        """
        return self._extract_section(feedback, r'REQUIREMENT[S]?\s+UPDATE[S]?')

    def _extract_diagnostic_experiments(self, interpretation: str) -> Optional[str]:
        """
        Extract only the "Diagnostic experiments recommended" section from an
        InterpretResults interpretation.

        Args:
            interpretation: Full InterpretResults output

        Returns:
            Only the diagnostic experiments content, or None if empty/not found
            (the common case on iterations with no UNSAT predicates to analyze)
        """
        return self._extract_section(interpretation, r'Diagnostic\s+experiments\s+recommended')

    def _inject_diagnostic_experiments(self, feedback: str, diagnostic_text: Optional[str]) -> str:
        """
        Deterministically splice diagnostic experiments text (extracted from
        InterpretResults) into the REPAIR INSTRUCTIONS section of feedback, as a
        safety net for cases where GenerateSemanticFeedback/RefineFeedback fail to
        carry it over on their own.

        Args:
            feedback: Full feedback text about to be sent to RE
            diagnostic_text: Diagnostic experiments content extracted from
                InterpretResults, or None/empty if there's nothing to inject

        Returns:
            feedback with diagnostic_text appended into REPAIR INSTRUCTIONS (or as a
            trailing section if REPAIR INSTRUCTIONS isn't found), or feedback
            unchanged if diagnostic_text is falsy
        """
        import re

        if not diagnostic_text:
            return feedback

        block = (
            "\n\n--- Diagnostic Experiments (verbatim from InterpretResults, auto-included) ---\n"
            f"{diagnostic_text}"
        )

        lines = feedback.split('\n')
        header_pattern = r'^===\s*REPAIR\s+INSTRUCTIONS\s*==='
        header_index = None
        for i, line in enumerate(lines):
            if re.match(header_pattern, line.strip(), re.IGNORECASE):
                header_index = i
                break

        if header_index is None:
            # Format drift edge case - append as a new trailing section rather than
            # silently dropping the diagnostic experiments.
            self.logger.log("[DEBUG] REPAIR INSTRUCTIONS section not found - appending diagnostic experiments as trailing section")
            return feedback.rstrip() + "\n\n=== DIAGNOSTIC EXPERIMENTS (AUTO-INCLUDED) ===" + block

        # Find the end of the REPAIR INSTRUCTIONS section (next section header, or EOF)
        next_header_index = len(lines)
        for i in range(header_index + 1, len(lines)):
            if re.match(r'^(===|##|\*\*|---)\s', lines[i]):
                next_header_index = i
                break

        new_lines = lines[:next_header_index] + block.split('\n') + lines[next_header_index:]

        print("  ✓ Diagnostic experiments from InterpretResults appended to REPAIR INSTRUCTIONS")
        return '\n'.join(new_lines)

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
        self.logger.log("\n🔨 Step 8: Updating Alloy model...")

        current_model = self.context.artifacts.get_latest_alloy_model()
        feedback = self.context.artifacts.get_latest_feedback()
        requirements = self.context.artifacts.get_latest_requirements()

        # Get previous model for diff calculation
        previous_iteration = self.context.iteration.current - 1
        previous_model = ""
        if previous_iteration > 0:
            previous_model = self.context.artifacts.alloy_models.get(previous_iteration, "")

        # Determine mode based on which action generated the feedback
        # Syntax mode: feedback from GenerateSyntaxRepairInstruction
        # Semantic mode: feedback from GenerateSemanticFeedback
        # NOTE: Feedback was stored in the previous iteration (before next_iteration() was called)
        feedback_action = self.context.artifacts.get_feedback_action_type(previous_iteration)

        import time
        if feedback_action == "GenerateSyntaxRepairInstruction":
            mode = "syntax"
            self.logger.log("  🔧 Mode: Syntax repair (minimal changes)")
            self.logger.log(f"  📝 Feedback source: {feedback_action}")
            self.logger.log("  ⏱️  Waiting 30 seconds for feedback review...")
            time.sleep(30)
            self.logger.log("  ✓ Proceeding with model update")
        else:
            mode = "semantic"
            self.logger.log("  🔧 Mode: Semantic repair (behavior improvements)")
            self.logger.log(f"  📝 Feedback source: {feedback_action or 'GenerateSemanticFeedback (default)'}")

        # Carry the previous iteration's escalation decision (if any) into the
        # RE agent's prompt so it knows which fixes are forbidden / whether the
        # enclosing block must be rewritten instead of minimally patched.
        escalation_directive = ""
        escalation_entry = self.context.regression_log.get_entry(previous_iteration)
        if escalation_entry and escalation_entry.repair_escalation:
            escalation = escalation_entry.repair_escalation
            if escalation.get('escalation_level', 0) > 0:
                escalation_directive = escalation.get('directive', '')
                self.logger.log(
                    f"  🚨 Escalation active for this update: "
                    f"{escalation.get('strategy')} (level {escalation.get('escalation_level')})"
                )
                # A regenerated block must be rebuilt from the REQUIREMENTS,
                # not from the broken model text - syntax mode normally omits
                # the requirements document, so attach it to the directive
                if (escalation.get('strategy') in ('REGENERATE_BLOCK', 'REQUIREMENTS_DIAGNOSIS',
                                                   'REGENERATE_PREDICATES')
                        and escalation_directive):
                    escalation_directive += (
                        "\n\nLATEST REQUIREMENTS (source of truth for the regenerated block):\n"
                        + (requirements or "")
                    )

        updated_model_response = await self.update_model.run(
            current_model=current_model,
            evaluation_feedback=feedback,
            requirements_document=requirements,
            mode=mode,
            escalation_directive=escalation_directive
        )

        self.logger.log("✓ Alloy model updated")

        # Parse regression tracking fields from RE response
        from .utils.regression_log import parse_re_response_for_regression, RegressionLogEntry, VerificationResult

        regression_fields = parse_re_response_for_regression(updated_model_response)

        # Extract the actual model code (after the regression fields) from the
        # ```alloy code block; falls back to the whole response. The shared
        # extractor also fixes the old local regex's edge case that required a
        # newline before the closing fence.
        from src.utils.alloy_model_validator import extract_alloy_code
        updated_model = extract_alloy_code(updated_model_response)

        # Save to file
        model_file = self.context.file_manager.save_alloy_model(
            updated_model,
            iteration=self.context.iteration.current
        )
        print(f"  Saved to: {model_file}")

        # Compute diff using Linux diff command on actual files
        updated_lines = ""
        if previous_iteration >= 0:
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
                # Previous model file not found
                updated_lines = "Initial model (no previous version to compare)"
        else:
            # This shouldn't happen (previous_iteration would be -1)
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
        self.logger.log(f"[DEBUG] Step 8 - Created entry for iteration {self.context.iteration.current}")
        self.logger.log(f"[DEBUG] Total entries in log: {len(self.context.regression_log.entries)}")

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
