"""
Actions for Evaluator agent (v2 - with LessonAwareAction).

These actions handle Alloy model evaluation and requirements updating.
"""
from .lesson_aware_action import LessonAwareAction
from typing import Dict, Any, List, Optional


class RunAlloyAnalyzer(LessonAwareAction):
    """
    Action to run Alloy Analyzer on the model.

    This action doesn't use LLM - it just executes the Alloy tool.
    """

    name: str = "RunAlloyAnalyzer"

    async def run(self, model_path: str) -> Dict[str, Any]:
        """
        Run Alloy Analyzer on model file.

        Args:
            model_path: Path to Alloy model file

        Returns:
            Dictionary with analyzer results
        """
        from ..utils.alloy_executor import AlloyExecutor

        # Get iteration and create output directory
        iteration = self.get_current_iteration()

        # Create output directory for this iteration
        import os
        output_dir = f"Output/AnalyzerOutput/{iteration}"
        os.makedirs(output_dir, exist_ok=True)

        # Run Alloy Analyzer
        executor = AlloyExecutor()
        from pathlib import Path

        results = executor.execute(
            model_path=Path(model_path),
            output_dir=Path(output_dir)
        )

        # Log Alloy execution details (if logger available in context)
        if hasattr(self.context, 'logger') and self.context.logger:
            self.context.logger.log_alloy_execution(
                model_path=str(model_path),
                stdout=results.get('stdout', ''),
                stderr=results.get('stderr', ''),
                return_code=results.get('return_code', -1),
                analysis=results.get('analysis', {})
            )

        # Store in artifacts
        self.get_artifacts().store_analyzer_results(iteration, results)

        return results


