"""
Audit trail of workflow-authored (deterministic) Alloy construct deletions.

The ownership audit prunes constructs that no live requirement owns before the
model update runs. That deletion is made by the workflow, not by the RE agent,
so without a record it is only visible by diffing two model files - and the
Evaluator, seeing a construct vanish between iterations, reads it as an
unintended regression and asks for it to be restored.

Persisted for the same reason RegressionLog is: the workflow is normally
restarted with `resume_iteration=N`, and an in-memory list starts empty on every
resume. Mirrors RequirementPatchLog's shape (load on init, trim on resume, copy
to Output/) so the three audit logs behave identically.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ConstructRemovalEntry:
    """One deterministic prune: what was deleted at an iteration, and why."""

    iteration_id: int
    removed: List[str]
    reason: str = "no live requirement owner"
    # construct -> kind ('fact', 'assert', 'pred', 'fun'), for the report.
    kinds: Dict[str, str] = field(default_factory=dict)
    # construct -> the dead requirement ID(s) it declared, when it declared any.
    orphan_owners: Dict[str, List[str]] = field(default_factory=dict)
    # Constructs that could NOT be removed because a survivor still refers to them.
    blocked: Dict[str, Any] = field(default_factory=dict)
    dropped_lines: int = 0
    source: str = "workflow (deterministic prune)"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration_id": self.iteration_id,
            "removed": self.removed,
            "reason": self.reason,
            "kinds": self.kinds,
            "orphan_owners": self.orphan_owners,
            "blocked": self.blocked,
            "dropped_lines": self.dropped_lines,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConstructRemovalEntry":
        return cls(
            iteration_id=data.get("iteration_id", 0),
            removed=data.get("removed", []),
            reason=data.get("reason", "no live requirement owner"),
            kinds=data.get("kinds", {}),
            orphan_owners=data.get("orphan_owners", {}),
            blocked=data.get("blocked", {}),
            dropped_lines=data.get("dropped_lines", 0),
            source=data.get("source", "workflow (deterministic prune)"),
        )


class ConstructRemovalLog:
    """Persistent record of constructs the workflow deleted, and why."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or Path("memory/construct_removal_log.json")
        self.entries: List[ConstructRemovalEntry] = []
        if self.log_path.exists():
            self._load_from_file()

    # ------------------------------------------------------------- writing #

    def add_entry(self, entry: ConstructRemovalEntry) -> None:
        self.entries.append(entry)
        self._save_to_file()

    # ------------------------------------------------------------- reading #

    def get_entries_for_iteration(self, iteration_id: int) -> List[ConstructRemovalEntry]:
        return [e for e in self.entries if e.iteration_id == iteration_id]

    def get_recent_entries(self, count: int = 3) -> List[ConstructRemovalEntry]:
        return self.entries[-count:] if count > 0 else []

    def removed_names(self, since_iteration: Optional[int] = None) -> List[str]:
        """Every construct deleted at or after `since_iteration` (all, if None).

        Used to answer "did this construct disappear on purpose?" without
        re-deriving it from the entry list at each call site.
        """
        names: List[str] = []
        for entry in self.entries:
            if since_iteration is not None and entry.iteration_id < since_iteration:
                continue
            for name in entry.removed:
                if name not in names:
                    names.append(name)
        return names

    # ------------------------------------------------------- prompt render #

    def format_for_prompt(self, count: int = 3) -> str:
        """Compact block for the Evaluator's regression analysis.

        States the deletion as deliberate, because the whole purpose of showing
        it is to stop the missing construct being diagnosed as a regression.
        """
        recent = self.get_recent_entries(count)
        if not recent:
            return "None - no constructs have been removed by the ownership audit."

        lines = [
            "The following constructs were DELETED DELIBERATELY by the workflow's "
            "ownership audit, not by the RE agent. Their requirement no longer "
            "exists, so the checks they performed are void. Do NOT report their "
            "absence as a regression or ask for them to be restored."
        ]
        for entry in recent:
            for name in entry.removed:
                kind = entry.kinds.get(name)
                owners = entry.orphan_owners.get(name) or []
                detail = f" (declared {', '.join(owners)}, not in requirements)" if owners else ""
                lines.append(
                    f"  iteration {entry.iteration_id}: {name}"
                    f"{f' [{kind}]' if kind else ''} - {entry.reason}{detail}"
                )
            for name, holders in (entry.blocked or {}).items():
                held = ", ".join(holders) if isinstance(holders, (list, tuple)) else str(holders)
                lines.append(
                    f"  iteration {entry.iteration_id}: {name} KEPT - still referenced by {held}"
                )
        return "\n".join(lines)

    # --------------------------------------------------------- persistence #

    def clear(self) -> None:
        """Used when starting fresh from iteration 0 (mirrors RegressionLog.clear)."""
        self.entries = []
        if self.log_path.exists():
            self.log_path.unlink()

    def trim_to_iteration(self, max_iteration: int) -> None:
        """Drop entries at or beyond max_iteration when resuming.

        Without this a resume to 23 would tell the Evaluator that a construct
        was removed at iteration 65 - a deletion that has not happened yet in
        the replayed timeline.
        """
        original_count = len(self.entries)
        self.entries = [e for e in self.entries if e.iteration_id < max_iteration]
        if len(self.entries) != original_count:
            self._save_to_file()

    def save_copy_to_output(self, output_dir: Optional[Path] = None) -> None:
        """Save a copy to Output/ConstructRemovalLog/ so the record survives
        even if memory/ is cleared on a later fresh start."""
        import shutil
        from .file_manager import run_snapshot_stamp

        output_dir = output_dir or Path("Output/ConstructRemovalLog")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Stamped with the run's start hour, so a run spanning an hour boundary
        # keeps writing the same file instead of starting a second one.
        output_file = output_dir / f"removals_{run_snapshot_stamp()}.log"

        if self.log_path.exists():
            shutil.copy2(self.log_path, output_file)
            print(f"  📋 Construct removal log saved to: {output_file}")
        elif self.entries:
            with open(output_file, "w") as f:
                json.dump([e.to_dict() for e in self.entries], f, indent=2)
            print(f"  📋 Construct removal log saved to: {output_file}")

    def _save_to_file(self) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.entries], f, indent=2)

    def _load_from_file(self) -> None:
        if not self.log_path or not self.log_path.exists():
            return
        if self.log_path.stat().st_size == 0:
            return
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = [ConstructRemovalEntry.from_dict(d) for d in data]
        except (json.JSONDecodeError, OSError, TypeError) as e:
            # A corrupt audit log must never stop a run.
            print(f"  ⚠️  construct removal log not loaded: {e}")
            self.entries = []
