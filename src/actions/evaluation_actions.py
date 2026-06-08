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

        # Get regression log context (only previous iteration)
        regression_log_str = self.context.regression_log.format_for_prompt(count=1)

        # Render base prompt
        prompt = self.render_prompt(
            analyzer_results=results_str,
            requirements_document=requirements_document,
            alloy_model=model_context,  # Use placeholder or full model
            regression_log=regression_log_str,
            user_preferences=user_prefs
        )

        # Conditionally append specialized sections based on analyzer results
        has_counterexamples = analysis.get('has_counterexamples', False)
        no_counterexamples = not has_counterexamples
        has_unsat_run_commands = len(analysis.get('unsat_run_commands', [])) > 0
        no_unsat_run_commands = not has_unsat_run_commands
        
        # Calculate positive predicate satisfaction for conditional sections
        positive_runs = analysis.get('positive_run_commands', 0)
        satisfied_positive = analysis.get('satisfied_positive_runs', 0)
        all_positive_satisfied = (positive_runs > 0 and positive_runs == satisfied_positive)

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
            prompt = prompt + "\n\n" + unsat_pred_section

        # Include InterpretCounterexample section only when:
        # 1. Counterexamples exist, AND
        # 2. All positive predicates are satisfied (or no UNSAT predicates at all)
        # This ensures we don't analyze counterexamples when positive predicates are UNSAT
        positive_runs = analysis.get('positive_run_commands', 0)
        satisfied_positive = analysis.get('satisfied_positive_runs', 0)
        all_positive_satisfied = (positive_runs > 0 and positive_runs == satisfied_positive)
        
        # Include counterexample analysis only if all positive predicates are satisfied
        # (any UNSAT predicates must be negative test predicates)
        if has_counterexamples and (no_unsat_run_commands or all_positive_satisfied):
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

        # Include InterpretSatInstance section if there are satisfying instances
        has_satisfying_instances = analysis.get('has_satisfying_instances', False)
        if has_satisfying_instances and not has_syntax_errors:
            sat_instance_section = self.context.prompt_manager.get_section(
                "Evaluator",
                "InterpretSatInstance"
            )
            # Format satisfying instances for this section
            satisfying_instances_str = self._format_satisfying_instances(analysis)
            # Render the section with satisfying_instances variable
            sat_instance_section_rendered = self.context.prompt_manager._substitute_variables(
                sat_instance_section,
                {"satisfying_instances": satisfying_instances_str}
            )
            prompt = prompt + "\n\n" + sat_instance_section_rendered

        # Include VacuityAnalysis section if hard metrics pass
        # Conditions: no syntax errors, no counterexamples, all positive runs satisfied
        if not has_syntax_errors and no_counterexamples and all_positive_satisfied:
            vacuity_section = self.context.prompt_manager.get_section(
                "Evaluator",
                "VacuityAnalysis"
            )
            prompt = prompt + "\n\n" + vacuity_section

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning, get cleaned output
        cleaned_response = self.parse_and_record_learning(response)

        # Parse outcome_classification from response and update regression log
        outcome_classification = self._parse_outcome_classification(cleaned_response)
        if outcome_classification:
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

        Extracts up to 3 sample instances (prioritizing comprehensive instance)
        for quality assessment.

        Args:
            analysis: Analysis dictionary from alloy_executor

        Returns:
            Formatted string with sample instances
        """
        import json

        sample_instances = analysis.get('sample_instances', [])
        comprehensive = analysis.get('comprehensive_instance')

        if not sample_instances:
            return "(No satisfying instances available for review)"

        lines = []
        lines.append("The following satisfying instances are provided for quality assessment:")
        lines.append("")

        for idx, inst in enumerate(sample_instances, 1):
            cmd_name = inst.get("command_name", "Unknown")
            is_comprehensive = (inst == comprehensive)
            marker = " [COMPREHENSIVE - includes All_Requirements]" if is_comprehensive else ""

            lines.append(f"Instance {idx}: {cmd_name}{marker}")
            lines.append(f"File: {inst.get('file', 'Unknown')}")
            lines.append("")

            # Include instance data (limited to avoid token bloat)
            instance_data = inst.get('data', {})
            data_str = json.dumps(instance_data, indent=2)

            # Limit each instance to ~1000 characters
            if len(data_str) > 1000:
                data_str = data_str[:1000] + "\n... (truncated for brevity)"

            lines.append(data_str)
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
            ce_data = ce.get('data', {})
            data_str = json.dumps(ce_data, indent=2)

            lines.append(data_str)
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

    name: str = "GenerateFeedback"

    async def run(
        self,
        interpretation: str,
        requirements_document: str,
        alloy_model: str,
        relevant_qa: str = ""
    ) -> str:
        """
        Generate actionable feedback for RE agent.

        Args:
            interpretation: Verification interpretation
            requirements_document: Current requirements
            alloy_model: Current Alloy model code
            relevant_qa: Formatted relevant Q&A records from previous iterations

        Returns:
            Structured feedback
        """
        # Get lessons
        lessons = self.get_lessons(limit=5)
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

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning
        self.parse_and_record_learning(response)

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
        Update requirements document.

        Args:
            requirements_document: Current requirements
            feedback: Verification feedback
            user_feedback: User's feedback (if any)

        Returns:
            Updated requirements document
        """
        # # Get lessons
        # lessons = self.get_lessons(limit=5)
        # lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        # Render prompt
        prompt = self.render_prompt(
            requirements_document=requirements_document,
            feedback=feedback,
            user_feedback=user_feedback if user_feedback else "No user feedback provided.",
            # lessons=lessons_str,
            user_preferences=user_prefs
        )

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning
        #self.parse_and_record_learning(response)

        # Store updated requirements
        iteration = self.get_current_iteration()
        self.get_artifacts().store_requirements(iteration, response)

        return response


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
        previous_failed_attempts: list = None
    ) -> str:
        """
        Generate syntax repair instructions.

        Args:
            code_snippet: Code snippet with syntax error
            error_message: Error message from Alloy Analyzer
            alloy_model: Current Alloy model code
            previous_failed_attempts: List of {feedback, changes} dicts from failed attempts

        Returns:
            Syntax repair instructions
        """
        # Get lessons related to syntax errors
        lessons = self.get_lessons_for_context(
            context_query="syntax error",
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

        # Render prompt
        prompt = self.render_prompt(
            code_snippet=code_snippet,
            error_message=error_message,
            alloy_model=alloy_model,
            lessons=lessons_str,
            previous_failed_attempts=failed_attempts_str,
            failed_fix_history=regression_failed_fixes
        )

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning
        self.parse_and_record_learning(response)

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
        user_review: str
    ) -> str:
        """
        Refine feedback based on user review.

        Args:
            draft_feedback: Initial draft feedback
            user_review: User's review comments

        Returns:
            Refined final feedback
        """
        # Get lessons
        lessons = self.get_lessons(limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        # Render prompt from template
        prompt = self.render_prompt(
            draft_feedback=draft_feedback,
            user_review=user_review,
            lessons=lessons_str,
            user_preferences=user_prefs
        )

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning
        self.parse_and_record_learning(response)

        return response
