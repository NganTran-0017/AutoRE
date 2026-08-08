"""
AutoRE Workflow (V2) - Using SharedRuntimeContext.

Simplified workflow that directly calls actions instead of message passing.
"""
import asyncio
import re
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


# Header for the verbatim InterpretResults experiments carried into every final
# feedback. Its own section, deliberately not part of REPAIR INSTRUCTIONS: the
# safety net guarantees the text survives, the header says it is not adopted work.
DIAGNOSTIC_CANDIDATES_HEADER = (
    "=== DIAGNOSTIC CANDIDATES (verbatim from InterpretResults - NOT adopted) ==="
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
                
                # Discard log entries for iterations the resume is about to redo.
                # Must run AFTER _resume_from_analyzer (which reads the target
                # iteration's regression entry to pick the feedback mode) and
                # BEFORE the repair below, which would otherwise re-analyze
                # models for iterations being discarded.
                self._trim_logs_to_resume_point()

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
                self.context.construct_removal_log.clear()
                self.context.requirement_status.clear()
                self._clear_semantic_memory_for_fresh_start()

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

                # HYBRID CONVERGENCE DECISION: Hard Metrics AND Agent Assessment,
                # AND no requirement update still awaiting verification - a run
                # that converges on a document containing unverified requirements
                # has verified the wrong document.
                if hard_metrics_pass and feedback_result["final_convergence"] \
                        and not self._requirement_probation_blocks_convergence():
                    self.logger.log("\n✅ Verification complete! All criteria met.")
                    self.logger.log("  Hard Metrics: ✓ Passed")
                    self.logger.log("  Agent Assessment: ✓ Converged")
                    self.logger.log("  Requirement updates: ✓ All verified")
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

            # Save copy of construct removal log to Output/ConstructRemovalLog/
            self.context.construct_removal_log.save_copy_to_output()
            self.context.requirement_status.save_copy_to_output()

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
            self.context.construct_removal_log.save_copy_to_output()
            self.context.requirement_status.save_copy_to_output()

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

            # Save copy of construct removal log even on failure
            self.context.construct_removal_log.save_copy_to_output()
            self.context.requirement_status.save_copy_to_output()

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

        # The log is read here (below, for the feedback mode) while still intact.
        # Entries at or after the resume point are trimmed by the caller via
        # _trim_logs_to_resume_point() once this method returns - do not trim
        # earlier, or the get_entry(target_iteration) lookup below loses the
        # entry it needs to tell syntax repair from semantic repair.
        print(f"✓ Regression log loaded with {len(self.context.regression_log.entries)} entries")

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

    def _clear_semantic_memory_for_fresh_start(self) -> None:
        """Start iteration 0 with an empty semantic memory.

        The three audit logs are cleared here; ChromaDB was not, so a "fresh"
        run inherited every lesson, convention and pending suspension from the
        previous one - including probation verdicts whose window no longer
        exists. Contents are snapshotted to Output/ first, since this is the
        only copy. Best-effort: the traditional backend has no collections, and
        an unavailable store must not abort the run.
        """
        memory = getattr(self.context, 'memory', None)
        if memory is None or not hasattr(memory, 'clear_all'):
            return
        try:
            stats = memory.get_stats() if hasattr(memory, 'get_stats') else {}
            memory.clear_all()
            self.logger.log(
                f"[FRESH_START] semantic memory cleared "
                f"({stats.get('total', '?')} items)"
            )
            print(f"  🧹 Semantic memory cleared for fresh start "
                  f"({stats.get('total', '?')} items)")
        except Exception as e:
            self.logger.log(f"[FRESH_START] semantic memory clear skipped: {e}")

    def _discard_future_lesson_conflicts(self, resume_point: int) -> None:
        """Restore lessons suspended at or after the resume point.

        The rerun derives its own lessons and re-decides the contradiction, so
        carrying the old verdict would leave a lesson withdrawn on evidence the
        run has discarded. Best-effort, and biased toward restoring.
        """
        memory = getattr(self.context, 'memory', None)
        if memory is None or not hasattr(memory, 'discard_lesson_conflicts_from'):
            return
        try:
            restored = memory.discard_lesson_conflicts_from(resume_point)
            # isinstance, not truthiness: a Mock context returns a truthy Mock,
            # and this runs before the logger is guaranteed to exist.
            if isinstance(restored, int) and restored > 0:
                print(f"  ↩️  Restored {restored} lesson(s) suspended by a "
                      f"discarded iteration")
        except Exception as e:
            print(f"  ⚠️  lesson conflict reconcile skipped: {e}")

    def _trim_requirement_status(self, resume_point: int) -> None:
        """Forget probation raised at or after the resume point, and reset every
        surviving streak.

        A status recorded at iteration N describes a change the rerun has not
        made yet. Surviving records keep their status but lose their streaks:
        a streak counts consecutive iterations, and the iterations that earned
        it are about to be re-run. Carrying them would let an update reach
        "verified" on evidence the run has discarded - the same failure the
        lesson-conflict discard exists to prevent, and biased the same way
        (toward re-earning, never toward promoting).

        Runs before the log-trim early return: a probation can outlive a run
        even when no log entry does. Uses print, not self.logger - this path
        runs before the logger is guaranteed to exist.
        """
        try:
            statuses = getattr(self.context, "requirement_status", None)
            if statuses is None:
                return
            statuses.save_copy_to_output()   # archive before the tail is lost
            dropped = statuses.trim_to_iteration(resume_point)
            if isinstance(dropped, list) and dropped:
                print(f"  ✂️  Discarded probation for {len(dropped)} requirement(s) "
                      f"changed at/after iteration {resume_point}: {', '.join(dropped)}")
        except Exception as e:
            print(f"  ⚠️  requirement status not trimmed: {e}")

    def _trim_logs_to_resume_point(self) -> None:
        """Drop audit-log entries for iterations the resume is about to redo.

        Resuming to N re-runs iteration N onward, so entries at N or later
        describe a timeline that is about to be rewritten:
          - RegressionLog.add_entry appends unconditionally while get_entry
            returns the FIRST match, so a surviving entry N shadows the fresh
            one for the rest of the run - including update_actual_impact.
          - RequirementPatchLog feeds changed_requirement_ids_since, which
            drives the stale-construct diagnosis; entries from the future
            report requirement changes that have not happened yet.
          - ConstructRemovalLog would tell the Evaluator a construct was
            deleted at an iteration the run has not reached.

        History BEFORE the resume point is untouched - that is the context
        worth preserving. The discarded tail is archived to Output/ first,
        because trimming is otherwise irreversible: resuming backwards to
        inspect a run would destroy the later history for good.
        """
        resume_point = self.context.iteration.current
        logs = (
            ("regression", self.context.regression_log),
            ("requirement patch", self.context.requirement_patch_log),
            ("construct removal", self.context.construct_removal_log),
        )

        # Lesson suspensions follow the same rule as the logs, and are settled
        # BEFORE the early return: a suspension can outlive a run even when no
        # log entry does, and one raised at/after the resume point belongs to a
        # timeline about to be rewritten.
        self._discard_future_lesson_conflicts(resume_point)
        self._trim_requirement_status(resume_point)

        # Duplicate iterations are a separate defect from a future timeline, and
        # they survive trimming because they sit BELOW the resume point. Left in
        # place every lookup answers from the first, stale copy - so collapse
        # them here, where the log is already being reconciled, and say so.
        try:
            collapsed = self.context.regression_log.deduplicate_entries()
            if collapsed:
                msg = (f"  🧹 Collapsed {collapsed} duplicate regression "
                       f"entr{'y' if collapsed == 1 else 'ies'} "
                       f"(one entry per iteration; kept the newest)")
                print(msg)
                self.logger.log(f"[RESUME] {msg.strip()}")
        except Exception as e:
            print(f"  ⚠️  regression log de-duplication skipped: {e}")

        stale = {
            label: sum(1 for e in log.entries if e.iteration_id >= resume_point)
            for label, log in logs
        }
        if not any(stale.values()):
            return

        dropped = ", ".join(f"{n} {label}" for label, n in stale.items() if n)
        print(f"  ✂️  Trimming logs to iteration < {resume_point} (dropping {dropped})")

        for label, log in logs:
            try:
                log.save_copy_to_output()      # archive before the tail is lost
            except Exception as e:
                print(f"  ⚠️  {label} log archive skipped: {e}")
            try:
                log.trim_to_iteration(resume_point)
            except Exception as e:
                print(f"  ⚠️  {label} log not trimmed: {e}")

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

        # Seed the requirement->construct traceability map from the initial model.
        self.context.traceability.rebuild(alloy_model or "")

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
            self._recover_diagnostic_placeholder(entry)
            self.context.regression_log.add_entry(entry)
        
        # Now update the entry with current verification results
        entry.current_result = current_verification

        # Record which assumption predicates (A1, A2, ...) are currently declared as
        # facts, i.e. have been promoted. Derived directly from the model text so the
        # cumulative set stays correct across both promotions and reverts.
        entry.promoted_assumptions = self._scan_promoted_assumptions(model_file)
        if entry.promoted_assumptions:
            self.logger.log(
                f"[DEBUG] Promoted assumptions (facts) in model: {entry.promoted_assumptions}"
            )

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

        # Mode 3 phase 5: the probes have now reported, so they are spent. Stage
        # their deletion before anything else can start treating them as part of
        # the model. A probe that survives its iteration drifts from the scenario
        # it duplicates and quietly answers a question nobody asked.
        self._stage_diagnostic_reissue(entry)
        self._retire_diagnostic_probes(entry)

        # Post-analysis chain, step 3 of 4: SemanticIssueTracker.
        # Track persistence of unsat predicates and assertion counterexamples
        # across syntactically-valid iterations; flags issues that require
        # escalation to requirements diagnosis instead of more model repair.
        entry.semantic_issue_persistence = self.semantic_issue_tracker.run(
            current_iteration=self.context.iteration.current,
            current_result=entry.current_result,
            regression_log_entries=self.context.regression_log.entries,
            current_is_diagnostic=(getattr(entry, "kind", "repair") == "diagnostic"),
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

        # Check if target issue from previous iteration is resolved. A diagnostic
        # iteration attempted no fix, so "did the fix work?" has no answer: it
        # stays None (rendered "n/a") rather than False, which would feed the
        # ladder and read as a failed repair.
        if getattr(entry, "kind", "repair") == "diagnostic":
            entry.resolved_target_issue = None
            self.logger.log(
                "[DEBUG] Resolved target issue: n/a (diagnostic iteration - no fix attempted)"
            )
        else:
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
        # Probation items discarded on oscillation: restore any convention that
        # was provisionally withdrawn (pending_withdrawn -> active), since the
        # fix that motivated its retraction did not stick.
        for item in _discarded_items:
            self.context.learning.revert_convention_retractions(
                item['pending'].get('retractions') or []
            )
            # Same gate for lessons: a lesson that suspended an older,
            # contradicting one loses that claim when its fix does not stick -
            # the older lesson goes back into circulation. Keyed on the lessons
            # themselves, not on the iteration: two lessons written in the same
            # iteration have unrelated fates, and the iteration key let one
            # settle the other's conflict.
            self.context.learning.resolve_lesson_conflicts(
                resolved=False,
                iteration=self.context.iteration.current,
                source_iteration=item['pending'].get('source_iteration'),
                lesson_texts=item['pending'].get('lessons'),
            )

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
                # The fix didn't resolve its target issue - restore any
                # provisionally withdrawn convention (pending_withdrawn -> active)
                # and any lesson suspended by a contradicting one from this source.
                self.context.learning.revert_convention_retractions(
                    pending.get('retractions') or []
                )
                self.context.learning.resolve_lesson_conflicts(
                    resolved=False,
                    iteration=self.context.iteration.current,
                    source_iteration=pending.get('source_iteration'),
                    lesson_texts=pending.get('lessons'),
                )
            setattr(self.context, pending_attr, None)

        # A suspension only ever ends if something reports the outcome it is
        # waiting for, and 8 of the 11 lesson store sites have no outcome to
        # report - no probation item, no fix whose fate could settle it. Bound
        # the wait so a provisional suspension cannot quietly become permanent:
        # past the window the older lesson is restored and both are injected
        # again, which at least makes the contradiction visible.
        expired = self.context.learning.expire_lesson_conflicts(
            self.context.iteration.current
        )
        if expired:
            self.logger.log(
                f"⏱️  {expired} lesson suspension(s) expired unsettled - the "
                f"older lesson(s) restored to active. See "
                f"Output/LessonDedup/decisions.jsonl for both texts."
            )

        # Advance requirement probation on this iteration's evidence: every
        # requirement update - added, reworded or removed - is provisional until
        # the model has been verified WITH it (or, for a removal, without it)
        # for three consecutive analyzed iterations.
        self._advance_requirement_probation(entry)

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
                current_issue=entry.issue,
                kind=getattr(entry, "kind", "repair"),
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

    def _advance_requirement_probation(self, entry) -> None:
        """Credit or debit one iteration of evidence against every requirement
        update still on probation, and act on the ones that reach a verdict.

        Runs in step 4, against the model the Analyzer has just evaluated -
        which is the model step 8 built from the requirements step 7 changed.
        Best-effort: probation bookkeeping must never break the evaluation loop.
        """
        try:
            from src.utils.requirement_status_store import evaluate_probation

            statuses = getattr(self.context, "requirement_status", None)
            if statuses is None:
                return
            self._reconcile_requirement_status(statuses)
            if not statuses.on_probation():
                return

            model_text = self.context.artifacts.get_latest_alloy_model() or ""
            # Rebuild the map against the model in hand: an item's evidence is
            # which constructs encode it NOW, not when it was recorded.
            self.context.traceability.rebuild(model_text)

            result = entry.current_result
            analyzed = bool(result is not None and result.syntax == "OK")
            audit = self.context.ownership_audit or {}
            unowned = list(audit.get('unclassified') or []) + \
                list(audit.get('undeclared_checks') or [])
            blocking = {
                fact
                for diag in (self.context.semantic_diagnostics or {}).values()
                for fact in ((diag or {}).get('localization') or {}).get('blocking_facts') or []
            }

            outcome = evaluate_probation(
                statuses,
                self.context.traceability,
                iteration=self.context.iteration.current,
                model_analyzed=analyzed,
                unsatisfied_predicates=(result.unsatisfied_predicates if result else []),
                counterexamples=(result.counterexamples if result else []),
                blocking_facts=blocking,
                unowned_constructs=unowned,
                removal_blocked=self._blocked_removal_ids(),
            )

            if outcome.get('skipped'):
                self.logger.log(
                    "[REQ_PROBATION] no verdict this iteration - the model did "
                    "not compile, so it is evidence about syntax, not about "
                    "requirement consistency"
                )
                return

            self._settle_probation_outcome(statuses, outcome)
            self._stage_encode_provisional(statuses, outcome, unowned)
        except Exception as e:
            self.logger.log(f"[REQ_PROBATION] skipped (non-fatal): {e}")

    def _stage_encode_provisional(self, statuses, outcome: dict,
                                  unowned: list) -> None:
        """Ask the RE to make an untraceable provisional requirement traceable.

        An item nothing in the model can be traced to accumulates no evidence in
        either direction; it just holds convergence open. So the workflow does
        not wait quietly - it names the item, states which remedy it needs, and
        escalates to the user once the instruction has demonstrably failed
        (`STALLED`, handled by _settle_probation_outcome).
        """
        unencoded_ids = [rid for rid in (outcome.get('unencoded') or [])
                         if statuses.status_of(rid) != "stalled"]
        unannotated_ids = [rid for rid in (outcome.get('unannotated') or [])
                           if statuses.status_of(rid) != "stalled"]
        if not (unencoded_ids or unannotated_ids):
            self.context.pending_encode_provisional = None
            return
        try:
            from src.utils.repair_plateau_detector import build_encode_provisional

            texts = self._requirement_texts(unencoded_ids + unannotated_ids)

            def _entry(rid, candidates=None):
                record = statuses.get(rid)
                item = {
                    "req_id": rid,
                    "text": texts.get(rid, "(text unavailable)"),
                    "streak": record.stall_streak if record else 1,
                }
                if candidates is not None:
                    item["candidates"] = candidates
                return item

            previous = list(
                (getattr(self.context, "pending_encode_provisional", None) or {})
                .get("encode_targets") or []
            ) + list(
                (getattr(self.context, "pending_encode_provisional", None) or {})
                .get("annotate_targets") or []
            )
            directive = build_encode_provisional(
                current_iteration=self.context.iteration.current,
                unencoded=[_entry(r) for r in unencoded_ids],
                unannotated=[_entry(r, unowned) for r in unannotated_ids],
                previous_targets=previous,
            )
            self.context.pending_encode_provisional = (
                directive if directive.get("directive") else None
            )
            if directive.get("directive"):
                self.logger.log(
                    f"[REQ_PROBATION] ENCODE_PROVISIONAL staged - "
                    f"build={directive['encode_targets']}, "
                    f"annotate={directive['annotate_targets']}"
                )
                print(f"  🧭 Untraceable requirement update(s): "
                      f"{', '.join(unencoded_ids + unannotated_ids)} "
                      f"- asking the RE to make them traceable")
        except Exception as e:
            self.logger.log(f"[REQ_PROBATION] encode directive skipped: {e}")

    def _requirement_texts(self, req_ids: list) -> dict:
        """Current text of each requirement, for the encode directive."""
        out = {}
        try:
            from src.utils.requirements_store import parse_requirements_document

            doc = parse_requirements_document(
                self.context.artifacts.get_latest_requirements() or "")
            for rid in req_ids:
                item = doc.find_item(rid)
                if item is not None:
                    out[rid] = " ".join(item.raw.split())
        except Exception:
            pass
        return out

    def _requirement_probation_blocks_convergence(self) -> bool:
        """Withhold convergence while any requirement update is unverified.

        Everything else about the run can be green while the document still
        contains a requirement nobody has verified is consistent with the rest -
        which is exactly the state this mechanism exists to make visible.

        The user can override: they are shown what is outstanding and asked. The
        override matters as much as the gate, because probation runs three
        iterations past the last requirement change, and a run whose
        requirements keep changing would otherwise never be allowed to finish.
        """
        try:
            from src.utils.requirement_status_store import format_outstanding

            statuses = getattr(self.context, "requirement_status", None)
            if statuses is None:
                return False
            outstanding = statuses.outstanding_items()
            if not outstanding:
                return False

            report = format_outstanding(outstanding)
            self.logger.log(f"[REQ_PROBATION] convergence withheld:\n{report}")
            print("\n⏸️  Convergence withheld - unverified requirement updates:")
            print(report)
            print(
                "\nThese have not completed verification. Continue refining "
                "(recommended), or type 'converge' to finish anyway and accept "
                "them as they stand."
            )
            answer = self.cli.request_input(
                prompt="Press Enter to keep refining, or type 'converge' to finish:",
                multiline=False,
            )
            if (answer or "").strip().lower().startswith("converge"):
                self.logger.log(
                    "[REQ_PROBATION] user overrode the gate - converging with "
                    f"{len(outstanding)} unverified update(s)"
                )
                print("  ⚠️  Converging with unverified requirement updates (user override)")
                return False
            return True
        except Exception as e:
            # A gate that cannot be evaluated must not be able to hang the run.
            self.logger.log(f"[REQ_PROBATION] convergence gate skipped: {e}")
            return False

    def _screen_requirement_conflicts(self, feedback: str):
        """Triage bucket 6: candidates that cannot coexist with a live item.

        A CONTRADICTS verdict is a CLAIM, not a finding. Nothing here consulted
        the solver: it is the Evaluator's reading of two pieces of English. So
        neither mode acts on it - the update is applied, goes on probation like
        any other, and VERIFICATION decides whether the two requirements can
        actually hold together. That is the evidence the claim was standing in
        for, and it arrives one iteration later.

        The modes differ only in who is told:
          - OBSERVE - recorded to the shadow log, nothing shown.
          - ACTIVE  - recorded, and flagged to the user as information, with
                      the claimed IDs attached to the update once it lands so
                      the contest can cite them if verification bears it out.

        Returns (feedback, notices). The feedback is returned UNCHANGED in both
        modes. Withholding the updates section on a claim meant the cost of a
        wrong claim was a discarded requirement, paid before anything had
        checked whether the conflict was real.
        """
        try:
            from src.utils.requirement_status_store import (
                conflict_key,
                format_conflict_notices,
                log_conflict_shadow,
                parse_conflict_declarations,
                validate_conflicts,
            )
            from src.utils.requirements_store import parse_requirements_document

            declared = parse_conflict_declarations(feedback)
            if not declared:
                return feedback, []

            requirements = self.context.artifacts.get_latest_requirements() or ""
            live = parse_requirements_document(requirements).all_item_ids()
            split = validate_conflicts(declared, live)
            accepted, downgraded = split["accepted"], split["downgraded"]

            mode = getattr(self.context, "requirement_conflict_mode", "observe")
            iteration = self.context.iteration.current
            log_conflict_shadow(accepted, mode, iteration, "contradicts")
            log_conflict_shadow(downgraded, mode, iteration, "downgraded")

            for entry in downgraded:
                self.logger.log(
                    f"[REQ_CONFLICT] downgraded to UNSURE - {entry['downgrade_reason']}"
                )
            # A conflict already settled once is not news a second time. The
            # detector re-runs every iteration with no memory of the outcome,
            # so this set is the only thing that stops it repeating itself.
            settled = self._acknowledged_conflicts()
            fresh = [e for e in accepted
                     if conflict_key(e["conflicts_with"]) not in settled]
            for entry in fresh:
                self.logger.log(
                    f"[REQ_CONFLICT] {mode}: {entry['affected']!r} vs "
                    f"{', '.join(entry['conflicts_with'])}"
                )
            if not fresh:
                return feedback, []
            if mode != "active":
                print(f"  👁️  Contradiction recorded (observe mode, not shown): "
                      f"{len(fresh)} candidate(s)")
                return feedback, []

            # Held for step 7, which attaches the claimed IDs to the update
            # once the patch gives it one - that record is what lets a later
            # contest say WHICH requirement this one was said to displace.
            self.context.pending_requirement_conflicts = fresh
            return feedback, format_conflict_notices(fresh)
        except Exception as e:
            self.logger.log(f"[REQ_CONFLICT] screening skipped (non-fatal): {e}")
            return feedback, []

    def _acknowledged_conflicts(self) -> set:
        """Conflict sets the user has already decided, memory plus store.

        Read from the store on every screening rather than seeded once at
        startup: the in-memory set is the fast path, the store is the one that
        survives a restart, and unioning at the point of use means no ordering
        between "the store loaded" and "the first conflict was screened" can
        make a decided conflict come back.
        """
        in_memory = getattr(self.context, "acknowledged_conflicts", None)
        keys = set(in_memory) if isinstance(in_memory, set) else set()
        try:
            statuses = getattr(self.context, "requirement_status", None)
            if statuses is not None:
                keys |= statuses.acknowledged_conflict_keys()
        except Exception as e:
            self.logger.log(f"[REQ_CONFLICT] stored acknowledgements unreadable: {e}")
        return keys

    def _attach_declared_conflicts(self) -> None:
        """Record which existing items an update was CLAIMED to contradict.

        Runs after the patch, because the update has no ID until then. The
        claim is stored on the update itself (`conflicts_with`, not
        acknowledged - nothing has confirmed it), and it is what lets a later
        contest say WHICH requirement this one was said to displace instead of
        asking the user to remember an iteration ago.

        Only an unambiguous attachment is made. The claim names the candidate
        in prose, so it is matched to an applied ID when the prose contains one
        and otherwise only when the iteration applied exactly one update -
        attaching it to the wrong item would later supersede a requirement that
        was never in the conflict.
        """
        pending = getattr(self.context, "pending_requirement_conflicts", None)
        if not isinstance(pending, list) or not pending:
            return
        self.context.pending_requirement_conflicts = []
        try:
            statuses = self.context.requirement_status
            iteration = self.context.iteration.current
            applied = self.context.requirement_patch_log.changed_requirement_ids(
                iteration, ops=("ADD", "MODIFY"))
            if not applied:
                self.logger.log(
                    "[REQ_CONFLICT] claim not attached - the update it referred "
                    "to was not applied this iteration"
                )
                return
            for entry in pending:
                claimed = entry.get("conflicts_with") or []
                target = self._claim_target(entry, applied, claimed)
                if target is None:
                    self.logger.log(
                        f"[REQ_CONFLICT] claim against {', '.join(claimed)} not "
                        f"attached - {len(applied)} updates applied and none "
                        f"named; a contest cannot cite it"
                    )
                    continue
                statuses.note_conflict(target, claimed, acknowledged=False,
                                       iteration=iteration)
                self.logger.log(
                    f"[REQ_CONFLICT] {target} carries a claim against "
                    f"{', '.join(claimed)} - unverified, to be settled by the solver"
                )
        except Exception as e:
            self.logger.log(f"[REQ_CONFLICT] claim attachment skipped: {e}")

    @staticmethod
    def _claim_target(entry: dict, applied: list, claimed: list) -> Optional[str]:
        """Which applied update a contradiction claim was about, or None."""
        candidates = [rid for rid in applied if rid not in set(claimed)]
        if not candidates:
            return None
        named = f"{entry.get('affected') or ''} {entry.get('recommended') or ''}"
        for rid in candidates:
            if re.search(rf"\b{re.escape(rid)}\b", named):
                return rid
        return candidates[0] if len(candidates) == 1 else None

    def _pending_decisions(self, statuses, status: str, attr: str) -> list:
        """The queue for one terminal status, derived from the store.

        The status file persists across a resume but the in-memory queue does
        not, and an item in a terminal status has already left the probation
        pool - so rebuilding the queue from the store is the only thing that
        stops a restart from stranding it there forever, blocking convergence
        with no question left to answer.
        """
        queued = list(getattr(self.context, attr, None) or [])
        queued = [e for e in queued if isinstance(e, dict) and e.get("req_id")]
        known = {e["req_id"] for e in queued}
        missing = [e for e in statuses.outstanding_items()
                   if e.status == status and e.req_id not in known]
        if missing:
            texts = self._requirement_texts([e.req_id for e in missing])
            for entry in missing:
                queued.append({
                    "req_id": entry.req_id,
                    "reason": self._contest_reason(statuses, entry.req_id, entry.reason),
                    "op": entry.op,
                    "text": texts.get(entry.req_id, ""),
                    "conflicts_with": list(entry.conflicts_with or []),
                })
        setattr(self.context, attr, queued)
        return queued

    def _pending_contests(self, statuses) -> list:
        from src.utils.requirement_status_store import CONTESTED

        return self._pending_decisions(
            statuses, CONTESTED, "pending_requirement_contests")

    def _pending_stalls(self, statuses) -> list:
        from src.utils.requirement_status_store import STALLED

        return self._pending_decisions(
            statuses, STALLED, "pending_requirement_stalls")

    def _resolve_requirement_contests(self) -> None:
        """Ask what to do about each contested update, and record the answer.

        Asked on its own input rather than folded into the feedback review: the
        vocabulary is `revert` / `keep`, not the gate's accept/reject, and one
        box cannot carry two decisions. This is the highest-priority question of
        the iteration - the solver has produced evidence against a requirement
        the user put there.

        `keep` clears the contest and leaves the document alone; `revert` stages
        the document edit for step 7. Silence decides nothing and the item is
        raised again next iteration.
        """
        try:
            from src.utils.requirement_status_store import (
                CONTESTED,
                format_contest_questions,
                parse_contest_resolution,
            )

            statuses = getattr(self.context, "requirement_status", None)
            if statuses is None:
                return
            pending = self._pending_contests(statuses)
            if not pending:
                return

            print("\n⚖️  CONTESTED REQUIREMENT UPDATE(S)")
            print("Verification implicated an update that has not yet been "
                  "confirmed. Reverting undoes it in the document; keeping "
                  "leaves it in place and clears the contest.")
            for question in format_contest_questions(pending):
                print(f"  {question}")
            answer = self.cli.request_input(
                prompt="Revert or keep each contested update "
                       "(e.g. 'revert R7', 'keep', or press Enter to decide later):",
                multiline=False,
            )
            ids = [e["req_id"] for e in pending if isinstance(e, dict) and e.get("req_id")]
            decision = parse_contest_resolution(answer, ids)
            if not (decision["revert"] or decision["keep"]):
                self.logger.log(
                    f"[REQ_CONTEST] undecided, still contested: {', '.join(ids)}")
                print("  ⏸️  Undecided - the contest stands and will be raised again.")
                return

            for req_id in decision["keep"]:
                statuses.restore(req_id)
                self.logger.log(f"[REQ_CONTEST] {req_id} kept - contest cleared")
                print(f"  ✅ {req_id}: kept; the update stands.")
                # Keeping an update the solver implicated over a requirement it
                # was claimed to contradict IS the decision the conflict was
                # waiting for - and now it rests on evidence rather than on the
                # Evaluator's reading. The item it displaces has to give way,
                # or the same failure returns every iteration.
                self._stage_conflict_supersession(req_id, statuses)
            staged = list(getattr(self.context, "pending_requirement_reverts", None) or [])
            for req_id in decision["revert"]:
                staged.append(req_id)
                self.logger.log(f"[REQ_CONTEST] {req_id} revert requested")
                print(f"  ↩️  {req_id}: will be reverted in the document.")
            self.context.pending_requirement_reverts = staged
            decided = set(decision["revert"]) | set(decision["keep"])
            self.context.pending_requirement_contests = [
                e for e in pending if e.get("req_id") not in decided
            ]
        except Exception as e:
            self.logger.log(f"[REQ_CONTEST] resolution skipped (non-fatal): {e}")

    def _resolve_requirement_stalls(self) -> None:
        """Ask what to do about a requirement nothing could encode.

        Three iterations of explicit directives produced no traceable construct.
        That is the point at which the run stops guessing: it is evidence the
        requirement may be unmodelable as stated, and only the user can say
        whether the text or the modeller is at fault.

        Until this existed a stalled item sat forever, blocking convergence with
        nothing offering a way out - the same dead end a contest used to be.

        `reword` sends it to the Evaluator as a REQUIREMENTS_DIAGNOSIS; `drop`
        removes it through the ordinary deferred path; `wait` grants another
        window. Silence decides nothing, as everywhere else.
        """
        try:
            from src.utils.requirement_status_store import (
                format_stall_questions,
                parse_stall_resolution,
            )

            statuses = getattr(self.context, "requirement_status", None)
            if statuses is None:
                return
            pending = self._pending_stalls(statuses)
            if not pending:
                return

            print("\n🚧  REQUIREMENT(S) THE MODEL COULD NOT ENCODE")
            print("Three iterations of encoding directives produced nothing "
                  "traceable. This is evidence about the requirement text, not "
                  "only about the model.")
            for question in format_stall_questions(pending):
                print(f"  {question}")
            answer = self.cli.request_input(
                prompt="Reword, drop, or wait for each stalled requirement "
                       "(e.g. 'reword R7', 'drop R8', or press Enter to decide later):",
                multiline=False,
            )
            ids = [e["req_id"] for e in pending if isinstance(e, dict) and e.get("req_id")]
            decision = parse_stall_resolution(answer, ids)
            if not any(decision.values()):
                self.logger.log(f"[REQ_STALL] undecided, still stalled: {', '.join(ids)}")
                print("  ⏸️  Undecided - the stall stands and will be raised again.")
                return

            by_id = {e["req_id"]: e for e in pending if isinstance(e, dict)}
            for req_id in decision["wait"]:
                statuses.resume_probation(req_id)
                self.logger.log(f"[REQ_STALL] {req_id} given another window")
                print(f"  ⏭️  {req_id}: back on probation for another 3 iterations.")
            staged = list(getattr(self.context, "pending_deferred_removals", None) or [])
            for req_id in decision["drop"]:
                staged.append({
                    "req_id": req_id,
                    "because": "dropped after three iterations with no encoding",
                    "by": "",
                })
                self.logger.log(f"[REQ_STALL] {req_id} drop requested")
                print(f"  🗑️  {req_id}: will be removed (deferred, revertible).")
            self.context.pending_deferred_removals = staged
            diagnose = [by_id[r] for r in decision["reword"] if r in by_id]
            if diagnose:
                queued = list(getattr(self.context, "pending_requirement_diagnosis", None) or [])
                self.context.pending_requirement_diagnosis = queued + diagnose
                for entry in diagnose:
                    statuses.resume_probation(entry["req_id"])
                    self.logger.log(f"[REQ_STALL] {entry['req_id']} sent for diagnosis")
                    print(f"  🔍 {entry['req_id']}: the Evaluator will diagnose the "
                          f"wording next iteration.")
            decided = {r for ids_ in decision.values() for r in ids_}
            self.context.pending_requirement_stalls = [
                e for e in pending if e.get("req_id") not in decided
            ]
        except Exception as e:
            self.logger.log(f"[REQ_STALL] resolution skipped (non-fatal): {e}")

    def _stage_stall_diagnosis(self, semantic_escalation: dict) -> None:
        """Deliver a stalled requirement's diagnosis through the escalation
        channel the Evaluator already reads.

        A requirement that resists encoding for three iterations is exactly what
        REQUIREMENTS_DIAGNOSIS means, so it travels the same way rather than
        through a second mechanism. Delivered once and cleared: repeating it
        every iteration would re-diagnose wording the Evaluator has answered.
        """
        pending = getattr(self.context, "pending_requirement_diagnosis", None)
        if not isinstance(pending, list) or not pending:
            return
        try:
            from src.utils.repair_plateau_detector import (
                build_unmodelable_requirement_diagnosis,
            )

            directive = build_unmodelable_requirement_diagnosis(
                current_iteration=self.context.iteration.current,
                items=pending,
            )
            self.context.pending_requirement_diagnosis = []
            if not directive:
                return
            existing = semantic_escalation.get('directive') or ""
            semantic_escalation['directive'] = (
                f"{existing}\n\n{directive}" if existing else directive)
            if not semantic_escalation.get('escalation_level'):
                semantic_escalation['escalation_level'] = 3
            self.logger.log(
                f"[REQ_STALL] diagnosis delivered for "
                f"{', '.join(e['req_id'] for e in pending)}"
            )
            print(f"  🔍 Requirements diagnosis requested for "
                  f"{', '.join(e['req_id'] for e in pending)}")
        except Exception as e:
            self.logger.log(f"[REQ_STALL] diagnosis staging skipped: {e}")

    def _perform_requirement_reverts(self, requirements: str) -> str:
        """Undo a contested update in the document and realign the model.

        A revert is not only a text edit. A reverted ADD leaves constructs that
        now encode nothing; a reverted MODIFY leaves constructs encoding wording
        the document no longer carries. Both are staged as a REVERT_REQUIREMENT
        directive for step 8 - without it the document and the model disagree
        and nothing downstream notices.

        Returns the document text to continue with (unchanged when nothing was
        due, or when no revert could be performed).
        """
        pending = getattr(self.context, "pending_requirement_reverts", None)
        if not isinstance(pending, list) or not pending or not requirements:
            return requirements
        try:
            from src.utils.repair_plateau_detector import build_requirement_revert
            from src.utils.requirement_status_store import PENDING_REMOVAL
            from src.utils.requirements_store import remove_item, replace_item

            statuses = self.context.requirement_status
            traceability = getattr(self.context, "traceability", None)
            text = requirements
            deleted, restored = [], []

            for req_id in pending:
                record = statuses.get(req_id)
                if record is None:
                    self.logger.log(f"[REQ_CONTEST] {req_id} revert skipped - no record")
                    continue
                try:
                    constructs = (traceability.constructs_for([req_id])
                                  if traceability else [])
                except Exception:
                    constructs = []

                if record.status == PENDING_REMOVAL:
                    # Nothing to put back in the document - a deferred removal
                    # never took the text out. What was lost is the ENCODING,
                    # so the revert is entirely model-side.
                    statuses.restore(req_id)
                    restored.append({
                        "req_id": req_id,
                        "text": self._requirement_texts([req_id]).get(req_id, ""),
                        "constructs": constructs,
                    })
                    self.logger.log(
                        f"[REQ_CONTEST] {req_id} removal reverted - the item stands "
                        f"and its encoding must be rebuilt")
                elif record.op == "ADD":
                    result = remove_item(text, req_id)
                    if not result["removed"]:
                        self.logger.log(
                            f"[REQ_CONTEST] {req_id} revert skipped - not in the document")
                        continue
                    text = result["text"]
                    statuses.supersede(req_id)
                    deleted.append({"req_id": req_id, "text": "",
                                    "constructs": constructs})
                    restored.extend(self._restore_displaced(req_id, statuses))
                else:
                    # MODIFY / MODIFY-SECTION: roll back to the wording the
                    # status store kept from the patch log's `before`.
                    if not (record.prior_text or "").strip():
                        self.logger.log(
                            f"[REQ_CONTEST] {req_id} revert skipped - no prior text kept")
                        continue
                    result = replace_item(text, req_id, record.prior_text)
                    if not result["replaced"]:
                        self.logger.log(
                            f"[REQ_CONTEST] {req_id} revert skipped - not in the document")
                        continue
                    text = result["text"]
                    statuses.restore(req_id)
                    restored.append({
                        "req_id": req_id,
                        "text": " ".join(record.prior_text.split()),
                        "constructs": constructs,
                    })
                    restored.extend(self._restore_displaced(req_id, statuses))

            self.context.pending_requirement_reverts = []
            if not (deleted or restored):
                return requirements

            directive = build_requirement_revert(
                current_iteration=self.context.iteration.current,
                deleted=deleted,
                restored=restored,
            )
            self.context.pending_revert_directive = (
                directive if directive.get("directive") else None
            )

            iteration = self.context.iteration.current
            self.context.artifacts.store_requirements(iteration, text)
            self.context.file_manager.save_requirements(text, iteration=iteration)
            reverted = [e["req_id"] for e in deleted + restored]
            self.logger.log(
                f"[REQ_CONTEST] reverted: {reverted}; "
                f"delete={directive['remove_targets']}, "
                f"regenerate={directive['regenerate_targets']}"
            )
            print(f"  ↩️  Reverted in the document: {', '.join(reverted)}")
            return text
        except Exception as e:
            self.logger.log(f"[REQ_CONTEST] revert failed (non-fatal): {e}")
            return requirements

    def _stage_conflict_supersession(self, req_id: str, statuses) -> None:
        """Settle a contradiction claim in favour of the update that survived it.

        Reached only from a contest the user resolved with `keep`, which means
        two independent things now agree: the Evaluator claimed the two cannot
        coexist, and the solver produced a failure consistent with that. The
        loser goes to PENDING_REMOVAL rather than out - deferred, so the
        decision is still reviewable and revertible.

        The link is exact here. The conflict is settled against a named,
        already-applied requirement, so there is no guessing about which update
        displaced which item - the ambiguity that made this unsafe to do at
        claim time.
        """
        from src.utils.requirement_status_store import conflict_key

        record = statuses.get(req_id)
        losers = list(record.conflicts_with) if record else []
        if not losers:
            return
        staged = getattr(self.context, "pending_deferred_removals", None)
        staged = list(staged) if isinstance(staged, list) else []
        known = {e["req_id"] for e in staged if isinstance(e, dict)}
        iteration = self.context.iteration.current
        for loser in losers:
            if loser in known:
                continue
            staged.append({
                "req_id": loser,
                "because": f"{req_id} was kept over it after verification",
                "by": req_id,
            })
        self.context.pending_deferred_removals = staged
        # Settled: the claim has had its answer, so stop reporting it.
        if not isinstance(getattr(self.context, "acknowledged_conflicts", None), set):
            self.context.acknowledged_conflicts = set()
        self.context.acknowledged_conflicts.add(conflict_key(losers))
        try:
            statuses.acknowledge_conflict(losers, iteration=iteration)
        except Exception as e:
            self.logger.log(f"[REQ_CONFLICT] settlement not persisted: {e}")
        self.logger.log(
            f"[REQ_CONFLICT] settled by verification: {req_id} stands, "
            f"{', '.join(losers)} → pending removal"
        )
        print(f"  ⚖️  {', '.join(losers)}: superseded by {req_id}; text kept for "
              f"review, encoding deleted, revertible while on probation.")

    def _contest_reason(self, statuses, req_id: str, reason: str) -> str:
        """The contest reason, plus what else a revert would bring back.

        A user deciding whether to undo an update needs to know it displaced
        another requirement - otherwise 'revert' looks like it removes one
        thing when it in fact restores two.
        """
        try:
            displaced = [e.req_id for e in statuses.displaced_by(req_id)]
            record = statuses.get(req_id)
            claimed = list(record.conflicts_with) if record else []
        except Exception:
            return reason
        if displaced:
            return (f"{reason} (reverting also restores {', '.join(displaced)}, "
                    f"currently pending removal)")
        if claimed:
            # The forward direction: the user is deciding a contradiction as
            # well as a contest, and needs to know keeping has a second effect.
            return (f"{reason}; the Evaluator flagged it as contradicting "
                    f"{', '.join(claimed)}, so keeping it puts "
                    f"{', '.join(claimed)} into pending removal")
        return reason

    def _restore_displaced(self, req_id: str, statuses) -> list:
        """Undo the supersessions that only held while `req_id` did.

        R2 was put into pending removal because the user accepted an update
        over it. Undoing that update and leaving R2 removed would enact half of
        a decision whose other half has just been withdrawn - the document
        would end up with neither requirement.

        Returns `restored` entries for the revert directive: their text never
        left the document, but their constructs were deleted, so the model side
        is a rebuild.
        """
        out = []
        try:
            displaced = statuses.displaced_by(req_id)
        except Exception:
            return out
        for entry in displaced:
            statuses.restore(entry.req_id)
            # Step 4 can schedule the deletion in the very iteration whose
            # step 5-6 revokes its cause, and step 7 performs deletions BEFORE
            # reverts - so without this the item is deleted from the document
            # a moment after being restored, and the restore silently loses.
            scheduled = getattr(self.context, "pending_requirement_deletions", None)
            if isinstance(scheduled, list) and entry.req_id in scheduled:
                self.context.pending_requirement_deletions = [
                    r for r in scheduled if r != entry.req_id
                ]
                self.logger.log(
                    f"[REQ_CONTEST] {entry.req_id} deletion cancelled - its "
                    f"supersession was reverted in the same iteration"
                )
            out.append({
                "req_id": entry.req_id,
                "text": self._requirement_texts([entry.req_id]).get(entry.req_id, ""),
                "constructs": [],
            })
            self.logger.log(
                f"[REQ_CONTEST] {entry.req_id} restored - the update that "
                f"superseded it ({req_id}) was reverted"
            )
            print(f"  ↩️  {entry.req_id}: restored; it was only superseded by {req_id}.")
        return out

    def _perform_staged_removals(self, requirements: str) -> list:
        """Put the losing side of an accepted conflict into pending removal.

        The user answered "accept the update and supersede R2". That is two
        operations, and only one of them was ever performed: without this, R2
        stays in force while its replacement is added, both get encoded, and
        the document holds the contradiction the triage was raised to prevent.

        It is a DEFERRED removal, the same shape the Evaluator's own REMOVE
        takes: R2's text stays in the document marked PENDING REMOVAL while its
        Alloy constructs are deleted. That is what keeps the supersession
        reviewable and revertible - the text is still there to restore, and
        three verified iterations have to pass before it finally goes.

        The document is NOT edited here (the marker comes from the store), so
        this returns the superseded IDs rather than text. The patch-log entry
        is what carries the removal into `changed_requirement_ids`, which is
        what stages the construct deletion for step 8.
        """
        pending = getattr(self.context, "pending_deferred_removals", None)
        if not isinstance(pending, list) or not pending or not requirements:
            return []
        try:
            from src.utils.requirements_store import parse_requirements_document
            from src.utils.requirement_patch_log import RequirementPatchLogEntry

            statuses = self.context.requirement_status
            iteration = self.context.iteration.current
            doc = parse_requirements_document(requirements)
            superseded, changes = [], []

            for record in pending:
                req_id = (record or {}).get("req_id")
                item = doc.find_item(req_id) if req_id else None
                if item is None:
                    self.logger.log(
                        f"[REQ_CONFLICT] supersession of {req_id} skipped - "
                        f"not in the document"
                    )
                    continue
                because = (record.get("because") or "").strip()
                statuses.record_change(
                    req_id=req_id,
                    op="REMOVE",
                    iteration=iteration,
                    # The revert target. Without it a restored supersession
                    # would have nothing to put back.
                    prior_text=item.raw,
                    provenance="conflict-supersession",
                    reason=(because or "superseded after verification"),
                )
                # Exact, because the contest named it - this is what a later
                # revert of the surviving update follows back.
                statuses.link_supersession(req_id, (record or {}).get("by") or "")
                superseded.append(req_id)
                changes.append({"op": "REMOVE", "target": req_id,
                                "before": item.raw, "after": ""})

            self.context.pending_deferred_removals = []
            if not superseded:
                return []

            # Logged as a patch attempt like any other, so the removal is
            # auditable next to the ops the Evaluator authored - and so the
            # stale-construct staging finds it.
            self.context.requirement_patch_log.add_entry(RequirementPatchLogEntry(
                iteration_id=iteration,
                raw_response="(workflow) conflict supersession accepted by the user",
                ops_requested=[{"op": "REMOVE", "target": r} for r in superseded],
                applied=[f"REMOVE {r}" for r in superseded],
                changes=changes,
                changed=True,
            ))
            self.logger.log(
                f"[REQ_CONFLICT] superseded (pending removal, deferred): {superseded}"
            )
            print(f"  ⚖️  Pending removal: {', '.join(superseded)} - text kept for "
                  f"review, encoding deleted, revertible for 3 iterations")
            return superseded
        except Exception as e:
            self.logger.log(f"[REQ_CONFLICT] supersession failed (non-fatal): {e}")
            return []

    def _reconcile_requirement_status(self, statuses) -> None:
        """Drop probation records for IDs the document no longer contains.

        The store is derived state and drifts if a document changes by any path
        other than UpdateRequirements. The drop is LOGGED rather than silent:
        a status that vanished and a status that was confirmed both leave an
        item unmarked, and only the log distinguishes them.
        """
        try:
            from src.utils.requirements_store import parse_requirements_document

            requirements = self.context.artifacts.get_latest_requirements() or ""
            if not requirements.strip():
                return
            doc = parse_requirements_document(requirements)
            dropped = statuses.reconcile(doc.all_item_ids())
            if dropped:
                self.logger.log(
                    f"[REQ_STATUS] reconciled away (no longer in the document): "
                    f"{', '.join(dropped)}"
                )
        except Exception as e:
            self.logger.log(f"[REQ_STATUS] reconcile skipped: {e}")

    def _blocked_removal_ids(self) -> set:
        """Requirement IDs whose construct deletion the pruner could not perform.

        A prune blocked because a surviving construct still references the
        target means the removal was never actually tested - crediting a clean
        iteration for it would confirm a removal that never happened.
        """
        ids = set()
        try:
            log = self.context.construct_removal_log
            entries = [e for e in log.entries
                       if e.iteration_id >= self.context.iteration.current - 1]
            for entry in entries:
                for construct in (entry.blocked or {}):
                    ids.update(self.context.traceability.requirements_for(construct))
        except Exception:
            return set()
        return ids

    def _settle_probation_outcome(self, statuses, outcome: dict) -> None:
        """Apply the document-level consequences of a probation round."""
        from src.utils.requirement_status_store import PENDING_REMOVAL

        for req_id in outcome.get('confirmed') or []:
            record = statuses.get(req_id)
            if record is not None and record.status == PENDING_REMOVAL:
                # The model has been verified without this requirement's
                # encoding for the full window: perform the deferred deletion.
                self.context.pending_requirement_deletions.append(req_id)
                self.logger.log(f"[REQ_PROBATION] {req_id} removal verified - "
                                f"scheduling deletion from the document")
                print(f"  🗑️  {req_id}: removal verified - will be deleted")
            else:
                statuses.confirm(req_id)
                self.logger.log(f"[REQ_PROBATION] {req_id} verified - now official")
                print(f"  ✅ {req_id}: verified over 3 iterations - now official")

        contested = outcome.get('contested') or []
        if contested:
            # Staged rather than acted on: a contest is the user's decision, and
            # the interaction belongs in step 5-6. A contested item leaves the
            # probation pool (on_probation covers provisional/pending_removal
            # only), so nothing raises it a second time - the queue has to hold
            # it until it is answered.
            texts = self._requirement_texts([rid for rid, _ in contested])
            queued = list(getattr(self.context, "pending_requirement_contests", None) or [])
            known = {e.get("req_id") for e in queued if isinstance(e, dict)}
            for req_id, reason in contested:
                record = statuses.get(req_id)
                if req_id not in known:
                    queued.append({
                        "req_id": req_id,
                        "reason": self._contest_reason(statuses, req_id, reason),
                        "op": record.op if record else "",
                        "text": texts.get(req_id, ""),
                    })
                self.logger.log(f"[REQ_PROBATION] {req_id} CONTESTED - {reason}")
                print(f"  ⚠️  {req_id}: {reason}")
            self.context.pending_requirement_contests = queued

        for req_id in outcome.get('stalled') or []:
            record = statuses.get(req_id)
            self.logger.log(
                f"[REQ_PROBATION] {req_id} STALLED - {record.reason if record else ''}"
            )
            print(f"  🚧 {req_id}: no verifiable encoding after 3 iterations")

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

            # Join the localization against the ownership audit. Blocking alone
            # is dismissible (a dozen facts block any given scenario) and
            # undeclared alone is dismissible (a dozen facts declare nothing);
            # a fact that is both has no defensible status.
            self.context.semantic_diagnostics = diagnosis['results']
            self._flag_unowned_blockers(semantic_escalation, diagnosis['results'],
                                        model_text)
        except Exception as e:
            self.logger.log(f"[SEMANTIC_DIAGNOSTICS] skipped: {e}")

    def _flag_unowned_blockers(self, semantic_escalation, diagnostics, model_text) -> None:
        """Surface undeclared facts that provably block an UNSAT predicate.

        Appended to the escalation directive rather than the interpretation
        prompt: the localization runs AFTER InterpretResults in the same
        iteration, so this is the earliest consumer that can act on it.
        """
        try:
            from src.utils.traceability_store import (
                BLOCKER_ESCALATION_THRESHOLD, audit_model, find_unowned_blockers,
                format_unowned_blockers, track_blocker_persistence,
            )

            audit = self.context.ownership_audit
            if not audit and model_text:
                audit = audit_model(
                    model_text, self.context.artifacts.get_latest_requirements() or ""
                )
            blockers = find_unowned_blockers(audit, diagnostics)
            self.context.unowned_blockers = blockers
            if not blockers:
                self.context.unowned_blocker_streaks = {}
                return

            streaks = track_blocker_persistence(
                blockers, self._collect_blocker_history()
            )
            self.context.unowned_blocker_streaks = streaks

            self.logger.log(f"[UNOWNED_BLOCKERS] {blockers} streaks={streaks}")
            print(
                f"  ⚠️  {len(blockers)} undeclared fact(s) block an UNSAT predicate: "
                f"{', '.join(blockers)}"
            )
            persistent = sorted(f for f, n in streaks.items()
                                if n >= BLOCKER_ESCALATION_THRESHOLD)
            if persistent:
                self.logger.log(
                    f"[UNOWNED_BLOCKERS] unresolved across iterations: {persistent}"
                )
                print(
                    f"  🚨 Still unowned after a previous instruction: "
                    f"{', '.join(persistent)}"
                )
            # No escalation_level bump: this method is only reachable from the
            # already-escalated branch, so the level is > 0 by construction and
            # the directive already reaches the RE at the hand-off gate.
            semantic_escalation['directive'] += "\n\n" + format_unowned_blockers(
                blockers, streaks
            )
            semantic_escalation['unowned_blockers'] = blockers
            semantic_escalation['unowned_blocker_streaks'] = streaks
        except Exception as e:
            self.logger.log(f"[UNOWNED_BLOCKERS] skipped: {e}")

    def _collect_blocker_history(self, limit: int = 6) -> list:
        """Prior iterations' unowned-blocker maps, most recent first.

        Read back out of the regression log rather than accumulated on the
        context: the log is already persisted and already trimmed on resume, so
        a streak cannot count iterations that a rewind discarded.
        """
        try:
            current = self.context.iteration.current
            previous = [e for e in self.context.regression_log.entries
                        if e.iteration_id < current]
            previous.sort(key=lambda e: e.iteration_id, reverse=True)
            return [
                (entry.repair_escalation or {}).get('unowned_blockers') or {}
                for entry in previous[:limit]
            ]
        except Exception:
            return []

    def _check_blocker_decisions(self, feedback: str) -> None:
        """Report flagged facts the Evaluator's feedback left undecided.

        The finding says "resolve every one"; without reading back what came out,
        that is an instruction with no compliance check - the same instruction-only
        approach that already failed once, when the stale fact was weakened instead
        of removed. Observation only: the omission is recorded here and the fact is
        re-flagged (with its streak) next iteration.
        """
        try:
            from src.utils.traceability_store import missing_blocker_decisions

            blockers = getattr(self.context, 'unowned_blockers', None)
            if not isinstance(blockers, dict) or not blockers:
                return
            missing = missing_blocker_decisions(blockers, feedback or "")
            if missing:
                self.logger.log(
                    f"[UNOWNED_BLOCKERS] no decision recorded for: {missing} "
                    f"({len(blockers) - len(missing)}/{len(blockers)} decided)"
                )
                print(
                    f"  ⚠️  Evaluator recorded no resolution for "
                    f"{len(missing)}/{len(blockers)} unowned blocker(s): "
                    f"{', '.join(missing)}"
                )
            else:
                self.logger.log(
                    f"[UNOWNED_BLOCKERS] all {len(blockers)} decided"
                )
        except Exception as e:
            self.logger.log(f"[UNOWNED_BLOCKERS] decision check skipped: {e}")

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
        Enforce the user's decision on any proposed requirement updates before
        Step 7 applies them. Originally rung 5 of the semantic escalation ladder
        (persistent issues), it now also gates ordinary triage-proposed updates
        on non-escalated iterations (escalated_issues empty -> record decision
        only, no predicate regeneration).

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
        # Recorded as each item's provenance in the status store. It does NOT
        # shorten or waive probation: the user confirms wording, and wording is
        # not what probation tests.
        self.context.requirement_gate_decision = gate_decision
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

            # Non-escalated accept: the updates come from ordinary triage, not a
            # persistent issue, so there are no escalated constructs to rebuild.
            # Record the decision (above) and let Step 8 patch normally instead
            # of forcing an empty REGENERATE_PREDICATES escalation.
            if not (semantic_escalation.get('escalated_issues') or []):
                self.logger.log(
                    f"[REQUIREMENT_GATE] {gate_decision} (non-escalated) -> "
                    f"updates applied via normal patch; no regeneration"
                )
                print("  ✅ Updates accepted - will be applied to the requirements")
                return feedback

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
                # Evidence gate: the InterpretResults causal analysis decides.
                # Requirements diagnosis stays mandated whenever it attributes
                # the failure to the requirements; otherwise the directive is
                # redirected to targeted model repair
                # (MODEL_OVERCONSTRAINT_REPAIR). The deterministic diagnostics
                # corroborate where the contradiction sits but do not veto the
                # cause. The alignment verdict is appended to the directive so
                # GenerateSemanticFeedback sees both evidence streams and the
                # binding conclusion.
                from src.utils.repair_plateau_detector import apply_evidence_alignment
                from src.utils.semantic_diagnostics import requirement_ids as _req_roots
                # Refresh the requirement->construct map against the current
                # model and compute recently-changed requirement IDs, so a stale
                # encoding of a just-changed requirement (an internal_contradiction
                # predicate tracing to that requirement) is attributed to the
                # requirement, not misread as a model overconstraint.
                self.context.traceability.rebuild(alloy_model or "")
                recently_changed = _req_roots(
                    self.context.requirement_patch_log.changed_requirement_ids_since(
                        max(0, self.context.iteration.current - 3)
                    ),
                    prefixes=("R", "E"),
                )
                alignment = apply_evidence_alignment(
                    semantic_escalation, interpretation,
                    traceability=self.context.traceability,
                    recently_changed=recently_changed,
                )
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
            # A requirement the user asked to have diagnosed rides the same
            # channel as any other requirements diagnosis, so it reaches the
            # Evaluator with the rest of the evidence rather than beside it.
            self._stage_stall_diagnosis(semantic_escalation)

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
            self._check_blocker_decisions(draft_feedback)

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

            # Requirement-change decision gate: ANY feedback that proposes
            # requirement updates needs an explicit user decision before Step 7
            # applies it to the requirements document. The gate is NOT tied to
            # escalation - the requirement-change triage now emits REQUIREMENT
            # UPDATES on ordinary (non-escalated) iterations too, and those must
            # still be gated. The review interaction doubles as the gate.
            gate_active = False
            # Contested updates are settled FIRST, on their own input: the
            # solver has produced evidence against a requirement already in the
            # document, which outranks any question about a new one.
            self._resolve_requirement_contests()
            # Then requirements nothing could encode. Same standing as a
            # contest - a terminal status the run cannot leave on its own - and
            # asked second only because a contest has solver evidence behind it.
            self._resolve_requirement_stalls()
            # Contradiction triage (bucket 6) runs BEFORE the decision gate so
            # its claim is visible while the user reviews the update. It is
            # shown, not enforced: the update still goes through the ordinary
            # gate, and the solver settles the claim next iteration.
            draft_feedback, conflict_notices = self._screen_requirement_conflicts(
                draft_feedback)
            proposed_updates = self._extract_requirement_updates(draft_feedback)
            if conflict_notices:
                print("\n⚔️  CONTRADICTION CLAIMED (for your information)")
                for notice in conflict_notices:
                    print(f"  {notice}")
                print()
            if proposed_updates:
                gate_active = True
                escalated = semantic_escalation['escalation_level'] > 0
                banner = (
                    "🚧 REQUIREMENT-CHANGE DECISION GATE"
                    + (" (persistent issue escalation)" if escalated else "")
                )
                print(banner)
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
                    user_review=user_review,
                    requirements_document=requirements
                )

                # Safety net: RefineFeedback only guarantees preserving the
                # CONVERGENCE_RECOMMENDATION section, so re-carry the diagnostic
                # candidates here in case its rewrite dropped them.
                final_feedback = self._inject_diagnostic_experiments(final_feedback, diagnostic_text)

                # Same safety net for the Mode 3 signal: the decision line and
                # the plan select how the RE runs next, so losing them in the
                # rewrite silently turns a measurement into a repair.
                final_feedback = self._preserve_diagnostic_signal(draft_feedback, final_feedback)

                # Interactive classification round: when the triage could not tell
                # whether a user-proposed change is a requirement, a constraint, or
                # a modeling note, it raised [CLASSIFICATION] question(s) instead of
                # guessing. Give the user a chance to answer them now so the
                # decision resolves in-iteration rather than defaulting to
                # "requirement" or waiting a full iteration.
                final_feedback = await self._resolve_classification_questions(
                    final_feedback, requirements
                )

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

                # Safety net: ensure the diagnostic experiments from InterpretResults
                # survive even if GenerateSemanticFeedback dropped them.
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
                # verified=True: this lesson only reaches here after its target
                # issue stayed resolved for the required clean iterations. That
                # is what entitles it to retire a lesson it contradicts - a
                # lesson never wins on being newer.
                self.context.memory.store(
                    content=lesson_content,
                    item_type='lesson',
                    agent=pending['agent_name'],
                    action=pending['action_name'],
                    iteration=pending['source_iteration'],
                    verified=True
                )
            if pending['lessons']:
                self.logger.log(
                    f"✅ Lesson from {pending['agent_name']}/{pending['action_name']} "
                    f"(iteration {pending['source_iteration']}) confirmed and recorded"
                )
                # The positive half of the gate, which nothing called before:
                # these lessons' change held, so a suspension THEY raised is now
                # settled in their favour. Scoped by lesson text - with the old
                # iteration key this would have retired an unrelated lesson on
                # evidence that was never about it, which is why it must not be
                # wired without that key.
                self.context.learning.resolve_lesson_conflicts(
                    resolved=True,
                    iteration=self.context.iteration.current,
                    lesson_texts=pending['lessons'],
                )
            # Apply any staged convention retractions now that the motivating
            # fix is confirmed - the convention is withdrawn only because the
            # change that superseded it stuck (same gate as lessons).
            retractions = pending.get('retractions') or []
            if retractions:
                self.context.learning.apply_convention_retractions(
                    retractions, pending['source_iteration']
                )
                self.logger.log(
                    f"↩️  {len(retractions)} convention retraction(s) from "
                    f"{pending['agent_name']}/{pending['action_name']} "
                    f"(iteration {pending['source_iteration']}) confirmed and applied"
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

    async def _resolve_classification_questions(
        self, final_feedback: str, requirements: str
    ) -> str:
        """
        Surface [CLASSIFICATION] questions raised by the requirement-change
        triage and let the user answer them in-iteration.

        The triage raises these when it cannot tell whether a user-proposed
        change is a new requirement, a constraint, or a modeling note. Rather
        than defaulting to "requirement" (which dilutes the document) or
        deferring a full iteration, we prompt the user now, persist the answer
        as a confirmed Q&A, and re-run RefineFeedback so the resolved
        classification flows into REQUIREMENT UPDATES before Step 7.

        Returns the (possibly re-refined) feedback. On no questions or no user
        answer, returns the feedback unchanged - the unresolved item is simply
        not written this iteration.
        """
        from src.utils.qa_parser import parse_user_questions

        questions = parse_user_questions(
            final_feedback, section_name="UPDATED USER QUESTIONS"
        )
        classification_qs = [
            q for q in (questions or []) if "[CLASSIFICATION]" in q.upper()
        ]
        if not classification_qs:
            return final_feedback

        print("\n" + "-" * 80)
        print("❓ CLASSIFICATION NEEDED - is each item a requirement, a constraint, "
              "or a modeling note?")
        for i, q in enumerate(classification_qs, 1):
            print(f"  {i}. {q}")
        print("-" * 80)

        answer = self.cli.request_input(
            prompt=(
                "The Evaluator needs you to classify the item(s) above before "
                "updating the requirements:\n"
                + "\n".join(f"{i}. {q}" for i, q in enumerate(classification_qs, 1))
                + "\nAnswer each (e.g. 'requirement', 'constraint', or 'modeling "
                  "note only'), or press Enter to defer."
            ),
            concise_prompt="Classify the item(s) above (requirement / constraint / modeling note):",
            multiline=True,
        )

        if not answer or not answer.strip():
            print("  ↳ Deferred - unclassified item(s) not written this iteration.")
            return final_feedback

        # Persist each classification answer as a confirmed Q&A so it is not
        # re-asked (honored by QAContextReuseAndUpdate).
        from src.utils.qa_parser import extract_question_context, parse_user_feedback_for_answers
        from src.utils.qa_database import QARecord, create_qa_id

        answer_map = parse_user_feedback_for_answers(answer, classification_qs)
        for idx, question in enumerate(classification_qs, start=1):
            self.context.qa_database.add_record(QARecord(
                id=create_qa_id(self.context.iteration.current, 900 + idx),
                iteration=self.context.iteration.current,
                question=question,
                answer=answer_map.get(idx - 1, answer),
                source="user",
                context=extract_question_context(question) or "requirement classification",
                status="confirmed",
            ))

        # Re-run RefineFeedback with the classification answers so the now-known
        # kind/placement is folded into REQUIREMENT UPDATES.
        print("  ↳ Applying your classification...")
        return await self.refine_feedback.run(
            draft_feedback=final_feedback,
            user_review=(
                "Classification decisions for the [CLASSIFICATION] question(s): "
                + answer.strip()
                + "\nApply these: place each item as the user classified it "
                  "(requirement vs constraint vs modeling note) and remove the "
                  "resolved [CLASSIFICATION] question(s)."
            ),
            requirements_document=requirements,
        )

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
        Deterministically carry the diagnostic experiments text (extracted from
        InterpretResults) into the feedback as its own DIAGNOSTIC CANDIDATES
        section, as a safety net for cases where GenerateSemanticFeedback /
        RefineFeedback fail to carry it over on their own.

        It is deliberately NOT spliced into REPAIR INSTRUCTIONS. That section is
        the Evaluator's adopted work order for the iteration; splicing raw
        candidates into it made unadopted suggestions read as instructions, and
        restated the adopted ones in different words (iteration 66 shipped 11
        numbered items that way). The safety net keeps its guarantee - nothing is
        lost when the Evaluator drops an experiment - but the RE now sees the
        candidates as reference material rather than as work.

        Args:
            feedback: Full feedback text about to be sent to RE
            diagnostic_text: Diagnostic experiments content extracted from
                InterpretResults, or None/empty if there's nothing to inject

        Returns:
            feedback with a trailing DIAGNOSTIC CANDIDATES section, or feedback
            unchanged if diagnostic_text is falsy or the section is already present
        """
        if not diagnostic_text:
            return feedback

        if DIAGNOSTIC_CANDIDATES_HEADER in feedback:
            # Already carried over on an earlier pass of this iteration.
            return feedback

        block = (
            f"{DIAGNOSTIC_CANDIDATES_HEADER}\n"
            "Reference material, not a work order. These experiments were proposed while\n"
            "interpreting the analyzer results; they are reproduced here only so they are\n"
            "not lost. Do NOT apply them as model edits. The work for this iteration is in\n"
            "the REPAIR INSTRUCTIONS section; anything from this list that was adopted\n"
            "already appears there in the Evaluator's own words.\n\n"
            f"{diagnostic_text}"
        )

        print("  ✓ Diagnostic experiments from InterpretResults carried over as DIAGNOSTIC CANDIDATES")
        self.logger.log(
            "[DIAGNOSTIC_CANDIDATES] carried over verbatim from InterpretResults "
            "(reference section, not REPAIR INSTRUCTIONS)"
        )
        return feedback.rstrip() + "\n\n" + block + "\n"

    async def _step7_update_requirements(self):
        """Step 7: Update requirements based on feedback."""
        print("\n📝 Step 7: Updating requirements...")

        full_feedback = self.context.artifacts.get_latest_feedback()
        requirements = self.context.artifacts.get_latest_requirements()

        # Perform removals whose probation completed BEFORE the update runs, so
        # neither the Evaluator nor the resulting document still shows an item
        # the run has finished verifying the absence of.
        requirements = self._perform_verified_deletions(requirements)
        # Same reason, for updates the user chose to undo: the revert lands
        # before this iteration's patch, so a patch touching the same item
        # applies to the reverted text rather than to what was rolled back.
        requirements = self._perform_requirement_reverts(requirements)
        # The losing side of a conflict the user resolved. Deferred, so it does
        # not edit the document - but it must be recorded before the patch, or
        # the superseding update and the item it supersedes both land as live
        # requirements for an iteration.
        superseded = self._perform_staged_removals(requirements)

        # Extract only REQUIREMENT_UPDATES section from feedback
        requirements_feedback = self._extract_requirement_updates(full_feedback)

        # Skip if no requirement updates found - reuse existing requirements file
        if requirements_feedback is None:
            print("✓ No requirement updates needed - using existing requirements")
            latest_reqs_file = self.context.file_manager.get_latest_requirements_file()
            if latest_reqs_file:
                print(f"  Using: {latest_reqs_file}")
            # A supersession is a requirement change even when the patch that
            # caused it never arrived: its constructs are stale either way, and
            # returning here would leave them encoding a retired requirement.
            if superseded:
                self._stage_requirement_change_regeneration(requirements)
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

        # The patch has landed, so an update named in a contradiction claim
        # now has an ID to carry it. Unverified - the solver settles it.
        self._attach_declared_conflicts()

        # A changed requirement's OLD encoding is now stale. Find the constructs
        # that encoded it (traceability map) and stage a REGENERATE_PREDICATES
        # directive so step 8 deletes+rebuilds them from the new text, instead of
        # leaving a stale construct that silently conflicts.
        self._stage_requirement_change_regeneration(updated_requirements)

    def _perform_verified_deletions(self, requirements: str) -> str:
        """Delete items whose probationary REMOVE completed, and persist.

        A REMOVE is recorded but not performed: the item stays in the document
        (marked PENDING REMOVAL) while its Alloy encoding is deleted, so the
        removal is verified against a model that no longer contains it and the
        text stays available to review and revert. This is the other half -
        once the window closes, the item finally goes.

        Returns the document text to continue with (unchanged when nothing was
        due, or when a deletion could not be performed).
        """
        # isinstance, not truthiness: a Mock context returns a truthy Mock.
        pending = getattr(self.context, "pending_requirement_deletions", None)
        if not isinstance(pending, list) or not pending or not requirements:
            return requirements
        try:
            from src.utils.requirements_store import remove_item

            text = requirements
            deleted = []
            for req_id in pending:
                result = remove_item(text, req_id)
                if not result["removed"]:
                    self.logger.log(
                        f"[REQ_PROBATION] deferred removal of {req_id} skipped - "
                        f"no longer in the document"
                    )
                    continue
                text = result["text"]
                deleted.append(req_id)
                self.context.requirement_status.supersede(req_id)
            self.context.pending_requirement_deletions = []
            if not deleted:
                return requirements

            iteration = self.context.iteration.current
            self.context.artifacts.store_requirements(iteration, text)
            self.context.file_manager.save_requirements(text, iteration=iteration)
            self.logger.log(f"[REQ_PROBATION] deleted after verification: {deleted}")
            print(f"  🗑️  Verified removal applied: {', '.join(deleted)}")
            return text
        except Exception as e:
            self.logger.log(f"[REQ_PROBATION] deferred deletion failed (non-fatal): {e}")
            return requirements

    def _audit_construct_ownership(self, model_text: str) -> Optional[Dict[str, Any]]:
        """Classify every construct by requirement ownership (report-only).

        Stores the audit on the context so the removal step can consume it.
        Best-effort: an observability pass must never break the model update.
        """
        from src.utils.traceability_store import audit_model, format_ownership_report

        self.context.ownership_audit = None
        try:
            requirements = self.context.artifacts.get_latest_requirements() or ""
            audit = audit_model(model_text, requirements)
            self.context.ownership_audit = audit

            report = format_ownership_report(audit)
            self.logger.log(f"[OWNERSHIP_AUDIT] {report}")
            summary = audit["summary"]
            if summary["orphan"] or summary["unclassified"] or summary["dead"]:
                print(
                    f"  🔍 Ownership audit: {summary['orphan']} orphaned, "
                    f"{summary['dead']} dead, {summary['unclassified']} unclassified "
                    f"of {summary['total']} constructs"
                )
            self._stage_stale_construct_removal(model_text, audit)
            return audit
        except Exception as e:
            print(f"  ⚠️  ownership audit skipped: {e}")
            return None

    def _stage_stale_construct_removal(self, model_text: str, audit: Dict[str, Any]) -> None:
        """Fix D: turn the audit's orphans/dead helpers into a removal directive.

        Staged for the NEXT model update (the audit runs after this iteration's
        model was written). Unclassified constructs are NOT removed - they are
        unlabelled, not proven stale.
        """
        from src.utils.repair_plateau_detector import build_stale_construct_removal
        from src.utils.traceability_store import compute_removable_closure

        self.context.pending_stale_removal = None
        try:
            # Auto-delete only orphaned FACTS (plus dead helpers). Removing a
            # fact merely relaxes the model, whereas deleting an assertion or a
            # run predicate silently removes verification coverage - and this
            # path's evidence is inferred ("owner absent from the parsed
            # requirements"), not proven. An explicit REMOVE in the patch log is
            # proof and deletes every kind; see _stage_removed_requirement_deletion.
            kinds = audit.get("kinds") or {}
            orphans = audit.get("orphan") or {}
            seeds = [n for n in orphans if kinds.get(n) == "fact"]
            seeds += list(audit.get("dead") or [])
            deferred = [n for n in orphans if kinds.get(n) != "fact"]
            if deferred:
                print(
                    f"  ⚠️  Orphaned non-fact constructs reported, NOT deleted "
                    f"(would remove verification coverage): {', '.join(deferred)}"
                )
            if not seeds:
                return
            closure = compute_removable_closure(model_text, seeds)
            if not closure["remove"]:
                return
            directive = build_stale_construct_removal(
                current_iteration=self.context.iteration.current,
                audit=audit,
                closure=closure,
            )
            if not directive.get("directive"):
                return
            self.context.pending_stale_removal = directive
            cascaded = closure["cascaded"]
            print(
                f"  🗑️  Stale constructs staged for removal: {closure['remove']}"
                + (f" (incl. {len(cascaded)} stranded helper(s))" if cascaded else "")
            )
        except Exception as e:
            print(f"  ⚠️  stale-construct removal staging skipped: {e}")

    def _stage_requirement_change_regeneration(self, updated_requirements: str) -> None:
        """Fix A: turn this iteration's requirement changes into a directive for
        the constructs those requirements encoded.

        MODIFY -> regenerate from the requirement's NEW text.
        REMOVE -> delete: the requirement is gone, so there is no text to rebuild
        from. Routing REMOVE to regeneration would tell the RE to rebuild from a
        requirement that no longer exists, and the ownership audit would then
        order the same construct deleted a step later.

        Best-effort: an enhancement that must never break the requirement-update
        flow, so any failure just leaves nothing staged.
        """
        from src.utils.repair_plateau_detector import (
            build_requirement_change_regeneration,
            build_stale_construct_removal,
        )
        from src.utils.semantic_diagnostics import requirement_ids as _req_roots
        from src.utils.traceability_store import compute_removable_closure

        self.context.pending_requirement_regeneration = None
        try:
            iteration = self.context.iteration.current
            patch_log = self.context.requirement_patch_log
            # Both requirement families are traced, so both must be looked up.
            modified = _req_roots(
                patch_log.changed_requirement_ids(iteration, ops=("MODIFY",)),
                prefixes=("R", "E"),
            )
            removed = _req_roots(
                patch_log.changed_requirement_ids(iteration, ops=("REMOVE",)),
                prefixes=("R", "E"),
            )
            if not modified and not removed:
                return

            current_model = self.context.artifacts.get_latest_alloy_model() or ""
            self.context.traceability.rebuild(current_model)

            if removed:
                self._stage_removed_requirement_deletion(
                    iteration, removed, current_model,
                    compute_removable_closure, build_stale_construct_removal,
                )

            if not modified:
                return
            targets = self.context.traceability.constructs_for(modified)
            if not targets:
                print(
                    f"  ℹ️  Requirement change {modified} has no traced constructs to "
                    f"regenerate (name it with a requirement-ID prefix or a //@req comment)"
                )
                return

            self.context.pending_requirement_regeneration = build_requirement_change_regeneration(
                current_iteration=iteration,
                changed_requirement_ids=modified,
                regenerate_targets=targets,
                updated_requirements=updated_requirements,
            )
            print(
                f"  ♻️  Requirement change {modified} invalidates constructs {targets}; "
                f"staged for regeneration in step 8"
            )
        except Exception as e:
            print(f"  ⚠️  requirement-change regeneration staging skipped: {e}")

    def _stage_removed_requirement_deletion(
        self, iteration, removed_ids, current_model, compute_closure, build_removal,
    ) -> None:
        """Stage deletion of the constructs a REMOVEd requirement left behind.

        Only assigns when there is something to delete, so a removal already
        staged by the previous iteration's ownership audit is not discarded.
        """
        seeds = self.context.traceability.constructs_for(removed_ids)
        if not seeds:
            return
        closure = compute_closure(current_model, seeds)
        if not closure["remove"]:
            return
        orphan = {
            name: [r for r in self.context.traceability.requirements_for(name)
                   if r in set(removed_ids)]
            for name in seeds if name in closure["remove"]
        }
        directive = build_removal(
            current_iteration=iteration,
            audit={"orphan": orphan, "dead": []},
            closure=closure,
        )
        if directive.get("directive"):
            self.context.pending_stale_removal = directive
            print(
                f"  🗑️  Requirement {removed_ids} removed; deleting its constructs "
                f"{closure['remove']} in step 8"
            )

    def _record_construct_removal(self, pending_removal, pruned) -> None:
        """Audit trail for a workflow-authored (not RE-authored) deletion.

        Without this the removal is only visible by diffing two models, and
        later diagnosis would attribute it to the RE agent.
        """
        try:
            from src.utils.construct_removal_log import ConstructRemovalEntry

            audit = pending_removal.get('audit') or {}
            removed = pruned['removed']
            entry = ConstructRemovalEntry(
                iteration_id=self.context.iteration.current,
                removed=removed,
                reason='no live requirement owner',
                # Carried so the Evaluator can see WHAT was removed, not just
                # its name: a deleted fact and a deleted assertion differ.
                kinds={n: k for n, k in (audit.get('kinds') or {}).items() if n in removed},
                orphan_owners=audit.get('orphan') or {},
                blocked=pending_removal.get('blocked') or {},
                dropped_lines=pruned['dropped_lines'],
            )
            self.context.construct_removal_log.add_entry(entry)
            self.logger.log(f"[CONSTRUCT_REMOVAL] {entry.to_dict()}")
            print(
                f"  🗑️  Removed {len(pruned['removed'])} stale construct(s) "
                f"before the model update: {', '.join(pruned['removed'])}"
            )
        except Exception as e:
            print(f"  ⚠️  construct-removal record skipped: {e}")

    def _evaluate_diagnostic_signal(
        self,
        feedback: str,
        model_text: str = "",
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Read the Mode 3 signal out of the feedback the RE is about to act on: the
        Evaluator's next-action decision plus the plan behind it, guard-railed
        against the model it will run on and the diagnosis already measured.

        Stored on the context as `diagnostic_signal`; `mode` is read from it.
        Every dropped plan item is logged - a silently discarded experiment reads
        exactly like one that was never proposed.

        An outstanding re-issue (an experiment ordered last iteration that
        produced no probe) is merged into the plan while the Evaluator is still
        diagnosing, and dropped the moment it chooses anything else: a fresh
        judgement outranks an outstanding retry, and a retry that could survive
        a change of direction would be a loop.
        """
        from src.utils.repair_plateau_detector import should_run_diagnostic_iteration

        signal = should_run_diagnostic_iteration(feedback, model_text, diagnostics)

        pending = getattr(self.context, "pending_diagnostic_reissue", None)
        if isinstance(pending, dict) and pending.get("items"):
            if signal["diagnostic"]:
                named = {i.get("construct") for i in signal["items"]}
                readded = [i for i in pending["items"] if i.get("construct") not in named]
                if readded:
                    signal["items"] = signal["items"] + [
                        {k: v for k, v in item.items() if k != "attempt"}
                        for item in readded
                    ]
                    self.logger.log(
                        f"  🔁 [MODE3] re-issued into this iteration's plan: "
                        f"{', '.join(i['construct'] for i in readded)}"
                    )
            else:
                self.logger.log(
                    f"  [MODE3] outstanding re-issue dropped - the Evaluator chose "
                    f"'{signal['decision'] or 'no parseable decision'}' instead of "
                    f"another diagnostic iteration"
                )
                self.context.pending_diagnostic_reissue = None

        self.context.diagnostic_signal = signal

        for drop in signal["dropped"]:
            self.logger.log(
                f"  [MODE3] plan item dropped: {drop['construct']} - {drop['reason']}"
            )
        if signal.get("status_block"):
            # Delivered to the RE with the Mode3 section (phase 3), which requires
            # it echoed in DIAGNOSTIC EXECUTION so the Evaluator reads the dropped
            # items' measured status instead of seeing them disappear.
            self.logger.log("[MODE3_DROPPED]\n" + signal["status_block"])

        if signal["diagnostic"]:
            constructs = ", ".join(i["construct"] for i in signal["items"])
            self.logger.log(
                f"  🔬 [MODE3] diagnostic iteration signalled ({signal['reason']}): {constructs}"
            )
            print(f"  🔬 Diagnostic experiments requested on: {constructs}")
        else:
            # Logged unconditionally, including when the decision is absent: a
            # diagnostic iteration that RefineFeedback rewrote away leaves no
            # other trace, and "no trace" reads exactly like "never proposed".
            self.logger.log(f"  [MODE3] not a diagnostic iteration: {signal['reason']}")

        return signal

    def _recover_diagnostic_placeholder(self, entry) -> None:
        """
        Recognise a diagnostic iteration whose entry was never written (T6).

        Step 8 saves the model file and then records the entry; a crash between
        the two leaves probes on disk with no entry, and step 4 rebuilds a
        placeholder that says `kind="repair"` with no manifest. The probes then
        report verdicts nothing can interpret, retirement never fires (it keys on
        `kind`), and they survive into the next iteration drifting from the
        scenario they duplicate.

        The probe NAMES are still in the model, so the loss is detectable even
        though the plan is not recoverable. Mark the entry diagnostic - that
        restores retirement and keeps the iteration off the repair ladder - and
        say plainly that the hypotheses are gone, rather than leaving verdicts
        that look interpretable but are not.
        """
        try:
            from src.utils.semantic_diagnostics import extract_all_blocks, is_probe_name

            model_text = self.context.artifacts.get_latest_alloy_model() or ""
            probes = sorted({
                b["name"] for b in extract_all_blocks(model_text) if is_probe_name(b["name"])
            })
            if not probes:
                return

            entry.kind = "diagnostic"
            entry.fix_intent = (
                "DIAGNOSTIC EXECUTION: recovered from a missing entry - the model "
                f"contains probe(s) {', '.join(probes)} but the plan they were written "
                "from was not recorded"
            )
            entry.diagnostic_execution = (
                "MANIFEST LOST: this iteration's regression entry was never written, so "
                "the hypotheses and declared readings behind these probes are gone. Their "
                "SAT/UNSAT verdicts cannot be interpreted and must not be read as evidence "
                f"either way. Probes present: {', '.join(probes)}."
            )
            self.logger.log(
                f"  ⚠️  [MODE3] recovered a diagnostic iteration with no manifest: "
                f"{', '.join(probes)} - verdicts are uninterpretable, probes will be retired"
            )
            print(
                f"  ⚠️  Diagnostic probes found with no recorded plan ({', '.join(probes)}) "
                f"- their results cannot be interpreted"
            )
        except Exception as e:
            self.logger.log(f"  [MODE3] placeholder recovery skipped: {e}")

    def _stage_diagnostic_reissue(self, entry) -> None:
        """
        Ask once more for a planned experiment that produced no probe (T1).

        `not_run` is the status that answers nothing: the readback refuses to read
        it as refuted, so without a retry the hypothesis simply stays unmeasured
        and the plan quietly shrinks. Re-issued exactly once - a second miss
        abandons the item, because two failures to express the same hypothesis
        say something about the hypothesis, not about the RE's diligence.

        Staged on the context; `_evaluate_diagnostic_signal` merges it into the
        next plan while the Evaluator is still diagnosing, and drops it when the
        Evaluator moves on - a fresh decision outranks an outstanding retry.
        """
        if getattr(entry, "kind", "repair") != "diagnostic":
            return
        try:
            from src.utils.repair_plateau_detector import (
                REISSUE_LIMIT,
                build_diagnostic_reissue,
                read_back_probe_verdicts,
            )

            plan = getattr(entry, "diagnostic_plan", None)
            if not plan:
                return
            result = entry.current_result
            readback = read_back_probe_verdicts(
                plan,
                satisfied=getattr(result, "satisfied_predicates", None) or [],
                unsatisfied=getattr(result, "unsatisfied_predicates", None) or [],
            )
            missed = [r for r in readback["results"] if r["status"] == "not_run"]
            if not missed:
                self.context.pending_diagnostic_reissue = None
                return

            prior = getattr(self.context, "pending_diagnostic_reissue", None)
            prior = prior if isinstance(prior, dict) else {}
            attempts = dict(prior.get("attempts") or {})

            retry, abandoned = [], []
            for item in missed:
                name = item["construct"]
                attempts[name] = attempts.get(name, 0) + 1
                record = {
                    "construct": name,
                    "hypothesis": item["hypothesis"],
                    "level": "predicate",
                    "reading": item["reading"],
                    "attempt": attempts[name],
                }
                (abandoned if attempts[name] >= REISSUE_LIMIT else retry).append(record)

            reissue = build_diagnostic_reissue(
                current_iteration=self.context.iteration.current,
                items=retry,
                abandoned=abandoned,
            )
            if retry:
                self.context.pending_diagnostic_reissue = {
                    "items": retry,
                    "attempts": attempts,
                    "directive": reissue["directive"],
                }
                self.logger.log(
                    f"  🔁 [MODE3] re-issuing unrun experiment(s): "
                    f"{', '.join(reissue['rerun_targets'])}"
                )
                print(f"  🔁 Re-issuing unrun experiment(s): {', '.join(reissue['rerun_targets'])}")
            else:
                self.context.pending_diagnostic_reissue = None

            if abandoned:
                self.logger.log(
                    f"  [MODE3] not retried after {REISSUE_LIMIT} attempts - left "
                    f"UNMEASURED: {', '.join(reissue['abandoned_targets'])}"
                )
                print(
                    f"  ⚠️  Experiment(s) never run, left unmeasured: "
                    f"{', '.join(reissue['abandoned_targets'])}"
                )
        except Exception as e:
            self.logger.log(f"  [MODE3] re-issue staging skipped: {e}")

    def _retire_diagnostic_probes(self, entry) -> None:
        """
        Stage deletion of every `probe<N>_` construct once its verdict has been
        read (RE Mode 3, phase 5).

        A probe duplicates the scenario body, so a surviving probe drifts from the
        scenario it mirrors and its verdict stops meaning what it meant. It rides
        the existing REMOVE_STALE_CONSTRUCTS channel, which prunes deterministically
        and records the deletion in the ConstructRemovalLog - so the removal is
        attributable to the workflow, not read later as the RE dropping a construct.
        """
        if getattr(entry, "kind", "repair") != "diagnostic":
            return
        try:
            from src.utils.semantic_diagnostics import extract_all_blocks, is_probe_name
            from src.utils.repair_plateau_detector import build_stale_construct_removal

            model_text = self.context.artifacts.get_latest_alloy_model() or ""
            probes = sorted({
                b["name"] for b in extract_all_blocks(model_text) if is_probe_name(b["name"])
            })
            if not probes:
                return

            removal = build_stale_construct_removal(
                current_iteration=self.context.iteration.current,
                audit={
                    "orphan": {p: "spent diagnostic probe (verdict already recorded)"
                               for p in probes},
                    "dead": [],
                    "kinds": {p: "pred" for p in probes},
                },
                closure={"remove": probes, "cascaded": [], "blocked": {}},
            )
            if removal.get("directive"):
                self.context.pending_stale_removal = removal
                self.logger.log(f"  🧹 [MODE3] retiring spent probes: {', '.join(probes)}")
                print(f"  🧹 Retiring diagnostic probe(s): {', '.join(probes)}")
        except Exception as e:
            self.logger.log(f"  [MODE3] probe retirement skipped: {e}")

    def _preserve_diagnostic_signal(self, draft_feedback: str, final_feedback: str) -> str:
        """
        Re-assert the Mode 3 decision and plan if RefineFeedback's rewrite dropped
        them, leaving a genuine user override alone (RE Mode 3, TODO T5).
        """
        from src.utils.repair_plateau_detector import preserve_diagnostic_signal

        outcome = preserve_diagnostic_signal(draft_feedback, final_feedback)
        if outcome["action"] == "restored":
            self.logger.log(
                f"  [MODE3] restored after refine: {', '.join(outcome['restored'])} "
                f"(the draft chose a diagnostic iteration and the rewrite dropped it)"
            )
            print("  🔬 Diagnostic decision restored after feedback refinement")
        elif outcome["action"] == "overridden":
            self.logger.log(
                "  [MODE3] diagnostic decision overridden by the user's review - kept as rewritten"
            )
        return outcome["text"]

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
            # Mode 3 signal (RE Mode 3, phases 1-3). Guard-railed against the
            # model the probes would run on and the diagnosis already measured
            # last iteration - both from the previous iteration, which is the
            # state the plan was written about.
            prior_entry = self.context.regression_log.get_entry(previous_iteration)
            diagnostic_signal = self._evaluate_diagnostic_signal(
                feedback,
                model_text=current_model,
                diagnostics=((prior_entry.repair_escalation or {}).get('diagnostics')
                             if prior_entry else None),
            )
            if diagnostic_signal["diagnostic"]:
                mode = "diagnostic"
                self.logger.log("  🔬 Mode: Diagnostic experiments (additive probes only)")

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

        # Requirement-change regeneration staged by step 7 THIS iteration: the RE
        # must delete + rebuild the changed requirement's stale constructs from
        # the updated text. Its directive already embeds the updated requirements.
        pending_regen = self.context.pending_requirement_regeneration
        if pending_regen and pending_regen.get('directive'):
            escalation_directive = (
                (escalation_directive + "\n\n" + pending_regen['directive'])
                if escalation_directive else pending_regen['directive']
            )
            self.logger.log(
                f"  ♻️  Regenerating stale constructs after requirement change: "
                f"{pending_regen.get('regenerate_targets')}"
            )
            self.context.pending_requirement_regeneration = None

        # Stale-construct removal: constructs whose requirement no longer exists
        # are DELETED (there is no requirement left to rebuild them from). The
        # deletion is applied to the model the RE is ABOUT to edit, rather than
        # asked for - the observed failure mode was the RE weakening such a
        # construct instead of removing it. Falls back to instructing the RE if
        # the prune cannot be validated.
        pending_removal = self.context.pending_stale_removal
        if pending_removal and pending_removal.get('directive'):
            from src.utils.traceability_store import prune_constructs
            from src.utils.repair_plateau_detector import build_stale_construct_removal

            removal_directive = pending_removal['directive']
            targets = pending_removal.get('remove_targets') or []
            pruned = prune_constructs(current_model or "", targets)
            if pruned['ok']:
                current_model = pruned['model_text']
                removal_directive = build_stale_construct_removal(
                    current_iteration=self.context.iteration.current,
                    audit=pending_removal.get('audit') or {},
                    closure={'remove': pruned['removed'],
                             'cascaded': pending_removal.get('cascaded') or [],
                             'blocked': pending_removal.get('blocked') or {}},
                    already_removed=True,
                )['directive']
                self._record_construct_removal(pending_removal, pruned)
            else:
                self.logger.log(
                    f"  [STALE_REMOVAL] deterministic prune skipped "
                    f"({pruned['reason']}) - instructing the RE instead"
                )
            escalation_directive = (
                (escalation_directive + "\n\n" + removal_directive)
                if escalation_directive else removal_directive
            )
            self.context.pending_stale_removal = None

        # A revert changed the document back; the model still encodes what it
        # used to say. Delivered ONCE and cleared - unlike the encoding
        # obligation, this is a one-time realignment, and repeating it after the
        # RE has complied would ask it to delete constructs it just rebuilt.
        pending_revert = getattr(self.context, "pending_revert_directive", None)
        if pending_revert and pending_revert.get('directive'):
            escalation_directive = (
                (escalation_directive + "\n\n" + pending_revert['directive'])
                if escalation_directive else pending_revert['directive']
            )
            self.logger.log(
                f"  ↩️  Revert realignment delivered: "
                f"delete={pending_revert.get('remove_targets')}, "
                f"regenerate={pending_revert.get('regenerate_targets')}"
            )
            self.context.pending_revert_directive = None

        # Encoding obligation for provisional requirements nothing in the model
        # can be traced to. Appended LAST among the requirement-side directives
        # so it reads as the outstanding item after any regeneration or removal
        # above has been accounted for. Kept staged (not cleared) until the item
        # becomes traceable, so a repeat can be named as a repeat.
        pending_encode = getattr(self.context, "pending_encode_provisional", None)
        if pending_encode and pending_encode.get('directive'):
            escalation_directive = (
                (escalation_directive + "\n\n" + pending_encode['directive'])
                if escalation_directive else pending_encode['directive']
            )
            self.logger.log(
                f"  🧭 Encoding obligation delivered: "
                f"build={pending_encode.get('encode_targets')}, "
                f"annotate={pending_encode.get('annotate_targets')}"
            )

        # Plan items the Phase 2 guard rails removed, with what the deterministic
        # diagnosis already measured about each. Delivered on a diagnostic
        # iteration so the RE can report them as `Executed: no` - otherwise the
        # Evaluator sees its hypothesis simply not come back and re-proposes it.
        if mode == "diagnostic":
            status_block = (getattr(self.context, "diagnostic_signal", None) or {}).get(
                "status_block")
            if status_block:
                escalation_directive = (
                    (escalation_directive + "\n\n" + status_block)
                    if escalation_directive else status_block
                )
            # An experiment ordered last iteration that produced no probe. Named
            # as a repeat, exactly as ENCODE_PROVISIONAL names a second ask, so
            # the RE cannot skip it a second time without saying why. Cleared on
            # delivery: staging happens again next iteration only if it is missed
            # again, and the attempt counter is what stops the second miss looping.
            reissue = getattr(self.context, "pending_diagnostic_reissue", None)
            if isinstance(reissue, dict) and reissue.get("directive"):
                escalation_directive = (
                    (escalation_directive + "\n\n" + reissue["directive"])
                    if escalation_directive else reissue["directive"]
                )
                self.logger.log(
                    f"  🔁 Re-issued experiment(s) delivered: "
                    f"{[i.get('construct') for i in reissue.get('items') or []]}"
                )
                self.context.pending_diagnostic_reissue = {
                    **reissue, "directive": "",
                }

        # Deterministic assumption fact-promotion: promote an assumption predicate
        # (A_k, SAT for >=2 consecutive iterations) to a fact, or revert a promotion
        # that broke `baseline`. Computed from the previous iteration's regression state.
        promotion_directive = self._build_assumption_promotion_directive(previous_iteration)

        updated_model_response = await self.update_model.run(
            current_model=current_model,
            evaluation_feedback=feedback,
            requirements_document=requirements,
            mode=mode,
            escalation_directive=escalation_directive,
            promotion_directive=promotion_directive
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

        # Refresh the requirement->construct traceability map against the newly
        # rebuilt model (picks up regenerated constructs and their //@req
        # comments; drops constructs that were deleted).
        self.context.traceability.rebuild(updated_model or "")

        # Ownership audit (report-only): which constructs still belong to a live
        # requirement. A fact constrains every run unconditionally, so one that
        # names a deleted requirement (orphan) or names nothing (unclassified)
        # is how a superseded requirement's encoding survives unnoticed.
        self._audit_construct_ownership(updated_model or "")

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
            expected_impact=regression_fields.get("expected_impact"),
            # A diagnostic iteration measured; it did not attempt a fix. `kind` is
            # what stops it being listed as a failed fix forever after and what
            # keeps it from advancing the escalation ladder.
            kind="diagnostic" if mode == "diagnostic" else "repair",
            diagnostic_execution=regression_fields.get("diagnostic_execution") or None,
            # The manifest, persisted with the iteration that ran it: the readback
            # next iteration needs to know what was SUPPOSED to run.
            diagnostic_plan=(
                (getattr(self.context, "diagnostic_signal", None) or {}).get("items")
                if mode == "diagnostic" else None
            ),
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

    def _scan_promoted_assumptions(self, model_file) -> list:
        """
        Return the assumption predicates (A1, A2, ...) currently declared as FACTS
        in the model, i.e. the ones that have been promoted. Read directly from the
        model text (`fact A<k>`), so the set self-corrects across promotions and
        reverts. Returns a sorted, de-duplicated list; [] if the file is unreadable.
        """
        import re
        try:
            text = Path(model_file).read_text()
        except Exception as e:
            self.logger.log(f"[DEBUG] _scan_promoted_assumptions: could not read model: {e}")
            return []
        names = re.findall(r'\bfact\s+(A\d+)\b', text)
        return sorted(set(names))

    def _build_assumption_promotion_directive(self, previous_iteration: int) -> str:
        """
        Decide whether an assumption predicate (A1, A2, ...) is due for promotion to a
        fact, or whether a prior promotion must be reverted, and return a directive
        block for the RE agent (empty when no action is due).

        - Revert takes priority: if promoting an assumption at `previous_iteration`
          flipped `baseline` SAT->UNSAT, instruct the agent to move it back to a `pred`.
        - Otherwise, any assumption SAT for >=2 consecutive iterations and not already
          a fact is due for promotion.
        """
        log = self.context.regression_log
        prev_entry = log.get_entry(previous_iteration)
        if not prev_entry:
            return ""

        already_promoted = set(log.get_promoted_assumptions())

        # --- Revert guard: a just-promoted assumption that broke `baseline` ---
        if prev_entry.actual_impact and 'baseline' in (prev_entry.actual_impact.sat_to_unsat or []):
            prev_prev = log.get_entry(previous_iteration - 1)
            before = set(prev_prev.promoted_assumptions or []) if prev_prev else set()
            newly = sorted(already_promoted - before)
            if newly:
                names = ", ".join(newly)
                self.logger.log(
                    f"  ↩️  Assumption promotion revert due: {names} broke baseline (SAT→UNSAT)"
                )
                return (
                    f"ASSUMPTION PROMOTION REVERT (deterministic, binding): promoting "
                    f"{names} to a fact made `baseline` UNSAT this iteration. Move "
                    f"{names} back from `fact` to `pred` and restore its `run {newly[0]}` "
                    f"command (likewise for each). Do NOT re-promote it. Change nothing else."
                )

        # --- Promotion trigger: streak >= 2 and not already a fact ---
        streaks = log.compute_assumption_sat_streaks(previous_iteration)
        due = sorted(a for a, c in streaks.items() if c >= 2 and a not in already_promoted)
        if due:
            detail = "; ".join(f"{a} (SAT {streaks[a]} consecutive iterations)" for a in due)
            names = ", ".join(due)
            self.logger.log(f"  🅰️  Assumption promotion due: {detail}")
            return (
                f"ASSUMPTION PROMOTION DUE (deterministic, binding): {detail}. Per the "
                f"MODELING DISCIPLINE, promote each of these VERIFIED assumption predicates "
                f"to a fact: change `pred {due[0]} {{ ... }}` to `fact {due[0]} {{ ... }}` "
                f"(and likewise for: {names}), keeping the body identical, and delete its "
                f"`run` command. Do NOT touch any prospective requirement (R*), assertion, "
                f"or other predicate."
            )
        return ""

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
