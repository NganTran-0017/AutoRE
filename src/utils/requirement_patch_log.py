"""
Structured audit log for requirements-document patch operations.

UpdateRequirements applies patches in code (requirements_store.apply_patch)
and previously reported the outcome only as free-text session-log lines
(self._debug), which is not queryable. This gives every patch attempt a
structured, persisted record: what the LLM proposed, what was applied /
blocked / errored, and the raw patch text - independent of the requirements
document that resulted, so drift or blocked removals can be audited without
grepping session logs.

Same persistence style as RegressionLog: JSON-backed, append-only, with a
save_copy_to_output() snapshot per run.
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime
from pathlib import Path
import json


@dataclass
class RequirementPatchLogEntry:
    """One UpdateRequirements patch attempt for a single iteration."""
    iteration_id: int
    raw_response: str  # LLM's raw === REQUIREMENT PATCH === text (post-retry, if retried)
    ops_requested: List[Dict[str, str]] = field(default_factory=list)  # [{"op", "target"}, ...] as parsed
    applied: List[str] = field(default_factory=list)
    blocked: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    no_change: bool = False
    changed: bool = False
    retried: bool = False  # True if the first patch was unusable and a retry was issued
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequirementPatchLogEntry":
        return cls(
            iteration_id=data["iteration_id"],
            raw_response=data.get("raw_response", ""),
            ops_requested=data.get("ops_requested", []),
            applied=data.get("applied", []),
            blocked=data.get("blocked", []),
            errors=data.get("errors", []),
            no_change=data.get("no_change", False),
            changed=data.get("changed", False),
            retried=data.get("retried", False),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )


class RequirementPatchLog:
    """Append-only structured log of requirement-document patch operations."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or Path("memory/requirement_patch_log.json")
        self.entries: List[RequirementPatchLogEntry] = []
        if self.log_path.exists():
            self._load_from_file()

    def add_entry(self, entry: RequirementPatchLogEntry) -> None:
        self.entries.append(entry)
        self._save_to_file()

    def get_entries_for_iteration(self, iteration_id: int) -> List[RequirementPatchLogEntry]:
        return [e for e in self.entries if e.iteration_id == iteration_id]

    def get_recent_entries(self, count: int = 5) -> List[RequirementPatchLogEntry]:
        return sorted(self.entries, key=lambda e: e.iteration_id, reverse=True)[:count]

    def get_all_blocked(self) -> List[Dict[str, Any]]:
        """All blocked-removal records across the run, e.g. to audit protected
        requirements an agent repeatedly tried to remove."""
        return [
            {"iteration_id": e.iteration_id, "blocked": entry}
            for e in self.entries
            for entry in e.blocked
        ]

    def clear(self) -> None:
        """Used when starting fresh from iteration 0 (mirrors RegressionLog.clear)."""
        self.entries = []
        if self.log_path.exists():
            self.log_path.unlink()

    def trim_to_iteration(self, max_iteration: int) -> None:
        """Remove entries at or beyond max_iteration. Used when resuming from
        a specific iteration (mirrors RegressionLog.trim_to_iteration)."""
        original_count = len(self.entries)
        self.entries = [e for e in self.entries if e.iteration_id < max_iteration]
        if len(self.entries) != original_count:
            self._save_to_file()

    def save_copy_to_output(self, output_dir: Optional[Path] = None) -> None:
        """Save a copy to Output/RequirementPatchLog/ so the record survives
        even if memory/ is cleared on a later fresh start."""
        import shutil

        output_dir = output_dir or Path("Output/RequirementPatchLog")
        output_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        output_file = output_dir / f"patchlog_{now.strftime('%m%d')}_{now.strftime('%I%p')}.log"

        if self.log_path.exists():
            shutil.copy2(self.log_path, output_file)
            print(f"  📋 Requirement patch log saved to: {output_file}")
        elif self.entries:
            with open(output_file, "w") as f:
                json.dump([e.to_dict() for e in self.entries], f, indent=2)
            print(f"  📋 Requirement patch log saved to: {output_file}")

    def _save_to_file(self) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.entries], f, indent=2, ensure_ascii=False)

    def _load_from_file(self) -> None:
        if not self.log_path or not self.log_path.exists():
            return
        if self.log_path.stat().st_size == 0:
            return
        with open(self.log_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                print("⚠ Warning: requirement patch log file is corrupted, starting fresh")
                return
        self.entries = [RequirementPatchLogEntry.from_dict(d) for d in data]
