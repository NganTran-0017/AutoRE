"""
Prompt template manager with string replacement.
"""
from pathlib import Path
from typing import Dict, Any, List
import re


class PromptManager:
    """
    Manages prompt templates for all agents and actions.

    Prompt file structure:
        [SECTION: Role]
        You are a requirement engineer...

        [SECTION: AnalyzeRequirements]
        Task: Analyze the requirements...
        Input: {{raw_requirements}}
        Lessons: {{lessons}}

    Variables in templates use {{variable_name}} syntax and are replaced
    with str.replace().
    """

    def __init__(self):
        """Initialize and load all prompt files."""
        self.prompts: Dict[str, Dict[str, str]] = {}
        self._load_all_prompts()

    def _load_all_prompts(self):
        """Load all prompt files from prompts/ directory."""
        prompt_dir = Path("prompts")
        if not prompt_dir.exists():
            raise FileNotFoundError(f"Prompts directory not found: {prompt_dir}")

        for prompt_file in prompt_dir.glob("*_prompt.txt"):
            agent_name = self._extract_agent_name(prompt_file)
            self.prompts[agent_name] = self._parse_prompt_file(prompt_file)

    def _extract_agent_name(self, file_path: Path) -> str:
        """
        Extract agent name from prompt filename.

        Examples:
            RE_prompt.txt → RE
            Evaluator_prompt.txt → Evaluator
        """
        stem = file_path.stem  # e.g., "RE_prompt"
        return stem.replace("_prompt", "")

    def _parse_prompt_file(self, file_path: Path) -> Dict[str, str]:
        """
        Parse prompt file into sections.

        Returns:
            Dictionary mapping section names to content
            {"SectionName": "content", ...}
        """
        sections = {}
        current_section = None
        current_content = []

        with open(file_path, encoding='utf-8') as f:
            for line in f:
                # Check for section header
                if line.strip().startswith("[SECTION:"):
                    # Save previous section
                    if current_section:
                        sections[current_section] = "\n".join(current_content).strip()

                    # Start new section
                    match = re.match(r'\[SECTION:\s*(.+?)\s*\]', line.strip())
                    if match:
                        current_section = match.group(1)
                        current_content = []
                else:
                    # Accumulate content
                    current_content.append(line.rstrip())

        # Save last section
        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def render_prompt(
        self,
        agent_name: str,
        action_name: str,
        **variables
    ) -> str:
        """
        Render complete prompt for action with variable substitution.

        Combines:
        - Role section (agent context)
        - Action-specific section
        - ResponseFormat section (action-specific or generic)
        - QualityStandards section (if exists)

        Then substitutes all {{variable}} placeholders with provided values.

        Args:
            agent_name: Agent name (e.g., "RE", "Evaluator")
            action_name: Action name (e.g., "AnalyzeRequirements")
            **variables: Template variables to substitute

        Returns:
            Fully rendered prompt string

        Raises:
            KeyError: If agent or action not found
            ValueError: If required variables not provided
        """
        # Get agent's prompt sections
        if agent_name not in self.prompts:
            raise KeyError(f"No prompts found for agent: {agent_name}")

        agent_prompts = self.prompts[agent_name]

        # Get required sections
        role = agent_prompts.get("Role", "")
        action_section = agent_prompts.get(action_name, "")

        if not action_section:
            raise KeyError(
                f"No prompt section found for action '{action_name}' "
                f"in agent '{agent_name}'"
            )

        # Map actions to their response format sections
        action_to_format = {
            # RE agent - Requirements actions
            "AnalyzeRequirements": "ResponseFormatRequirements",
            "IncorporateClarifications": "ResponseFormatRequirements",
            
            # RE agent - Alloy model actions
            "BuildAlloyModel": "ResponseFormatAlloyModel",
            "UpdateAlloyModel": "ResponseFormatUpdateAlloyModel",
            
            # Evaluator agent - Specific response formats
            "InterpretResults": "ResponseFormatInterpretation",
            "GenerateFeedback": "ResponseFormatFeedback",
            "UpdateRequirements": "ResponseFormatRequirements",
            "RefineFeedback": "ResponseFormatFeedback",  # Uses same format as GenerateFeedback
        }

        # Determine which ResponseFormat section to use
        format_section_name = action_to_format.get(action_name, "ResponseFormat")
        response_format = agent_prompts.get(format_section_name, "")
        
        # Fall back to generic ResponseFormat if specific one not found
        if not response_format and format_section_name != "ResponseFormat":
            response_format = agent_prompts.get("ResponseFormat", "")

        # Get optional sections
        quality_standards = agent_prompts.get("QualityStandards", "")
        learning_instructions = agent_prompts.get("LearningInstructions", "")
        abstraction_guidance = agent_prompts.get("AbstractionGuidance", "")
        analysis_principles = agent_prompts.get("AnalysisPrinciples", "")
        primary_goal = agent_prompts.get("PrimaryGoal", "")
        convergence_criteria = agent_prompts.get("ConvergenceCriteria", "")

        # Define which actions should include AbstractionGuidance
        actions_with_abstraction = {
            "AnalyzeRequirements",      # RE - initial requirements analysis
            "GenerateFeedback"#,         # Evaluator - formulating user questions
           # "UpdateRequirements",       # Evaluator - updating requirements
        }

        # Define which actions should include AnalysisPrinciples
        actions_with_analysis = {
            "InterpretResults",         # Evaluator - interpreting verification results
        }

        # Define which actions should NOT include PrimaryGoal
        actions_without_primary_goal = {
            "GenerateFeedback",         # Evaluator - feedback generation doesn't need primary goal
            "UpdateRequirements",       # Evaluator - updating requirements doesn't need primary goal
            "RefineFeedback",           # Evaluator - refining feedback doesn't need primary goal
        }

        # Define which actions should NOT include ConvergenceCriteria
        actions_without_convergence = {
            "UpdateRequirements",       # Evaluator - updating requirements doesn't need convergence criteria
            "GenerateSyntaxRepairInstruction",  # Evaluator - syntax repair is pre-verification, no convergence concept
        }

        # Define which actions should NOT include QualityStandards
        actions_without_quality_standards = {
            "IncorporateClarifications",  # RE - incorporating clarifications is straightforward update
            "UpdateRequirements",  # Evaluator - updating requirements is straightforward document update
            "GenerateSyntaxRepairInstruction",  # Evaluator - syntax repair has specific quality requirements in its own prompt
        }

        # Define which actions should NOT include LearningInstructions
        actions_without_learning = {
            "IncorporateClarifications",  # RE - simple clarification incorporation doesn't need learning
            "UpdateRequirements",  # Evaluator - updating requirements is straightforward document update
        }

        # Define which actions should NOT include Role section
        actions_without_role = {
            "RefineFeedback",  # Evaluator - refining feedback is a simple adjustment task
            "UpdateRequirements",  # Evaluator - updating requirements is straightforward document update
        }

        # Combine sections - conditionally add role
        sections = []
        if action_name not in actions_without_role:
            sections.append(role)
        sections.append(action_section)

        # Add PrimaryGoal for all actions except those in exclusion list
        if primary_goal and action_name not in actions_without_primary_goal:
            sections.append(primary_goal)

        # Add AbstractionGuidance only for specific actions
        if abstraction_guidance and action_name in actions_with_abstraction:
            sections.append(abstraction_guidance)

        # Add AnalysisPrinciples only for specific actions
        if analysis_principles and action_name in actions_with_analysis:
            sections.append(analysis_principles)

        if response_format:
            sections.append(response_format)
        
        # Add QualityStandards for all actions except those in exclusion list
        if quality_standards and action_name not in actions_without_quality_standards:
            sections.append(quality_standards)

        # Add ConvergenceCriteria for all actions except those in exclusion list
        if convergence_criteria and action_name not in actions_without_convergence:
            sections.append(convergence_criteria)

        # Add LearningInstructions for all actions except those in exclusion list
        if learning_instructions and action_name not in actions_without_learning:
            sections.append(learning_instructions)

        template = "\n\n".join(filter(None, sections))

        # Perform variable substitution
        rendered = self._substitute_variables(template, variables)

        return rendered

    def _substitute_variables(self, template: str, variables: Dict[str, Any]) -> str:
        """
        Replace {{variable}} placeholders with values.

        Args:
            template: Template string with {{variable}} placeholders
            variables: Dictionary of variable names to values

        Returns:
            Template with all variables substituted

        Raises:
            ValueError: If a required variable is missing
        """
        # Find all variables in template
        var_pattern = r'\{\{(\w+)\}\}'
        required_vars = set(re.findall(var_pattern, template))

        # Check for missing variables
        provided_vars = set(variables.keys())
        missing_vars = required_vars - provided_vars

        if missing_vars:
            raise ValueError(
                f"Missing required variables: {', '.join(sorted(missing_vars))}"
            )

        # Substitute each variable
        result = template
        for var_name, var_value in variables.items():
            placeholder = f"{{{{{var_name}}}}}"
            # Convert value to string
            value_str = str(var_value) if var_value is not None else ""
            result = result.replace(placeholder, value_str)

        return result

    def validate_prompt(self, agent_name: str, action_name: str) -> bool:
        """
        Check if prompt exists for agent/action.

        Args:
            agent_name: Agent name
            action_name: Action name

        Returns:
            True if prompt exists, False otherwise
        """
        return (
            agent_name in self.prompts and
            action_name in self.prompts[agent_name]
        )

    def list_agents(self) -> List[str]:
        """Get list of all loaded agent names."""
        return list(self.prompts.keys())

    def list_sections(self, agent_name: str) -> List[str]:
        """
        Get list of all sections for an agent.

        Args:
            agent_name: Agent name

        Returns:
            List of section names

        Raises:
            KeyError: If agent not found
        """
        if agent_name not in self.prompts:
            raise KeyError(f"No prompts found for agent: {agent_name}")
        return list(self.prompts[agent_name].keys())

    def get_section(self, agent_name: str, section_name: str) -> str:
        """
        Get raw content of a specific section.

        Args:
            agent_name: Agent name
            section_name: Section name

        Returns:
            Section content

        Raises:
            KeyError: If agent or section not found
        """
        if agent_name not in self.prompts:
            raise KeyError(f"No prompts found for agent: {agent_name}")

        if section_name not in self.prompts[agent_name]:
            raise KeyError(
                f"No section '{section_name}' found for agent '{agent_name}'"
            )

        return self.prompts[agent_name][section_name]

    def __repr__(self) -> str:
        agent_count = len(self.prompts)
        total_sections = sum(len(sections) for sections in self.prompts.values())
        return (
            f"PromptManager("
            f"agents={agent_count}, "
            f"sections={total_sections})"
        )
