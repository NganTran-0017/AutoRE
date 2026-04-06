"""File management utilities for requirements and models."""
import os
from pathlib import Path
from typing import Optional, List
import shutil


class FileManager:
    """Manages files for requirements, models, and analyzer outputs."""

    def __init__(self, base_dir: str = "."):
        """
        Initialize file manager.

        Args:
            base_dir: Base directory for the project
        """
        self.base_dir = Path(base_dir)
        self.reqs_dir = self.base_dir / "ReqsDoc"
        self.models_dir = self.base_dir / "AlloyModels"
        self.output_dir = self.base_dir / "AnalyzerOutput"

        # Create directories if they don't exist
        self.reqs_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_requirements(self, content: str, iteration: int):
        """
        Save requirements document.

        Args:
            content: Requirements content
            iteration: Iteration number
        """
        filepath = self.reqs_dir / f"Reqs_{iteration}.txt"
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Requirements saved to: {filepath}")

    def load_requirements(self, iteration: int) -> Optional[str]:
        """
        Load requirements document.

        Args:
            iteration: Iteration number

        Returns:
            Requirements content or None if not found
        """
        filepath = self.reqs_dir / f"Reqs_{iteration}.txt"
        if filepath.exists():
            with open(filepath, 'r') as f:
                return f.read()
        return None

    def get_latest_requirements(self) -> Optional[str]:
        """
        Get the latest requirements document.

        Returns:
            Latest requirements content or None
        """
        files = list(self.reqs_dir.glob("Reqs_*.txt"))
        if not files:
            return None
        latest = max(files, key=lambda p: int(p.stem.split('_')[1]))
        with open(latest, 'r') as f:
            return f.read()

    def save_alloy_model(self, content: str, iteration: int):
        """
        Save Alloy model.

        Args:
            content: Alloy model content
            iteration: Iteration number
        """
        filepath = self.models_dir / f"AlloyModel__{iteration}.als"
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Alloy model saved to: {filepath}")

    def load_alloy_model(self, iteration: int) -> Optional[str]:
        """
        Load Alloy model.

        Args:
            iteration: Iteration number

        Returns:
            Alloy model content or None if not found
        """
        filepath = self.models_dir / f"AlloyModel__{iteration}.als"
        if filepath.exists():
            with open(filepath, 'r') as f:
                return f.read()
        return None

    def get_latest_alloy_model(self) -> Optional[str]:
        """
        Get the latest Alloy model.

        Returns:
            Latest model content or None
        """
        files = list(self.models_dir.glob("AlloyModel__*.als"))
        if not files:
            return None
        latest = max(files, key=lambda p: int(p.stem.split('__')[1]))
        with open(latest, 'r') as f:
            return f.read()

    def get_alloy_model_path(self, iteration: int) -> Path:
        """
        Get path to Alloy model file.

        Args:
            iteration: Iteration number

        Returns:
            Path to model file
        """
        return self.models_dir / f"AlloyModel__{iteration}.als"

    def create_analyzer_output_dir(self, iteration: int) -> Path:
        """
        Create output directory for analyzer results.

        Args:
            iteration: Iteration number

        Returns:
            Path to output directory
        """
        output_path = self.output_dir / str(iteration)
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path

    def get_analyzer_output_files(self, iteration: int) -> List[Path]:
        """
        Get all analyzer output files for a given iteration.

        Args:
            iteration: Iteration number

        Returns:
            List of output file paths
        """
        output_path = self.output_dir / str(iteration)
        if not output_path.exists():
            return []
        return list(output_path.glob("*.json"))

    def load_user_feedback(self, feedback_file: str = "user_feedback.txt") -> Optional[str]:
        """
        Load user feedback from file.

        Args:
            feedback_file: Name of feedback file

        Returns:
            Feedback content or None
        """
        filepath = self.base_dir / feedback_file
        if filepath.exists():
            with open(filepath, 'r') as f:
                content = f.read()
            # Archive the feedback file after reading
            archive_path = self.base_dir / f"archived_{feedback_file}"
            shutil.move(str(filepath), str(archive_path))
            return content
        return None

    def create_user_prompt_file(self, prompt: str, filename: str = "user_prompt.txt"):
        """
        Create a file with prompt for user.

        Args:
            prompt: Prompt text
            filename: Name of prompt file
        """
        filepath = self.base_dir / filename
        with open(filepath, 'w') as f:
            f.write(prompt)
        print(f"\nUser prompt created: {filepath}")
        print(f"Please review and provide your response in 'user_feedback.txt'")

    def get_all_requirement_versions(self) -> List[int]:
        """
        Get all available requirement versions.

        Returns:
            List of iteration numbers
        """
        files = list(self.reqs_dir.glob("Reqs_*.txt"))
        return sorted([int(f.stem.split('_')[1]) for f in files])

    def get_all_model_versions(self) -> List[int]:
        """
        Get all available model versions.

        Returns:
            List of iteration numbers
        """
        files = list(self.models_dir.glob("AlloyModel__*.als"))
        return sorted([int(f.stem.split('__')[1]) for f in files])