class InterpretResults(LessonAwareAction):
    """
    Action to interpret Alloy Analyzer results.
    """

    name: str = "InterpretResults"

    async def run(
        self,
        analyzer_results: Dict[str, Any],
        requirements_document: str,
        alloy_model: str
    ) -> str:
        """
        Interpret analyzer results and identify issues.

        Args:
            analyzer_results: Results from Alloy Analyzer
            requirements_document: Current requirements
            alloy_model: Current Alloy model code

        Returns:
            Structured interpretation
        """
        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        # Format analyzer results (this already includes code snippets for syntax errors)
        results_str = self._format_analyzer_results(analyzer_results)

        # Check if there are syntax errors
        analysis = analyzer_results.get('analysis', {})
        has_syntax_errors = analysis.get('has_syntax_errors', False)

        model_context = alloy_model
        if has_syntax_errors:
            # When there are syntax errors, the code snippets are already in analyzer_results
            # So we don't need to repeat them here - just omit the model
            model_context = "(Full model omitted - syntax errors shown in Analyzer Results above)"

        # Get regression log context (filtered by current issues)
        regression_log_str = self.context.regression_log.format_for_prompt_filtered(
            current_analysis=analysis,
            count=3
        )

        # Which requirement each construct encodes, and what the workflow already
        # deleted. Without it "map the blocker to a requirement" and "name the
        # requirement this fact encodes" are answerable only by guessing at names.
        ownership_str = self._format_ownership_context(alloy_model, requirements_document)

        # Render base prompt
        prompt = self.render_prompt(
            analyzer_results=results_str,
            requirements_document=requirements_document,
            alloy_model=model_context,  # Use placeholder or full model
            regression_log=regression_log_str,
            ownership_audit=ownership_str,
            user_preferences=user_prefs
        )

        # Conditionally append specialized sections based on analyzer results
        # PRIORITY-BASED SEQUENTIAL ANALYSIS:
        # 1. Syntax errors (blocking - must fix first)
        # 2. UNSAT predicates (blocking - must fix inconsistency/overconstraint)
        # 3. Counterexamples (blocking - must fix missing constraints)
        # 4. Satisfying instances + Vacuity (quality analysis - only when no failures)
        has_counterexamples = analysis.get('has_counterexamples', False)
        no_counterexamples = not has_counterexamples
        has_unsat_run_commands = len(analysis.get('unsat_run_commands', [])) > 0
        no_unsat_run_commands = not has_unsat_run_commands

        # Log analysis priority
        print(f"  [Analysis Priority] Syntax errors: {has_syntax_errors}, UNSAT predicates: {has_unsat_run_commands}, Counterexamples: {has_counterexamples}")

        # Calculate positive predicate satisfaction for conditional sections
        positive_runs = analysis.get('positive_run_commands', 0)
        satisfied_positive = analysis.get('satisfied_positive_runs', 0)
        all_positive_satisfied = (positive_runs > 0 and positive_runs == satisfied_positive)

        # Check if UNSAT predicates have been stuck for 2+ consecutive iterations
        unsat_stuck = self._check_unsat_stuck(analysis, consecutive_iterations=2)
        if unsat_stuck:
            print(f"  [Priority Override] UNSAT predicates stuck for 2+ iterations")

        # Include SyntaxError section if syntax errors exist
        if has_syntax_errors:
            syntax_error_section = self.context.prompt_manager.get_section(
                "Evaluator",
                "SyntaxError"
            )
            prompt = prompt + "\n\n" + syntax_error_section

        # Include InterpretUNSATPred section if unsatisfiable predicates exist
        if has_unsat_run_commands:
            unsat_pred_section = self.context.prompt_manager.get_section(
                "Evaluator",
                "InterpretUNSATPred"
            )
            # No ownership_audit substitution here: this section is appended to
            # the base prompt, which already carries the block. Its step 3 refers
            # to it rather than repeating it in the same request.
            prompt = prompt + "\n\n" + unsat_pred_section

        # Include InterpretCounterexample section when:
        # 1. Counterexamples exist, AND
        # 2. One of the following:
        #    a) No UNSAT predicates at all, OR
        #    b) All positive predicates are satisfied, OR
        #    c) UNSAT predicates have been stuck for 2+ consecutive iterations (allow parallel analysis)
        # This ensures we don't analyze counterexamples when positive predicates are UNSAT,
        # UNLESS the UNSAT issue has persisted for 2+ iterations (indicating we need alternative approaches)
        allow_counterexample_analysis = no_unsat_run_commands or all_positive_satisfied or unsat_stuck

        if has_counterexamples and allow_counterexample_analysis:
            if unsat_stuck:
                print("  ⚠️  UNSAT predicates stuck for 2+ iterations - allowing counterexample analysis")

            counterexample_section = self.context.prompt_manager.get_section(
                "Evaluator",
                "InterpretCounterexample"
            )
            # Format counterexamples for the section
            counterexamples_str = self._format_counterexamples(analysis)
            # Render the section with counterexample variable
            counterexample_section_rendered = self.context.prompt_manager._substitute_variables(
                counterexample_section,
                {"counterexample": counterexamples_str}
            )
            prompt = prompt + "\n\n" + counterexample_section_rendered

        # QUALITY ANALYSIS: Sequential two-step process when all hard metrics pass
        # Step 1: InterpretSatInstance (if satisfying instances exist)
        # Step 2: VacuityAnalysis (always when hard metrics pass)

        has_satisfying_instances = analysis.get('has_satisfying_instances', False)
        all_hard_metrics_pass = not has_syntax_errors and no_counterexamples and all_positive_satisfied

        # Check if we need quality analysis (sequential sat instance + vacuity)
        if all_hard_metrics_pass:
            print("  → All hard metrics passed - performing quality analysis")

            # STEP 1: InterpretSatInstance analysis (if instances exist)
            instance_response = ""
            if has_satisfying_instances:
                print("  → Step 1: Analyzing satisfying instances")

                # Log step marker
                self.context.logger.log("\n" + "="*80, to_console=False)
                self.context.logger.log("QUALITY ANALYSIS - STEP 1: InterpretSatInstance", to_console=False)
                self.context.logger.log("="*80, to_console=False)

                sat_instance_section = self.context.prompt_manager.get_section(
                    "Evaluator",
                    "InterpretSatInstance"
                )
                # Format satisfying instances for this section
                satisfying_instances_str = self._format_satisfying_instances(analysis)
                
                # Render the section with all required variables
                # IMPORTANT: Do NOT prepend base InterpretResults prompt - use ONLY this section
                instance_prompt = self.context.prompt_manager._substitute_variables(
                    sat_instance_section,
                    {
                        "satisfying_instances": satisfying_instances_str,
                        "alloy_model": alloy_model,
                        "requirements_document": requirements_document
                    }
                )

                # First LLM call for instance analysis (logged automatically by _aask)
                instance_response = await self._aask(instance_prompt)
                instance_response = self.parse_and_record_learning(instance_response)
                print(f"  ✓ Satisfying instance analysis complete ({len(instance_response)} chars)")
            else:
                # Log skip reason
                self.context.logger.log("\n" + "="*80, to_console=False)
                self.context.logger.log("QUALITY ANALYSIS - STEP 1: InterpretSatInstance - SKIPPED (no satisfying instances)", to_console=False)
                self.context.logger.log("="*80 + "\n", to_console=False)

            # STEP 2: VacuityAnalysis (always when hard metrics pass)
            print("  → Step 2: Performing vacuity & underspecification analysis")

            # Log step marker
            self.context.logger.log("\n" + "="*80, to_console=False)
            self.context.logger.log("QUALITY ANALYSIS - STEP 2: VacuityAnalysis", to_console=False)
            self.context.logger.log("="*80, to_console=False)

            vacuity_section = self.context.prompt_manager.get_section(
                "Evaluator",
                "VacuityAnalysis"
            )
            
            # Render the section with all required variables
            # IMPORTANT: Do NOT prepend base InterpretResults prompt - use ONLY this section
            vacuity_prompt = self.context.prompt_manager._substitute_variables(
                vacuity_section,
                {
                    "analyzer_results": results_str,
                    "alloy_model": alloy_model,
                    "requirements_document": requirements_document,
                    # Reduce Assumptions asks which requirement each fact
                    # encodes before recommending it be weakened.
                    "ownership_audit": ownership_str
                }
            )

            # Second LLM call for vacuity analysis (logged automatically by _aask)
            vacuity_response = await self._aask(vacuity_prompt)
            vacuity_response = self.parse_and_record_learning(vacuity_response)
            print(f"  ✓ Vacuity analysis complete ({len(vacuity_response)} chars)")

            # Concatenate both responses
            if instance_response:
                cleaned_response = instance_response + "\n\n---\n\n" + vacuity_response
            else:
                cleaned_response = vacuity_response

            # Log completion marker
            self.context.logger.log("\n" + "="*80, to_console=False)
            self.context.logger.log("QUALITY ANALYSIS COMPLETE (2 sequential LLM calls)", to_console=False)
            self.context.logger.log("="*80 + "\n", to_console=False)

            print("  ✓ Quality analysis complete (2 sequential analyses)")
        else:
            # Single LLM call for failure analysis (syntax/unsat/counterexample)
            response = await self._aask(prompt)
            cleaned_response = self.parse_and_record_learning(response)

        # Parse outcome_classification from response and update regression log.
        # "pending" means the section was missing/unparseable - in that case keep
        # the deterministic classification set in step 4 instead of clobbering it.
        outcome_classification = self._parse_outcome_classification(cleaned_response)
        if outcome_classification and outcome_classification != "pending":
            iteration = self.get_current_iteration()
            entry = self.context.regression_log.get_entry(iteration)
            if entry and entry.actual_impact is not None:
                # Only update if we have actual_impact calculated
                entry.outcome_classification = outcome_classification
                self.context.regression_log._save_to_file()

        # Store cleaned interpretation
        iteration = self.get_current_iteration()
        self.get_artifacts().store_evaluation(iteration, cleaned_response)

        return cleaned_response

    def _format_ownership_context(self, alloy_model: str, requirements_document: str) -> str:
        """Ownership audit + deliberate-removal history, as one prompt block.

        The audit is normally computed at the end of the previous step 8, but it
        is absent on the first iteration and after a resume (the context is
        rebuilt from disk). It is a deterministic text parse, so recompute it
        here rather than leave the Evaluator to guess ownership from names.

        Best-effort: supplying context must never break the interpretation.
        """
        try:
            from ..utils.traceability_store import audit_model, format_ownership_for_prompt

            audit = getattr(self.context, "ownership_audit", None)
            if not audit and alloy_model:
                audit = audit_model(alloy_model, requirements_document)

            removal_log = getattr(self.context, "construct_removal_log", None)
            removals = removal_log.format_for_prompt() if removal_log else None

            # From the previous iteration's localization - it runs after this
            # action, so the current iteration's own join is not available yet.
            blockers = getattr(self.context, "unowned_blockers", None)
            if not isinstance(blockers, dict):
                blockers = {}
            streaks = getattr(self.context, "unowned_blocker_streaks", None)
            if not isinstance(streaks, dict):
                streaks = {}

            return format_ownership_for_prompt(audit, removals=removals,
                                               blockers=blockers, streaks=streaks)
        except Exception as e:
            self._debug(f"[DEBUG] ownership context unavailable: {e}")
            return "OWNERSHIP AUDIT: unavailable for this iteration."

    def _check_unsat_stuck(self, current_analysis: Dict[str, Any], consecutive_iterations: int = 2) -> bool:
        """
        Check if UNSAT predicates have been stuck for N consecutive iterations.

        Args:
            current_analysis: Current analysis results
            consecutive_iterations: Number of consecutive iterations to check (default: 2)

        Returns:
            True if same UNSAT predicates appear in N consecutive iterations, False otherwise
        """
        current_unsat = current_analysis.get('unsat_run_commands', [])
        if not current_unsat:
            return False  # No UNSAT predicates currently

        # Extract current UNSAT predicate names
        current_unsat_names = set()
        for pred in current_unsat:
            if isinstance(pred, dict):
                current_unsat_names.add(pred.get('name', ''))
            else:
                current_unsat_names.add(str(pred))

        if not current_unsat_names:
            return False

        # Check regression log for previous iterations
        current_iteration = self.get_current_iteration()
        regression_log = self.context.regression_log

        # Look back N-1 iterations (current iteration + N-1 previous = N consecutive)
        iterations_to_check = consecutive_iterations - 1
        consecutive_count = 0

        for i in range(1, iterations_to_check + 1):
            prev_iteration = current_iteration - i
            if prev_iteration < 0:
                break

            prev_entry = regression_log.get_entry(prev_iteration)
            if not prev_entry or not prev_entry.current_result:
                break

            # Extract UNSAT predicate names from previous iteration
            prev_unsat_names = set(prev_entry.current_result.unsatisfied_predicates or [])

            # Check if any current UNSAT predicates were also UNSAT in previous iteration
            if current_unsat_names & prev_unsat_names:  # Intersection
                consecutive_count += 1
            else:
                break  # Consecutive chain broken

        # Return True if we found N-1 consecutive previous iterations with same UNSAT predicates
        return consecutive_count >= iterations_to_check

    def _format_analyzer_results(self, results: Dict[str, Any]) -> str:
        """Format analyzer results for prompt."""
        lines = []

        # Extract analysis dict (results are nested under 'analysis' key)
        analysis = results.get('analysis', {})

        # Syntax errors
        syntax_errors = analysis.get('syntax_errors', [])
        if syntax_errors:
            lines.append("SYNTAX ERRORS:")
            for error in syntax_errors:
                # Handle both dict and string formats
                if isinstance(error, dict):
                    line = error.get('line', '?')
                    col = error.get('column', '?')
                    msg = error.get('message', 'Unknown error')
                    code_snippet = error.get('code_snippet', '')
                    context = error.get('context', '')

                    lines.append(f"  - Line {line}, Column {col}: {msg}")

                    # Include code snippet if available
                    if code_snippet:
                        lines.append("")
                        # Indent the code snippet
                        for snippet_line in code_snippet.split('\n'):
                            lines.append(f"    {snippet_line}")
                        lines.append("")

                    # Include context (additional error details) after code snippet
                    if context:
                        lines.append(f"    Additional context: {context}")
                        lines.append("")

                elif isinstance(error, str):
                    # Try to extract line/column from string representation if it's a dict string
                    if "'line':" in error and "'column':" in error:
                        # Parse dict string to extract key info
                        import re
                        line_match = re.search(r"'line':\s*(\d+)", error)
                        col_match = re.search(r"'column':\s*(\d+)", error)
                        msg_match = re.search(r"'message':\s*'([^']+)'", error)

                        if line_match and col_match:
                            line_num = line_match.group(1)
                            col_num = col_match.group(1)
                            msg = msg_match.group(1) if msg_match else "Syntax error"
                            lines.append(f"  - Line {line_num}, Column {col_num}: {msg}")
                        else:
                            lines.append(f"  - {error}")
                    else:
                        lines.append(f"  - {error}")
                else:
                    lines.append(f"  - {str(error)}")

            # When syntax errors exist, counterexamples and instances are not applicable
            lines.append("")
            lines.append("COUNTEREXAMPLES: N/A (syntax errors prevent verification)")
            lines.append("")
            lines.append("SATISFYING INSTANCES: N/A (syntax errors prevent verification)")

            return "\n".join(lines)
        else:
            lines.append("SYNTAX: OK")

        lines.append("")

        # Counterexamples (only shown if no syntax errors)
        # Only show summary - detailed JSON data is in InterpretCounterexample section
        counterexamples = analysis.get('counterexamples', [])
        total_check_commands = analysis.get('total_check_commands', 0)
        if counterexamples:
            lines.append(f"COUNTEREXAMPLES FOUND: {len(counterexamples)}/{total_check_commands}")
            lines.append("(Details provided in InterpretCounterexample section below)")
            for i, ce in enumerate(counterexamples[:3], 1):  # Limit to 3
                if isinstance(ce, dict):
                    cmd_name = ce.get('command_name', 'Unknown')
                    lines.append(f"  {i}. {cmd_name}")
                else:
                    lines.append(f"  {i}. {ce}")
        else:
            lines.append(f"COUNTEREXAMPLES: 0/{total_check_commands}")

        lines.append("")

        # Unsatisfiable predicates (only shown if no syntax errors)
        unsat_run_commands = analysis.get('unsat_run_commands', [])
        if unsat_run_commands:
            lines.append(f"UNSATISFIABLE PREDICATES: {len(unsat_run_commands)}")
            lines.append("(These run commands could not find satisfying instances - indicates overconstraint)")
            for i, unsat in enumerate(unsat_run_commands, 1):
                if isinstance(unsat, dict):
                    cmd_name = unsat.get('name', 'Unknown')
                    cmd_number = unsat.get('number', '?')
                    lines.append(f"  {i}. {cmd_name} (command #{cmd_number})")
                else:
                    lines.append(f"  {i}. {unsat}")
        else:
            lines.append("UNSATISFIABLE PREDICATES: None")

        lines.append("")

        # Instances (only shown if no syntax errors)
        # Only show summary - detailed JSON data is in InterpretSatInstance section
        instances = analysis.get('instances', [])
        total_run_commands = analysis.get('total_run_commands', 0)
        if instances:
            lines.append(f"SATISFYING INSTANCES: {len(instances)}/{total_run_commands}")
            lines.append("(Details provided in InterpretSatInstance section below if hard metrics pass)")
            for i, inst in enumerate(instances, 1):  # Show all instances
                if isinstance(inst, dict):
                    cmd_name = inst.get('command_name', 'Unknown')
                    lines.append(f"  {i}. {cmd_name}")
                else:
                    lines.append(f"  {i}. {inst}")
        else:
            lines.append(f"SATISFYING INSTANCES: 0/{total_run_commands}")
            lines.append("(No instances were generated by the analyzer)")

        return "\n".join(lines)

    def _format_satisfying_instances(self, analysis: Dict[str, Any]) -> str:
        """
        Format satisfying instances for Evaluator review.

        Shows only 2 specific instances with full JSON data:
        1. All_Requirements (or AllRequirements) - comprehensive requirement validation
        2. baseline - existing system state

        Args:
            analysis: Analysis dictionary from alloy_executor

        Returns:
            Formatted string with sample instances
        """
        import json

        sample_instances = analysis.get('sample_instances', [])

        if not sample_instances:
            return "(No satisfying instances available for review)"

        lines = []
        lines.append("The following satisfying instances are provided for quality assessment:")
        lines.append("")

        for idx, inst in enumerate(sample_instances, 1):
            cmd_name = inst.get("command_name", "Unknown")
            
            # Add marker for instance type
            if cmd_name in ["All_Requirements", "AllRequirements"]:
                marker = " [COMPREHENSIVE - includes All_Requirements]"
            elif cmd_name == "baseline":
                marker = " [BASELINE - existing system state]"
            else:
                marker = ""

            lines.append(f"Instance {idx}: {cmd_name}{marker}")
            lines.append(f"File: {inst.get('file', 'Unknown')}")
            lines.append("")

            # Include full instance data (no truncation)
            # Replace newlines with double spaces for more compact representation
            instance_data = inst.get('data', {})
            data_str = json.dumps(instance_data, indent=2)
            data_str_compact = data_str.replace('\n', '  ')

            lines.append(data_str_compact)
            lines.append("")
            lines.append("-" * 80)
            lines.append("")

        return "\n".join(lines)

    def _format_counterexamples(self, analysis: Dict[str, Any]) -> str:
        """
        Format counterexamples for InterpretCounterexample section.

        Extracts up to 3 counterexamples with full JSON data.

        Args:
            analysis: Analysis dictionary from alloy_executor

        Returns:
            Formatted string with counterexamples
        """
        import json

        counterexamples = analysis.get('counterexamples', [])[:3]  # Limit to 3

        if not counterexamples:
            return "(No counterexamples found)"

        lines = []
        lines.append("The following counterexamples were found:")
        lines.append("")

        for idx, ce in enumerate(counterexamples, 1):
            cmd_name = ce.get("command_name", "Unknown")
            lines.append(f"Counterexample {idx}: {cmd_name}")
            lines.append(f"File: {ce.get('file', 'Unknown')}")
            lines.append("")

            # Include counterexample data
            # Replace newlines with double spaces for more compact representation
            ce_data = ce.get('data', {})
            data_str = json.dumps(ce_data, indent=2)
            data_str_compact = data_str.replace('\n', '  ')

            lines.append(data_str_compact)
            lines.append("")
            lines.append("-" * 80)
            lines.append("")

        return "\n".join(lines)

    def _parse_outcome_classification(self, interpretation: str) -> str:
        """
        Parse outcome classification from Evaluator's interpretation.

        Args:
            interpretation: Evaluator's interpretation response

        Returns:
            Outcome classification string or "pending" if not found
        """
        import re

        # Extract OUTCOME CLASSIFICATION section
        outcome_match = re.search(
            r'===\s*OUTCOME CLASSIFICATION\s*===\s*\n(.*?)(?=\n===|$)',
            interpretation,
            re.DOTALL | re.IGNORECASE
        )

        if not outcome_match:
            return "pending"

        outcome_text = outcome_match.group(1).strip()

        # Look for "Classification:" line
        classification_match = re.search(
            r'Classification:\s*(.+?)(?:\n|$)',
            outcome_text,
            re.IGNORECASE
        )

        if not classification_match:
            return "pending"

        classification_line = classification_match.group(1).strip()

        # Parse the classification
        if "expected_improvement" in classification_line.lower():
            return "expected_improvement"
        elif "unintended_regression" in classification_line.lower():
            return "unintended_regression"
        elif "spec_clarification" in classification_line.lower():
            # Check if there's a colon with additional rationale
            clarification_match = re.search(
                r'spec_clarification:\s*(.+)',
                classification_line,
                re.IGNORECASE
            )
            if clarification_match:
                rationale = clarification_match.group(1).strip()
                return f"spec_clarification: {rationale}"
            # Just "spec_clarification" without colon
            return "spec_clarification"
        
        return "pending"

    def _find_comprehensive_instance(self, instances: List[Dict]) -> Optional[Dict]:
        """
        Find the most comprehensive satisfying instance.

        Priority:
        1. Instance named "All_Requirements"
        2. Longest R-chain (R1R2R3 > R1R2 > R1)
        3. Instance named "baseline" (existing system)
        4. Last instance in the list

        Args:
            instances: List of satisfying instance dictionaries

        Returns:
            Most comprehensive instance or None
        """
        if not instances:
            return None

        # Priority 1: Look for "All_Requirements"
        for inst in instances:
            if inst.get('command_name') == 'All_Requirements':
                return inst

        # Priority 2: Find longest R-chain (R1R2R3 > R1R2 > R1)
        r_chain_instances = []
        for inst in instances:
            cmd_name = inst.get('command_name', '')
            # Count consecutive R digits (R1, R1R2, R1R2R3, etc.)
            if cmd_name.startswith('R') and any(c.isdigit() for c in cmd_name):
                # Count how many R-number pairs
                r_count = cmd_name.count('R')
                r_chain_instances.append((r_count, inst))

        if r_chain_instances:
            # Sort by R-count descending, return highest
            r_chain_instances.sort(key=lambda x: x[0], reverse=True)
            return r_chain_instances[0][1]

        # Priority 3: Look for "baseline"
        for inst in instances:
            if inst.get('command_name') == 'baseline':
                return inst

        # Priority 4: Return last instance (fallback)
        return instances[-1]


