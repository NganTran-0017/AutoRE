"""
Shared runtime context for workflow execution.
"""
from pathlib import Path
from .memory_system import LongTermMemorySystem
from .user_preferences import UserPreferenceTracker
from .prompt_manager import PromptManager
from .learning_system import LearningSystem
from .iteration_tracker import IterationTracker
from .file_manager import FileManager
from .artifact_store import ArtifactStore


class SharedRuntimeContext:
    """
    Shared runtime context for one workflow run.

    Created once by workflow at startup and passed to all agents/actions.
    Contains all shared services and state.

    Components:
    - memory: Long-term memory with multi-dimensional tagging
    - user_preferences: Accumulates user preferences across iterations
    - prompt_manager: Renders prompts for any agent/action
    - learning: Coordinates learning across agents
    - iteration: Tracks current iteration number
    - file_manager: Handles file I/O
    - artifacts: In-memory store of all outputs

    Lifecycle:
    1. Created at workflow start
    2. Iteration incremented between cycles
    3. State persisted to disk at end

    Not shared:
    - Each agent's MetaGPT short-term memory (rc.memory)
    - Temporary prompt construction details
    """

    def __init__(self, project_name: str = "default", logger=None, use_semantic_memory: bool = True, config: dict = None):
        """
        Initialize shared runtime context.

        Args:
            project_name: Project identifier for isolation
            logger: Optional AutoRELogger instance
            use_semantic_memory: Use ChromaDB for semantic retrieval (default: True)
            config: Optional configuration dict (loaded from config.yaml)
        """
        self.project_name = project_name
        self.logger = logger

        # Get memory configuration
        config = config or {}
        memory_config = config.get('memory', {})
        dedup_config = memory_config.get('semantic_deduplication', {})
        agents_config = config.get('agents', {})
        memory_assistant_config = agents_config.get('memory_assistant', {})

        # Add memory assistant config to dedup config
        if memory_assistant_config:
            dedup_config['memory_assistant_config'] = memory_assistant_config

        # Initialize memory system (semantic or traditional)
        if use_semantic_memory:
            from .semantic_memory import SemanticMemorySystem
            self.memory = SemanticMemorySystem(
                project_name,
                enable_dedup=dedup_config.get('enabled', True),
                dedup_config=dedup_config
            )
            self._memory_type = "semantic"
        else:
            self.memory = LongTermMemorySystem(project_name)
            self._memory_type = "traditional"

        # User preference storage path
        pref_path = Path(f"memory/{project_name}/user_preferences.json")
        self.user_preferences = UserPreferenceTracker(storage_path=pref_path)

        self.prompt_manager = PromptManager()
        self.learning = LearningSystem(self.memory)
        self.iteration = IterationTracker()
        self.file_manager = FileManager()
        self.artifacts = ArtifactStore()
        
        # Q&A database for tracking user clarifications
        from .qa_database import QADatabase
        qa_path = Path(f"memory/{project_name}/qa_database.json")
        self.qa_database = QADatabase(storage_path=qa_path)

        # Regression log for tracking model evolution
        from .regression_log import RegressionLog
        regression_path = Path(f"memory/{project_name}/regression_log.json")
        self.regression_log = RegressionLog(log_path=regression_path)

        # Structured audit log of requirements-document patch operations
        from .requirement_patch_log import RequirementPatchLog
        patch_log_path = Path(f"memory/{project_name}/requirement_patch_log.json")
        self.requirement_patch_log = RequirementPatchLog(log_path=patch_log_path)

        # Staged lessons awaiting confirmation that the issue they targeted was resolved
        self.pending_evaluator_feedback_lesson = None  # GenerateSyntaxRepairInstruction / RefineSyntaxRepairInstruction / GenerateSemanticFeedback
        self.pending_re_fix_lesson = None  # UpdateAlloyModel

        # Requirement -> Alloy-construct traceability, rebuilt/reconciled against
        # the current model each iteration so a changed requirement's stale
        # constructs can be found and regenerated. Annotations (construct -> R#)
        # are RE-declared for constructs whose name doesn't carry the ID.
        from .traceability_store import TraceabilityStore
        self.traceability = TraceabilityStore()
        self.traceability_annotations = {}  # {construct_name: [req_id, ...]}
        # Regeneration directive staged by step 7 (requirement change) for step 8.
        self.pending_requirement_regeneration = None
        # Latest construct-ownership audit (orphan / dead / unclassified buckets).
        self.ownership_audit = None
        # Latest deterministic UNSAT localization, and its join with the audit:
        # undeclared facts proven to block a predicate.
        self.semantic_diagnostics = None
        self.unowned_blockers = {}
        # Consecutive iterations each current blocker has gone unresolved, so a
        # fact that survived a delivered instruction gets different guidance
        # than one being reported for the first time.
        self.unowned_blocker_streaks = {}
        # Removal directive staged by the audit for the next model update.
        self.pending_stale_removal = None
        # Audit trail of workflow-authored (deterministic) construct deletions.
        # Persisted: a resume rebuilds the context, and an in-memory list would
        # lose every removal made before the resume point.
        from .construct_removal_log import ConstructRemovalLog
        removal_log_path = Path(f"memory/{project_name}/construct_removal_log.json")
        self.construct_removal_log = ConstructRemovalLog(log_path=removal_log_path)

        # Standing of each requirement: every applied patch operation is
        # provisional until it survives three consecutive verified iterations.
        # Persisted like the audit logs - a resume must not silently promote
        # updates whose probation window is being re-run.
        from .requirement_status_store import RequirementStatusStore
        status_path = Path(f"memory/{project_name}/requirement_status.json")
        self.requirement_status = RequirementStatusStore(log_path=status_path)
        # How the last requirement update was authorised ('accepted', 'edited',
        # 'rejected', 'provisional'), recorded as each item's provenance. It does
        # NOT exempt anything from probation: confirming wording is not
        # confirming consistency.
        self.requirement_gate_decision = ""
        # Items whose probation completed and whose deferred REMOVE the next
        # requirement step must perform.
        self.pending_requirement_deletions = []
        # ENCODE_PROVISIONAL directive staged when a provisional requirement has
        # no traceable construct, so probation can never receive evidence.
        self.pending_encode_provisional = None
        # Contradiction triage: "observe" (record the claim, show nothing) or
        # "active" (also tell the user and attach the claim to the update).
        # Neither withholds anything - verification settles the claim.
        self.requirement_conflict_mode = (
            config.get('requirements', {}).get('conflict_mode', 'observe')
        )
        # Contradiction claims made this iteration, held until the patch gives
        # the update they refer to an ID, and the ones verification has already
        # settled (so a decided conflict is not reported every iteration).
        self.pending_requirement_conflicts = []
        self.acknowledged_conflicts = set()
        # Items superseded once verification settled a contradiction claim,
        # applied as deferred removals in step 7 (text kept, encoding deleted)
        # so the supersession is reviewable and revertible rather than instant.
        self.pending_deferred_removals = []
        # Contested updates awaiting the user's revert/keep answer, and stalled
        # ones awaiting reword/drop/wait. Held across iterations until answered:
        # both statuses leave the probation pool, so nothing would raise them a
        # second time. Rebuilt from the store each iteration so a resume cannot
        # strand an item in a terminal status with no question attached.
        self.pending_requirement_contests = []
        self.pending_requirement_stalls = []
        # Requirements the user asked the Evaluator to diagnose because nothing
        # could encode them; delivered once through the escalation directive.
        self.pending_requirement_diagnosis = []
        # Reverts the user asked for, applied to the document in step 7, and the
        # REVERT_REQUIREMENT directive that realigns the model in step 8.
        self.pending_requirement_reverts = []
        self.pending_revert_directive = None

    def next_iteration(self):
        """Move to next iteration."""
        self.iteration.increment()

    def get_current_iteration(self) -> int:
        """Get current iteration number."""
        return self.iteration.current

    def save_state(self):
        """
        Persist all state to disk.

        Saves:
        - Long-term memory
        - User preferences
        """
        self.memory.save()
        self.user_preferences.save()

    def __repr__(self) -> str:
        return (
            f"SharedRuntimeContext("
            f"project={self.project_name}, "
            f"iteration={self.iteration.current}, "
            f"memory_items={self.memory.get_stats()['total']}, "
            f"preferences={len(self.user_preferences.preferences)})"
        )
