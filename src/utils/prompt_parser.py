"""Utility for parsing and extracting sections from prompt files."""
import re
from typing import Dict, Optional, List


def extract_prompt_sections(prompt_text: str) -> Dict[str, str]:
    """
    Extract sections and subsections from a structured prompt file.

    Sections are identified by:
    - ### SECTION NAME: for main sections
    - ## SUBSECTION or ##N. SUBSECTION for subsections

    Args:
        prompt_text: Full prompt text from file

    Returns:
        Dictionary mapping section names to their content
        Subsections are stored as "PARENT_SECTION.SUBSECTION_NAME"
    """
    sections = {}

    # Patterns to match headers
    section_pattern = r'^###\s+([A-Z][A-Z\s_]+):\s*$'  # ### SECTION:
    subsection_pattern = r'^##\s*(\d+\.\s+)?([A-Z][A-Z\s_]+)\s*$'  # ##1. SUBSECTION or ## SUBSECTION

    lines = prompt_text.split('\n')
    current_section = None
    current_subsection = None
    current_content = []

    for line in lines:
        # Check for main section header (### SECTION:)
        section_match = re.match(section_pattern, line.strip())
        if section_match:
            # Save previous content
            if current_subsection:
                key = f"{current_section}.{current_subsection}"
                sections[key] = '\n'.join(current_content).strip()
            elif current_section:
                sections[current_section] = '\n'.join(current_content).strip()

            # Start new section
            current_section = section_match.group(1).strip()
            current_subsection = None
            current_content = []
            continue

        # Check for subsection header (##1. SUBSECTION or ## SUBSECTION)
        subsection_match = re.match(subsection_pattern, line.strip())
        if subsection_match and current_section:
            # Save previous subsection if exists
            if current_subsection:
                key = f"{current_section}.{current_subsection}"
                sections[key] = '\n'.join(current_content).strip()
            elif current_content:
                # Save section content before first subsection
                sections[current_section] = '\n'.join(current_content).strip()

            # Start new subsection (remove number prefix if present)
            subsection_name = subsection_match.group(2).strip()
            current_subsection = subsection_name
            current_content = []
            continue

        # Add line to current content
        if current_section:
            current_content.append(line)

    # Save the last section/subsection
    if current_subsection:
        key = f"{current_section}.{current_subsection}"
        sections[key] = '\n'.join(current_content).strip()
    elif current_section:
        sections[current_section] = '\n'.join(current_content).strip()

    return sections


def get_section(sections: Dict[str, str], section_name: str, default: str = "") -> str:
    """
    Get a specific section from extracted sections.

    Args:
        sections: Dictionary of sections
        section_name: Name of section to retrieve
        default: Default value if section not found

    Returns:
        Section content or default
    """
    return sections.get(section_name, default)


def get_subsection(sections: Dict[str, str], parent_section: str, subsection_name: str, default: str = "") -> str:
    """
    Get a specific subsection from extracted sections.

    Args:
        sections: Dictionary of sections
        parent_section: Name of parent section (e.g., "CORE RESPONSIBILITIES")
        subsection_name: Name of subsection (e.g., "REQUIREMENT ANALYSIS")
        default: Default value if subsection not found

    Returns:
        Subsection content or default
    """
    key = f"{parent_section}.{subsection_name}"
    return sections.get(key, default)


def get_all_subsections(sections: Dict[str, str], parent_section: str) -> Dict[str, str]:
    """
    Get all subsections under a parent section.

    Args:
        sections: Dictionary of sections
        parent_section: Name of parent section

    Returns:
        Dictionary mapping subsection names to their content
    """
    subsections = {}
    prefix = f"{parent_section}."
    
    for key, value in sections.items():
        if key.startswith(prefix):
            subsection_name = key[len(prefix):]
            subsections[subsection_name] = value
    
    return subsections


def extract_workflow_steps(sections: Dict[str, str], workflow_section: str = "WORKFLOW") -> Dict[str, str]:
    """
    Extract workflow steps from the WORKFLOW section.
    
    Parses steps like:
    1. Step Name: description
    2. Another Step: description
    
    Args:
        sections: Dictionary of sections
        workflow_section: Name of workflow section
        
    Returns:
        Dictionary mapping step numbers/names to content
    """
    workflow = sections.get(workflow_section, "")
    if not workflow:
        return {}
    
    steps = {}
    # Pattern: 1. Step Name: content (until next step or end)
    pattern = r'(\d+)\.\s+([^:]+):(.*?)(?=\d+\.|$)'
    
    for match in re.finditer(pattern, workflow, re.DOTALL):
        step_num = match.group(1)
        step_name = match.group(2).strip()
        step_content = match.group(3).strip()
        
        # Store with both number and name as key
        key = f"{step_num}. {step_name}"
        steps[key] = step_content
        steps[step_num] = step_content  # Also store by number only
    
    return steps


def combine_sections(sections: Dict[str, str], section_names: list) -> str:
    """
    Combine multiple sections into a single prompt.

    Args:
        sections: Dictionary of sections
        section_names: List of section names to combine

    Returns:
        Combined prompt text
    """
    parts = []
    for name in section_names:
        if name in sections:
            parts.append(f"{name}:")
            parts.append(sections[name])
            parts.append("")  # Blank line between sections

    return '\n'.join(parts).strip()


def extract_workflow_step(sections: Dict[str, str], step_identifier: str, workflow_type: str = "INTERACTION WORKFLOW") -> Optional[str]:
    """
    Extract a specific workflow step from the workflow section.

    Args:
        sections: Dictionary of sections
        step_identifier: Step identifier (e.g., "Step 1", "Step 2", "STEP 3")
        workflow_type: Type of workflow section to search (e.g., "INTERACTION WORKFLOW" or "VERIFICATION WORKFLOW")

    Returns:
        Step instructions or None if not found
    """
    workflow = sections.get(workflow_type, "")

    if not workflow:
        return None

    # Pattern to match a step section
    # Matches "Step X:" or "STEP X:" (case-insensitive) through to the next "Step" or end
    # Normalize step_identifier to handle both "Step 1" and "STEP 1"
    step_num = re.search(r'\d+', step_identifier)
    if not step_num:
        return None

    num = step_num.group(0)

    # Pattern that matches both "Step N:" and "STEP N:" (with optional space before colon)
    pattern = rf'(?:Step|STEP)\s*{num}\s*:.*?(?=(?:Step|STEP)\s*\d+\s*:|$)'

    match = re.search(pattern, workflow, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()

    return None