class GenerateSemanticFeedback(LessonAwareAction):
    """
    Action to generate actionable feedback for semantic issues (counterexamples, unsat predicates).
    Does NOT handle syntax errors - use GenerateSyntaxRepairInstruction for those.
    """

    name: str = "GenerateSemanticFeedback"

    async def run(
        self,
        interpretation: str,
        requirements_document: str,
        alloy_model: str,
        relevant_qa: str = "",
        persistence_status: str = ""
    ) -> str:
        """
        Generate actionable feedback for RE agent.

        Args:
            interpretation: Verification interpretation
            requirements_document: Current requirements
            alloy_model: Current Alloy model code
            relevant_qa: Formatted relevant Q&A records from previous iterations
            persistence_status: Evidence block from the RepairPlateauDetector
                when semantic issues persisted past thresholds; when non-empty,
                the PersistentIssueEscalation prompt section is appended and
                requirements diagnosis becomes mandatory

        Returns:
            Structured feedback
        """
        # Get lessons, ranked by semantic similarity to the current interpretation
        lessons = self.get_lessons_for_context(context_query=interpretation, limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # TODO: Re-enable user preferences later
        # Get user preferences
        # user_prefs = self.get_user_preferences()
        # if not user_prefs:
        #     user_prefs = ""
        user_prefs = ""  # Temporarily disabled

        # Get failed fix history for current issue
        from ..utils.regression_log import format_failed_fix_history
        failed_fix_history = "None - this is the first attempt at fixing this issue."

        iteration = self.get_current_iteration()
        regression_log = self.context.regression_log
        current_entry = regression_log.get_entry(iteration)

        # Debug logging
        self._debug(f"[DEBUG] GenerateFeedback - Iteration: {iteration}")
        self._debug(f"[DEBUG] Total regression log entries: {len(regression_log.entries)}")
        self._debug(f"[DEBUG] Current entry found: {current_entry is not None}")
        if current_entry:
            self._debug(f"[DEBUG] Current entry issue: {current_entry.issue}")
            self._debug(f"[DEBUG] Current entry resolved_target_issue: {current_entry.resolved_target_issue}")

        if current_entry and current_entry.issue:
            failed_fix_history = format_failed_fix_history(
                current_issue=current_entry.issue,
                regression_log_entries=regression_log.entries
            )
        else:
            if not current_entry:
                self._debug(f"[DEBUG] No entry found for iteration {iteration}")
            elif not current_entry.issue:
                self._debug(f"[DEBUG] Entry found but issue field is None or empty")

        # Check if there are syntax errors and extract code snippets from analyzer_results
        model_context = alloy_model
        if "SYNTAX STATUS: Errors found" in interpretation or "SYNTAX STATUS: Error" in interpretation:
            # Retrieve analyzer results from artifacts
            iteration = self.get_current_iteration()
            analyzer_results = self.get_artifacts().get_analyzer_results(iteration)
            
            if analyzer_results:
                # Extract code snippets from syntax_errors
                analysis = analyzer_results.get('analysis', {})
                syntax_errors = analysis.get('syntax_errors', [])
                
                snippets = []
                for error in syntax_errors:
                    if isinstance(error, dict):
                        code_snippet = error.get('code_snippet', '')
                        if code_snippet:
                            snippets.append(code_snippet)
                
                if snippets:
                    model_context = "RELEVANT CODE SNIPPETS (faulty sections only):\n\n" + "\n\n".join(snippets)
                    model_context += "\n\n(Full model omitted to focus on syntax errors)"

        # Render prompt
        prompt = self.render_prompt(
            interpretation=interpretation,
            requirements_document=requirements_document,
            alloy_model=model_context,  # Use snippet or full model
            lessons=lessons_str,
            relevant_qa=relevant_qa if relevant_qa else "No relevant prior Q&A pairs found.",
            user_preferences=user_prefs,
            failed_fix_history=failed_fix_history
        )

        # Conditionally append QAContextReuseAndUpdate section if relevant Q&A exists
        if relevant_qa and relevant_qa != "No relevant prior Q&A pairs found.":
            qa_reuse_section = self.context.prompt_manager.get_section(
                "Evaluator",
                "QAContextReuseAndUpdate"
            )
            prompt = prompt + "\n\n" + qa_reuse_section

        # Conditionally append PersistentIssueEscalation section when the
        # RepairPlateauDetector requires requirements diagnosis (semantic
        # issues survived repeated repair attempts)
        if persistence_status and persistence_status.strip():
            from ..utils.repair_plateau_detector import select_binding_rules

            escalation_section = self.context.prompt_manager.get_section(
                "Evaluator",
                "PersistentIssueEscalation"
            )
            # The evidence gate already chose between the two opposed rulebooks
            # this section carries; send only that one. Substitute afterwards -
            # the STRATEGY line is read off the directive, not the filled text.
            escalation_section = select_binding_rules(
                escalation_section, persistence_status
            )
            escalation_section = escalation_section.replace(
                "{{persistence_status}}", persistence_status
            )
            prompt = prompt + "\n\n" + escalation_section

        # Append the shared triage decision procedure so any verification-driven
        # requirement/constraint change is deduped, placed, and classified before
        # it lands in REQUIREMENT UPDATES.
        triage_section = self.context.prompt_manager.get_section(
            "Evaluator", "RequirementChangeTriage"
        )
        prompt = prompt + "\n\n" + triage_section

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning; deferred until the targeted issue is
        # confirmed resolved next iteration
        self.parse_and_record_learning(response, defer=True, pending_attr='pending_evaluator_feedback_lesson')

        # Store feedback
        iteration = self.get_current_iteration()
        self.get_artifacts().store_feedback(iteration, response)

        return response


class UpdateRequirements(LessonAwareAction):
    """
    Action to update requirements based on verification and user feedback.
    """

    name: str = "UpdateRequirements"

    async def run(
        self,
        requirements_document: str,
        feedback: str,
        user_feedback: str = ""
    ) -> str:
        """
        Update requirements document via patch operations (anti-drift).

        The LLM no longer regenerates the whole document. It receives the
        current document (annotated with [E#] item markers) plus the
        immutable original input as ground truth, and returns a
        === REQUIREMENT PATCH === delta. The patch is applied in code:
        items not named in it are copied byte-for-byte, and REMOVE of an
        original-source requirement is blocked.

        Args:
            requirements_document: Current requirements
            feedback: Verification feedback
            user_feedback: User's feedback (if any)

        Returns:
            Updated requirements document (unchanged text if the patch
            could not be applied - the safe default)
        """
        from ..utils import requirements_store as rs

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        original = self.get_artifacts().get_original_requirements()
        protected_ids = rs.parse_original_requirement_ids(original)
        # Existing-system items are protected too, but by TEXT: their E-numbers
        # are positional, so an ID captured once stops denoting the same bullet
        # as soon as one is inserted above it. The baseline is the iteration-0
        # document - the first derivation of the user's system description -
        # falling back to the current one, which over-protects rather than
        # under-protects when that artifact is unavailable.
        baseline = (self.get_artifacts().get_requirements(0)
                    or requirements_document)
        protected_texts = rs.existing_system_texts(baseline)
        statuses = getattr(self.context, "requirement_status", None)
        annotated = self.annotate_requirements(requirements_document,
                                               addressing_markers=True)

        # Render prompt
        prompt = self.render_prompt(
            requirements_document=annotated,
            feedback=feedback,
            user_feedback=user_feedback if user_feedback else "No user feedback provided.",
            user_preferences=user_prefs,
            original_requirements=original or (
                "Original input unavailable (run resumed without a preserved "
                "source copy) - apply the preservation rules to the current "
                "document's requirement IDs instead."
            ),
        )

        # Call LLM and apply the patch; one retry on an unusable patch.
        # Removals are deferred while the status store exists: the item stays in
        # the document (marked) until the model has been verified without its
        # encoding for the full probation window.
        defer = statuses is not None
        response = await self._aask(prompt)
        result = rs.apply_patch(requirements_document, response, protected_ids,
                                defer_removals=defer,
                                protected_texts=protected_texts)

        retried = False
        if not result["changed"] and not result["no_change"] and result["errors"] \
                and not result["applied"]:
            self._debug(f"[REQ_PATCH] retry - patch not applicable: {result['errors']}")
            retry_prompt = (
                prompt
                + "\n\nYour previous patch could not be applied:\n- "
                + "\n- ".join(result["errors"])
                + "\nRe-emit a corrected `=== REQUIREMENT PATCH ===` block only, "
                  "using the item IDs exactly as shown in the current document."
            )
            response = await self._aask(retry_prompt)
            result = rs.apply_patch(requirements_document, response, protected_ids,
                                    defer_removals=defer,
                                    protected_texts=protected_texts)
            retried = True

        for entry in result["blocked"]:
            self._debug(f"[REQ_PATCH] BLOCKED: {entry}")
            print(f"  🛡️  Requirement protection: {entry}")
        if result["errors"]:
            self._debug(f"[REQ_PATCH] errors: {result['errors']}")
        if result["applied"]:
            self._debug(f"[REQ_PATCH] applied: {result['applied']}")
            print(f"  ✏️  Requirement patch applied: {', '.join(result['applied'])}")
        elif result["no_change"]:
            print("  ✏️  Requirement patch: no changes needed")
        else:
            print("  ⚠️  Requirement patch could not be applied - document unchanged")
        if result.get("deferred"):
            print(f"  ⏳ Removal deferred pending verification: "
                  f"{', '.join(result['deferred'])}")

        updated = result["text"]

        # Store updated requirements
        iteration = self.get_current_iteration()
        self.get_artifacts().store_requirements(iteration, updated)

        # Every applied operation goes on probation - ADD, MODIFY and REMOVE
        # alike, confirmed or not. Confirming WORDING is not confirming
        # consistency with the rest of the document.
        self._record_requirement_status(iteration, result)

        # Record a structured audit entry of every patch operation (applied,
        # blocked, errored) so requirement changes are queryable independent of
        # the resulting document and the free-text session log.
        self._record_patch_audit(iteration, response, result, retried)

        return updated

    def _record_requirement_status(self, iteration, result):
        """Put every applied op on probation (best-effort; never break updates)."""
        statuses = getattr(self.context, "requirement_status", None)
        if statuses is None:
            return
        try:
            provenance = getattr(self.context, "requirement_gate_decision", "") or "triage"
            recorded = statuses.record_changes(
                result.get("changes", []), iteration, provenance=provenance)
            if recorded:
                self._debug(
                    "[REQ_STATUS] on probation: "
                    + ", ".join(f"{e.req_id}({e.status})" for e in recorded)
                )
                from ..utils.requirement_status_store import PROBATION_ITERATIONS
                print(f"  🕒 On probation ({PROBATION_ITERATIONS} verified "
                      f"iterations needed): "
                      f"{', '.join(e.req_id for e in recorded)}")
        except Exception as e:
            self._debug(f"[REQ_STATUS] recording failed (non-fatal): {e}")

    def _record_patch_audit(self, iteration, response, result, retried):
        """Append a structured entry to the requirement patch log (best-effort;
        auditing must never break the update flow)."""
        try:
            from ..utils import requirements_store as rs
            from ..utils.requirement_patch_log import RequirementPatchLogEntry

            patch_log = getattr(self.context, "requirement_patch_log", None)
            if patch_log is None:
                return

            parsed = rs.parse_patch(response)
            ops_requested = [
                {"op": op.get("op", ""), "target": op.get("target", "")}
                for op in parsed.get("ops", [])
            ]
            patch_log.add_entry(RequirementPatchLogEntry(
                iteration_id=iteration,
                raw_response=response or "",
                ops_requested=ops_requested,
                applied=list(result.get("applied", [])),
                changes=list(result.get("changes", [])),
                blocked=list(result.get("blocked", [])),
                errors=list(result.get("errors", [])),
                no_change=bool(result.get("no_change", False)),
                changed=bool(result.get("changed", False)),
                retried=retried,
            ))
        except Exception as e:
            self._debug(f"[REQ_PATCH] audit log failed (non-fatal): {e}")


class GenerateSyntaxRepairInstruction(LessonAwareAction):
    """
    Action to generate syntax repair instructions when syntax/type errors are detected.
    Specialized for fixing syntax errors only (not semantic issues).
    Includes previous failed attempts to prevent repeated mistakes.
    """

    name: str = "GenerateSyntaxRepairInstruction"

    async def run(
        self,
        code_snippet: str,
        error_message: str,
        alloy_model: str,
        previous_failed_attempts: list = None,
        known_good_attempts: list = None,
        user_guidance: str = "",
        pattern_status: str = ""
    ) -> str:
        """
        Generate syntax repair instructions.

        Args:
            code_snippet: Code snippet with syntax error
            error_message: Error message from Alloy Analyzer
            alloy_model: Current Alloy model code
            previous_failed_attempts: List of {feedback, changes} dicts from failed attempts
            known_good_attempts: List of {feedback, changes} dicts from prior repairs that
                RESOLVED their target issue - surfaced as proven approaches, NOT forbidden
            user_guidance: Optional user guidance when previous attempts failed
            pattern_status: Cross-iteration escalation evidence block from the
                RepairPlateauDetector (pattern type, matched iterations,
                forbidden prior fixes, required strategy)

        Returns:
            Syntax repair instructions
        """
        # Get lessons, ranked by semantic similarity to the actual error
        lessons = self.get_lessons_for_context(
            context_query=error_message,
            limit=5
        )
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Format previous failed attempts
        failed_attempts_str = "None - this is the first attempt."
        if previous_failed_attempts and len(previous_failed_attempts) > 0:
            attempts = []
            for i, attempt in enumerate(previous_failed_attempts, 1):
                attempts.append(f"--- Attempt {i} ---")
                attempts.append(f"Feedback: {attempt.get('feedback', 'N/A')}")
                attempts.append(f"Changes Made: {attempt.get('changes', 'N/A')}")
                attempts.append("")
            failed_attempts_str = "\n".join(attempts)

        # Format known-good approaches (prior repairs that RESOLVED their target issue).
        # These are NOT forbidden - the same error family recurring in a different block
        # is a new site, so a proven fix should be reused, adapted to the current location.
        known_good_str = "None recorded."
        if known_good_attempts and len(known_good_attempts) > 0:
            good = []
            for i, attempt in enumerate(known_good_attempts, 1):
                good.append(f"--- Known-Good Approach {i} {attempt.get('changes', '')} ---")
                good.append(f"Repair that RESOLVED a matching error earlier: {attempt.get('feedback', 'N/A')}")
                good.append("")
            known_good_str = "\n".join(good)

        # Get failed fix history from regression log
        from ..utils.regression_log import format_failed_fix_history
        regression_failed_fixes = "None"

        iteration = self.get_current_iteration()
        regression_log = self.context.regression_log
        current_entry = regression_log.get_entry(iteration)

        if current_entry and current_entry.issue:
            regression_failed_fixes = format_failed_fix_history(
                current_issue=current_entry.issue,
                regression_log_entries=regression_log.entries
            )

        # Choose prompt section based on whether user guidance is provided
        if user_guidance and user_guidance.strip():
            # Use RefineSyntaxRepairInstruction section when user provides guidance
            action_name_for_prompt = "RefineSyntaxRepairInstruction"
            self._debug(
                "🔄 Feedback is refined with RefineSyntaxRepairInstruction prompt "
                "(incorporating user guidance into syntax repair instructions)"
            )
        else:
            # Use default GenerateSyntaxRepairInstruction section
            action_name_for_prompt = self.action_name

        # Render prompt with appropriate section
        prompt = self.context.prompt_manager.render_prompt(
            agent_name=self.agent_name,
            action_name=action_name_for_prompt,
            code_snippet=code_snippet,
            error_message=error_message,
            alloy_model=alloy_model,
            lessons=lessons_str,
            previous_failed_attempts=failed_attempts_str,
            known_good_approaches=known_good_str,
            failed_fix_history=regression_failed_fixes,
            user_guidance=user_guidance,
            pattern_status=pattern_status if pattern_status and pattern_status.strip() else (
                "No cross-iteration error pattern detected - this is the first "
                "occurrence of this error."
            )
        )

        # Call LLM - temporarily use the actual prompt section name so the
        # logged LLM communication header reflects RefineSyntaxRepairInstruction
        # rather than always showing GenerateSyntaxRepairInstruction
        original_action_name = self.action_name
        self.action_name = action_name_for_prompt
        try:
            response = await self._aask(prompt)
        finally:
            self.action_name = original_action_name

        # Parse and record learning; deferred until the targeted issue is
        # confirmed resolved next iteration
        self.parse_and_record_learning(response, defer=True, pending_attr='pending_evaluator_feedback_lesson')

        return response





class RefineFeedback(LessonAwareAction):
    """
    Action to refine draft feedback based on user input (two-phase evaluation).

    This is used when we want to get user review before finalizing feedback.
    """

    name: str = "RefineFeedback"

    async def run(
        self,
        draft_feedback: str,
        user_review: str,
        requirements_document: str = ""
    ) -> str:
        """
        Refine feedback based on user review.

        Args:
            draft_feedback: Initial draft feedback
            user_review: User's review comments
            requirements_document: Current requirements document. Annotated with
                [E#] markers and shown to the model so it can run the
                REQUIREMENT-CHANGE TRIAGE (dedup / placement / classify) on any
                requirement or constraint change the user review proposes.

        Returns:
            Refined final feedback
        """
        from ..utils import requirements_store as rs

        # Get lessons, ranked by semantic similarity to the user's review comments
        lessons = self.get_lessons_for_context(context_query=user_review, limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        # Annotate the document with [E#] markers so triage can address bullets,
        # and with each item's standing so the triage can see which items are
        # themselves still unverified.
        annotated_doc = (
            self.annotate_requirements(requirements_document, addressing_markers=True)
            if requirements_document else "(current requirements unavailable)"
        )

        # Render prompt from template
        prompt = self.render_prompt(
            draft_feedback=draft_feedback,
            user_review=user_review,
            lessons=lessons_str,
            user_preferences=user_prefs,
            requirements_document=annotated_doc
        )

        # Append the shared triage decision procedure so user-proposed
        # requirement/constraint changes are deduped, placed, and classified
        # before they reach the document.
        triage_section = self.context.prompt_manager.get_section(
            "Evaluator", "RequirementChangeTriage"
        )
        prompt = prompt + "\n\n" + triage_section

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning
        self.parse_and_record_learning(response)

        return response
