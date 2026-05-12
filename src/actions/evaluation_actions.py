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

        # Render base prompt
        prompt = self.render_prompt(
            analyzer_results=results_str,
            requirements_document=requirements_document,
            alloy_model=model_context,  # Use placeholder or full model
            user_preferences=user_prefs
        )

        # Conditionally append special case sections based on analyzer results
        has_counterexamples = analysis.get('has_counterexamples', False)
        no_counterexamples = not has_counterexamples
        no_unsat_run_commands = len(analysis.get('unsat_run_commands', [])) == 0

        # Include InterpretCounterexample section if counterexamples exist
        if has_counterexamples:
            counterexample_section = self.context.prompt_manager.get_section(
                "Evaluator", 
                "InterpretCounterexample"
            )
            prompt = prompt + "\n\n" + counterexample_section

        # Include InterpretSatInstance section if success state
        # Conditions: no syntax errors, no counterexamples, all run commands SAT
        if not has_syntax_errors and no_counterexamples and no_unsat_run_commands:
            sat_instance_section = self.context.prompt_manager.get_section(
                "Evaluator", 
                "InterpretSatInstance"
            )
            prompt = prompt + "\n\n" + sat_instance_section

        # Call LLM
        response = await self._aask(prompt)

        # Parse and record learning, get cleaned output
        cleaned_response = self.parse_and_record_learning(response)

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
        counterexamples = analysis.get('counterexamples', [])
        total_check_commands = analysis.get('total_check_commands', 0)
        if counterexamples:
            lines.append(f"COUNTEREXAMPLES FOUND: {len(counterexamples)}/{total_check_commands}")
            for i, ce in enumerate(counterexamples[:5], 1):  # Limit to 5
                if isinstance(ce, dict):
                    cmd_name = ce.get('command_name', 'Unknown')
                    lines.append(f"\n  {i}. {cmd_name}:")
                    # Include full JSON data
                    import json
                    ce_data = ce.get('data', {})
                    lines.append(f"     {json.dumps(ce_data, indent=6)}")
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
        instances = analysis.get('instances', [])
        total_run_commands = analysis.get('total_run_commands', 0)
        if instances:
            lines.append(f"SATISFYING INSTANCES: {len(instances)}/{total_run_commands}")
            for i, inst in enumerate(instances, 1):  # Show all instances
                if isinstance(inst, dict):
                    cmd_name = inst.get('command_name', 'Unknown')
                    lines.append(f"  {i}. {cmd_name}")
                else:
                    lines.append(f"  {i}. {inst}")
        else:
            lines.append(f"SATISFYING INSTANCES: 0/{total_run_commands}")
            lines.append("(No instances were generated by the analyzer)")

        # Add comprehensive instance analysis if success state
        # Conditions: no syntax errors, no counterexamples, all run commands SAT (no unsatisfiable predicates)
        no_syntax_errors = not analysis.get('has_syntax_errors', False)
        no_counterexamples = not analysis.get('has_counterexamples', False)
        no_unsat_run_commands = len(analysis.get('unsat_run_commands', [])) == 0

        if no_syntax_errors and no_counterexamples and no_unsat_run_commands:
            comprehensive_instance = self._find_comprehensive_instance(instances)

            if comprehensive_instance:
                lines.append("")
                lines.append("=" * 80)
                lines.append("COMPREHENSIVE INSTANCE ANALYSIS")
                lines.append("=" * 80)
                lines.append("")
                # lines.append("All assertions passed and all predicates are satisfiable.")
                # lines.append("Analyze the most comprehensive satisfying instance below to verify:")
                # lines.append("- All requirements are correctly captured")
                # lines.append("- No unintended behaviors are allowed")
                # lines.append("- All requirement interactions are properly modeled")
                lines.append("")
                lines.append(f"INSTANCE: {comprehensive_instance['command_name']}")
                lines.append("")

                import json
                instance_data = comprehensive_instance.get('data', {})
                lines.append(json.dumps(instance_data, indent=2))

        return "\n".join(lines)

    def _find_comprehensive_instance(self, instances: List[Dict]) -> Optional[Dict]:
        """
        Find the most comprehensive satisfying instance.

        Priority:
        1. Instance named "All_Requirements"
        2. Last instance in the list (typically most comprehensive run statement)

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

        # Priority 2: Return last instance (typically most comprehensive run statement)
        return instances[-1]


class GenerateFeedback(LessonAwareAction):
    """
    Action to generate actionable feedback based on interpretation.
    """

    name: str = "GenerateFeedback"

    async def run(
        self,
        interpretation: str,
        requirements_document: str,
        alloy_model: str
    ) -> str:
        """
        Generate actionable feedback for RE agent.

        Args:
            interpretation: Verification interpretation
            requirements_document: Current requirements
            alloy_model: Current Alloy model code

        Returns:
            Structured feedback
        """
        # Get lessons
        lessons = self.get_lessons(limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

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
            user_preferences=user_prefs
        )

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
