"""
Regression Log for tracking Alloy model updates and their impact across iterations.

Purpose: Provides context for regression analysis to speed up convergence.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime
import json
from pathlib import Path
import difflib
import re
import sys

# Assumption predicates are named A1, A2, A3, ... (kept separate from prospective
# requirement predicates R1, R1R2, ...). Only these are eligible for auto-promotion
# to facts; the regex guarantees requirement predicates can never accrue a streak.
_ASSUMPTION_PRED_RE = re.compile(r'^A\d+$')


def _debug_log(message: str):
    """Print debug message to both console and capture for log file."""
    print(message)
    sys.stdout.flush()  # Ensure it gets written immediately


@dataclass
class VerificationResult:
    """Verification result snapshot."""
    syntax: str  # "OK" or "Error"
    error_message: Optional[str] = None  # Error message context if syntax is "Error"
    satisfied_predicates: List[str] = field(default_factory=list)  # List of successful run commands
    unsatisfied_predicates: List[str] = field(default_factory=list)  # List of unsuccessful run commands
    counterexamples: List[str] = field(default_factory=list)  # List of assert command names that generated SAT instances
    no_counterexample: List[str] = field(default_factory=list)  # List of assert command names with no counterexamples

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VerificationResult':
        return cls(**data)


@dataclass
class ImpactAnalysis:
    """Impact analysis for model changes."""
    sat_to_unsat: List[str] = field(default_factory=list)  # run commands that became UNSAT
    unsat_to_sat: List[str] = field(default_factory=list)  # run commands that became SAT
    pass_to_fail: List[str] = field(default_factory=list)  # assertions that started failing
    fail_to_pass: List[str] = field(default_factory=list)  # assertions that started passing

    def to_dict(self) -> Dict[str, Any]:
        return {
            "satToUnsat": self.sat_to_unsat,
            "unsatToSat": self.unsat_to_sat,
            "passToFail": self.pass_to_fail,
            "failToPass": self.fail_to_pass
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImpactAnalysis':
        return cls(
            sat_to_unsat=data.get("satToUnsat", []),
            unsat_to_sat=data.get("unsatToSat", []),
            pass_to_fail=data.get("passToFail", []),
            fail_to_pass=data.get("failToPass", [])
        )


@dataclass
class RegressionLogEntry:
    """Single entry in the regression log."""
    iteration_id: int
    model_file_location: str
    fix_intent: str  # What the RE agent intended to fix
    source_ref: str  # Cause of update (extracted from RE response)
    current_result: VerificationResult
    previous_result: Optional[VerificationResult]
    updated_lines: str  # Diff between current and previous model
    expected_impact: ImpactAnalysis  # RE agent's prediction
    actual_impact: Optional[ImpactAnalysis] = None  # Filled by Evaluator
    outcome_classification: str = "pending"  # LLM: "expected_improvement" / "unintended_regression" / "spec_clarification: comment"; deterministic fallback (see derive_outcome_classification): "initial_verification" / "syntax_error_blocked" / "no_improvement" / "unclassified" variants. "pending" only transiently before step-4 evaluation.
    issue: Optional[str] = None  # Description of issues (e.g., "syntax error in fact ExistingSystem; unsat predicate: R1R2")
    syntax_error_context: Optional[str] = None  # Context field from syntax_error dictionary (for error message comparison)
    resolved_target_issue: Optional[bool] = None  # True if target issue resolved, False if not, None for first iteration. Flipped back to False by update_resolution_statuses if the issue recurs (oscillation).
    resolution_status: Optional[Dict[str, Any]] = None  # Provisional-resolution tracking: {'status': 'temporarily_absent'|'resolved_confirmed'|'resolution_reverted', 'target_issue', 'target_signature', 'recurred_at'?, 'confirmed_at'?}
    fix_pattern_detected: Optional[str] = None  # Pattern note if same fix approach tried multiple times (e.g., "Fix approach 'add guard constraint' attempted 3 times")
    is_reverted: bool = False  # True if this iteration reverted to a previous executable model
    evaluator_feedback: Optional[str] = None  # Full feedback from Evaluator (GenerateSemanticFeedback/RefineFeedback/GenerateSyntaxRepairInstruction)
    error_signature: Optional[Dict[str, Any]] = None  # Normalized error signature from ErrorNormalizer (stable, location-independent)
    issue_pattern: Optional[Dict[str, Any]] = None  # Cross-iteration pattern classification from IssuePatternTracker
    semantic_issue_persistence: Optional[Dict[str, Any]] = None  # Persistence of unsat predicates/counterexamples from SemanticIssueTracker
    repair_escalation: Optional[Dict[str, Any]] = None  # Escalation decision from RepairPlateauDetector (consumed by Evaluator/RE prompts)
    repair_signature: Optional[Dict[str, Any]] = None  # Normalized signature of the repair PRESCRIBED at this iteration (from normalize_repair): {'operation_families', 'target', 'strategy', 'normalized_signature'}
    promoted_assumptions: Optional[List[str]] = None  # Cumulative set of assumption predicates (A1, A2, ...) promoted to `fact A_k` as of this iteration. Per MODELING DISCIPLINE, an assumption is auto-promoted after >=2 consecutive SAT iterations; a revert (promotion broke baseline) removes it from the set.
    kind: str = "repair"  # "repair" (the RE attempted a fix) or "diagnostic" (RE Mode 3: the RE added probes to MEASURE, attempting no fix). A diagnostic entry is never listed as an attempted fix and never advances persistence - counting it would make careful diagnosis look like repeated failure.
    diagnostic_execution: Optional[str] = None  # Mode 3 only: the RE's per-plan-item execution report (which experiment, which probe, executed yes/no + reason). Also summarized into fix_intent, which must never be blank.
    diagnostic_dropped: Optional[str] = None  # Plan items the guard rails removed, with what the deterministic diagnosis already measured about each. Recorded even when the drops emptied the plan and the iteration fell back to an ordinary repair - that is exactly the case where nothing else carries them, and the Evaluator would otherwise re-propose the same experiment.
    diagnostic_plan: Optional[List[Dict[str, str]]] = None  # Mode 3 only: the MANIFEST the probes were written from (construct, hypothesis, level, reading). Persisted because the readback must know what was SUPPOSED to run - a probe that was never written produces no analyzer row, and without the manifest that silence is indistinguishable from UNSAT.
    diagnostic_control: Optional[str] = None  # Mode 3 only: the CONTROL line from the diff check. Mode 3 permits additions only; if the RE edited anything else, the verdicts were measured against a model nobody approved and are void. Rolling the model back does not undo that - the analyzer already ran - so the verdicts must carry their own trust flag.
    diagnostic_probe_bodies: Optional[Dict[str, str]] = None  # Mode 3 only: probe name -> source. The declared reading is the RE's CLAIM about what a probe altered; the body is the evidence. The probes are rolled out of the model before the next iteration reads it, so this is the only place they survive.
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration_id": self.iteration_id,
            "model_file_location": self.model_file_location,
            "fix_intent": self.fix_intent,
            "source_ref": self.source_ref,
            "current_result": self.current_result.to_dict(),
            "previous_result": self.previous_result.to_dict() if self.previous_result else None,
            "updated_lines": self.updated_lines,
            "expected_impact": self.expected_impact.to_dict(),
            "actual_impact": self.actual_impact.to_dict() if self.actual_impact else None,
            "outcome_classification": self.outcome_classification,
            "issue": self.issue,
            "syntax_error_context": self.syntax_error_context,
            "resolved_target_issue": self.resolved_target_issue,
            "resolution_status": self.resolution_status,
            "fix_pattern_detected": self.fix_pattern_detected,
            "is_reverted": self.is_reverted,
            "evaluator_feedback": self.evaluator_feedback,
            "error_signature": self.error_signature,
            "issue_pattern": self.issue_pattern,
            "semantic_issue_persistence": self.semantic_issue_persistence,
            "repair_escalation": self.repair_escalation,
            "repair_signature": self.repair_signature,
            "promoted_assumptions": self.promoted_assumptions,
            "kind": self.kind,
            "diagnostic_execution": self.diagnostic_execution,
            "diagnostic_plan": self.diagnostic_plan,
            "diagnostic_dropped": self.diagnostic_dropped,
            "diagnostic_control": self.diagnostic_control,
            "diagnostic_probe_bodies": self.diagnostic_probe_bodies,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RegressionLogEntry':
        return cls(
            iteration_id=data["iteration_id"],
            model_file_location=data["model_file_location"],
            fix_intent=data["fix_intent"],
            source_ref=data["source_ref"],
            current_result=VerificationResult.from_dict(data["current_result"]),
            previous_result=VerificationResult.from_dict(data["previous_result"]) if data.get("previous_result") else None,
            updated_lines=data["updated_lines"],
            expected_impact=ImpactAnalysis.from_dict(data["expected_impact"]),
            actual_impact=ImpactAnalysis.from_dict(data["actual_impact"]) if data.get("actual_impact") else None,
            outcome_classification=data.get("outcome_classification", "pending"),
            issue=data.get("issue"),
            syntax_error_context=data.get("syntax_error_context"),
            resolved_target_issue=data.get("resolved_target_issue"),
            resolution_status=data.get("resolution_status"),
            fix_pattern_detected=data.get("fix_pattern_detected"),
            is_reverted=data.get("is_reverted", False),
            evaluator_feedback=data.get("evaluator_feedback"),
            error_signature=data.get("error_signature"),
            issue_pattern=data.get("issue_pattern"),
            semantic_issue_persistence=data.get("semantic_issue_persistence"),
            repair_escalation=data.get("repair_escalation"),
            repair_signature=data.get("repair_signature"),
            promoted_assumptions=data.get("promoted_assumptions"),
            kind=data.get("kind", "repair"),
            diagnostic_execution=data.get("diagnostic_execution"),
            diagnostic_plan=data.get("diagnostic_plan"),
            diagnostic_dropped=data.get("diagnostic_dropped"),
            diagnostic_control=data.get("diagnostic_control"),
            diagnostic_probe_bodies=data.get("diagnostic_probe_bodies"),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


class RegressionLog:
    """Manages the regression log for tracking model evolution."""

    def __init__(self, log_path: Optional[Path] = None):
        """
        Initialize regression log.

        Args:
            log_path: Path to regression log JSON file
        """
        self.log_path = log_path or Path("memory/regression_log.json")
        self.entries: List[RegressionLogEntry] = []

        # Index: maps error symbols to list of iteration IDs with that error
        # Example: {"pred Next": [0, 3, 5], "fact DelegationClearance": [1, 4]}
        self.error_symbol_index: Dict[str, List[int]] = {}

        # Load existing log
        if self.log_path.exists():
            self._load_from_file()

    def clear(self) -> None:
        """
        Clear all entries from the regression log.
        Used when starting fresh from iteration 0.
        """
        self.entries = []
        self.error_symbol_index = {}
        if self.log_path.exists():
            self.log_path.unlink()  # Delete the file
        print("  Regression log cleared (fresh start)")

    def trim_to_iteration(self, max_iteration: int) -> None:
        """
        Remove all entries beyond the specified iteration.
        Used when resuming from a specific iteration.

        Args:
            max_iteration: Keep only entries with iteration_id < max_iteration
        """
        original_count = len(self.entries)
        self.entries = [e for e in self.entries if e.iteration_id < max_iteration]
        removed = original_count - len(self.entries)

        if removed > 0:
            # The symbol index maps error symbols to the iterations they appeared
            # in; leaving discarded iterations in it would keep matching issues
            # against a history that no longer exists.
            trimmed_index = {}
            for symbol, iterations in self.error_symbol_index.items():
                kept = [i for i in iterations if i < max_iteration]
                if kept:
                    trimmed_index[symbol] = kept
            self.error_symbol_index = trimmed_index

            self._save_to_file()
            print(f"  Regression log trimmed: removed {removed} entries after iteration {max_iteration - 1}")

    def save_copy_to_output(self, output_dir: Path = None) -> None:
        """
        Save a copy of the regression log to Output/RegressionLog/ directory.
        This preserves a historical record even if memory/ log is cleared.
        
        Args:
            output_dir: Optional custom output directory (defaults to Output/RegressionLog/)
        """
        import shutil
        from .file_manager import run_snapshot_stamp

        # Default output directory
        if output_dir is None:
            output_dir = Path("Output/RegressionLog")

        # Create directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)

        # MMDD_HH(AM/PM) of the RUN's start hour, not of this save - one run
        # writes one file, however many hours it lasts or saves it takes.
        output_file = output_dir / f"regression{run_snapshot_stamp()}.log"
        
        # Copy the current log file if it exists
        if self.log_path.exists():
            shutil.copy2(self.log_path, output_file)
            print(f"  📋 Regression log saved to: {output_file}")
        else:
            # If no file exists, save current in-memory state
            if self.entries:
                import json
                with open(output_file, 'w') as f:
                    json.dump([e.to_dict() for e in self.entries], f, indent=2)
                print(f"  📋 Regression log saved to: {output_file}")

    def save_error_symbol_index(self) -> None:
        """Save error symbol index to Output/RegressionLog directory."""
        from datetime import datetime
        import os
        
        # Create Output/RegressionLog directory if it doesn't exist
        output_dir = Path("Output/RegressionLog")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with current date (MMDD format)
        date_suffix = datetime.now().strftime("%m%d")
        output_file = output_dir / f"SimilarIssues_{date_suffix}.json"
        
        # Save index to file
        with open(output_file, 'w') as f:
            json.dump(self.error_symbol_index, f, indent=2)
        
        print(f"  📊 Error symbol index saved to: {output_file}")

    def _index_symbol(self, entry: RegressionLogEntry) -> None:
        """Record this entry's error symbol against its iteration, once."""
        if not (entry.issue and " in " in entry.issue):
            return
        symbol = entry.issue.split(" in ", 1)[1].strip()
        if not symbol:
            return
        iterations = self.error_symbol_index.setdefault(symbol, [])
        if entry.iteration_id not in iterations:
            iterations.append(entry.iteration_id)

    def add_entry(self, entry: RegressionLogEntry) -> None:
        """
        Record the entry for its iteration, REPLACING any entry already held for
        that iteration rather than appending beside it.

        An iteration has one outcome, so the log holds one entry for it. Two
        writers reach here - _step4_evaluate_model creates a placeholder when
        none exists, and _step8_update_model records the update it just made -
        and they normally land on different iterations because the counter
        increments between them. When they do collide, appending was silently
        destructive: get_entry and update_actual_impact both return the FIRST
        match, so the newer, more complete record was written and then never
        read again, while the stale placeholder answered every lookup for the
        rest of the run. It also inflated every count taken over `entries`.

        Replacing in place keeps chronological order and makes the newest
        record the one that answers, which is what both call sites intend.

        Args:
            entry: RegressionLogEntry to record
        """
        existing = next(
            (i for i, e in enumerate(self.entries)
             if e.iteration_id == entry.iteration_id),
            None,
        )
        if existing is None:
            self.entries.append(entry)
        else:
            self.entries[existing] = entry

        self._index_symbol(entry)
        self._save_to_file()

    def deduplicate_entries(self) -> int:
        """Collapse pre-existing duplicate iterations to their LAST entry.

        Logs written before add_entry replaced in place carry several entries
        for one iteration; every read has been answering from the first of them.
        Keeping the last matches what add_entry now does. Returns the number of
        entries dropped, so a caller can report it rather than silently
        rewriting history.
        """
        by_iteration = {}
        for entry in self.entries:
            by_iteration[entry.iteration_id] = entry     # last write wins
        if len(by_iteration) == len(self.entries):
            return 0

        removed = len(self.entries) - len(by_iteration)
        self.entries = [by_iteration[i] for i in sorted(by_iteration)]
        self.error_symbol_index = {}
        for entry in self.entries:
            self._index_symbol(entry)
        self._save_to_file()
        return removed

    def update_actual_impact(
        self,
        iteration_id: int,
        actual_impact: ImpactAnalysis,
        outcome_classification: str
    ) -> bool:
        """
        Update actual impact and outcome classification for an entry.

        Args:
            iteration_id: Iteration ID to update
            actual_impact: Actual impact observed
            outcome_classification: Outcome classification by Evaluator

        Returns:
            True if updated, False if entry not found
        """
        for entry in self.entries:
            if entry.iteration_id == iteration_id:
                entry.actual_impact = actual_impact
                entry.outcome_classification = outcome_classification
                self._save_to_file()
                return True
        return False

    def get_entry(self, iteration_id: int) -> Optional[RegressionLogEntry]:
        """Get entry by iteration ID."""
        for entry in self.entries:
            if entry.iteration_id == iteration_id:
                return entry
        return None

    def get_promoted_assumptions(self) -> List[str]:
        """
        Return the current cumulative set of assumption predicates (A1, A2, ...) that
        have been promoted to facts, read from the most recent entry that recorded it.

        Entries snapshot the cumulative set as-of their iteration (reverts remove members),
        so the latest non-None snapshot is the live set. Returns [] if none recorded yet.
        """
        for entry in reversed(self.entries):
            if entry.promoted_assumptions is not None:
                return list(entry.promoted_assumptions)
        return []

    def compute_assumption_sat_streaks(self, up_to_iteration: int) -> Dict[str, int]:
        """
        For each assumption predicate (A1, A2, ...) that is SAT at `up_to_iteration`,
        count how many CONSECUTIVE iterations (counting backward, stopping at the
        first gap or missing entry) it has been SAT - i.e. present in
        current_result.satisfied_predicates.

        Only names matching ^A\\d+$ are considered, so prospective requirement
        predicates (R1, R1R2, ...) can never accrue a promotion streak. Mirrors the
        backward-walk of _check_unsat_stuck. Returns {A_k: consecutive_sat_count}.
        """
        latest = self.get_entry(up_to_iteration)
        if not latest or not latest.current_result:
            return {}

        latest_sat = {
            name for name in (latest.current_result.satisfied_predicates or [])
            if _ASSUMPTION_PRED_RE.match(name)
        }

        streaks: Dict[str, int] = {}
        for name in latest_sat:
            count = 0
            i = up_to_iteration
            while i >= 0:
                entry = self.get_entry(i)
                if not entry or not entry.current_result:
                    break
                if name in (entry.current_result.satisfied_predicates or []):
                    count += 1
                    i -= 1
                else:
                    break
            streaks[name] = count
        return streaks

    def get_iterations_for_symbol(self, symbol: str) -> List[int]:
        """
        Get list of iteration IDs that had errors in the given symbol.

        Args:
            symbol: Error symbol (e.g., "pred Next", "fact DelegationClearance")

        Returns:
            List of iteration IDs with errors in this symbol, in chronological order
        """
        return self.error_symbol_index.get(symbol, [])

    def get_recent_entries(self, count: int = 3) -> List[RegressionLogEntry]:
        """
        Get most recent entries.

        Args:
            count: Number of recent entries to retrieve

        Returns:
            List of recent entries (newest first)
        """
        return sorted(self.entries, key=lambda e: e.iteration_id, reverse=True)[:count]

    def compute_diff(self, current_model: str, previous_model: str) -> str:
        """
        Compute unified diff between current and previous model.

        Args:
            current_model: Current model content
            previous_model: Previous model content

        Returns:
            Unified diff string
        """
        current_lines = current_model.splitlines(keepends=True)
        previous_lines = previous_model.splitlines(keepends=True)

        diff = difflib.unified_diff(
            previous_lines,
            current_lines,
            fromfile='previous_model.als',
            tofile='current_model.als',
            lineterm=''
        )

        return ''.join(diff)

    def format_for_prompt(self, count: int = 3) -> str:
        """
        Format recent entries for inclusion in Evaluator prompt.

        Args:
            count: Number of recent entries to include

        Returns:
            Formatted string
        """
        recent = self.get_recent_entries(count)

        if not recent:
            return "No regression log entries available."

        lines = ["RECENT MODEL UPDATE HISTORY:"]
        lines.append("")

        for i, entry in enumerate(recent, 1):
            lines.append(f"--- Iteration {entry.iteration_id} ---")
            if getattr(entry, "kind", "repair") == "diagnostic":
                # Mode 3: this iteration measured, it did not repair. Labelling it
                # is what stops the reader treating an experiment as a failed fix,
                # and the verdict table is the measurement itself - the hypotheses
                # and readings declared before the run, joined to what the analyzer
                # returned. Without it the probe verdicts are bare SAT/UNSAT lines.
                lines.append("Iteration kind: DIAGNOSTIC (experiments only - no fix attempted)")
                verdicts = format_probe_verdicts(entry)
                if verdicts:
                    lines.append(verdicts)
                # What the RE reports it DID, beside what the analyzer measured.
                # A skipped item's stated reason lives only here - the verdict
                # table can say an item did not run, never why.
                if entry.diagnostic_execution:
                    lines.append("Diagnostic execution report (from the RE):")
                    lines.append(entry.diagnostic_execution)
            if getattr(entry, "diagnostic_dropped", None):
                lines.append(entry.diagnostic_dropped)
            lines.append(f"Fix Intent: {entry.fix_intent}")
            lines.append(f"Source: {entry.source_ref}")

            # Results comparison
            prev = entry.previous_result
            curr = entry.current_result
            if prev:
                lines.append(f"Result Change:")
                lines.append(f"  Syntax: {prev.syntax} → {curr.syntax}")
                if curr.syntax == "Error" and curr.error_message:
                    lines.append(f"  Error: {curr.error_message}")
                
                # Satisfied predicates comparison
                prev_sat = ', '.join(prev.satisfied_predicates) if prev.satisfied_predicates else 'None'
                curr_sat = ', '.join(curr.satisfied_predicates) if curr.satisfied_predicates else 'None'
                lines.append(f"  Satisfied Predicates: [{prev_sat}] → [{curr_sat}]")
                
                # Unsatisfied predicates comparison
                prev_unsat = ', '.join(prev.unsatisfied_predicates) if prev.unsatisfied_predicates else 'None'
                curr_unsat = ', '.join(curr.unsatisfied_predicates) if curr.unsatisfied_predicates else 'None'
                lines.append(f"  Unsatisfied Predicates: [{prev_unsat}] → [{curr_unsat}]")
                
                # Counterexamples comparison
                prev_ce = ', '.join(prev.counterexamples) if prev.counterexamples else 'None'
                curr_ce = ', '.join(curr.counterexamples) if curr.counterexamples else 'None'
                lines.append(f"  Counterexamples: [{prev_ce}] → [{curr_ce}]")
                
                # No counterexample comparison
                prev_no_ce = ', '.join(prev.no_counterexample) if prev.no_counterexample else 'None'
                curr_no_ce = ', '.join(curr.no_counterexample) if curr.no_counterexample else 'None'
                lines.append(f"  Passing Assertions: [{prev_no_ce}] → [{curr_no_ce}]")
            else:
                lines.append(f"Current Result:")
                lines.append(f"  Syntax: {curr.syntax}")
                if curr.syntax == "Error" and curr.error_message:
                    lines.append(f"  Error: {curr.error_message}")
                sat = ', '.join(curr.satisfied_predicates) if curr.satisfied_predicates else 'None'
                lines.append(f"  Satisfied Predicates: [{sat}]")
                unsat = ', '.join(curr.unsatisfied_predicates) if curr.unsatisfied_predicates else 'None'
                lines.append(f"  Unsatisfied Predicates: [{unsat}]")
                ce = ', '.join(curr.counterexamples) if curr.counterexamples else 'None'
                lines.append(f"  Counterexamples: [{ce}]")
                no_ce = ', '.join(curr.no_counterexample) if curr.no_counterexample else 'None'
                lines.append(f"  Passing Assertions: [{no_ce}]")

            # Impact
            if entry.actual_impact:
                actual = entry.actual_impact
                lines.append(f"Actual Impact:")
                if actual.unsat_to_sat:
                    lines.append(f"  UNSAT→SAT: {', '.join(actual.unsat_to_sat)}")
                if actual.sat_to_unsat:
                    lines.append(f"  SAT→UNSAT: {', '.join(actual.sat_to_unsat)}")
                if actual.fail_to_pass:
                    lines.append(f"  FAIL→PASS: {', '.join(actual.fail_to_pass)}")
                if actual.pass_to_fail:
                    lines.append(f"  PASS→FAIL: {', '.join(actual.pass_to_fail)}")
                lines.append(f"Outcome: {entry.outcome_classification}")

            # Previous Result (full details)
            if entry.previous_result:
                prev = entry.previous_result
                lines.append(f"Previous Result:")
                lines.append(f"  Syntax: {prev.syntax}")
                if prev.syntax == "Error" and prev.error_message:
                    lines.append(f"  Error: {prev.error_message}")
                prev_sat = ', '.join(prev.satisfied_predicates) if prev.satisfied_predicates else 'None'
                lines.append(f"  Satisfied Predicates: [{prev_sat}]")
                prev_unsat = ', '.join(prev.unsatisfied_predicates) if prev.unsatisfied_predicates else 'None'
                lines.append(f"  Unsatisfied Predicates: [{prev_unsat}]")
                prev_ce = ', '.join(prev.counterexamples) if prev.counterexamples else 'None'
                lines.append(f"  Counterexamples: [{prev_ce}]")
                prev_no_ce = ', '.join(prev.no_counterexample) if prev.no_counterexample else 'None'
                lines.append(f"  Passing Assertions: [{prev_no_ce}]")

            # Updated Lines (already filtered to exclude comments)
            if entry.updated_lines:
                lines.append(f"Updated Lines (diff):")
                lines.append(entry.updated_lines)

            lines.append("")

        return "\n".join(lines)

    def format_for_prompt_filtered(self, current_analysis: Dict[str, Any], count: int = 3) -> str:
        """
        Format regression log entries, filtering by relevance to current issues.
        
        Only shows history for the same types of issues currently present:
        - If current has syntax errors, show previous syntax error attempts (in same symbol)
        - If current has counterexamples, show previous attempts for same assertions
        - If current has unsat predicates, show previous attempts for same predicates
        
        Args:
            current_analysis: Current analyzer results to determine relevant issues
            count: Maximum number of relevant entries to include
            
        Returns:
            Formatted string with only relevant regression history
        """
        # Determine current issues
        has_syntax_errors = current_analysis.get('has_syntax_errors', False)

        # Extract counterexample command names
        current_counterexamples_raw = current_analysis.get('counterexamples', [])
        if current_counterexamples_raw and isinstance(current_counterexamples_raw[0], dict):
            current_counterexamples = {ce.get('command_name', '') for ce in current_counterexamples_raw}
        else:
            current_counterexamples = set(current_counterexamples_raw)

        # Extract unsat predicate names
        current_unsat_raw = current_analysis.get('unsat_run_commands', [])
        if current_unsat_raw and isinstance(current_unsat_raw[0], dict):
            # Extract predicate names if it's a dict
            current_unsat = {pred.get('name', '') for pred in current_unsat_raw}
        else:
            current_unsat = set(current_unsat_raw)

        # Debug logging
        _debug_log = lambda msg: print(f"[REGRESSION_FILTER] {msg}")
        _debug_log(f"Filtering regression log for current issues:")
        _debug_log(f"  Has syntax errors: {has_syntax_errors}")
        _debug_log(f"  Current counterexamples: {current_counterexamples}")
        _debug_log(f"  Current unsat predicates: {current_unsat}")
        
        # Extract current syntax error symbol if applicable
        current_syntax_symbol = None
        if has_syntax_errors:
            current_entry = self.get_entry(len(self.entries) - 1) if self.entries else None
            if current_entry and current_entry.issue and " in " in current_entry.issue:
                current_syntax_symbol = current_entry.issue.split(" in ", 1)[1].strip()
        
        # Filter entries by relevance
        relevant_entries = []
        
        for entry in reversed(self.entries[:-1]):  # Exclude current iteration
            is_relevant = False
            
            # Check if this entry relates to current issues
            if has_syntax_errors:
                # Only show previous syntax error attempts in the same symbol
                if entry.issue and "syntax error" in entry.issue.lower():
                    entry_symbol = None
                    if " in " in entry.issue:
                        entry_symbol = entry.issue.split(" in ", 1)[1].strip()
                    if entry_symbol == current_syntax_symbol:
                        is_relevant = True
            
            else:
                # Check for matching counterexamples
                if current_counterexamples and entry.current_result:
                    entry_ces = set(entry.current_result.counterexamples or [])
                    if entry_ces & current_counterexamples:  # Intersection
                        is_relevant = True
                
                # Check for matching unsat predicates
                if current_unsat and entry.current_result:
                    entry_unsat = set(entry.current_result.unsatisfied_predicates or [])
                    if entry_unsat & current_unsat:  # Intersection
                        is_relevant = True
            
            if is_relevant:
                relevant_entries.append(entry)
                _debug_log(f"  ✓ Iteration {entry.iteration_id} is relevant: {entry.issue}")
                if len(relevant_entries) >= count:
                    break
            else:
                _debug_log(f"  ✗ Iteration {entry.iteration_id} not relevant: {entry.issue}")

        # Reverse to show chronologically
        relevant_entries.reverse()

        # Report the span, not just the count: "out of N previous" read as a
        # trim failure when the log held duplicates, because N exceeded the
        # iteration actually being run.
        prior = self.entries[:-1]
        span = (f"iterations {prior[0].iteration_id}-{prior[-1].iteration_id}"
                if prior else "no prior iterations")
        _debug_log(
            f"Found {len(relevant_entries)} relevant entries out of "
            f"{len(prior)} prior log entries ({span})"
        )

        # Get current entry and previous iteration's issue
        current_entry = self.entries[-1] if self.entries else None  # Current iteration
        previous_issue = "None"
        if len(self.entries) >= 2:
            prev_entry = self.entries[-2]  # Previous iteration
            if prev_entry.issue:
                previous_issue = prev_entry.issue

        # Start formatting with previous model issue
        lines = []
        lines.append("PREVIOUS MODEL ISSUE:")
        lines.append(f"{previous_issue}")
        lines.append("")

        # Show Result Change from previous iteration to current iteration
        if current_entry and current_entry.previous_result and current_entry.current_result:
            prev = current_entry.previous_result  # Previous iteration's result
            curr = current_entry.current_result   # Current iteration's result
            lines.append("RESULT CHANGE (Previous → Current):")
            lines.append(f"  Syntax: {prev.syntax} → {curr.syntax}")
            if curr.syntax == "Error" and curr.error_message:
                lines.append(f"  Error: {curr.error_message}")

            prev_sat = ', '.join(prev.satisfied_predicates) if prev.satisfied_predicates else 'None'
            curr_sat = ', '.join(curr.satisfied_predicates) if curr.satisfied_predicates else 'None'
            lines.append(f"  Satisfied Predicates: [{prev_sat}] → [{curr_sat}]")

            prev_unsat = ', '.join(prev.unsatisfied_predicates) if prev.unsatisfied_predicates else 'None'
            curr_unsat = ', '.join(curr.unsatisfied_predicates) if curr.unsatisfied_predicates else 'None'
            lines.append(f"  Unsatisfied Predicates: [{prev_unsat}] → [{curr_unsat}]")

            prev_ce = ', '.join(prev.counterexamples) if prev.counterexamples else 'None'
            curr_ce = ', '.join(curr.counterexamples) if curr.counterexamples else 'None'
            lines.append(f"  Counterexamples: [{prev_ce}] → [{curr_ce}]")

            prev_no_ce = ', '.join(prev.no_counterexample) if prev.no_counterexample else 'None'
            curr_no_ce = ', '.join(curr.no_counterexample) if curr.no_counterexample else 'None'
            lines.append(f"  Passing Assertions: [{prev_no_ce}] → [{curr_no_ce}]")
            lines.append("")

        if not relevant_entries:
            lines.append("RELEVANT MODEL UPDATE HISTORY:")
            lines.append("No relevant regression history for current issues.")
            return '\n'.join(lines)

        # Format the relevant entries (reuse existing formatting logic)
        lines.append("RELEVANT MODEL UPDATE HISTORY (filtered by current issues):")
        lines.append("")
        
        for entry in relevant_entries:
            lines.append(f"--- Iteration {entry.iteration_id} ---")
            if getattr(entry, "kind", "repair") == "diagnostic":
                # Mode 3: this iteration measured, it did not repair. Labelling it
                # is what stops the reader treating an experiment as a failed fix,
                # and the verdict table is the measurement itself - the hypotheses
                # and readings declared before the run, joined to what the analyzer
                # returned. Without it the probe verdicts are bare SAT/UNSAT lines.
                lines.append("Iteration kind: DIAGNOSTIC (experiments only - no fix attempted)")
                verdicts = format_probe_verdicts(entry)
                if verdicts:
                    lines.append(verdicts)
                # What the RE reports it DID, beside what the analyzer measured.
                # A skipped item's stated reason lives only here - the verdict
                # table can say an item did not run, never why.
                if entry.diagnostic_execution:
                    lines.append("Diagnostic execution report (from the RE):")
                    lines.append(entry.diagnostic_execution)
            if getattr(entry, "diagnostic_dropped", None):
                lines.append(entry.diagnostic_dropped)
            lines.append(f"Fix Intent: {entry.fix_intent}")
            lines.append(f"Source: {entry.source_ref}")
            
            # Results comparison
            prev = entry.previous_result
            curr = entry.current_result
            if prev:
                lines.append(f"Result Change:")
                lines.append(f"  Syntax: {prev.syntax} → {curr.syntax}")
                if curr.syntax == "Error" and curr.error_message:
                    lines.append(f"  Error: {curr.error_message}")
                
                # Satisfied predicates comparison
                prev_sat = ', '.join(prev.satisfied_predicates) if prev.satisfied_predicates else 'None'
                curr_sat = ', '.join(curr.satisfied_predicates) if curr.satisfied_predicates else 'None'
                lines.append(f"  Satisfied Predicates: [{prev_sat}] → [{curr_sat}]")
                
                # Unsatisfied predicates comparison
                prev_unsat = ', '.join(prev.unsatisfied_predicates) if prev.unsatisfied_predicates else 'None'
                curr_unsat = ', '.join(curr.unsatisfied_predicates) if curr.unsatisfied_predicates else 'None'
                lines.append(f"  Unsatisfied Predicates: [{prev_unsat}] → [{curr_unsat}]")
                
                # Counterexamples comparison
                prev_ce = ', '.join(prev.counterexamples) if prev.counterexamples else 'None'
                curr_ce = ', '.join(curr.counterexamples) if curr.counterexamples else 'None'
                lines.append(f"  Counterexamples: [{prev_ce}] → [{curr_ce}]")
                
                # No counterexample comparison
                prev_no_ce = ', '.join(prev.no_counterexample) if prev.no_counterexample else 'None'
                curr_no_ce = ', '.join(curr.no_counterexample) if curr.no_counterexample else 'None'
                lines.append(f"  Passing Assertions: [{prev_no_ce}] → [{curr_no_ce}]")
            else:
                lines.append(f"Current Result:")
                lines.append(f"  Syntax: {curr.syntax}")
                if curr.syntax == "Error" and curr.error_message:
                    lines.append(f"  Error: {curr.error_message}")
                sat = ', '.join(curr.satisfied_predicates) if curr.satisfied_predicates else 'None'
                lines.append(f"  Satisfied Predicates: [{sat}]")
                unsat = ', '.join(curr.unsatisfied_predicates) if curr.unsatisfied_predicates else 'None'
                lines.append(f"  Unsatisfied Predicates: [{unsat}]")
                ce = ', '.join(curr.counterexamples) if curr.counterexamples else 'None'
                lines.append(f"  Counterexamples: [{ce}]")
                no_ce = ', '.join(curr.no_counterexample) if curr.no_counterexample else 'None'
                lines.append(f"  Passing Assertions: [{no_ce}]")
            
            # Impact
            if entry.actual_impact:
                actual = entry.actual_impact
                lines.append(f"Actual Impact:")
                if actual.unsat_to_sat:
                    lines.append(f"  UNSAT→SAT: {', '.join(actual.unsat_to_sat)}")
                if actual.sat_to_unsat:
                    lines.append(f"  SAT→UNSAT: {', '.join(actual.sat_to_unsat)}")
                if actual.fail_to_pass:
                    lines.append(f"  FAIL→PASS: {', '.join(actual.fail_to_pass)}")
                if actual.pass_to_fail:
                    lines.append(f"  PASS→FAIL: {', '.join(actual.pass_to_fail)}")
                lines.append(f"Outcome: {entry.outcome_classification}")
            
            # Previous Result (full details)
            if entry.previous_result:
                prev = entry.previous_result
                lines.append(f"Previous Result:")
                lines.append(f"  Syntax: {prev.syntax}")
                if prev.syntax == "Error" and prev.error_message:
                    lines.append(f"  Error: {prev.error_message}")
                prev_sat = ', '.join(prev.satisfied_predicates) if prev.satisfied_predicates else 'None'
                lines.append(f"  Satisfied Predicates: [{prev_sat}]")
                prev_unsat = ', '.join(prev.unsatisfied_predicates) if prev.unsatisfied_predicates else 'None'
                lines.append(f"  Unsatisfied Predicates: [{prev_unsat}]")
                prev_ce = ', '.join(prev.counterexamples) if prev.counterexamples else 'None'
                lines.append(f"  Counterexamples: [{prev_ce}]")
                prev_no_ce = ', '.join(prev.no_counterexample) if prev.no_counterexample else 'None'
                lines.append(f"  Passing Assertions: [{prev_no_ce}]")
            
            # Updated Lines (already filtered to exclude comments)
            if entry.updated_lines:
                lines.append(f"Updated Lines (diff):")
                lines.append(entry.updated_lines)
            
            lines.append("")
        
        return '\n'.join(lines)

    def _save_to_file(self) -> None:
        """Save regression log to JSON file."""
        if not self.log_path:
            return

        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.log_path, 'w', encoding='utf-8') as f:
            data = [entry.to_dict() for entry in self.entries]
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_from_file(self) -> None:
        """Load regression log from JSON file."""
        if not self.log_path or not self.log_path.exists():
            return

        # Check if file is empty
        if self.log_path.stat().st_size == 0:
            return

        with open(self.log_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                # File is corrupted, start fresh
                print(f"⚠ Warning: regression log file is corrupted, starting fresh")
                return

        self.entries = [RegressionLogEntry.from_dict(entry) for entry in data]

        # Rebuild error symbol index from loaded entries
        self.error_symbol_index = {}
        for entry in self.entries:
            if entry.issue and " in " in entry.issue:
                symbol = entry.issue.split(" in ", 1)[1].strip()
                if symbol:
                    if symbol not in self.error_symbol_index:
                        self.error_symbol_index[symbol] = []
                    self.error_symbol_index[symbol].append(entry.iteration_id)



def _extract_error_message_from_context(context: str) -> str:
    """
    Extract error message from syntax error context field.
    
    The context field contains both the error description and location information.
    This function extracts only the error description part (before "Syntax error in...").
    
    Example:
        Input: "There are 30 possible tokens that can appear here:\n# ( * / @ Int NAME...\nSyntax error in /path/file.als at line 53 column 20:"
        Output: "There are 30 possible tokens that can appear here:\n# ( * / @ Int NAME..."
    
    Args:
        context: Context field from syntax_error dictionary
    
    Returns:
        Error description (without location information)
    """
    import re
    
    if not context:
        return ""
    
    # Split at "Syntax error in" or "Type error in" to remove location information
    # Pattern: "Syntax error in <path> at line XX column YY:" or "Type error in <path>..."
    pattern = r'\n(?:Syntax|Type) error in .+?\.als at line \d+ column \d+:'
    
    parts = re.split(pattern, context, maxsplit=1)
    
    if len(parts) > 0:
        # Return the part before the location information
        error_message = parts[0].strip()
        return error_message
    
    # Fallback: return full context if pattern not found
    return context.strip()


def count_non_comment_lines_between(file_path: str, line1: int, line2: int) -> int:
    """
    Count non-comment lines between two line numbers in an Alloy file.
    
    This helps determine if two syntax errors are truly close in code distance,
    even if they appear far apart due to intervening comments.
    
    Args:
        file_path: Path to the Alloy model file
        line1: First line number (1-indexed)
        line2: Second line number (1-indexed)
    
    Returns:
        Number of non-comment lines between line1 and line2 (inclusive).
        Falls back to abs(line2 - line1) if file cannot be read.
    """
    import os
    
    # Ensure line1 <= line2
    if line1 > line2:
        line1, line2 = line2, line1
    
    # Fallback value if we can't read the file
    raw_distance = abs(line2 - line1)
    
    # Check if file exists
    if not os.path.exists(file_path):
        return raw_distance
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Validate line numbers
        if line1 < 1 or line2 > len(lines):
            return raw_distance
        
        # Count non-comment lines
        non_comment_count = 0
        in_multiline_comment = False
        
        for i in range(line1 - 1, line2):  # Convert to 0-indexed
            line = lines[i].strip()
            
            # Check for multi-line comment start
            if '/*' in line:
                in_multiline_comment = True
            
            # Check for multi-line comment end
            if '*/' in line:
                in_multiline_comment = False
                continue  # Skip this line as it's part of comment
            
            # Skip if we're inside a multi-line comment
            if in_multiline_comment:
                continue
            
            # Skip single-line comments
            if line.startswith('//'):
                continue
            
            # Skip empty lines
            if not line:
                continue
            
            # This is a non-comment line
            non_comment_count += 1
        
        return non_comment_count
    
    except Exception as e:
        # On any error, fall back to raw distance
        _debug_log(f"[NON_COMMENT_COUNT] Error reading {file_path}: {e}")
        return raw_distance


def count_consecutive_same_syntax_errors(
    regression_log_entries: List['RegressionLogEntry'],
    current_iteration: int,
    current_issue: str,
    current_syntax_error: Optional[Dict[str, Any]] = None,
    window: int = 7
) -> Dict[str, int]:
    """
    Count occurrences of THE SAME syntax error in previous iterations.

    Returns both consecutive count (how many times in a row) and total count
    (how many times within the recency window, even with gaps).

    Same syntax error is defined as:
    1. Syntax error within +/-5 non-comment lines of previous error, AND
    2. Same error message from context field (truncated at location info)

    Args:
        regression_log_entries: List of all regression log entries
        current_iteration: Current iteration number
        current_issue: Current syntax error issue description
        current_syntax_error: Current syntax_error dictionary (with context field)
        window: How many iterations to look back over, including the current one.
            Only occurrences within this window count toward 'total'.

    Returns:
        Dict with 'consecutive' and 'total' counts (both including current iteration)
    """
    import re

    # Initialize counts to 1 to represent the current iteration itself
    consecutive_count = 1
    total_count = 1
    consecutive_broken = False  # Flag to stop consecutive counting after first mismatch

    if not current_issue:
        return {'consecutive': consecutive_count, 'total': total_count}

    # Extract line number and error message from current iteration
    current_line = _extract_line_number_from_issue(current_issue)
    current_error_msg = ""
    
    if current_syntax_error and isinstance(current_syntax_error, dict):
        context = current_syntax_error.get('context', '')
        current_error_msg = _extract_error_message_from_context(context)
    
    # If we can't parse line number, fall back to exact string matching
    if current_line is None:
        current_issue_normalized = current_issue.lower().strip()

        # Loop through previous iterations within the recency window
        for i in range(current_iteration - 1, -1, -1):
            # Stop once we walk past the window (window includes current iteration)
            if i < current_iteration - (window - 1):
                break
            entry = next((e for e in regression_log_entries if e.iteration_id == i), None)
            if not entry or not entry.issue:
                consecutive_broken = True
                continue

            entry_issue_normalized = entry.issue.lower().strip()
            if entry_issue_normalized == current_issue_normalized:
                total_count += 1
                if not consecutive_broken:
                    consecutive_count += 1
            else:
                consecutive_broken = True

        return {'consecutive': consecutive_count, 'total': total_count}

    # Count backwards from previous iteration, comparing both line numbers AND error messages.
    # Only iterations within the recency window count toward the total.
    for i in range(current_iteration - 1, -1, -1):
        # Stop once we walk past the window (window includes current iteration)
        if i < current_iteration - (window - 1):
            break
        entry = next((e for e in regression_log_entries if e.iteration_id == i), None)
        if not entry or not entry.issue:
            consecutive_broken = True
            continue

        # Check if entry has a syntax error
        if not entry.issue.lower().startswith("syntax error"):
            # Hit a non-syntax-error iteration
            consecutive_broken = True
            continue

        # Extract line number from entry issue
        entry_line = _extract_line_number_from_issue(entry.issue)

        if entry_line is None:
            # Can't parse line number from this entry, check exact match
            if entry.issue.lower().strip() == current_issue.lower().strip():
                total_count += 1
                if not consecutive_broken:
                    consecutive_count += 1
            else:
                consecutive_broken = True
            continue

        # Check line number tolerance (±5 non-comment lines)
        raw_distance = abs(entry_line - current_line)
        
        is_close = False
        if raw_distance <= 5:
            is_close = True
        else:
            # Try non-comment distance calculation to account for comment lines
            current_model_path = f"Output/AlloyModels/AlloyModel__{current_iteration}.als"
            code_distance = count_non_comment_lines_between(
                current_model_path,
                min(entry_line, current_line),
                max(entry_line, current_line)
            )
            
            _debug_log(f"[SAME_ERROR_CHECK] Line distance: raw={raw_distance}, code={code_distance}")
            
            if code_distance <= 5:
                is_close = True
                _debug_log(f"[SAME_ERROR_CHECK] Errors close in code (within 5 non-comment lines)")

        if not is_close:
            # Different location
            consecutive_broken = True
            continue

        # Extract symbol names from issue descriptions for comparison
        # Format: "syntax error at line X in <symbol>"
        current_symbol = ""
        entry_symbol = ""

        if " in " in current_issue:
            current_symbol = current_issue.split(" in ", 1)[1].strip()
        if " in " in entry.issue:
            entry_symbol = entry.issue.split(" in ", 1)[1].strip()

        # Extract error message from entry's stored context
        entry_error_msg = ""
        if entry.syntax_error_context:
            entry_error_msg = _extract_error_message_from_context(entry.syntax_error_context)

        # Compare error messages (normalized - remove all whitespace variations)
        # Normalize by: lowercasing, stripping edges, collapsing internal whitespace
        current_msg_normalized = ' '.join(current_error_msg.strip().lower().split())
        entry_msg_normalized = ' '.join(entry_error_msg.strip().lower().split())

        # Debug logging
        _debug_log(f"[SAME_ERROR_CHECK] Comparing iteration {current_iteration} with {i}:")
        _debug_log(f"  Current line: {current_line}, Entry line: {entry_line}, Diff: {abs(entry_line - current_line)}")
        _debug_log(f"  Current symbol: '{current_symbol}', Entry symbol: '{entry_symbol}'")
        _debug_log(f"  Current msg: '{current_msg_normalized[:80]}...'")
        _debug_log(f"  Entry msg: '{entry_msg_normalized[:80]}...'")

        # Check if symbols match (if both available)
        if current_symbol and entry_symbol and current_symbol != entry_symbol:
            # Different symbols - this is a different error
            _debug_log(f"  Result: DIFFERENT symbol")
            consecutive_broken = True
            continue

        # IMPORTANT: Only compare if BOTH error messages are non-empty
        # If either is empty, we can't reliably determine if they're the same error
        if not current_msg_normalized or not entry_msg_normalized:
            # Missing error context - cannot determine if same error
            # Be conservative: assume different error
            _debug_log(f"  Result: STOP (missing context)")
            consecutive_broken = True
            continue

        # All conditions must match: line number (±5) AND symbol AND error message
        if current_msg_normalized == entry_msg_normalized:
            total_count += 1
            if not consecutive_broken:
                consecutive_count += 1
            _debug_log(f"  Result: SAME (consecutive={consecutive_count}, total={total_count})")
        else:
            # Different error message at similar location
            _debug_log(f"  Result: DIFFERENT error message")
            consecutive_broken = True

    return {'consecutive': consecutive_count, 'total': total_count}


def _extract_line_number_from_issue(issue: str) -> Optional[int]:
    """
    Extract line number from syntax error issue description.

    Expected format: "syntax error at line XX (...)" or similar variations

    Args:
        issue: Issue description string

    Returns:
        Line number as integer, or None if not found
    """
    import re

    if not issue:
        return None

    # Pattern to match "line XX" or "line: XX"
    pattern = r'\bline[:\s]+(\d+)\b'
    match = re.search(pattern, issue, re.IGNORECASE)

    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None

    return None


def extract_issue_description(analysis_result: Dict[str, Any]) -> str:
    """
    Extract issue description from analysis results.
    
    Concatenates all issues found:
    - Syntax errors with function/fact/pred/assert name from code_snippet
    - Unsat predicates
    - Counterexamples (failed assertions)
    
    Args:
        analysis_result: Dictionary containing analysis results
        
    Returns:
        Concatenated string of all issues (e.g., "syntax error in fact ExistingSystem; unsat predicate: R1R2; counterexample: assertMutEx")
    """
    import re
    
    issues = []
    
    # Check for syntax errors
    syntax_errors = analysis_result.get('syntax_errors', [])
    if syntax_errors:
        for error in syntax_errors:
            if isinstance(error, dict):
                # Extract block name from code_snippet
                code_snippet = error.get('code_snippet', '')
                line_num = error.get('line', 0)
                block_name = ""
                
                # Pattern 1: "CODE CONTEXT - COMPLETE BLOCK: fact ExistingSystem (lines ...)"
                match = re.search(r'CODE CONTEXT - COMPLETE BLOCK:\s*(.+?)\s*\(lines', code_snippet)
                if match:
                    block_name = match.group(1).strip()
                    issues.append(f"syntax error at line {line_num} in {block_name}")
                else:
                    # Pattern 2: "CODE CONTEXT (lines X-Y):" - try to extract what's on the error line
                    # Look for lines with the error marker
                    lines = code_snippet.split('\n')
                    error_line_content = ""
                    for line in lines:
                        if '^^ ERROR' in line:
                            # Find the previous line which has the actual code
                            idx = lines.index(line)
                            if idx > 0:
                                # Get the code line (remove line number prefix)
                                code_line = lines[idx - 1]
                                # Extract content after line number (format: "  4: open util/seq...")
                                match_code = re.search(r'^\s*\d+:\s*(.+?)$', code_line)
                                if match_code:
                                    error_line_content = match_code.group(1).strip()
                            break
                    
                    if error_line_content:
                        # Try to identify what kind of statement it is
                        if error_line_content.startswith('open '):
                            issues.append(f"syntax error at line {line_num} (open statement)")
                        elif any(keyword in error_line_content for keyword in ['sig ', 'abstract sig']):
                            issues.append(f"syntax error at line {line_num} (sig definition)")
                        elif error_line_content.startswith('pred '):
                            issues.append(f"syntax error at line {line_num} (pred definition)")
                        elif error_line_content.startswith('fun '):
                            issues.append(f"syntax error at line {line_num} (fun definition)")
                        elif error_line_content.startswith('fact '):
                            issues.append(f"syntax error at line {line_num} (fact definition)")
                        elif error_line_content.startswith('assert '):
                            issues.append(f"syntax error at line {line_num} (assert definition)")
                        else:
                            issues.append(f"syntax error at line {line_num}")
                    else:
                        # Fallback - just use line number
                        issues.append(f"syntax error at line {line_num}")
    
    # Check for unsatisfied predicates
    unsat_predicates = analysis_result.get('unsat_run_commands', [])
    if unsat_predicates:
        # Extract just the predicate names
        pred_names = []
        for pred in unsat_predicates:
            if isinstance(pred, dict):
                pred_names.append(pred.get('name', 'unknown'))
            else:
                pred_names.append(str(pred))
        if pred_names:
            pred_str = ', '.join(pred_names)
            issues.append(f"unsat predicate: {pred_str}")
    
    # Check for counterexamples (failed assertions)
    counterexamples = analysis_result.get('counterexamples', [])
    if counterexamples:
        # Extract just the command names
        ce_names = []
        for ce in counterexamples:
            if isinstance(ce, dict):
                ce_names.append(ce.get('command_name', 'unknown'))
            else:
                ce_names.append(str(ce))
        if ce_names:
            ce_str = ', '.join(ce_names)
            issues.append(f"counterexample: {ce_str}")
    
    return '; '.join(issues) if issues else "No issues"




def _get_embedding_device() -> str:
    """
    Get the device to use for embedding models from config.
    
    Returns:
        Device string: "cpu", "cuda", or automatically determined
    """
    try:
        import yaml
        from pathlib import Path
        
        config_path = Path("config.yaml")
        if not config_path.exists():
            return "cpu"  # Default to CPU if no config
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        device_setting = config.get('embeddings', {}).get('device', 'auto')
        
        if device_setting == "auto":
            # Auto-detect: use CUDA if available, otherwise CPU
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda"
            except:
                pass
            return "cpu"
        elif device_setting == "cuda":
            # User explicitly requested CUDA - check if available
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda"
                else:
                    print("  ⚠️  Warning: CUDA requested but not available, falling back to CPU")
                    return "cpu"
            except:
                print("  ⚠️  Warning: PyTorch not available, falling back to CPU")
                return "cpu"
        else:
            # CPU or any other value defaults to CPU
            return "cpu"
    except Exception as e:
        print(f"  ⚠️  Warning: Error reading config for device setting: {e}, defaulting to CPU")
        return "cpu"


def _get_embedding_model_name() -> str:
    """
    Get the embedding model name from config.
    
    Returns:
        Model name string
    """
    try:
        import yaml
        from pathlib import Path
        
        config_path = Path("config.yaml")
        if not config_path.exists():
            return "all-MiniLM-L6-v2"  # Default model
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        return config.get('embeddings', {}).get('model_name', 'all-MiniLM-L6-v2')
    except Exception as e:
        print(f"  ⚠️  Warning: Error reading config for model name: {e}, using default")
        return "all-MiniLM-L6-v2"


def detect_fix_pattern(
    current_issue: str,
    regression_log_entries: List['RegressionLogEntry']
) -> Optional[str]:
    """
    Detect if the same fix approach has been tried multiple times for the same issue.
    Uses semantic similarity (embeddings) to detect similar fix approaches.

    Args:
        current_issue: Current issue description
        regression_log_entries: List of all regression log entries

    Returns:
        Pattern note string if pattern detected, None otherwise
    """
    # Extract same-issue failed fixes
    failed_fixes = get_same_issue_failed_fixes(current_issue, regression_log_entries)

    # If no previous failed fixes, this is the first attempt
    if len(failed_fixes) == 0:
        return "First attempt at fixing this issue"

    # If only 1 previous failed fix
    if len(failed_fixes) == 1:
        return "1 previous fix attempt for this issue has failed"

    # For 2+ failed fixes, use semantic similarity to detect patterns
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np

        # Get device and model name from config
        device = _get_embedding_device()
        model_name = _get_embedding_model_name()
        
        # Load model with configured device
        model = SentenceTransformer(model_name, device=device)

        # Extract fix_intent texts
        fix_intents = [entry.fix_intent for entry in failed_fixes]

        # Encode to embeddings
        embeddings = model.encode(fix_intents, convert_to_numpy=True)

        # Compute cosine similarity matrix
        from sklearn.metrics.pairwise import cosine_similarity
        similarity_matrix = cosine_similarity(embeddings)

        # Find clusters of similar fix approaches (similarity > 0.75)
        similarity_threshold = 0.80
        clusters = []
        used = set()

        for i in range(len(fix_intents)):
            if i in used:
                continue

            # Start new cluster with this fix_intent
            cluster = [i]
            used.add(i)

            # Find all similar fix_intents
            for j in range(i + 1, len(fix_intents)):
                if j not in used and similarity_matrix[i][j] > similarity_threshold:
                    cluster.append(j)
                    used.add(j)

            clusters.append(cluster)

        # Find largest cluster (most repeated approach)
        largest_cluster = max(clusters, key=len)
        total_attempts = len(failed_fixes)

        if len(largest_cluster) >= 2:
            # Get representative fix_intent from cluster (first one)
            representative_intent = fix_intents[largest_cluster[0]]

            # Show complete statement (no truncation)
            return f"{total_attempts} total fix attempts for this issue. Similar approach used {len(largest_cluster)} times: \"{representative_intent}\""

    except Exception as e:
        # Fallback if embedding fails
        print(f"Warning: Failed to detect pattern using embeddings: {e}")

    # Fallback: just count total failed attempts
    return f"{len(failed_fixes)} total fix attempts for this issue have failed"


def _parse_issue_components(issue: str):
    """
    Parse an issue description into its components.

    Handles the three historical syntax-error formats plus unsat-predicate and
    counterexample lists (previously duplicated inline in
    get_same_issue_failed_fixes for the current issue and for each entry).

    Returns:
        (syntax_block, syntax_construct, unsat_predicates, counterexamples)
        where the first two are Optional[str] and the last two are sets.
    """
    import re

    syntax_block = None
    syntax_construct = None
    unsat_preds = set()
    counterexamples = set()

    # Format 1 (current): "syntax error at line X in block_name"
    syntax_match = re.search(r'syntax error at line \d+ in (.+?)(?:;|$)', issue)
    if syntax_match:
        syntax_block = syntax_match.group(1).strip()
    else:
        # Format 2 (old): "syntax error in fact ExistingSystem"
        syntax_match = re.search(r'syntax error in (.+?)(?:;|$)', issue)
        if syntax_match:
            syntax_block = syntax_match.group(1).strip()
        else:
            # Format 3 (older): "syntax error at line 4 (open statement)"
            syntax_match = re.search(r'syntax error at line \d+ \((.+?)\)', issue)
            if syntax_match:
                syntax_construct = syntax_match.group(1).strip()

    unsat_match = re.search(r'unsat predicate: (.+?)(?:;|$)', issue)
    if unsat_match:
        unsat_preds = set(p.strip() for p in unsat_match.group(1).split(','))

    ce_match = re.search(r'counterexample: (.+?)(?:;|$)', issue)
    if ce_match:
        counterexamples = set(c.strip() for c in ce_match.group(1).split(','))

    return syntax_block, syntax_construct, unsat_preds, counterexamples


def format_probe_verdicts(entry: Any) -> str:
    """
    Render a diagnostic entry's measured results: the manifest joined to what the
    analyzer returned for each probe.

    This is how the experiment's context reaches InterpretResults - the verdicts
    alone are meaningless without the hypothesis and the reading declared before
    the run, and a plan item with no probe must show as UNMEASURED rather than
    silently look like an UNSAT.

    Returns "" for a non-diagnostic entry or one with no manifest.
    """
    if getattr(entry, "kind", "repair") != "diagnostic":
        return ""
    plan = getattr(entry, "diagnostic_plan", None)
    if not plan:
        return ""
    try:
        from .repair_plateau_detector import (
            build_probe_verdict_block,
            read_back_probe_verdicts,
        )
        result = getattr(entry, "current_result", None)
        readback = read_back_probe_verdicts(
            plan,
            satisfied=getattr(result, "satisfied_predicates", None) or [],
            unsatisfied=getattr(result, "unsatisfied_predicates", None) or [],
        )
        return build_probe_verdict_block(
            readback,
            control=getattr(entry, "diagnostic_control", None),
            probe_bodies=getattr(entry, "diagnostic_probe_bodies", None),
        )
    except Exception:
        return ""


def derive_outcome_classification(
    has_syntax_errors: bool,
    resolved_target_issue: Optional[bool],
    has_previous_iteration: bool,
    current_issue: Optional[str] = None,
    kind: str = "repair",
) -> str:
    """
    Deterministically classify an iteration's outcome from verification facts.

    Used as a guaranteed fallback so entries never stay "pending":
    InterpretResults (the LLM classifier) is skipped entirely on syntax-error
    iterations and may fail to produce/parse a classification on semantic
    ones; this derives an honest classification from data the workflow
    already computed. The LLM classification, when available, overwrites it.

    Returns one of:
        "initial_verification: ..."   - first evaluated model, no prior fix to classify
        "syntax_error_blocked: ..."   - model does not parse, resolution undeterminable
        "no_improvement: ..."         - the targeted issue persists after the fix
        "unintended_regression: ..."  - prior issue resolved but a new syntax error appeared
        "expected_improvement: ..."   - the targeted issue was resolved
        "unclassified: ..."           - no prior issue comparison was possible
        "diagnostic_measurement: ..." - RE Mode 3: probes were added to measure,
                                       no fix was attempted, so "did it improve?"
                                       has no answer. Without this the entry falls
                                       through to "unclassified", which reads as a
                                       failure to classify rather than as nothing
                                       to classify.
    """
    if kind == "diagnostic":
        if has_syntax_errors:
            return ("diagnostic_measurement: probes added but the model does not "
                    "parse; no verdicts were produced")
        return ("diagnostic_measurement: probes added to measure a hypothesis; "
                "no fix attempted, so no improvement or regression is implied")

    if not has_previous_iteration:
        if has_syntax_errors:
            return "initial_verification: initial model does not parse"
        return "initial_verification: first evaluation; no prior fix to classify"

    if has_syntax_errors:
        if resolved_target_issue is True:
            return ("unintended_regression: previous target issue resolved "
                    "but a new syntax error was introduced")
        if resolved_target_issue is False:
            return "no_improvement: syntax error persists after repair attempt"
        return "syntax_error_blocked: model does not parse; verification skipped"

    if resolved_target_issue is True:
        # Deliberately provisional: a single absent iteration is not proof of
        # resolution (oscillating errors). update_resolution_statuses upgrades
        # this to expected_improvement after several clean iterations, or
        # corrects it to no_improvement if the issue recurs.
        if current_issue:
            return f"provisional_improvement: target issue absent (confirmation pending); remaining issues: {current_issue}"
        return "provisional_improvement: target issue absent (confirmation pending); no outstanding issues"
    if resolved_target_issue is False:
        return "no_improvement: previous target issue persists"

    if current_issue:
        return f"unclassified: no prior issue to compare; current issues: {current_issue}"
    return "expected_improvement: no prior issue and no outstanding issues"


def issues_match(
    target_issue: Optional[str],
    target_signature: Optional[str],
    current_issue: Optional[str],
    current_signature: Optional[str],
    target_fingerprint: Optional[str] = None,
    current_fingerprint: Optional[str] = None,
) -> bool:
    """
    Decide whether the current iteration's issue is a recurrence of a target issue.

    When both normalized signatures are known, they are the authoritative,
    location-independent identity of the error (category + detail + construct),
    so matching relies on signature equality: a different signature means a
    genuinely different issue even within the same block (e.g. an arity error
    then a delimiter error in the same predicate).

    The normalized signature is deliberately coarse, so two DIFFERENT errors in
    the same construct can share it (e.g. an illegal '>' on a Classification
    value vs on a Time value in the same predicate). When both errors carry a
    finer detail_fingerprint (offending operand type + nearby token) and those
    fingerprints DIFFER, the current error is a different error at the same
    family/site - NOT a recurrence. Missing fingerprints fall back to
    signature-only (previous behavior).

    Only when a signature is missing (semantic issues carry None) does it fall
    back to issue-component overlap (same syntax block, or a shared unsat
    predicate / counterexample name). Shared by LessonProbation and
    update_resolution_statuses.
    """
    if target_signature and current_signature:
        if target_signature != current_signature:
            return False
        if target_fingerprint and current_fingerprint and target_fingerprint != current_fingerprint:
            return False
        return True
    if target_issue and current_issue:
        t_block, t_construct, t_unsat, t_ce = _parse_issue_components(target_issue)
        c_block, c_construct, c_unsat, c_ce = _parse_issue_components(current_issue)
        if t_block and c_block and t_block == c_block:
            return True
        if t_unsat and (t_unsat & c_unsat):
            return True
        if t_ce and (t_ce & c_ce):
            return True
    return False


def update_resolution_statuses(
    entries: List['RegressionLogEntry'],
    current_iteration: int,
    required_clean_iterations: int = 3,
    logger=None,
) -> Dict[str, List[int]]:
    """
    Advance provisional resolutions ("temporarily_absent") toward confirmation
    or reversion, so an oscillating error (A, B, A, B...) is never permanently
    recorded as resolved.

    An entry is marked resolution_status={'status': 'temporarily_absent', ...}
    by the workflow when its target issue is first observed absent. This
    function, called every iteration, re-examines each such entry against the
    log itself (stateless, so it also works across resume):

      - REVERTED: the target issue recurred in some iteration since - the
        entry's status becomes 'resolution_reverted', resolved_target_issue is
        flipped to False (so the fix re-enters failed-fix history instead of
        being hidden by the resolved filter), and outcome_classification is
        corrected to "no_improvement: ... recurred".
      - CONFIRMED: the target issue stayed absent for required_clean_iterations
        consecutive OBSERVABLE iterations (a syntax-broken iteration cannot
        show whether a semantic issue is still present, so it neither advances
        nor breaks confirmation of semantic targets) - status becomes
        'resolved_confirmed' and a provisional outcome_classification is
        upgraded to expected_improvement.

    Returns:
        {'confirmed': [iteration_ids], 'reverted': [iteration_ids]}
    """
    result: Dict[str, List[int]] = {'confirmed': [], 'reverted': []}
    by_iter = {e.iteration_id: e for e in entries}

    for entry in entries:
        rs = entry.resolution_status
        if not rs or rs.get('status') != 'temporarily_absent':
            continue
        if entry.iteration_id > current_iteration:
            continue

        target_issue = rs.get('target_issue') or ''
        target_signature = rs.get('target_signature')
        target_fingerprint = rs.get('target_fingerprint')
        semantic_target = ('unsat predicate' in target_issue
                           or 'counterexample' in target_issue)

        recurred_at = None
        clean_count = 0
        for it in range(entry.iteration_id, current_iteration + 1):
            later = by_iter.get(it)
            if later is None:
                continue
            later_signature = (later.error_signature or {}).get('normalized_signature')
            later_fingerprint = (later.error_signature or {}).get('detail_fingerprint')
            if issues_match(target_issue, target_signature, later.issue, later_signature,
                            target_fingerprint, later_fingerprint):
                recurred_at = it
                break
            observable = (later.current_result is not None
                          and later.current_result.syntax == "OK") or not semantic_target
            if observable:
                clean_count += 1

        if recurred_at is not None:
            rs['status'] = 'resolution_reverted'
            rs['recurred_at'] = recurred_at
            entry.resolved_target_issue = False
            entry.outcome_classification = (
                f"no_improvement: target issue recurred at iteration {recurred_at} "
                f"(temporary absence, not a real fix)"
            )
            result['reverted'].append(entry.iteration_id)
            if logger and hasattr(logger, "log"):
                logger.log(
                    f"🔁 Resolution REVERTED for iteration {entry.iteration_id}: "
                    f"target issue '{target_issue[:80]}' recurred at iteration {recurred_at}"
                )
        elif clean_count >= required_clean_iterations:
            rs['status'] = 'resolved_confirmed'
            rs['confirmed_at'] = current_iteration
            if entry.outcome_classification.startswith("provisional_improvement"):
                entry.outcome_classification = (
                    "expected_improvement" + entry.outcome_classification[len("provisional_improvement"):]
                )
            result['confirmed'].append(entry.iteration_id)
            if logger and hasattr(logger, "log"):
                logger.log(
                    f"✅ Resolution CONFIRMED for iteration {entry.iteration_id}: "
                    f"target issue '{target_issue[:80]}' stayed absent for "
                    f"{clean_count} observable iterations"
                )

    return result


def get_same_issue_failed_fixes(
    current_issue: str,
    regression_log_entries: List['RegressionLogEntry']
) -> List['RegressionLogEntry']:
    """
    Extract all failed fixes that targeted the same issue as current.

    Matches by:
    - Same syntax error (same block name OR same construct type)
    - Same unsat predicate (same predicate name)
    - Same counterexample (same assertion name)

    Args:
        current_issue: Current issue description
        regression_log_entries: List of all regression log entries

    Returns:
        List of entries with resolved_target_issue=False targeting same issue
    """
    import re

    failed_fixes = []

    # Parse current issue to extract components
    _debug_log(f"[FAILED_FIX_HISTORY] Searching for previous failures matching issue: '{current_issue}'")

    (current_syntax_block, current_syntax_construct,
     current_unsat_preds, current_counterexamples) = _parse_issue_components(current_issue)

    _debug_log(f"[FAILED_FIX_HISTORY] Extracted components: block='{current_syntax_block}', construct='{current_syntax_construct}'")

    # Find entries with resolved_target_issue=False and matching issue
    for entry in regression_log_entries:
        if entry.resolved_target_issue is False and entry.issue:
            # Parse entry issue
            (entry_syntax_block, entry_syntax_construct,
             entry_unsat_preds, entry_counterexamples) = _parse_issue_components(entry.issue)
            
            # Check if any component matches
            match = False
            match_reason = ""

            # Syntax error matching:
            # - Old format: exact block name match
            # - New format: same construct type (e.g., both "open statement")
            # - Cross format: if one has block and other has construct, don't match
            if current_syntax_block and entry_syntax_block:
                if entry_syntax_block == current_syntax_block:
                    match = True
                    match_reason = f"same syntax block '{current_syntax_block}'"
            elif current_syntax_construct and entry_syntax_construct:
                if entry_syntax_construct == current_syntax_construct:
                    match = True
                    match_reason = f"same syntax construct '{current_syntax_construct}'"

            # Unsat predicates
            if current_unsat_preds and entry_unsat_preds & current_unsat_preds:
                match = True
                match_reason = f"same unsat predicates"

            # Counterexamples
            if current_counterexamples and entry_counterexamples & current_counterexamples:
                match = True
                match_reason = f"same counterexamples"

            if match:
                _debug_log(f"[FAILED_FIX_HISTORY] Found match in iteration {entry.iteration_id}: {match_reason}")
                failed_fixes.append(entry)

    _debug_log(f"[FAILED_FIX_HISTORY] Total previous failures found: {len(failed_fixes)}")
    return failed_fixes


def check_issue_resolved(
    current_analysis: Dict[str, Any],
    previous_analysis: Optional[Dict[str, Any]],
    current_entry: 'RegressionLogEntry',
    previous_entry: Optional['RegressionLogEntry']
) -> Optional[bool]:
    """
    Determine if the target issue from previous iteration has been resolved.
    
    Returns:
        - None: First iteration (no previous to compare)
        - True: Target issue resolved (error eliminated or moved forward significantly)
        - False: Target issue persists or moved backward
    
    Args:
        current_analysis: Current iteration's analysis results
        previous_analysis: Previous iteration's analysis results
        current_entry: Current regression log entry
        previous_entry: Previous regression log entry
    """
    import re
    
    # First iteration - no previous to compare
    if previous_entry is None or previous_analysis is None:
        return None
    
    # Get the issue strings that were already extracted
    prev_issue = previous_entry.issue if previous_entry.issue else ""
    curr_issue = current_entry.issue if current_entry.issue else ""
    
    _debug_log(f"[DEBUG] check_issue_resolved - Issue comparison:")
    _debug_log(f"  Previous issue: '{prev_issue}'")
    _debug_log(f"  Current issue: '{curr_issue}'")
    
    resolved_status = True  # Assume resolved unless we find evidence otherwise
    
    # === Check Syntax Errors ===
    prev_syntax_errors = previous_analysis.get('syntax_errors', [])
    curr_syntax_errors = current_analysis.get('syntax_errors', [])
    
    if prev_syntax_errors:
        if not curr_syntax_errors:
            # Syntax error resolved DEFINITIVELY. Alloy could not compile the
            # previous model, so no semantic data (unsat predicates /
            # counterexamples) ever existed for it to leave a persisting issue
            # behind. A model that now compiles cleanly proves the target
            # syntax error is genuinely gone, so short-circuit here and return
            # resolved: the unsat/counterexample checks below compare against
            # previous semantic data that, for a syntax-error iteration, does
            # not exist and must not be allowed to flip this to "not resolved".
            _debug_log(f"  → Syntax errors cleared (model compiles) - RESOLVED (definitive)")
            return True
        else:
            # A syntax error persists. The normalized signature (from
            # ErrorNormalizer) is the authoritative, location-independent identity
            # of the error (category + detail + construct): the same signature
            # means the target error persists; a different signature means the
            # target was resolved even if a new error surfaced in the same block.
            prev_sig = (previous_entry.error_signature or {}).get('normalized_signature')
            curr_sig = (current_entry.error_signature or {}).get('normalized_signature')
            if prev_sig and curr_sig:
                if prev_sig == curr_sig:
                    # Same coarse signature. If both errors carry a finer
                    # detail_fingerprint (operand type + nearby token) and they
                    # DIFFER, this is a different error at the same family/site
                    # (e.g. the target '>' on Classification was fixed and a new
                    # '<' on Time surfaced in the same predicate) - so the target
                    # WAS resolved. Only an identical fingerprint (or missing
                    # fingerprints) means the target error genuinely persists.
                    prev_fp = (previous_entry.error_signature or {}).get('detail_fingerprint')
                    curr_fp = (current_entry.error_signature or {}).get('detail_fingerprint')
                    if prev_fp and curr_fp and prev_fp != curr_fp:
                        _debug_log(
                            f"  → Same signature ({curr_sig}) but different detail "
                            f"fingerprint (prev={prev_fp!r}, curr={curr_fp!r}) - RESOLVED "
                            f"(different error at same family/site)"
                        )
                    else:
                        _debug_log(f"  → Same normalized signature ({curr_sig}) and fingerprint - NOT resolved")
                        resolved_status = False
                else:
                    _debug_log(f"  → Different normalized signature (prev={prev_sig}, curr={curr_sig}) - RESOLVED")
            else:
                # No signature to compare - cannot prove the error changed; treat
                # the syntax issue as still unresolved (conservative).
                _debug_log("  → Missing normalized signature - NOT resolved (conservative)")
                resolved_status = False

    # === Check Unsat Predicates ===
    prev_unsat_raw = previous_analysis.get('unsat_run_commands', [])
    curr_unsat_raw = current_analysis.get('unsat_run_commands', [])
    
    # Extract predicate names from previous unsat predicates
    prev_unsat = set()
    for pred in prev_unsat_raw:
        if isinstance(pred, dict):
            prev_unsat.add(pred.get('name', ''))
        else:
            prev_unsat.add(str(pred))
    
    # Extract predicate names from current unsat predicates
    curr_unsat = set()
    for pred in curr_unsat_raw:
        if isinstance(pred, dict):
            curr_unsat.add(pred.get('name', ''))
        else:
            curr_unsat.add(str(pred))
    
    if prev_unsat:
        # Check if previous unsat predicates are still unsat
        still_unsat = prev_unsat & curr_unsat
        
        if still_unsat:
            # Some previous unsat predicates still unsat
            _debug_log(f"  → Unsat predicates still failing: {still_unsat} - NOT resolved")
            resolved_status = False
        else:
            _debug_log(f"  → Previous unsat predicates resolved")
    
    # === Check Counterexamples ===
    prev_counterexamples = previous_analysis.get('counterexamples', [])
    curr_counterexamples = current_analysis.get('counterexamples', [])

    if prev_counterexamples:
        # Extract command names from previous counterexamples
        prev_ce_names = set()
        for ce in prev_counterexamples:
            if isinstance(ce, dict):
                prev_ce_names.add(ce.get('command_name', ''))  # Fixed: use 'command_name' not 'command'

        # Extract command names from current counterexamples
        curr_ce_names = set()
        for ce in curr_counterexamples:
            if isinstance(ce, dict):
                curr_ce_names.add(ce.get('command_name', ''))  # Fixed: use 'command_name' not 'command'

        # Check if any previous counterexample (same assertion) still has counterexample
        still_failing = prev_ce_names & curr_ce_names

        if still_failing:
            # Same assertion still has counterexample - NOT resolved
            _debug_log(f"  → Counterexamples still failing: {still_failing} - NOT resolved")
            resolved_status = False
        else:
            _debug_log(f"  → Previous counterexamples resolved")
    
    _debug_log(f"[DEBUG] check_issue_resolved - Final decision: {resolved_status}")
    return resolved_status



def format_failed_fix_history(
    current_issue: str,
    regression_log_entries: List['RegressionLogEntry']
) -> str:
    """
    Format failed fix history for inclusion in Evaluator prompt.
    
    Args:
        current_issue: Current issue description
        regression_log_entries: List of all regression log entries
        
    Returns:
        Formatted string of failed fix history, or "None - this is the first attempt" if no history
    """
    failed_fixes = get_same_issue_failed_fixes(current_issue, regression_log_entries)
    
    if not failed_fixes:
        return "None - this is the first attempt at fixing this issue."
    
    lines = []
    
    # Add pattern detection note if available
    pattern_note = detect_fix_pattern(current_issue, regression_log_entries)
    if pattern_note:
        lines.append(f"⚠️ PATTERN DETECTED: {pattern_note}")
        lines.append("")
    
    lines.append(f"Previous failed attempts for this issue ({len(failed_fixes)} total):")
    lines.append(f"Issue: {current_issue}")
    lines.append("")

    for i, entry in enumerate(failed_fixes, 1):
        lines.append(f"--- Attempt {i} (Iteration {entry.iteration_id}) ---")
        lines.append(f"Fix Intent: {entry.fix_intent}")
        lines.append(f"Source Ref: {entry.source_ref}")
        lines.append("")
    
    return '\n'.join(lines)



def is_feedback_too_similar(
    new_feedback: str,
    previous_feedbacks: List[str],
    threshold: float = 0.80
) -> tuple[bool, Optional[int], Optional[float]]:
    """
    Check if new feedback is too similar to any previous feedback.
    
    Uses semantic similarity (embeddings) to detect if the new feedback
    repeats a previously tried approach.
    
    Args:
        new_feedback: New feedback text to check
        previous_feedbacks: List of previous feedback texts
        threshold: Similarity threshold (default 0.80)
        
    Returns:
        Tuple of (is_too_similar, index_of_similar, similarity_score)
        - is_too_similar: True if similarity > threshold
        - index_of_similar: Index in previous_feedbacks that matched (None if no match)
        - similarity_score: Highest similarity score found (None if error)
    """
    if not previous_feedbacks or len(previous_feedbacks) == 0:
        return (False, None, None)
    
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        
        # Get device and model name from config
        device = _get_embedding_device()
        model_name = _get_embedding_model_name()
        
        # Load model with configured device
        model = SentenceTransformer(model_name, device=device)
        
        # Encode all feedbacks
        all_feedbacks = [new_feedback] + previous_feedbacks
        embeddings = model.encode(all_feedbacks, convert_to_numpy=True)
        
        # Compute cosine similarity between new and each previous
        from sklearn.metrics.pairwise import cosine_similarity
        new_embedding = embeddings[0:1]  # First one is new feedback
        prev_embeddings = embeddings[1:]  # Rest are previous feedbacks
        
        similarities = cosine_similarity(new_embedding, prev_embeddings)[0]
        
        # Find max similarity
        max_similarity = float(np.max(similarities))
        max_index = int(np.argmax(similarities))
        
        is_too_similar = max_similarity > threshold
        
        return (is_too_similar, max_index if is_too_similar else None, max_similarity)
        
    except Exception as e:
        print(f"Warning: Failed to check feedback similarity: {e}")
        return (False, None, None)

# unused helper function. *TO-REMOVE 
def extract_repair_instructions(feedback: str) -> str:
    """
    Extract the [REPAIR INSTRUCTIONS] section from syntax repair feedback.

    Args:
        feedback: Full feedback text from GenerateSyntaxRepairInstruction

    Returns:
        Text content of the REPAIR INSTRUCTIONS section, or full feedback if section not found
    """
    import re

    # Try to find the REPAIR INSTRUCTIONS section
    # Pattern: [REPAIR INSTRUCTIONS]: followed by content until next section or end
    pattern = r'\[REPAIR INSTRUCTIONS\]:?\s*\n(.*?)(?:\n\[(?:RATIONALE|LESSON|DIAGNOSIS|FIX INTENT)\]:|$)'

    match = re.search(pattern, feedback, re.DOTALL | re.IGNORECASE)

    if match:
        instructions = match.group(1).strip()
        return instructions if instructions else feedback

    # Fallback: return full feedback if section not found
    return feedback


def extract_fix_intent(feedback: str) -> str:
    """
    Extract the [FIX INTENT] section from syntax repair feedback.

    Args:
        feedback: Full feedback text from GenerateSyntaxRepairInstruction

    Returns:
        Text content of the FIX INTENT section, or empty string if section not found
    """
    import re

    # Try to find the FIX INTENT section
    # Pattern: [FIX INTENT]: followed by content (same line or next line)
    # until the next section header or end of text
    pattern = r'\[FIX INTENT\]:?\s*(.*?)(?:\n\[(?:REPAIR INSTRUCTIONS|RATIONALE|LESSON|DIAGNOSIS)\]:|$)'

    match = re.search(pattern, feedback, re.DOTALL | re.IGNORECASE)

    if match:
        return match.group(1).strip()

    # Section not found - return empty string (combined separately with
    # extract_repair_instructions, which already has a full-feedback fallback)
    return ""


def extract_fix_intent_and_repair_instructions(feedback: str) -> str:
    """
    Extract and combine the [FIX INTENT] and [REPAIR INSTRUCTIONS] sections
    from syntax repair feedback, for use in similarity comparisons.

    Combining both captures the high-level intent of the fix as well as the
    concrete steps, so two attempts with the same intent but differently
    worded steps (or vice versa) are still recognized as similar.

    Args:
        feedback: Full feedback text from GenerateSyntaxRepairInstruction

    Returns:
        Combined text of FIX INTENT + REPAIR INSTRUCTIONS, or full feedback
        if neither section is found
    """
    fix_intent = extract_fix_intent(feedback)
    repair_instructions = extract_repair_instructions(feedback)

    if not fix_intent and repair_instructions == feedback:
        # Neither section was found - fall back to full feedback
        return feedback

    return f"{fix_intent}\n{repair_instructions}".strip()


def save_rejected_feedback(
    feedback: str,
    iteration: int,
    reason: str,
    similarity_score: float = None,
    similar_to_attempt: int = None
):
    """
    Save rejected feedback to Output/Feedback/RejectedFeedback_MMDD.txt
    
    Args:
        feedback: The rejected feedback text
        iteration: Current iteration number
        reason: Reason for rejection
        similarity_score: Similarity score if rejected due to similarity
        similar_to_attempt: Which attempt it was similar to
    """
    from datetime import datetime
    from pathlib import Path
    
    # Create output directory
    output_dir = Path("Output/Feedback")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename with MMDD
    timestamp = datetime.now().strftime("%m%d")
    output_file = output_dir / f"RejectedFeedback_{timestamp}.txt"
    
    # Format entry
    entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    separator = "=" * 80
    
    entry = f"\n{separator}\n"
    entry += f"REJECTED FEEDBACK - {entry_time}\n"
    entry += f"{separator}\n"
    entry += f"Iteration: {iteration}\n"
    entry += f"Reason: {reason}\n"
    
    if similarity_score is not None:
        entry += f"Similarity Score: {similarity_score:.4f}\n"
    if similar_to_attempt is not None:
        entry += f"Similar to Attempt: {similar_to_attempt}\n"
    
    entry += f"\nFeedback:\n"
    entry += f"{feedback}\n"
    entry += f"{separator}\n"
    
    # Append to file
    with open(output_file, 'a') as f:
        f.write(entry)
    
    print(f"  ⚠️  Rejected feedback saved to: {output_file}")


def parse_re_response_for_regression(response: str) -> Dict[str, Any]:
    """
    Parse RE agent response to extract regression tracking fields.

    Extracts:
    - fix_intent (on a Mode 3 diagnostic iteration, filled from DIAGNOSTIC
      EXECUTION with a "DIAGNOSTIC EXECUTION: " prefix - never left blank)
    - source_ref
    - diagnostic_execution (the raw Mode 3 report, "" otherwise)
    - expected_impact (ImpactAnalysis)

    Args:
        response: RE agent's response text

    Returns:
        Dictionary with extracted fields, or None if parsing fails
    """
    import re

    result = {
        "fix_intent": "",
        "source_ref": "",
        "diagnostic_execution": "",
        "expected_impact": ImpactAnalysis()
    }

    # Extract FIX INTENT
    fix_intent_match = re.search(
        r'===\s*FIX INTENT\s*===\s*\n(.*?)(?=\n===|$)',
        response,
        re.DOTALL | re.IGNORECASE
    )
    if fix_intent_match:
        result["fix_intent"] = fix_intent_match.group(1).strip()

    # Extract DIAGNOSTIC EXECUTION (RE Mode 3). It REPLACES FIX INTENT on a
    # diagnostic iteration, so without this the entry ships with an empty
    # fix_intent - and an empty field erases the iteration from every view built
    # on it (failed-fix history, the Evaluator's regression log rendering, the
    # similarity clustering). The prefix is what marks the entry as a measurement
    # when it is read back; RegressionLogEntry.kind is what filters it.
    diagnostic_match = re.search(
        r'===\s*DIAGNOSTIC EXECUTION\s*===\s*\n(.*?)(?=\n===|```|$)',
        response,
        re.DOTALL | re.IGNORECASE
    )
    if diagnostic_match:
        report = diagnostic_match.group(1).strip()
        if report:
            result["diagnostic_execution"] = report
            if not result["fix_intent"]:
                # Collapsed to one line: fix_intent is rendered inline in several
                # prompt views, and a multi-line value breaks their "Fix Intent: x"
                # shape.
                summary = " ".join(line.strip() for line in report.splitlines() if line.strip())
                result["fix_intent"] = f"DIAGNOSTIC EXECUTION: {summary}"

    # Extract SOURCE REFERENCE
    source_ref_match = re.search(
        r'===\s*SOURCE REFERENCE\s*===\s*\n(.*?)(?=\n===|$)',
        response,
        re.DOTALL | re.IGNORECASE
    )
    if source_ref_match:
        result["source_ref"] = source_ref_match.group(1).strip()

    # Extract EXPECTED IMPACT
    impact_match = re.search(
        r'===\s*EXPECTED IMPACT\s*===\s*\n(.*?)(?=\n===|```|$)',
        response,
        re.DOTALL | re.IGNORECASE
    )
    if impact_match:
        impact_text = impact_match.group(1)

        # Parse satToUnsat
        sat_to_unsat_match = re.search(r'satToUnsat:\s*\[(.*?)\]', impact_text, re.IGNORECASE)
        if sat_to_unsat_match:
            items = sat_to_unsat_match.group(1).strip()
            if items and items.lower() != "none":
                result["expected_impact"].sat_to_unsat = [
                    item.strip() for item in items.split(',') if item.strip()
                ]

        # Parse unsatToSat
        unsat_to_sat_match = re.search(r'unsatToSat:\s*\[(.*?)\]', impact_text, re.IGNORECASE)
        if unsat_to_sat_match:
            items = unsat_to_sat_match.group(1).strip()
            if items and items.lower() != "none":
                result["expected_impact"].unsat_to_sat = [
                    item.strip() for item in items.split(',') if item.strip()
                ]

        # Parse passToFail
        pass_to_fail_match = re.search(r'passToFail:\s*\[(.*?)\]', impact_text, re.IGNORECASE)
        if pass_to_fail_match:
            items = pass_to_fail_match.group(1).strip()
            if items and items.lower() != "none":
                result["expected_impact"].pass_to_fail = [
                    item.strip() for item in items.split(',') if item.strip()
                ]

        # Parse failToPass
        fail_to_pass_match = re.search(r'failToPass:\s*\[(.*?)\]', impact_text, re.IGNORECASE)
        if fail_to_pass_match:
            items = fail_to_pass_match.group(1).strip()
            if items and items.lower() != "none":
                result["expected_impact"].fail_to_pass = [
                    item.strip() for item in items.split(',') if item.strip()
                ]

    return result
