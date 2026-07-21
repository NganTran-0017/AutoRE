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
        # Get lessons from memory, ranked by semantic similarity to the input
        lessons = self.get_lessons_for_context(context_query=raw_requirements, limit=5)
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
        # Get lessons, ranked by semantic similarity to the user's clarifications
        lessons = self.get_lessons_for_context(context_query=user_clarifications, limit=5)
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
        # Get lessons, ranked by semantic similarity to the requirements
        lessons = self.get_lessons_for_context(context_query=requirements_document, limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Get all established modeling conventions (always injected in full)
        conventions_str = self.get_modeling_conventions() or "No modeling conventions established yet."

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        # Render prompt
        prompt = self.render_prompt(
            requirements_document=requirements_document,
            user_feedback=user_feedback if user_feedback else "No user feedback yet.",
            lessons=lessons_str,
            modeling_conventions=conventions_str,
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
    
    Supports two modes:
    - Mode 1 (syntax): Minimal syntax-only repairs after GenerateSyntaxRepairInstruction
    - Mode 2 (semantic): Full semantic improvements after GenerateSemanticFeedback
    """

    name: str = "UpdateAlloyModel"

    async def run(
        self,
        current_model: str,
        evaluation_feedback: str,
        requirements_document: str,
        mode: str = "semantic",
        escalation_directive: str = ""
    ) -> str:
        """
        Update Alloy model based on evaluator feedback.

        Args:
            current_model: Current Alloy model code
            evaluation_feedback: Feedback from Evaluator
            requirements_document: Latest requirements (only used in semantic mode)
            mode: Either "syntax" or "semantic" - determines repair constraints
            escalation_directive: Cross-iteration escalation evidence block from
                the RepairPlateauDetector (forbidden prior fixes, oscillation
                partner, rewrite-block requirement); empty when no escalation

        Returns:
            Updated Alloy model code
        """
        # Validate mode
        if mode not in ["syntax", "semantic"]:
            raise ValueError(f"Invalid mode: {mode}. Must be 'syntax' or 'semantic'")

        # Get lessons, ranked by semantic similarity to the evaluator's feedback
        lessons = self.get_lessons_for_context(context_query=evaluation_feedback, limit=5)
        lessons_str = self.format_lessons(lessons) if lessons else "No previous lessons."

        # Get all established modeling conventions (always injected in full)
        conventions_str = self.get_modeling_conventions() or "No modeling conventions established yet."

        # Get user preferences
        user_prefs = self.get_user_preferences()
        if not user_prefs:
            user_prefs = ""

        # Retry logic for syntax mode to catch snippet responses
        max_retries = 3
        length_threshold = 0.5  # Reject if response is less than 50% of original
        
        # Track rejected models for debugging
        rejected_models = []  # List of {attempt_number, model, reason, issues}
        
        for attempt in range(max_retries):
            # Build prompt based on mode
            prompt = self._build_prompt(
                mode=mode,
                current_model=current_model,
                evaluation_feedback=evaluation_feedback,
                requirements_document=requirements_document,
                lessons_str=lessons_str,
                conventions_str=conventions_str,
                user_prefs=user_prefs,
                escalation_directive=escalation_directive
            )
            
            # Add retry warning for syntax mode if this is not the first attempt
            if mode == "syntax" and attempt > 0:
                retry_warning = f"\n\n**CRITICAL WARNING - RETRY {attempt}/{max_retries}:**\n"
                retry_warning += "Your previous response was REJECTED because it was too short.\n"
                retry_warning += "You MUST return the COMPLETE, FULL Alloy model - every single line.\n"
                retry_warning += "DO NOT return only the modified section or a snippet.\n"
                retry_warning += "The system needs the ENTIRE model from first line to last line.\n"
                prompt = prompt + retry_warning

            # Call LLM
            response = await self._aask(prompt)

            # Parse and record learning, get cleaned output; deferred until
            # the targeted issue is confirmed resolved next iteration
            cleaned_response = self.parse_and_record_learning(response, defer=True, pending_attr='pending_re_fix_lesson')
            
            # Validate response for syntax mode
            if mode == "syntax":
                # First check: Length validation
                is_valid_length, length_msg = self._validate_model_length(
                    current_model=current_model,
                    updated_response=cleaned_response,
                    threshold=length_threshold
                )
                
                if not is_valid_length:
                    # Track rejected model
                    rejected_models.append({
                        'attempt_number': attempt + 1,
                        'model': cleaned_response,
                        'reason': 'Length validation failed',
                        'details': length_msg
                    })
                    print(f"  ⚠️  {length_msg}")
                    print(f"  🔄 Retrying (attempt {attempt + 1}/{max_retries})...")
                    continue  # Retry
                
                # Second check: Structure validation (comprehensive)
                from src.utils.alloy_model_validator import validate_alloy_model_completeness
                
                is_valid_structure, structure_issues = validate_alloy_model_completeness(
                    model_code=cleaned_response,
                    check_structure=True,
                    check_snippets=True
                )
                
                if not is_valid_structure:
                    # Track rejected model
                    rejected_models.append({
                        'attempt_number': attempt + 1,
                        'model': cleaned_response,
                        'reason': 'Structure validation failed',
                        'details': structure_issues
                    })
                    # Model failed structure validation - likely a snippet
                    print(f"  ⚠️  Model structure validation failed:")
                    for issue in structure_issues[:3]:  # Show first 3 issues
                        print(f"      - {issue}")
                    print(f"  🔄 Retrying (attempt {attempt + 1}/{max_retries})...")
                    continue  # Retry
                
                # Both validations passed
                print(f"  ✓ {length_msg}")
                print(f"  ✓ Model structure validation passed")
                break  # Valid response, exit retry loop
            else:
                # Semantic mode - no validation needed
                break
        else:
            # All retries exhausted (for loop completed without break)
            if mode == "syntax" and rejected_models:
                # Save all rejected models to file for inspection
                from datetime import datetime
                from pathlib import Path
                
                timestamp = datetime.now().strftime("%m%d")
                output_dir = Path("Output/AlloyModels")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_file = output_dir / f"RejectedCodeSnippet_{timestamp}.als"
                
                # Write all rejected attempts to file
                with open(output_file, 'w') as f:
                    f.write(f"// REJECTED CODE SNIPPETS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"// All {len(rejected_models)} attempts failed validation\n")
                    f.write(f"// Iteration: {self.get_current_iteration()}\n")
                    f.write("=" * 80 + "\n\n")
                    
                    for rejected in rejected_models:
                        f.write(f"\n{'=' * 80}\n")
                        f.write(f"ATTEMPT {rejected['attempt_number']}\n")
                        f.write(f"Reason: {rejected['reason']}\n")
                        f.write(f"Details: {rejected['details']}\n")
                        f.write(f"{'=' * 80}\n\n")
                        f.write(rejected['model'])
                        f.write("\n\n")
                
                warning_msg = (
                    f"⚠️  UpdateAlloyModel (syntax mode) - all {max_retries} attempts failed validation.\n"
                    f"    All rejected models saved to: {output_file}\n"
                    f"    Proceeding with last attempt (may contain errors)."
                )
                self.context.logger.log(warning_msg)
                print(f"\n  ⚠️  All {max_retries} validation attempts failed")
                print(f"  📝 Rejected models saved to: {output_file}")
                print(f"  ⚠️  Proceeding with last attempt (model may be incomplete)\n")

        # Final validation and structure analysis (for logging/debugging)
        from src.utils.alloy_model_validator import validate_model_structure_details
        
        structure = validate_model_structure_details(cleaned_response)
        
        # Log structure details
        self.context.logger.log("\n" + "="*80)
        self.context.logger.log(f"Updated Alloy Model Structure (Iteration {self.get_current_iteration()}):")
        self.context.logger.log(f"  Mode: {mode}")
        self.context.logger.log(f"  Signatures: {structure['signature_count']}")
        self.context.logger.log(f"  Facts: {structure['fact_count']}")
        self.context.logger.log(f"  Predicates: {structure['predicate_count']}")
        self.context.logger.log(f"  Assertions: {structure['assertion_count']}")
        self.context.logger.log(f"  Run commands: {structure['run_count']}")
        self.context.logger.log(f"  Check commands: {structure['check_count']}")
        self.context.logger.log(f"  Total lines: {structure['line_count']}")
        self.context.logger.log(f"  Has baseline: {structure['has_baseline']}")
        self.context.logger.log(f"  Has All_Requirements: {structure['has_all_requirements']}")
        self.context.logger.log("="*80 + "\n")

        # Store cleaned output in artifacts
        iteration = self.get_current_iteration()
        self.get_artifacts().store_alloy_model(iteration, cleaned_response)

        return cleaned_response

    def _validate_model_length(
        self,
        current_model: str,
        updated_response: str,
        threshold: float
    ) -> tuple[bool, str]:
        """
        Validate that updated model is not drastically shorter than current model.
        
        This catches cases where the LLM returns only a snippet instead of the full model.
        
        Args:
            current_model: Original Alloy model
            updated_response: Response from LLM (may contain metadata + code)
            threshold: Minimum acceptable length ratio (e.g., 0.5 = 50%)
            
        Returns:
            Tuple of (is_valid: bool, message: str)
        """
        from src.utils.alloy_model_validator import extract_alloy_code

        # Extract alloy code from response (if wrapped in ```alloy blocks);
        # falls back to the whole response when no code block is present
        updated_model = extract_alloy_code(updated_response)
        
        # Calculate lengths (using line count as primary metric)
        current_lines = len([line for line in current_model.split('\n') if line.strip()])
        updated_lines = len([line for line in updated_model.split('\n') if line.strip()])
        
        # Also check character count as secondary metric
        current_chars = len(current_model.strip())
        updated_chars = len(updated_model.strip())
        
        # Calculate ratios
        line_ratio = updated_lines / current_lines if current_lines > 0 else 0
        char_ratio = updated_chars / current_chars if current_chars > 0 else 0
        
        # Consider invalid if either metric drops below threshold
        if line_ratio < threshold or char_ratio < threshold:
            msg = (
                f"Model length validation FAILED: "
                f"Lines {updated_lines}/{current_lines} ({line_ratio:.1%}), "
                f"Chars {updated_chars}/{current_chars} ({char_ratio:.1%}). "
                f"Threshold: {threshold:.0%}"
            )
            return False, msg
        else:
            msg = (
                f"Model length validation passed: "
                f"Lines {updated_lines}/{current_lines} ({line_ratio:.1%}), "
                f"Chars {updated_chars}/{current_chars} ({char_ratio:.1%})"
            )
            return True, msg

    def _build_prompt(
        self,
        mode: str,
        current_model: str,
        evaluation_feedback: str,
        requirements_document: str,
        lessons_str: str,
        user_prefs: str,
        escalation_directive: str = "",
        conventions_str: str = "No modeling conventions established yet."
    ) -> str:
        """
        Build prompt based on mode (syntax or semantic).
        
        Mode 1 (syntax): Base + Mode1_SyntaxRepair + ResponseFormat (unified)
        Mode 2 (semantic): Base + Mode2_SemanticRepair + ResponseFormat (unified)
        
        Args:
            mode: "syntax" or "semantic"
            current_model: Current Alloy model
            evaluation_feedback: Evaluator feedback
            requirements_document: Latest requirements
            lessons_str: Formatted lessons
            user_prefs: User preferences
            
        Returns:
            Complete prompt string
        """
        prompt_manager = self.context.prompt_manager
        agent_name = self.agent_name  # "RE"
        
        # Get base section (shared by both modes)
        base_section = prompt_manager.get_section(agent_name, "UpdateAlloyModel_Base")
        
        # Get shared sections
        response_format = prompt_manager.get_section(agent_name, "ResponseFormatUpdateAlloyModel")
        quality_standards = prompt_manager.get_section(agent_name, "QualityStandards")
        learning_instructions = prompt_manager.get_section(agent_name, "LearningInstructions")
        
        # Build prompt based on mode
        sections = [base_section]
        
        if mode == "syntax":
            # Mode 1: Syntax repair
            mode_section = prompt_manager.get_section(agent_name, "UpdateAlloyModel_Mode1_SyntaxRepair")
            sections.append(mode_section)
        else:
            # Mode 2: Semantic repair
            mode_section = prompt_manager.get_section(agent_name, "UpdateAlloyModel_Mode2_SemanticRepair")
            sections.append(mode_section)
        
        # Add shared sections (same for both modes)
        sections.extend([response_format, quality_standards, learning_instructions])
        
        # Combine sections
        template = "\n\n".join(filter(None, sections))
        
        # Prepare variables for substitution
        variables = {
            "current_model": current_model,
            "evaluation_feedback": evaluation_feedback,
            "lessons": lessons_str,
            "modeling_conventions": conventions_str,
            "user_preferences": user_prefs,
            "escalation_directive": escalation_directive if escalation_directive and escalation_directive.strip() else (
                "None - no cross-iteration escalation is active."
            )
        }
        
        # For semantic mode, include requirements document
        if mode == "semantic":
            variables["requirements_document"] = requirements_document
        
        # Substitute variables
        rendered = prompt_manager._substitute_variables(template, variables)
        
        return rendered
