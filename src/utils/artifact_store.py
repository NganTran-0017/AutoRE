"""
In-memory store for all workflow artifacts.
"""
from typing import Dict, Optional, List, Any


class ArtifactStore:
    """
    In-memory repository for all workflow artifacts.

    Stores outputs by iteration:
    - Requirements documents
    - Alloy models
    - Analyzer results
    - Evaluations
    - Feedback

    Note: This is an in-memory cache. FileManager handles persistence to disk.
    """

    def __init__(self):
        """Initialize empty stores."""
        self.requirements: Dict[int, str] = {}
        self.alloy_models: Dict[int, str] = {}
        self.analyzer_results: Dict[int, Dict[str, Any]] = {}
        self.evaluations: Dict[int, str] = {}
        self.feedback: Dict[int, str] = {}
        self.feedback_action_type: Dict[int, str] = {}  # Track which action generated the feedback
        self.pending_questions: Dict[int, List[str]] = {}  # Questions from InterpretResults
        self.original_requirements: Optional[str] = None  # immutable source input

    # Requirements
    def store_requirements(self, iteration: int, content: str):
        """Store requirements document for iteration."""
        self.requirements[iteration] = content

    def store_original_requirements(self, content: str):
        """Store the original input requirements (immutable ground truth).

        Write-once: subsequent calls are ignored so nothing in the workflow
        can ever overwrite the source the drift checks anchor to.
        """
        if self.original_requirements is None and content:
            self.original_requirements = content

    def get_original_requirements(self) -> Optional[str]:
        """Get the original input requirements (None if not captured)."""
        return self.original_requirements

    def get_requirements(self, iteration: int) -> Optional[str]:
        """Get requirements for specific iteration."""
        return self.requirements.get(iteration)

    def get_latest_requirements(self) -> Optional[str]:
        """Get most recent requirements document."""
        if not self.requirements:
            return None
        max_iter = max(self.requirements.keys())
        return self.requirements[max_iter]

    # Alloy Models
    def store_alloy_model(self, iteration: int, content: str):
        """
        Store Alloy model for iteration, extracting only the code from markdown fences if present.
        
        This ensures that repair instructions (=== FIX INTENT === etc.) are not included
        in the stored model that gets shown to the Evaluator.
        """
        from .alloy_model_validator import extract_alloy_code

        content = extract_alloy_code(content, strip_generic_fence=True)

        self.alloy_models[iteration] = content

    def get_alloy_model(self, iteration: int) -> Optional[str]:
        """Get Alloy model for specific iteration."""
        return self.alloy_models.get(iteration)

    def get_latest_alloy_model(self) -> Optional[str]:
        """Get most recent Alloy model."""
        if not self.alloy_models:
            return None
        max_iter = max(self.alloy_models.keys())
        return self.alloy_models[max_iter]

    # Analyzer Results
    def store_analyzer_results(self, iteration: int, results: Dict[str, Any]):
        """Store Alloy Analyzer results for iteration."""
        self.analyzer_results[iteration] = results

    def get_analyzer_results(self, iteration: int) -> Optional[Dict[str, Any]]:
        """Get analyzer results for specific iteration."""
        return self.analyzer_results.get(iteration)

    def get_latest_analyzer_results(self) -> Optional[Dict[str, Any]]:
        """Get most recent analyzer results."""
        if not self.analyzer_results:
            return None
        max_iter = max(self.analyzer_results.keys())
        return self.analyzer_results[max_iter]

    # Evaluations
    def store_evaluation(self, iteration: int, evaluation: str):
        """Store evaluation for iteration."""
        self.evaluations[iteration] = evaluation

    def get_evaluation(self, iteration: int) -> Optional[str]:
        """Get evaluation for specific iteration."""
        return self.evaluations.get(iteration)

    def get_latest_evaluation(self) -> Optional[str]:
        """Get most recent evaluation."""
        if not self.evaluations:
            return None
        max_iter = max(self.evaluations.keys())
        return self.evaluations[max_iter]

    # Feedback
    def store_feedback(self, iteration: int, feedback: str, action_type: str = "GenerateSemanticFeedback"):
        """
        Store user feedback for iteration.

        Args:
            iteration: Iteration number
            feedback: Feedback content
            action_type: Name of action that generated feedback ("GenerateSemanticFeedback" or "GenerateSyntaxRepairInstruction")
        """
        self.feedback[iteration] = feedback
        self.feedback_action_type[iteration] = action_type

    def get_feedback(self, iteration: int) -> Optional[str]:
        """Get feedback for specific iteration."""
        return self.feedback.get(iteration)

    def get_feedback_action_type(self, iteration: int) -> Optional[str]:
        """Get the action type that generated the feedback for this iteration."""
        return self.feedback_action_type.get(iteration)

    # Pending Questions (from InterpretResults for use in GenerateFeedback)
    def store_pending_questions(self, iteration: int, questions: List[str]):
        """Store questions from InterpretResults for use in GenerateFeedback."""
        self.pending_questions[iteration] = questions

    def get_pending_questions(self, iteration: int) -> List[str]:
        """Get pending questions for iteration."""
        return self.pending_questions.get(iteration, [])

    def get_latest_feedback(self) -> Optional[str]:
        """Get most recent feedback."""
        if not self.feedback:
            return None
        max_iter = max(self.feedback.keys())
        return self.feedback[max_iter]

    def get_all_feedback(self) -> List[str]:
        """Get all feedback in chronological order."""
        sorted_iters = sorted(self.feedback.keys())
        return [self.feedback[i] for i in sorted_iters]

    # Utility
    def get_iteration_count(self) -> int:
        """Get number of completed iterations."""
        # Use requirements as the source of truth
        return len(self.requirements)

    def has_iteration(self, iteration: int) -> bool:
        """Check if iteration has any stored data."""
        return (
            iteration in self.requirements or
            iteration in self.alloy_models or
            iteration in self.analyzer_results or
            iteration in self.evaluations or
            iteration in self.feedback
        )

    def clear(self):
        """Clear all stored outputs."""
        self.requirements.clear()
        self.alloy_models.clear()
        self.analyzer_results.clear()
        self.evaluations.clear()
        self.feedback.clear()

    def __repr__(self) -> str:
        return (
            f"ArtifactStore("
            f"iterations={self.get_iteration_count()}, "
            f"requirements={len(self.requirements)}, "
            f"models={len(self.alloy_models)}, "
            f"results={len(self.analyzer_results)})"
        )
