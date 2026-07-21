"""Logging utility for AutoRE system."""
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
import yaml


class AutoRELogger:
    """Logger that writes to both console and log file."""

    def __init__(self, log_dir: str = None):
        """
        Initialize logger.

        Args:
            log_dir: Directory for log files (if None, loads from config)
        """
        if log_dir is None:
            # Load from config
            config_path = Path("config.yaml")
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                log_dir = config.get('user_interaction', {}).get('log_directory', 'outputlog')
            else:
                log_dir = "outputlog"

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create log file with format MMDDYY.log
        date_str = datetime.now().strftime("%m%d%y")
        self.log_file = self.log_dir / f"{date_str}.log"

        # Open log file in append mode
        self.log_handle = open(self.log_file, 'a', encoding='utf-8')

        # Write session start marker
        self._write_session_start()

    def _write_session_start(self):
        """Write session start marker to log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80
        self.log_handle.write(f"\n{separator}\n")
        self.log_handle.write(f"SESSION START: {timestamp}\n")
        self.log_handle.write(f"{separator}\n\n")
        self.log_handle.flush()

    def log(self, message: str, to_console: bool = True, to_file: bool = True):
        """
        Log message to console and/or file.

        Args:
            message: Message to log
            to_console: Whether to print to console
            to_file: Whether to write to log file
        """
        if to_console:
            print(message)

        if to_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.log_handle.write(f"[{timestamp}] {message}\n")
            self.log_handle.flush()

    def log_separator(self, char: str = "=", length: int = 70):
        """
        Log a separator line.

        Args:
            char: Character to use for separator
            length: Length of separator
        """
        separator = char * length
        self.log(separator)

    def log_section(self, title: str):
        """
        Log a section header.

        Args:
            title: Section title
        """
        self.log_separator()
        self.log(title)
        self.log_separator()

    def log_user_prompt(self, prompt: str, concise_version: Optional[str] = None):
        """
        Log user prompt (full to file, concise to console).

        Args:
            prompt: Full prompt text
            concise_version: Optional concise version for console
        """
        # To file: full prompt
        self.log("\n--- USER PROMPT (FULL) ---", to_console=False, to_file=True)
        self.log(prompt, to_console=False, to_file=True)
        self.log("--- END PROMPT ---\n", to_console=False, to_file=True)

        # To console: concise version or full if not provided
        display = concise_version if concise_version else prompt
        self.log_separator()
        self.log(display, to_console=True, to_file=False)
        self.log_separator()

    def log_user_input(self, user_input: str):
        """
        Log user input.

        Args:
            user_input: User's input
        """
        self.log("\n--- USER INPUT ---", to_console=False)
        self.log(user_input)
        self.log("--- END INPUT ---\n", to_console=False)

    def log_agent_communication(self, agent_name: str, action_name: str, prompt: str, response: str, iteration: int = None):
        """
        Log agent prompt and response.

        Args:
            agent_name: Name of the agent
            action_name: Name of the action
            prompt: Prompt sent to LLM
            response: Response from LLM
            iteration: Optional iteration number
        """
        self.log(f"\n{'='*80}", to_console=False)
        if iteration is not None:
            self.log(f"[{agent_name.upper()}] {action_name} - Iteration {iteration}", to_console=False)
        else:
            self.log(f"[{agent_name.upper()}] {action_name}", to_console=False)
        self.log(f"{'='*80}", to_console=False)
        self.log("\n--- PROMPT SENT TO LLM ---", to_console=False)
        self.log(prompt, to_console=False)
        if iteration is not None:
            self.log(f"\n--- {action_name} - Iteration {iteration} --- RESPONSE FROM LLM ---", to_console=False)
        else:
            self.log(f"\n--- {action_name} --- RESPONSE FROM LLM ---", to_console=False)
        self.log(response, to_console=False)
        self.log(f"{'='*80}\n", to_console=False)

    def log_alloy_execution(self, model_path: str, stdout: str, stderr: str, return_code: int, analysis: dict):
        """
        Log Alloy Analyzer execution details.

        Args:
            model_path: Path to the model file
            stdout: Standard output from Alloy
            stderr: Standard error from Alloy
            return_code: Return code from execution
            analysis: Analysis results dictionary
        """
        self.log(f"\n{'='*80}", to_console=False)
        self.log(f"ALLOY ANALYZER EXECUTION", to_console=False)
        self.log(f"{'='*80}", to_console=False)
        self.log(f"Model: {model_path}", to_console=False)
        self.log(f"Return Code: {return_code}", to_console=False)

        self.log("\n--- ALLOY STDOUT ---", to_console=False)
        self.log(stdout if stdout else "(empty)", to_console=False)

        self.log("\n--- ALLOY STDERR ---", to_console=False)
        self.log(stderr if stderr else "(empty)", to_console=False)

        # Log analysis summary (not full details with instances/counterexamples)
        self.log("\n--- ANALYSIS SUMMARY ---", to_console=False)
        # analysis parameter is already the analysis dict (not wrapped)
        summary_info = {
            'has_syntax_errors': analysis.get('has_syntax_errors', False),
            'has_counterexamples': analysis.get('has_counterexamples', False),
            'num_instances': len(analysis.get('instances', [])),
            'num_counterexamples': len(analysis.get('counterexamples', [])),
            'num_unsat_run_commands': len(analysis.get('unsat_run_commands', []))
        }
        import json
        self.log(json.dumps(summary_info, indent=2), to_console=False)
        self.log(f"{'='*80}\n", to_console=False)

    def log_file_update(self, file_path: str, description: str = "Updated"):
        """
        Log file update.

        Args:
            file_path: Path to updated file
            description: Description of update
        """
        self.log(f"{description}: {file_path}")

    def log_error(self, error: str):
        """
        Log error message.

        Args:
            error: Error message
        """
        self.log(f"ERROR: {error}")

    def close(self):
        """Close log file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80
        self.log_handle.write(f"\n{separator}\n")
        self.log_handle.write(f"SESSION END: {timestamp}\n")
        self.log_handle.write(f"{separator}\n\n")
        self.log_handle.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
