"""CLI-based user interaction with timeout support."""
import sys
import select
import signal
from typing import Optional
from .logger import AutoRELogger


class TimeoutError(Exception):
    """Raised when input timeout occurs."""
    pass


class CLIInteraction:
    """Manages CLI-based user interaction with timeout."""

    def __init__(self, logger: AutoRELogger, timeout: int = 300):
        """
        Initialize CLI interaction.

        Args:
            logger: AutoRELogger instance
            timeout: Timeout in seconds (default: 300 = 5 minutes)
        """
        self.logger = logger
        self.timeout = timeout

    def _timeout_handler(self, signum, frame):
        """Handle timeout signal."""
        raise TimeoutError("Input timeout")

    def request_input(self, prompt: str, concise_prompt: Optional[str] = None,
                     multiline: bool = True) -> Optional[str]:
        """
        Request input from user via CLI.

        Args:
            prompt: Full prompt text (logged to file)
            concise_prompt: Concise version for console display
            multiline: Whether to accept multi-line input

        Returns:
            User input or None if timeout
        """
        # Log the prompt
        self.logger.log_user_prompt(prompt, concise_prompt)

        if multiline:
            return self._get_multiline_input()
        else:
            return self._get_singleline_input()

    def _get_singleline_input(self) -> Optional[str]:
        """
        Get single-line input with timeout.

        Returns:
            User input or None if timeout
        """
        self.logger.log("\nYour response (press Enter when done):", to_file=False)
        self.logger.log(f"Timeout: {self.timeout} seconds ({self.timeout//60} minutes)")

        # Set up timeout using signal
        old_handler = signal.signal(signal.SIGALRM, self._timeout_handler)
        signal.alarm(self.timeout)

        try:
            user_input = input("> ").strip()
            signal.alarm(0)  # Cancel alarm

            if user_input:
                self.logger.log_user_input(user_input)
                return user_input
            else:
                self.logger.log("No input provided (empty)")
                return None

        except TimeoutError:
            signal.alarm(0)
            self.logger.log_separator()
            self.logger.log("TIMEOUT: No input received within time limit")
            self.logger.log("Proceeding with assumption: No feedback from user")
            self.logger.log_separator()
            return None
        except EOFError:
            signal.alarm(0)
            self.logger.log("Input interrupted (EOF)")
            return None
        finally:
            signal.signal(signal.SIGALRM, old_handler)

    def _get_multiline_input(self) -> Optional[str]:
        """
        Get multi-line input with timeout.
        User types lines and ends with 'END' on a new line.

        Returns:
            User input or None if timeout
        """
        self.logger.log("\nYour response (type your feedback, then 'END' on a new line):", to_file=False)
        self.logger.log(f"Timeout: {self.timeout} seconds ({self.timeout//60} minutes)")
        self.logger.log("")

        lines = []
        start_time = None

        # Set up timeout
        old_handler = signal.signal(signal.SIGALRM, self._timeout_handler)

        try:
            signal.alarm(self.timeout)

            while True:
                try:
                    line = input()

                    # Check for end marker
                    if line.strip().upper() == 'END':
                        signal.alarm(0)
                        break

                    lines.append(line)

                    # Reset alarm for each line
                    signal.alarm(self.timeout)

                except EOFError:
                    signal.alarm(0)
                    break

            user_input = '\n'.join(lines).strip()

            if user_input:
                self.logger.log_user_input(user_input)
                return user_input
            else:
                self.logger.log("No input provided (empty)", to_file=True)
                return None

        except TimeoutError:
            signal.alarm(0)
            self.logger.log_separator()
            self.logger.log("TIMEOUT: No input received within time limit")
            self.logger.log("Proceeding with assumption: No feedback from user")
            self.logger.log_separator()
            return None
        except Exception as e:
            signal.alarm(0)
            self.logger.log_error(f"Input error: {e}")
            return None
        finally:
            signal.signal(signal.SIGALRM, old_handler)

    def show_file_update(self, file_path: str, description: str = "Updated"):
        """
        Show file update notification.

        Args:
            file_path: Path to updated file
            description: Description of update
        """
        self.logger.log_file_update(file_path, description)

    def create_clarification_request(self, iteration: int, requirements_file: str) -> tuple[str, str]:
        """
        Create clarification request prompt.

        Args:
            iteration: Current iteration
            requirements_file: Path to requirements file

        Returns:
            Tuple of (full_prompt, concise_prompt)
        """
        full_prompt = f"""
CLARIFICATION REQUEST - Iteration {iteration}

The Requirement Engineer has analyzed your requirements and created a structured
requirements document. Please review the document and provide clarification on any
assumptions or ambiguities.

Requirements document: {requirements_file}

Please review the document and provide:
- Clarifications on any assumptions
- Corrections to any misunderstandings
- Additional context or constraints

You can also confirm if the requirements are correctly understood.
"""

        concise_prompt = f"""
CLARIFICATION REQUEST - Iteration {iteration}

Requirements document created: {requirements_file}

Please review and provide clarification on assumptions and requirements.
Type your feedback below (end with 'END' on a new line):
"""

        return full_prompt, concise_prompt

    def create_evaluation_request(self, iteration: int, current_state: str,
                                  has_errors: bool, has_counterexamples: bool,
                                  has_instances: bool) -> tuple[str, str]:
        """
        Create evaluation request prompt.

        Args:
            iteration: Current iteration
            current_state: Current state summary
            has_errors: Whether there are syntax errors
            has_counterexamples: Whether there are counterexamples
            has_instances: Whether there are satisfying instances

        Returns:
            Tuple of (full_prompt, concise_prompt)
        """
        status = []
        if not has_errors:
            status.append("✓ Syntax: OK")
        else:
            status.append("✗ Syntax: ERRORS")

        if not has_counterexamples:
            status.append("✓ Counterexamples: None")
        else:
            status.append("✗ Counterexamples: Found")

        if has_instances:
            status.append("✓ Instances: Valid scenarios exist")
        else:
            status.append("✗ Instances: None (over-constrained?)")

        status_str = "\n".join(status)

        full_prompt = f"""
EVALUATION REVIEW - Iteration {iteration}

{current_state}

Analysis Results:
{status_str}

The Evaluator has analyzed the Alloy model and generated feedback for improvements.
Check the AnalyzerOutput/{iteration}/ directory for detailed results.

Please provide:
1. Your feedback on the current state
2. Any additional scenarios you want to check
3. Type 'SATISFIED' if you're satisfied with the results

If you have additional scenarios, describe:
- Scenario name/description
- What should be checked
- Expected behavior
"""

        concise_prompt = f"""
EVALUATION REVIEW - Iteration {iteration}

{status_str}

Results in: AnalyzerOutput/{iteration}/

Provide feedback, additional scenarios, or type 'SATISFIED':
(End with 'END' on a new line)
"""

        return full_prompt, concise_prompt
