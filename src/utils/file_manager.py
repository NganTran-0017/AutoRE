"""File management utilities for requirements and models."""
import os
from pathlib import Path
from typing import Optional, List
import shutil
import yaml


class FileManager:
    """Manages files for requirements, models, and analyzer outputs."""

    def __init__(self, base_dir: str = "."):
        """
        Initialize file manager.

        Args:
            base_dir: Base directory for the project
        """
        self.base_dir = Path(base_dir)

        # Load paths from config.yaml
        config_path = self.base_dir / "config.yaml"
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            paths = config.get('paths', {})
            self.reqs_dir = self.base_dir / paths.get('requirements_dir', 'ReqsDoc')
            self.models_dir = self.base_dir / paths.get('models_dir', 'AlloyModels')
            self.output_dir = self.base_dir / paths.get('output_dir', 'AnalyzerOutput')
            self.feedback_dir = self.base_dir / paths.get('feedback_dir', 'Output/Feedback')
        else:
            # Fallback to default paths
            self.reqs_dir = self.base_dir / "ReqsDoc"
            self.models_dir = self.base_dir / "AlloyModels"
            self.output_dir = self.base_dir / "AnalyzerOutput"
            self.feedback_dir = self.base_dir / "Output/Feedback"

        # Create directories if they don't exist
        self.reqs_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.feedback_dir.mkdir(parents=True, exist_ok=True)

    def save_requirements(self, content: str, iteration: int) -> Path:
        """
        Save requirements document.

        Args:
            content: Requirements content
            iteration: Iteration number

        Returns:
            Path to saved file
        """
        filepath = self.reqs_dir / f"Reqs_{iteration}.txt"
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Requirements saved to: {filepath}")
        return filepath

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

    def get_latest_requirements_file(self) -> Optional[Path]:
        """
        Get the path to the latest requirements document file.

        Returns:
            Path to latest requirements file or None
        """
        files = list(self.reqs_dir.glob("Reqs_*.txt"))
        if not files:
            return None
        latest = max(files, key=lambda p: int(p.stem.split('_')[1]))
        return latest

    def get_latest_requirements_up_to(self, max_iteration: int) -> Optional[int]:
        """
        Get the latest requirements file iteration number up to max_iteration.
        
        Args:
            max_iteration: Maximum iteration to consider
            
        Returns:
            Iteration number of latest requirements file, or None if not found
        """
        files = list(self.reqs_dir.glob("Reqs_*.txt"))
        if not files:
            return None
        
        # Get all iterations <= max_iteration
        valid_iterations = [
            int(f.stem.split('_')[1]) 
            for f in files 
            if int(f.stem.split('_')[1]) <= max_iteration
        ]
        
        if not valid_iterations:
            return None
            
        return max(valid_iterations)

    def save_alloy_model(self, content: str, iteration: int) -> Path:
        """
        Save Alloy model, extracting code from markdown fences if present.

        Args:
            content: Alloy model content (may contain ```alloy ... ```)
            iteration: Iteration number

        Returns:
            Path to saved file
        """
        import re
        
        content = content.strip()
        
        # Try to extract code from markdown fence (```alloy ... ```)
        # Look for the first alloy code block in the response
        alloy_block_pattern = r'```alloy\s*\n(.*?)```'
        match = re.search(alloy_block_pattern, content, re.DOTALL)
        
        if match:
            # Found alloy code block - extract just the code
            content = match.group(1).strip()
        elif content.startswith('```'):
            # Generic code block at start - strip fences
            lines = content.split('\n')
            # Remove first line (```alloy or ```)
            if lines[0].startswith('```'):
                lines = lines[1:]
            # Remove last line if it's a closing fence
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            content = '\n'.join(lines)
        # else: assume it's already plain Alloy code

        filepath = self.models_dir / f"AlloyModel__{iteration}.als"
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Alloy model saved to: {filepath}")
        return filepath

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

    def save_feedback(self, feedback: dict, iteration: int):
        """
        Save evaluator feedback to file.

        Args:
            feedback: Feedback dictionary from evaluator
            iteration: Iteration number
        """
        filepath = self.feedback_dir / f"feedback_{iteration}.txt"
        
        # Format feedback dict as readable text
        content_parts = []
        
        if isinstance(feedback, dict):
            for key, value in feedback.items():
                content_parts.append(f"=== {key.upper().replace('_', ' ')} ===\n")
                content_parts.append(f"{value}\n\n")
        else:
            content_parts.append(str(feedback))
        
        content = "".join(content_parts)
        
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Feedback saved to: {filepath}")

    def load_feedback(self, iteration: int) -> Optional[str]:
        """
        Load evaluator feedback from file.

        Args:
            iteration: Iteration number

        Returns:
            Feedback content or None if not found
        """
        filepath = self.feedback_dir / f"feedback_{iteration}.txt"
        if filepath.exists():
            with open(filepath, 'r') as f:
                return f.read()
        return None

    def get_latest_feedback(self) -> Optional[str]:
        """
        Get the latest feedback document.

        Returns:
            Latest feedback content or None
        """
        files = list(self.feedback_dir.glob("feedback_*.txt"))
        if not files:
            return None
        latest = max(files, key=lambda p: int(p.stem.split('_')[1]))
        with open(latest, 'r') as f:
            return f.read()

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
