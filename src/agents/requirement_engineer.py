"""
Requirement Engineer agent (v2 - uses SharedRuntimeContext).

Standard MetaGPT Role with context-aware actions.
"""
from metagpt.roles import Role
from ..utils.runtime_context import SharedRuntimeContext
from ..actions.requirement_actions import (
    AnalyzeRequirements,
    BuildAlloyModel,
    UpdateAlloyModel
)


class RequirementEngineerRole(Role):
    """
    Requirement Engineer agent for requirements analysis and Alloy modeling.

    Uses SharedRuntimeContext for memory, prompts, and artifacts.
    """

    def __init__(self, context: SharedRuntimeContext):
        """
        Initialize Requirement Engineer.

        Args:
            context: Shared runtime context
        """
        super().__init__(
            name="RequirementEngineer",
            profile="RequirementEngineer"
        )

        self.context = context

        # Set up actions with context
        self.set_actions([
            AnalyzeRequirements(context, agent_name="RE"),
            BuildAlloyModel(context, agent_name="RE"),
            UpdateAlloyModel(context, agent_name="RE")
        ])
