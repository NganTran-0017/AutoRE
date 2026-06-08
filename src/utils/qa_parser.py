"""
Utilities for parsing Q&A related information from agent responses.
"""
import re
from typing import List, Dict, Tuple, Optional


def parse_user_questions(response_text: str, section_name: str = "USER QUESTIONS") -> List[str]:
    """
    Parse numbered questions from === USER QUESTIONS === or === UPDATED USER QUESTIONS === section.

    Args:
        response_text: Full agent response text
        section_name: Section name to parse (default: "USER QUESTIONS")

    Returns:
        List of question strings (without numbering)

    Example:
        Input:
            === USER QUESTIONS ===
            1. Should Emergency mode allow multiple administrators?
            2. Can delegations be revoked during Emergency?

        Output:
            ["Should Emergency mode allow multiple administrators?",
             "Can delegations be revoked during Emergency?"]
    """
    # Extract section
    section_pattern = rf"===\s*{section_name}\s*===(.*?)(?:===|$)"
    match = re.search(section_pattern, response_text, re.DOTALL | re.IGNORECASE)

    if not match:
        return []

    section_content = match.group(1).strip()

    if not section_content or section_content.lower() in ['none', 'n/a', 'no questions']:
        return []

    questions = []
    # Match numbered questions (1., 2., etc.)
    question_pattern = r'^\d+\.\s*(.+?)(?=\n\d+\.|\Z)'

    for match in re.finditer(question_pattern, section_content, re.MULTILINE | re.DOTALL):
        question = match.group(1).strip()
        # Clean up multi-line questions
        question = ' '.join(question.split())
        questions.append(question)

    return questions


def parse_qa_updates(response_text: str) -> Dict[str, str]:
    """
    Parse Q&A status updates from === Q&A UPDATE === section.

    Args:
        response_text: Full agent response text

    Returns:
        Dictionary mapping Q&A ID to new status

    Example:
        Input:
            === Q&A UPDATE ===
            Q5_1: status: confirmed
            Q7_2: status: outdated
            Q8_3: status: provisional

        Output:
            {"Q5_1": "confirmed", "Q7_2": "outdated", "Q8_3": "provisional"}
    """
    # Extract section
    section_pattern = r"===\s*Q&A UPDATE\s*===(.*?)(?:===|$)"
    match = re.search(section_pattern, response_text, re.DOTALL | re.IGNORECASE)

    if not match:
        return {}

    section_content = match.group(1).strip()

    if not section_content or section_content.lower() in ['none', 'n/a']:
        return {}

    updates = {}
    # Match lines like: Q5_1: status: confirmed
    update_pattern = r'(Q\d+_\d+):\s*status:\s*(confirmed|provisional|outdated)'

    for match in re.finditer(update_pattern, section_content, re.IGNORECASE):
        qa_id = match.group(1)
        status = match.group(2).lower()
        updates[qa_id] = status

    return updates


def parse_reused_qids(response_text: str) -> List[str]:
    """
    Parse reused Q&A IDs from response text.

    Looks for patterns like:
    - "Per Q5_1, Emergency requires..."
    - "As clarified in Q7_2..."
    - "Referencing Q8_3..."

    Args:
        response_text: Full agent response text

    Returns:
        List of unique Q&A IDs that were referenced

    Example:
        Input:
            "Per Q5_1, Emergency requires 2 admins. As mentioned in Q7_2, delegations..."

        Output:
            ["Q5_1", "Q7_2"]
    """
    # Pattern to match Q&A ID references
    pattern = r'\b(Q\d+_\d+)\b'

    matches = re.findall(pattern, response_text)

    # Return unique IDs, preserving order
    seen = set()
    unique_ids = []
    for qa_id in matches:
        if qa_id not in seen:
            seen.add(qa_id)
            unique_ids.append(qa_id)

    return unique_ids


def extract_question_context(question: str) -> Optional[str]:
    """
    Extract context keyword or requirement reference from a question.

    Looks for:
    - Requirement references: R1, R2, R4.2, etc.
    - Key domain terms: Emergency, delegation, role, etc.

    Args:
        question: Question text

    Returns:
        Context string (requirement ref or keyword), or None if not found

    Example:
        "Regarding R4, should delegations be revoked?" -> "R4"
        "Can Emergency mode allow multiple admins?" -> "Emergency"
    """
    # Check for requirement references first
    req_pattern = r'\b(R\d+(?:\.\d+)?[a-z]?)\b'
    req_match = re.search(req_pattern, question, re.IGNORECASE)
    if req_match:
        return req_match.group(1).upper()

    # Extract key domain terms
    question_lower = question.lower()

    # Priority keywords (check in order)
    priority_keywords = [
        'emergency',
        'delegation',
        'role',
        'clearance',
        'administrator',
        'permission',
        'revocation',
        'mutual exclusivity'
    ]

    for keyword in priority_keywords:
        if keyword in question_lower:
            return keyword.capitalize()

    # Fallback: extract first noun phrase (simple heuristic)
    # Look for capitalized words or common patterns
    words = question.split()
    for word in words:
        if len(word) > 4 and word[0].isupper():
            return word

    return "General"


def parse_user_feedback_for_answers(
    user_feedback: str,
    questions: List[str]
) -> Dict[int, str]:
    """
    Parse user feedback to map answers to specific questions.

    If user provides structured answers (numbered), map them.
    Otherwise, treat entire feedback as answer to all questions.

    Args:
        user_feedback: User's feedback text
        questions: List of questions that were asked

    Returns:
        Dictionary mapping question index to answer text

    Example:
        Input:
            user_feedback: "1. Yes, exactly 2 admins. 2. No, cannot revoke during Emergency."
            questions: ["Allow multiple admins?", "Can revoke during Emergency?"]

        Output:
            {0: "Yes, exactly 2 admins.", 1: "No, cannot revoke during Emergency."}
    """
    if not user_feedback or not questions:
        return {}

    # Check if user provided numbered answers
    numbered_pattern = r'^\d+\.\s*(.+?)(?=\n\d+\.|\Z)'
    matches = list(re.finditer(numbered_pattern, user_feedback, re.MULTILINE | re.DOTALL))

    if matches and len(matches) == len(questions):
        # User provided structured answers
        answers = {}
        for idx, match in enumerate(matches):
            answer = match.group(1).strip()
            answer = ' '.join(answer.split())  # Clean whitespace
            answers[idx] = answer
        return answers
    else:
        # Treat entire feedback as answer to all questions
        # (Questions are related or user provided single response)
        cleaned_feedback = ' '.join(user_feedback.split())
        return {idx: cleaned_feedback for idx in range(len(questions))}


def format_qa_updates_for_display(updates: Dict[str, str]) -> str:
    """
    Format Q&A status updates for user-friendly display.

    Args:
        updates: Dictionary mapping Q&A ID to new status

    Returns:
        Formatted string for logging/display
    """
    if not updates:
        return "No Q&A status updates."

    lines = ["Q&A Status Updates:"]
    for qa_id, status in updates.items():
        emoji = {
            'confirmed': '✓',
            'provisional': '~',
            'outdated': '✗'
        }.get(status, '?')
        lines.append(f"  {emoji} {qa_id}: {status}")

    return '\n'.join(lines)