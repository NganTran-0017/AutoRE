"""CLI-based user interaction with timeout support."""
import sys
import select
import signal
import threading
import time
from datetime import datetime, timedelta
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

        # Extension settings (per session)
        self.max_extensions = 10
        self.extension_duration = 300  # 5 minutes per extension
        self.extensions_used = 0

        # Countdown state
        self.deadline = None
        self.countdown_active = False
        self.countdown_thread = None
        self.force_display = False  # Flag to force immediate countdown display

    def _timeout_handler(self, signum, frame):
        """Handle timeout signal."""
        raise TimeoutError("Input timeout")

    def _display_countdown(self):
        """
        Display countdown every 2 minutes.
        Shows time remaining and extension availability.
        Updates are printed as new lines (not overwritten).
        """
        last_display_time = None
        warning_30s_shown = False  # Track if 30-second warning has been shown

        while self.countdown_active and self.deadline:
            now = datetime.now()
            remaining = (self.deadline - now).total_seconds()

            if remaining <= 0:
                break

            # Special warning at 30 seconds
            if remaining <= 30 and not warning_30s_shown:
                print("\n⚠️  30 seconds remaining, hit ENTER to save input, or type EXTEND for more time\n")
                warning_30s_shown = True
                last_display_time = now
                time.sleep(1)
                continue

            # Display every 2 minutes (120 seconds) OR when forced
            should_display = False

            if last_display_time is None:
                # First display
                should_display = True
            elif self.force_display:
                # Force display (e.g., after EXTEND command)
                should_display = True
                self.force_display = False  # Reset flag
            else:
                # Check if 2 minutes (120 seconds) have passed
                elapsed_since_last = (now - last_display_time).total_seconds()
                if elapsed_since_last >= 120:
                    should_display = True

            if should_display:
                mins = int(remaining // 60)
                secs = int(remaining % 60)

                # Build extension message
                ext_remaining = self.max_extensions - self.extensions_used
                if ext_remaining > 0:
                    ext_msg = f" | Type 'EXTEND' to add {self.extension_duration//60} min ({ext_remaining} extensions left)"
                else:
                    ext_msg = " | No extensions remaining"

                # Display countdown on new line
                print(f"⏱  Time remaining: {mins}m {secs:02d}s{ext_msg}")

                last_display_time = now

            # Check every second
            time.sleep(1)

    def _handle_extension(self) -> bool:
        """
        Handle user's extension request.

        Returns:
            True if extension granted, False otherwise
        """
        if self.extensions_used >= self.max_extensions:
            print(f"\n⚠️  Maximum extensions ({self.max_extensions}) already used. Cannot extend further.\n")
            return False

        # Grant extension
        self.deadline += timedelta(seconds=self.extension_duration)
        self.extensions_used += 1
        ext_remaining = self.max_extensions - self.extensions_used

        total_mins = int((self.deadline - datetime.now()).total_seconds() // 60)

        print(f"\n✓ Time extended by {self.extension_duration//60} minutes!")
        print(f"  Extensions used: {self.extensions_used}/{self.max_extensions}")
        print(f"  Total time remaining: ~{total_mins} minutes")

        # Force countdown display to show updated time
        self.force_display = True
        # Give countdown thread a moment to display
        time.sleep(1.5)

        print()  # Extra newline for spacing

        return True

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
        Get single-line input with timeout and extension support.

        Returns:
            User input or None if timeout
        """
        # Reset session state
        self.extensions_used = 0
        self.deadline = datetime.now() + timedelta(seconds=self.timeout)
        self.countdown_active = True

        print()
        print(f"Timeout: {self.timeout} seconds ({self.timeout//60} minutes)")
        print(f"Type 'EXTEND' to add {self.extension_duration//60} minutes (max {self.max_extensions} extensions)")
        print()

        # Start countdown thread
        self.countdown_thread = threading.Thread(target=self._display_countdown, daemon=True)
        self.countdown_thread.start()

        # Set up signal handler for timeout
        old_handler = signal.signal(signal.SIGALRM, self._timeout_handler)

        try:
            while True:
                # Calculate remaining time until deadline
                remaining = (self.deadline - datetime.now()).total_seconds()
                
                if remaining <= 0:
                    raise TimeoutError()

                # Set alarm for remaining time (rounded up)
                alarm_seconds = max(1, int(remaining) + 1)
                signal.alarm(alarm_seconds)

                try:
                    user_input = input("> ").strip()

                    # Cancel alarm since we got input
                    signal.alarm(0)

                    # Check for extension
                    if user_input.upper() == 'EXTEND':
                        self._handle_extension()
                        continue

                    # Valid input received
                    if user_input:
                        self.countdown_active = False
                        if self.countdown_thread:
                            self.countdown_thread.join(timeout=1)
                        print()

                        self.logger.log_user_input(user_input)
                        if self.extensions_used > 0:
                            self.logger.log(f"(User used {self.extensions_used} time extension(s))", to_file=True)
                        return user_input

                except EOFError:
                    signal.alarm(0)
                    raise TimeoutError()

        except TimeoutError:
            signal.alarm(0)
            self.countdown_active = False
            if self.countdown_thread:
                self.countdown_thread.join(timeout=1)

            print()
            self.logger.log_separator()
            self.logger.log("⏱️  TIMEOUT: No input received")
            self.logger.log_separator()
            return None

        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
            self.countdown_active = False

    def _get_multiline_input(self) -> Optional[str]:
        """
        Get multi-line input with live countdown and extension support.
        User types lines and ends with 'END' on a new line.
        Can type 'EXTEND' to add more time (up to 10 times per session).

        Returns:
            User input or None if timeout
        """
        # Reset session state
        self.extensions_used = 0
        self.deadline = datetime.now() + timedelta(seconds=self.timeout)
        self.countdown_active = True

        # Display instructions
        print()
        print("─" * 80)
        self.logger.log("Your response (type your feedback, then 'END' on a new line):", to_file=False)
        self.logger.log(f"Initial timeout: {self.timeout} seconds ({self.timeout//60} minutes)")
        self.logger.log(f"You can extend time up to {self.max_extensions} times by typing 'EXTEND' on a new line")
        print("─" * 80)
        print()

        # Start countdown thread
        self.countdown_thread = threading.Thread(target=self._display_countdown, daemon=True)
        self.countdown_thread.start()

        lines = []

        # Set up signal handler for timeout
        old_handler = signal.signal(signal.SIGALRM, self._timeout_handler)

        try:
            while True:
                # Calculate remaining time until deadline
                remaining = (self.deadline - datetime.now()).total_seconds()
                
                if remaining <= 0:
                    raise TimeoutError()

                # Set alarm for remaining time (rounded up to ensure we don't timeout too early)
                alarm_seconds = max(1, int(remaining) + 1)
                signal.alarm(alarm_seconds)

                try:
                    line = input()

                    # Cancel alarm since we got input
                    signal.alarm(0)

                    # Check for extension command
                    if line.strip().upper() == 'EXTEND':
                        self._handle_extension()
                        continue

                    # Check for end marker
                    if line.strip().upper() == 'END':
                        break

                    lines.append(line)

                except EOFError:
                    signal.alarm(0)
                    break

            # Stop countdown
            signal.alarm(0)
            self.countdown_active = False
            if self.countdown_thread:
                self.countdown_thread.join(timeout=1)
            print()  # New line after countdown

            user_input = '\n'.join(lines).strip()

            if user_input:
                self.logger.log_user_input(user_input)
                if self.extensions_used > 0:
                    self.logger.log(f"(User used {self.extensions_used} time extension(s))", to_file=True)
                return user_input
            else:
                self.logger.log("No input provided (empty)", to_file=True)
                return None

        except TimeoutError:
            signal.alarm(0)
            self.countdown_active = False
            if self.countdown_thread:
                self.countdown_thread.join(timeout=1)

            print()
            self.logger.log_separator()

            # Check if user had typed anything before timeout
            user_input = '\n'.join(lines).strip()

            if user_input:
                # User typed content but forgot to type END
                self.logger.log("⏱️  TIMEOUT: Time limit reached (user forgot to type 'END')")
                total_time = self.timeout + self.extensions_used * self.extension_duration
                self.logger.log(f"Total time allowed: {self.timeout//60} + {self.extensions_used * self.extension_duration//60} = {total_time//60} minutes")
                self.logger.log("User had typed content - capturing input provided before timeout")
                self.logger.log_separator()

                # Log the captured input
                self.logger.log_user_input(user_input)
                if self.extensions_used > 0:
                    self.logger.log(f"(User used {self.extensions_used} time extension(s))", to_file=True)

                return user_input
            else:
                # User truly provided no input
                self.logger.log("⏱️  TIMEOUT: No input received within time limit")
                total_time = self.timeout + self.extensions_used * self.extension_duration
                self.logger.log(f"Total time allowed: {self.timeout//60} + {self.extensions_used * self.extension_duration//60} = {total_time//60} minutes")
                self.logger.log("Proceeding with assumption: No feedback from user")
                self.logger.log_separator()
                return None

        except Exception as e:
            signal.alarm(0)
            self.countdown_active = False
            if self.countdown_thread:
                self.countdown_thread.join(timeout=1)
            self.logger.log_error(f"Input error: {e}")
            return None

        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
            self.countdown_active = False

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
