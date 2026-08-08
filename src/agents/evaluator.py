"""
Evaluator agent (v2 - uses SharedRuntimeContext).

Standard MetaGPT Role with context-aware actions.
"""
from metagpt.roles import Role
from ..utils.runtime_context import SharedRuntimeContext
from ..actions.evaluation_actions import (
    RunAlloyAnalyzer,
    InterpretResults,
    GenerateSemanticFeedback,
    UpdateRequirements,
    RefineFeedback
)


class EvaluatorRole(Role):
    """
    Evaluator agent for Alloy verification and requirements improvement.

    Uses SharedRuntimeContext for memory, prompts, and artifacts.
    """

    def __init__(self, context: SharedRuntimeContext):
        """
        Initialize Evaluator.

        Args:
            context: Shared runtime context
        """
        super().__init__(
            name="Evaluator",
            profile="Evaluator"
        )

        self.context = context

        # Set up actions with context
        self.set_actions([
            RunAlloyAnalyzer(context, agent_name="Evaluator"),
            InterpretResults(context, agent_name="Evaluator"),
            GenerateSemanticFeedback(context, agent_name="Evaluator"),
            UpdateRequirements(context, agent_name="Evaluator"),
            RefineFeedback(context, agent_name="Evaluator")
        ])
