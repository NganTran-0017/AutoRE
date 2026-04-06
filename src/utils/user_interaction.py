"""User interaction utilities for file-based communication."""
from pathlib import Path
from typing import Optional
import time


class UserInteraction:
    """Manages file-based user interaction."""

    def __init__(self, base_dir: str = "."):
        """
        Initialize user interaction manager.

        Args:
            base_dir: Base directory for interaction files
        """
        self.base_dir = Path(base_dir)
        self.prompt_file = self.base_dir / "user_prompt.txt"
        self.feedback_file = self.base_dir / "user_feedback.txt"
        self.archived_feedback = self.base_dir / "archived_user_feedback.txt"

    def request_user_input(self, prompt: str, wait_for_response: bool = False,
                          timeout: int = 300) -> Optional[str]:
        """
        Request input from user via file.

        Args:
            prompt: Prompt text to show user
            wait_for_response: Whether to wait for user response
            timeout: Timeout in seconds (default: 300 = 5 minutes)

        Returns:
            User response if wait_for_response is True, else None
        """
        # Write prompt
        with open(self.prompt_file, 'w') as f:
            f.write(prompt)

        print(f"\n{'='*70}")
        print("USER INPUT REQUESTED")
        print(f"{'='*70}")
        print(f"A prompt has been written to: {self.prompt_file}")
        print(f"Please review the prompt and provide your response in: {self.feedback_file}")
        print(f"{'='*70}\n")

        if not wait_for_response:
            return None

        # Wait for feedback
        return self._wait_for_feedback(timeout)

    def _wait_for_feedback(self, timeout: int = 300) -> Optional[str]:
        """
        Wait for user feedback file to be created.

        Args:
            timeout: Timeout in seconds (default: 300 = 5 minutes)

        Returns:
            User feedback content or None if timeout
        """
        start_time = time.time()
        start_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        print(f"Waiting for user feedback...")
        print(f"Wait started at: {start_timestamp}")
        print(f"Timeout: {timeout} seconds ({timeout//60} minutes)")
        print(f"Checking for feedback file: {self.feedback_file}")
        print()

        last_update = start_time
        while True:
            current_time = time.time()
            elapsed = current_time - start_time

            # Print periodic updates every 30 seconds
            if current_time - last_update >= 30:
                remaining = timeout - elapsed
                print(f"Still waiting... {int(remaining)} seconds remaining ({int(remaining//60)} min {int(remaining%60)} sec)")
                last_update = current_time

            if self.feedback_file.exists():
                # Give a moment for file writing to complete
                time.sleep(0.5)

                with open(self.feedback_file, 'r') as f:
                    content = f.read().strip()

                if content:
                    # Archive the feedback
                    self._archive_feedback(content)
                    # Remove the feedback file
                    self.feedback_file.unlink()
                    end_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    print(f"\n{'='*70}")
                    print(f"User feedback received at: {end_timestamp}")
                    print(f"{'='*70}\n")
                    return content

            # Check timeout
            if timeout > 0 and elapsed > timeout:
                end_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n{'='*70}")
                print(f"WAIT TIME EXPIRED")
                print(f"{'='*70}")
                print(f"Wait ended at: {end_timestamp}")
                print(f"No user feedback received within {timeout} seconds ({timeout//60} minutes)")
                print(f"Proceeding with assumption: No feedback from user")
                print(f"{'='*70}\n")
                return None

            time.sleep(2)  # Check every 2 seconds

    def _archive_feedback(self, content: str):
        """
        Archive user feedback.

        Args:
            content: Feedback content
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.archived_feedback, 'a') as f:
            f.write(f"\n{'='*70}\n")
            f.write(f"Feedback at {timestamp}\n")
            f.write(f"{'='*70}\n")
            f.write(content)
            f.write(f"\n{'='*70}\n\n")

    def has_pending_feedback(self) -> bool:
        """
        Check if there is pending user feedback.

        Returns:
            True if feedback file exists and has content
        """
        if not self.feedback_file.exists():
            return False

        with open(self.feedback_file, 'r') as f:
            return bool(f.read().strip())

    def get_pending_feedback(self) -> Optional[str]:
        """
        Get pending feedback without waiting.

        Returns:
            Feedback content or None
        """
        if not self.has_pending_feedback():
            return None

        with open(self.feedback_file, 'r') as f:
            content = f.read().strip()

        if content:
            self._archive_feedback(content)
            self.feedback_file.unlink()
            return content

        return None

    def clear_prompt(self):
        """Clear the prompt file."""
        if self.prompt_file.exists():
            self.prompt_file.unlink()

    def create_clarification_request(self, iteration: int, assumptions: str,
                                    requirements_summary: str) -> str:
        """
        Create a clarification request prompt.

        Args:
            iteration: Current iteration number
            assumptions: Assumptions requiring clarification
            requirements_summary: Summary of requirements

        Returns:
            Prompt text
        """
        prompt = f"""
{'='*70}
CLARIFICATION REQUEST - Iteration {iteration}
{'='*70}

REQUIREMENTS SUMMARY:
{requirements_summary}

ASSUMPTIONS REQUIRING CLARIFICATION:
{assumptions}

INSTRUCTIONS:
Please review the above assumptions and provide clarification for each point.
Your feedback will help refine the requirements and create a more accurate model.

Provide your clarification in the file: {self.feedback_file}

You may also:
- Confirm assumptions that are correct
- Correct any misunderstandings
- Provide additional context or constraints

Format your response as clear, structured text.
{'='*70}
"""
        return prompt

    def create_evaluation_request(self, iteration: int, interpretation: str,
                                 feedback: dict, current_state: str) -> str:
        """
        Create an evaluation feedback request.

        Args:
            iteration: Current iteration
            interpretation: Result interpretation
            feedback: Generated feedback
            current_state: Current state summary

        Returns:
            Prompt text
        """
        prompt = f"""
{'='*70}
EVALUATION REVIEW - Iteration {iteration}
{'='*70}

CURRENT STATE:
{current_state}

ANALYZER INTERPRETATION:
{interpretation}

SUGGESTED IMPROVEMENTS:

Alloy Model:
{feedback.get('alloy_improvements', 'None')}

Requirements:
{feedback.get('requirement_updates', 'None')}

Additional Assumptions:
{feedback.get('assumptions', 'None')}

INSTRUCTIONS:
Please review the analysis and provide:
1. Your feedback on the suggested improvements
2. Any additional scenarios you want to check
3. Whether you're satisfied with the current state

Provide your response in the file: {self.feedback_file}

If you provide additional scenarios, format them clearly with:
- Scenario name/description
- What should be checked
- Expected behavior

If no additional scenarios and you're satisfied, simply respond: "SATISFIED"
{'='*70}
"""
        return prompt