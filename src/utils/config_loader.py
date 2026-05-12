"""Configuration loader for AutoRE."""
import os
import yaml
from pathlib import Path
from typing import Dict, Any


class ConfigLoader:
    """Loads and manages AutoRE configuration."""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize config loader.

        Args:
            config_path: Path to config.yaml file
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)

        return config or {}

    def get_llm_config(self) -> Dict[str, Any]:
        """
        Get LLM configuration.

        Returns:
            Dictionary with LLM settings
        """
        llm_config = self.config.get('llm', {})

        # Get API key from environment variable
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable not set. "
                "Please set it or create a .env file with your API key."
            )

        return {
            'api_key': api_key,
            'model': llm_config.get('model', 'gpt-4.1'),
            'temperature': llm_config.get('temperature', 0.7),
            'max_tokens': llm_config.get('max_tokens', 4000),
            'api_type': llm_config.get('api_type', 'openai'),
            'api_base': os.getenv('OPENAI_API_BASE', llm_config.get('api_base'))
        }

    def get_alloy_config(self) -> Dict[str, Any]:
        """Get Alloy Analyzer configuration."""
        return self.config.get('alloy', {})

    def get_workflow_config(self) -> Dict[str, Any]:
        """Get workflow configuration."""
        return self.config.get('workflow', {})

    def get_paths_config(self) -> Dict[str, str]:
        """Get file paths configuration."""
        return self.config.get('paths', {})

    def get_agents_config(self) -> Dict[str, Any]:
        """Get agents configuration."""
        return self.config.get('agents', {})

    def get_user_interaction_config(self) -> Dict[str, Any]:
        """Get user interaction configuration."""
        return self.config.get('user_interaction', {})
