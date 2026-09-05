"""
Standing of each requirement in the document: verified, or still on trial.

A requirement update becomes official the instant `apply_patch` writes it -
`DocItem` is `{id, raw}` with no status, so a requirement the user confirmed the
WORDING of is indistinguishable from one whose consistency with the rest of the
document has actually been verified. The user cannot check consistency by
reading; that is what the solver is for. So every applied operation - ADD,
MODIFY, REMOVE, MODIFY-SECTION, with or without user confirmation - is
PROVISIONAL until it survives PROBATION_ITERATIONS consecutive verified
iterations.

The status lives HERE and not in the document text. `render_document`
concatenates `DocItem.raw` byte-for-byte, so a marker inside `raw` breaks that
invariant and invites agents to copy it into requirement wording. Markers are
injected at prompt-render time only, exactly as the `[E#]` addressing markers
are (`requirements_store.annotate_for_prompt`).

Lifecycle, mirroring the convention/lesson one (nothing is ever auto-deleted -
the outcome raises and the user decides):

                  +- 3 clean iterations ------> active
    provisional --+- implicated ---------------> contested -> user decides
                  +- 3 iterations unencoded ---> stalled   -> user decides

    pending_removal -- 3 clean --> item deleted from the document
                    +- failure --> back to active

Persistence style follows the other three audit logs (RequirementPatchLog,
RegressionLog, ConstructRemovalLog): JSON-backed, load on init, trim on resume,
snapshot to Output/.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import json
import re

# Consecutive verified iterations an update must survive before it is official.
# Matches the lesson probation gate (`_store_confirmed_lessons`).
PROBATION_ITERATIONS = 3

# Consecutive iterations a provisional item may go unencoded before the workflow
# stops re-instructing the RE and escalates to the user. Same cadence, because
# the question it answers is the same: has the instruction demonstrably failed?
STALL_ITERATIONS = 3

# Terminal states. Everything else is outstanding and holds convergence open.
ACTIVE = "active"
PROVISIONAL = "provisional"
PENDING_REMOVAL = "pending_removal"
CONTESTED = "contested"
STALLED = "stalled"
SUPERSEDED = "superseded"

# Statuses that mean "this requirement is not yet verified". Convergence is
# withheld while any item is in one of these (Phase 5), and each is rendered
# with its own marker so the reader can tell a healthy probation from a stuck
# one.
OUTSTANDING = (PROVISIONAL, PENDING_REMOVAL, CONTESTED, STALLED)

# Which status an applied patch operation lands in. A REMOVE is deferred rather
# than applied: the item stays in the document (marked) while its Alloy
# constructs are deleted, which is what makes the removal both verifiable and
# revertible.
_OP_STATUS = {
    "ADD": PROVISIONAL,
    "MODIFY": PROVISIONAL,
    "MODIFY-SECTION": PROVISIONAL,
    "REMOVE": PENDING_REMOVAL,
}


def conflict_key(conflicts_with: Optional[List[str]]) -> Tuple[str, ...]:
    """The identity of a conflict SET, for suppressing a decided conflict.

    Sorted and de-duplicated on purpose: the Evaluator writes the IDs in
    whatever order it happens to, and keying on that order would re-raise
    "R5, R2" as a conflict the user already answered as "R2, R5".
    """
    return tuple(sorted({rid.strip() for rid in (conflicts_with or []) if rid and rid.strip()}))


@dataclass
class RequirementStatus:
    """One requirement's standing, and the evidence accumulated for it."""

    req_id: str
    status: str = PROVISIONAL
    op: str = ""                 # the operation that put it on probation
    since_iteration: int = 0
    provenance: str = ""         # e.g. "user-accepted", "user-timeout", "triage"
    clean_streak: int = 0
    # Two distinct stalls, counted separately because the remedies are opposite:
    # one needs the construct built, the other needs one comment line.
    unencoded_streak: int = 0
    unannotated_streak: int = 0
    # The text before a MODIFY (from the patch log's `before`), so a failed
    # probation can be reverted without re-deriving anything.
    prior_text: str = ""
    superseded_by: str = ""
    # The declared conflict SET this item belongs to, stored whole on every
    # member - so the suppression key can be rebuilt from any one record.
    conflicts_with: List[str] = field(default_factory=list)
    # Set when the user admits an item over a CONTRADICTS verdict. Without it
    # the same conflict is re-raised every iteration.
    conflict_acknowledged: bool = False
    # When the acknowledgement was given. A resume to before it must forget it,
    # the same way it forgets probation raised after the resume point.
    conflict_iteration: int = 0
    # Why it was contested / stalled, for the message that asks the user.
    reason: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequirementStatus":
        return cls(
            req_id=data["req_id"],
            status=data.get("status", PROVISIONAL),
            op=data.get("op", ""),
            since_iteration=data.get("since_iteration", 0),
            provenance=data.get("provenance", ""),
            clean_streak=data.get("clean_streak", 0),
            unencoded_streak=data.get("unencoded_streak", 0),
            unannotated_streak=data.get("unannotated_streak", 0),
            prior_text=data.get("prior_text", ""),
            superseded_by=data.get("superseded_by", ""),
            conflicts_with=data.get("conflicts_with", []),
            conflict_acknowledged=data.get("conflict_acknowledged", False),
            conflict_iteration=data.get("conflict_iteration", 0),
            reason=data.get("reason", ""),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )

    @property
    def outstanding(self) -> bool:
        return self.status in OUTSTANDING

    @property
    def progress(self) -> str:
        """`2/3` - how far through probation, for the rendered marker."""
        return f"{self.clean_streak}/{PROBATION_ITERATIONS}"

    @property
    def stall_streak(self) -> int:
        """Consecutive iterations with no verifiable encoding, either cause.

        The two are counted apart so the directive can name the right remedy,
        but the escalation ladder runs on their total: an item that alternates
        between unbuilt and unannotated is stuck just as surely as one stuck
        the same way twice.
        """
        return self.unencoded_streak + self.unannotated_streak


class RequirementStatusStore:
    """Requirement ID -> standing, reconciled against the document each iteration."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or Path("memory/requirement_status.json")
        self.statuses: Dict[str, RequirementStatus] = {}
        if self.log_path.exists():
            self._load_from_file()

    # ------------------------------------------------------------------ #
    # Recording
    # ------------------------------------------------------------------ #

    def record_change(
        self,
        req_id: str,
        op: str,
        iteration: int,
        prior_text: str = "",
        provenance: str = "",
        reason: str = "",
    ) -> Optional[RequirementStatus]:
        """
        Put one applied patch operation on probation.

        Every op and every gate decision lands here - confirming WORDING is not
        confirming CONSISTENCY, so user confirmation buys no exemption. Touching
        an item that is already on probation restarts its clock: the evidence
        gathered so far was about different text.
        """
        kind = (op or "").strip().upper()
        status = _OP_STATUS.get(kind)
        if not req_id or status is None:
            return None

        existing = self.statuses.get(req_id)
        entry = RequirementStatus(
            req_id=req_id,
            status=status,
            op=kind,
            since_iteration=iteration,
            provenance=provenance,
            # A MODIFY of an item already on probation must keep the ORIGINAL
            # pre-probation text as the revert target, not the intermediate one.
            prior_text=(existing.prior_text if existing and existing.prior_text
                        else prior_text),
            # Why this op happened, when it was not the Evaluator's own patch -
            # a supersession the user accepted reads as an unexplained removal
            # otherwise.
            reason=reason,
            conflicts_with=list(existing.conflicts_with) if existing else [],
            conflict_acknowledged=bool(existing and existing.conflict_acknowledged),
            conflict_iteration=(existing.conflict_iteration if existing else 0),
        )
        self.statuses[req_id] = entry
        self._save_to_file()
        return entry

    def record_changes(
        self,
        changes: List[Dict[str, str]],
        iteration: int,
        provenance: str = "",
    ) -> List[RequirementStatus]:
        """Record a whole `apply_patch` report's `changes` list."""
        recorded = []
        for change in changes or []:
            entry = self.record_change(
                req_id=(change.get("target") or "").strip(),
                op=change.get("op") or "",
                iteration=iteration,
                prior_text=change.get("before") or "",
                provenance=provenance,
            )
            if entry:
                recorded.append(entry)
        return recorded

    def note_conflict(self, req_id: str, conflicts_with: List[str],
                      acknowledged: bool = False, iteration: int = 0) -> None:
        """Attach a CONTRADICTS finding to an item - the supersession record.

        Creates a record when the item has none. The item on the losing side of
        a conflict is usually an ORIGINAL-source requirement, which by design
        carries no status entry (it was never on probation); refusing to record
        there would leave exactly the common case unwritten. The record it gets
        is ACTIVE, so it renders no marker and is outstanding for nothing - it
        exists only to carry the conflict.

        `conflicts_with` is stored whole on every member of the set, so
        `acknowledged_conflict_keys` can rebuild the suppression key from any
        single surviving record.
        """
        ids = [rid for rid in (conflicts_with or []) if rid]
        entry = self.statuses.get(req_id)
        if entry is None:
            if not req_id or not ids:
                return
            entry = RequirementStatus(
                req_id=req_id,
                status=ACTIVE,
                since_iteration=iteration,
                provenance="conflict",
            )
            self.statuses[req_id] = entry
        entry.conflicts_with = list(ids)
        entry.conflict_acknowledged = bool(acknowledged)
        entry.conflict_iteration = iteration
        entry.updated_at = datetime.now().isoformat()
        self._save_to_file()

    def acknowledge_conflict(self, conflicts_with: List[str],
                             iteration: int = 0) -> Tuple[str, ...]:
        """Record one whole acknowledged conflict set; returns its key.

        Written to every member so a later reconcile that drops one ID still
        leaves the acknowledgement standing on the others - the alternative,
        one anchor record, resurrects a decided conflict the moment the anchor
        is the item that goes away.
        """
        key = conflict_key(conflicts_with)
        for req_id in conflicts_with or []:
            self.note_conflict(req_id, list(conflicts_with), acknowledged=True,
                               iteration=iteration)
        return key

    def link_supersession(self, req_id: str, superseded_by: str) -> None:
        """Name the item that replaced this one, WITHOUT retiring it.

        `supersede` is the end of the story; this is the middle of it. A
        conflict the user resolved in favour of a new update leaves the old
        item in PENDING_REMOVAL - still in the document, encoding deleted - and
        this link is what makes that reversible: undo the replacement and the
        item it displaced can be found and restored.
        """
        entry = self.statuses.get(req_id)
        if entry is None or not superseded_by:
            return
        entry.superseded_by = superseded_by
        entry.updated_at = datetime.now().isoformat()
        self._save_to_file()

    def displaced_by(self, req_id: str) -> List[RequirementStatus]:
        """Items whose removal is only justified by `req_id` still standing."""
        return [e for e in self.statuses.values()
                if e.superseded_by == req_id and e.status == PENDING_REMOVAL]

    def acknowledged_conflict_keys(self) -> Set[Tuple[str, ...]]:
        """Every conflict set the user has already decided.

        The durable half of `context.acknowledged_conflicts`: without it a
        restart re-raises a conflict that was answered before the restart.
        """
        return {
            conflict_key(e.conflicts_with)
            for e in self.statuses.values()
            if e.conflict_acknowledged and e.conflicts_with
        }

    # ------------------------------------------------------------------ #
    # Probation
    # ------------------------------------------------------------------ #

    def register_clean(self, req_id: str) -> bool:
        """
        Credit one verified iteration. Returns True when probation completes.

        Only the caller knows whether the iteration produced evidence at all -
        a syntax-error iteration analyzed nothing and must not be credited.
        """
        entry = self.statuses.get(req_id)
        if entry is None or entry.status not in (PROVISIONAL, PENDING_REMOVAL):
            return False
        entry.clean_streak += 1
        entry.unencoded_streak = 0
        entry.unannotated_streak = 0
        entry.updated_at = datetime.now().isoformat()
        done = entry.clean_streak >= PROBATION_ITERATIONS
        self._save_to_file()
        return done

    def register_implicated(self, req_id: str, reason: str) -> Optional[RequirementStatus]:
        """The item's encoding is implicated in a failure: reset and contest it."""
        entry = self.statuses.get(req_id)
        if entry is None or entry.status not in (PROVISIONAL, PENDING_REMOVAL):
            return None
        entry.clean_streak = 0
        entry.status = CONTESTED
        entry.reason = reason
        entry.updated_at = datetime.now().isoformat()
        self._save_to_file()
        return entry

    def reset_streak(self, req_id: str, reason: str = "") -> None:
        """Withhold credit for this iteration without contesting the item.

        Used when a failure implicates several provisional items at once: with
        no unique culprit, none of them is contested, but none is credited
        either.
        """
        entry = self.statuses.get(req_id)
        if entry is None:
            return
        entry.clean_streak = 0
        if reason:
            entry.reason = reason
        entry.updated_at = datetime.now().isoformat()
        self._save_to_file()

    def register_stall(self, req_id: str, kind: str) -> Optional[RequirementStatus]:
        """
        Count one iteration in which the item produced no verifiable encoding.

        `kind` is 'unencoded' (no construct names or annotates it) or
        'unannotated' (a construct exists but declares no owner). They are
        counted apart because the remedy differs: build vs. annotate.
        """
        entry = self.statuses.get(req_id)
        if entry is None or entry.status not in (PROVISIONAL, PENDING_REMOVAL):
            return None
        if kind == "unannotated":
            entry.unannotated_streak += 1
        else:
            entry.unencoded_streak += 1
        entry.clean_streak = 0
        entry.updated_at = datetime.now().isoformat()
        if entry.stall_streak >= STALL_ITERATIONS:
            entry.status = STALLED
            entry.reason = (
                f"no verifiable encoding after {entry.stall_streak} iterations "
                f"({kind})"
            )
        self._save_to_file()
        return entry

    def confirm(self, req_id: str) -> Optional[RequirementStatus]:
        """Probation passed: the update is now official."""
        entry = self.statuses.get(req_id)
        if entry is None:
            return None
        entry.status = ACTIVE
        entry.reason = ""
        entry.updated_at = datetime.now().isoformat()
        self._save_to_file()
        return entry

    def supersede(self, req_id: str, superseded_by: str = "") -> None:
        """The item left the document (a completed removal, or replaced)."""
        entry = self.statuses.get(req_id)
        if entry is None:
            return
        entry.status = SUPERSEDED
        entry.superseded_by = superseded_by or entry.superseded_by
        entry.updated_at = datetime.now().isoformat()
        self._save_to_file()

    def resume_probation(self, req_id: str) -> None:
        """Give a stalled item another full window instead of deciding it.

        The stall counts failures to ENCODE, not failures of the requirement -
        so when the user judges the modeller to be at fault, the streaks reset
        and the item goes back on probation rather than out of it.
        """
        entry = self.statuses.get(req_id)
        if entry is None or entry.status != STALLED:
            return
        entry.status = PENDING_REMOVAL if entry.op == "REMOVE" else PROVISIONAL
        entry.unencoded_streak = 0
        entry.unannotated_streak = 0
        entry.clean_streak = 0
        entry.reason = ""
        entry.updated_at = datetime.now().isoformat()
        self._save_to_file()

    def restore(self, req_id: str) -> None:
        """A failed removal / resolved contest: put the item back in circulation."""
        entry = self.statuses.get(req_id)
        if entry is None:
            return
        entry.status = ACTIVE
        entry.clean_streak = 0
        entry.reason = ""
        entry.updated_at = datetime.now().isoformat()
        self._save_to_file()

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    def get(self, req_id: str) -> Optional[RequirementStatus]:
        return self.statuses.get(req_id)

    def status_of(self, req_id: str) -> str:
        """An item with no record is ACTIVE - original-source requirements are
        ground truth, not updates, and were never on probation."""
        entry = self.statuses.get(req_id)
        return entry.status if entry else ACTIVE

    def outstanding_items(self) -> List[RequirementStatus]:
        """Everything still on trial, worst first (stalled/contested lead)."""
        order = {STALLED: 0, CONTESTED: 1, PENDING_REMOVAL: 2, PROVISIONAL: 3}
        return sorted(
            (e for e in self.statuses.values() if e.outstanding),
            key=lambda e: (order.get(e.status, 9), e.since_iteration, e.req_id),
        )

    def items_with_status(self, *wanted: str) -> List[RequirementStatus]:
        return [e for e in self.statuses.values() if e.status in wanted]

    def pending_removals(self) -> List[str]:
        """IDs whose deletion is deferred - still in the document, not encoded."""
        return sorted(e.req_id for e in self.statuses.values()
                      if e.status == PENDING_REMOVAL)

    def on_probation(self) -> List[RequirementStatus]:
        """Items actively accumulating evidence (not yet contested or stalled)."""
        return [e for e in self.statuses.values()
                if e.status in (PROVISIONAL, PENDING_REMOVAL)]

    # ------------------------------------------------------------------ #
    # Reconciliation and persistence
    # ------------------------------------------------------------------ #

    def reconcile(self, live_ids: Set[str]) -> List[str]:
        """
        Drop records for IDs the document no longer contains.

        The store is derived state and can drift if a patch path bypasses
        UpdateRequirements. Reconciling every iteration bounds that - but the
        drop is RETURNED so the caller can log it, because a status that
        silently vanished looks exactly like one that was confirmed.

        A PENDING_REMOVAL is exempt: its whole point is that the ID is still in
        the document, and a SUPERSEDED record outlives the item by design.
        """
        live = set(live_ids or ())
        dropped = [
            rid for rid, e in self.statuses.items()
            if rid not in live and e.status not in (PENDING_REMOVAL, SUPERSEDED)
        ]
        for rid in dropped:
            del self.statuses[rid]
        if dropped:
            self._save_to_file()
        return sorted(dropped)

    def clear(self) -> None:
        """Fresh start from iteration 0 (mirrors RequirementPatchLog.clear)."""
        self.statuses = {}
        if self.log_path.exists():
            self.log_path.unlink()

    def trim_to_iteration(self, max_iteration: int) -> List[str]:
        """
        Resume from `max_iteration`: forget probation raised at or after it.

        Records from the discarded iterations describe changes the rerun has not
        made yet. Surviving records keep their status but lose every streak: the
        streaks count consecutive iterations, and the iterations that produced
        them are being re-run. Same bias toward starting over that the lesson
        conflict discard uses.
        """
        dropped = [rid for rid, e in self.statuses.items()
                   if e.since_iteration >= max_iteration]
        for rid in dropped:
            del self.statuses[rid]
        for entry in self.statuses.values():
            entry.clean_streak = 0
            entry.unencoded_streak = 0
            entry.unannotated_streak = 0
            # An acknowledgement given at or after the resume point is a
            # decision about a conflict the rerun has not raised yet. A record
            # can outlive its own acknowledgement (the item may predate it), so
            # this is cleared per-field rather than by dropping the record.
            if entry.conflict_acknowledged and entry.conflict_iteration >= max_iteration:
                entry.conflict_acknowledged = False
                entry.conflicts_with = []
                entry.conflict_iteration = 0
        self._save_to_file()
        return sorted(dropped)

    def save_copy_to_output(self, output_dir: Optional[Path] = None) -> None:
        """Snapshot to Output/ so the record survives a later fresh start."""
        import shutil
        from .file_manager import run_snapshot_stamp

        output_dir = output_dir or Path("Output/RequirementStatus")
        output_dir.mkdir(parents=True, exist_ok=True)
        # Stamped with the run's start hour, so a run spanning an hour boundary
        # keeps writing the same file instead of starting a second one.
        output_file = output_dir / f"reqstatus_{run_snapshot_stamp()}.log"

        if self.log_path.exists():
            shutil.copy2(self.log_path, output_file)
            print(f"  🧾 Requirement status saved to: {output_file}")
        elif self.statuses:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in self.statuses.values()], f, indent=2)
            print(f"  🧾 Requirement status saved to: {output_file}")

    def _save_to_file(self) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.statuses.values()],
                      f, indent=2, ensure_ascii=False)

    def _load_from_file(self) -> None:
        if not self.log_path or not self.log_path.exists():
            return
        if self.log_path.stat().st_size == 0:
            return
        with open(self.log_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                print("⚠ Warning: requirement status file is corrupted, starting fresh")
                return
        self.statuses = {
            d["req_id"]: RequirementStatus.from_dict(d) for d in data if d.get("req_id")
        }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def format_marker(entry: Optional[RequirementStatus]) -> str:
    """The `[PROVISIONAL since it.23, 2/3]` tag appended to a rendered item."""
    if entry is None or entry.status == ACTIVE:
        return ""
    if entry.status == PROVISIONAL:
        return f"[PROVISIONAL since it.{entry.since_iteration}, {entry.progress}]"
    if entry.status == PENDING_REMOVAL:
        return f"[PENDING REMOVAL since it.{entry.since_iteration}, {entry.progress}]"
    if entry.status == CONTESTED:
        return f"[CONTESTED since it.{entry.since_iteration}]"
    if entry.status == STALLED:
        return f"[STALLED - not encoded since it.{entry.since_iteration}]"
    if entry.status == SUPERSEDED:
        return "[SUPERSEDED]"
    return ""


# Explains the markers to whichever agent is reading the annotated document.
# The last line is load-bearing: without it the RE reads "provisional" as
# "lower priority", skips the encoding, and probation never gets a signal.
STATUS_LEGEND = (
    "REQUIREMENT STANDING (markers are added for reading only - never write "
    "them into requirement text):\n"
    "  [PROVISIONAL since it.N, k/3]      - added or reworded at iteration N; "
    "official after 3 consecutive verified iterations.\n"
    "  [PENDING REMOVAL since it.N, k/3]  - removal requested at iteration N. "
    "The text is still shown so the removal can be reviewed and reverted, but "
    "its encoding has been DELETED - do not re-add a construct for it.\n"
    "  [CONTESTED since it.N]             - its encoding was implicated in a "
    "verification failure; awaiting a user decision.\n"
    "  [STALLED - not encoded since it.N] - no construct could be traced to it "
    "for 3 iterations; awaiting a user decision.\n"
    "  An item with no marker is verified and official.\n"
    "  PROVISIONAL describes an item's STANDING IN THE DOCUMENT, not its "
    "priority. Encode a provisional requirement exactly as you would any other "
    "- the probation is decided by verifying that encoding, so skipping it "
    "keeps the item on probation forever."
)


def evaluate_probation(
    statuses: RequirementStatusStore,
    traceability: Any,
    iteration: int,
    model_analyzed: bool,
    unsatisfied_predicates: Optional[List[str]] = None,
    counterexamples: Optional[List[str]] = None,
    blocking_facts: Optional[Set[str]] = None,
    unowned_constructs: Optional[List[str]] = None,
    removal_blocked: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Advance every item on probation by one iteration of evidence.

    Called once per iteration, against the model that was just analyzed. An
    update recorded in iteration N's requirement step is encoded in iteration
    N's model step and first analyzed at N+1, so this is where its evidence
    arrives.

    `model_analyzed` is False on a syntax-error iteration. Nothing advances
    then, in either direction: a model Alloy could not compile is evidence
    about the model's syntax, not about whether a requirement is consistent.

    Returns {'confirmed', 'contested', 'stalled', 'held', 'skipped'} - the
    caller performs the document-level consequences (deleting a completed
    removal, asking the user about a contest).
    """
    outcome: Dict[str, Any] = {
        'confirmed': [], 'contested': [], 'stalled': [], 'held': [],
        # Split by cause, because the remedies are opposite: one needs the
        # construct built, the other needs one `//@req` comment.
        'unencoded': [], 'unannotated': [],
        'skipped': not model_analyzed,
    }
    items = statuses.on_probation()
    if not items or not model_analyzed:
        return outcome

    unsat = set(unsatisfied_predicates or ())
    cex = set(counterexamples or ())
    blockers = set(blocking_facts or ())
    blocked_removals = set(removal_blocked or ())
    # Constructs in the model that declare no requirement at all. If a
    # provisional item has no construct AND some construct is unowned, the
    # likely cause is a missing `//@req` label rather than a missing build -
    # opposite remedies, so they are counted apart.
    unowned = list(unowned_constructs or ())

    implicated: List[tuple] = []
    for entry in items:
        constructs = []
        try:
            constructs = traceability.constructs_for([entry.req_id]) if traceability else []
        except Exception:
            constructs = []

        if entry.status == PENDING_REMOVAL:
            # Verified when the encoding is actually gone. A construct that
            # survived (or was re-added) means the removal has not been tested.
            if entry.req_id in blocked_removals or constructs:
                statuses.register_stall(entry.req_id, "unencoded")
                outcome['held'].append(entry.req_id)
                continue
            if statuses.register_clean(entry.req_id):
                outcome['confirmed'].append(entry.req_id)
            continue

        if entry.op == "MODIFY-SECTION":
            # A section blob carries no requirement ID, so there is no construct
            # to trace and no encoding obligation to enforce. It accrues time
            # like anything else, but can never stall.
            if statuses.register_clean(entry.req_id):
                outcome['confirmed'].append(entry.req_id)
            continue

        if not constructs:
            kind = "unannotated" if unowned else "unencoded"
            updated = statuses.register_stall(entry.req_id, kind)
            outcome[kind].append(entry.req_id)
            if updated and updated.status == STALLED:
                outcome['stalled'].append(entry.req_id)
            else:
                outcome['held'].append(entry.req_id)
            continue

        # A contradiction claim says where else to look. If this item was
        # declared to conflict with R2, then a failure landing on R2's
        # constructs is evidence about THIS item - and without widening the
        # test that is precisely the case nothing catches: the item's own
        # constructs stay clean, it accrues three verified iterations, and an
        # unresolved contradiction is promoted to official.
        claim = _unsettled_claim(entry)
        claimed_constructs = []
        if claim:
            try:
                claimed_constructs = traceability.constructs_for(claim) if traceability else []
            except Exception:
                claimed_constructs = []

        failing = sorted(
            {c for c in constructs if c in unsat or c in cex or c in blockers}
        )
        by_claim = sorted(
            {c for c in claimed_constructs if c in unsat or c in cex or c in blockers}
        )
        # An existing-system item lives in a fact, and an inconsistent fact
        # shows up as `baseline` UNSAT rather than as its own predicate.
        if entry.req_id.startswith("E") and "baseline" in unsat:
            failing = sorted(set(failing) | {"baseline"})
        if failing or by_claim:
            implicated.append((entry, sorted(set(failing) | set(by_claim))))
            continue

        if statuses.register_clean(entry.req_id):
            outcome['confirmed'].append(entry.req_id)

    # Unique-culprit rule: one failure that implicates several provisional items
    # identifies none of them. Withhold credit from all, contest only a lone
    # suspect - contesting the wrong requirement is worse than waiting.
    #
    # A contradiction claim breaks that tie. When exactly one of the implicated
    # items was already declared unable to coexist with something live, it is
    # the one there is a stated reason to ask about; the others are held as
    # before. Without this the pair sits implicated together every iteration
    # and no question is ever asked.
    suspects = [pair for pair in implicated if _unsettled_claim(pair[0])]
    if len(implicated) == 1:
        chosen = implicated[0]
    elif len(suspects) == 1:
        chosen = suspects[0]
    else:
        chosen = None

    for entry, failing in implicated:
        if chosen is not None and entry.req_id == chosen[0].req_id:
            claim = _unsettled_claim(entry)
            reason = (
                f"encoding implicated in this iteration's failure: "
                f"{', '.join(failing)}"
            )
            if claim:
                reason += (f"; it was declared to contradict {', '.join(claim)}, "
                           f"which the failure is consistent with")
            statuses.register_implicated(entry.req_id, reason)
            outcome['contested'].append((entry.req_id, reason))
            continue
        others = [e.req_id for e, _ in implicated if e.req_id != entry.req_id]
        statuses.reset_streak(
            entry.req_id,
            f"implicated together with {', '.join(others)} ({', '.join(failing)})"
        )
        outcome['held'].append(entry.req_id)
    return outcome


def _unsettled_claim(entry: RequirementStatus) -> List[str]:
    """The IDs this item was declared to contradict, while that is undecided.

    Empty once acknowledged: the user has settled it, so it is no longer a
    hypothesis worth steering verification by.
    """
    if entry is None or entry.conflict_acknowledged:
        return []
    return [rid for rid in (entry.conflicts_with or []) if rid != entry.req_id]


# --------------------------------------------------------------------------- #
# Contradiction triage (bucket 6)
# --------------------------------------------------------------------------- #

_ENTRY_FIELD = re.compile(r"^\s*[-*]?\s*([A-Za-z][A-Za-z /&]*?)\s*:\s*(.*)$")
_ID_TOKEN = re.compile(r"\b([RE]\d+(?:\.\d+)*)\b")
# "none", "n/a", "-", "" all mean the entry declared no conflict.
_NO_CONFLICT = ("none", "n/a", "na", "-", "", "no conflict", "none - ")


def parse_conflict_declarations(feedback: str) -> List[Dict[str, Any]]:
    """
    Read the `Conflicts with:` field out of each `=== REQUIREMENT UPDATES ===`
    entry.

    Entries are separated by their `Affected ...:` line, so a declaration is
    attributed to the candidate it was written under rather than to whichever
    one happened to be parsed last.

    Returns [{'affected', 'recommended', 'conflicts_with': [ID], 'why'}], one
    per entry that named at least one ID.
    """
    if not feedback:
        return []
    body = _requirement_updates_section(feedback)
    if not body:
        return []

    out: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in body.splitlines():
        match = _ENTRY_FIELD.match(line)
        if not match:
            continue
        label = match.group(1).strip().lower()
        value = match.group(2).strip()
        if label.startswith("affected"):
            if current and current["conflicts_with"]:
                out.append(current)
            current = {"affected": value, "recommended": "",
                       "conflicts_with": [], "why": ""}
        elif current is None:
            continue
        elif label.startswith("recommended"):
            current["recommended"] = value
        elif label.startswith("conflicts with"):
            plain = value.strip().strip('.').lower()
            if plain in _NO_CONFLICT:
                continue
            ids, seen = [], set()
            for token in _ID_TOKEN.findall(value):
                if token not in seen:
                    seen.add(token)
                    ids.append(token)
            current["conflicts_with"] = ids
            current["why"] = value
    if current and current["conflicts_with"]:
        out.append(current)
    return out


def _requirement_updates_section(feedback: str) -> str:
    """The body of `=== REQUIREMENT UPDATES ===`, up to the next `=== ... ===`."""
    lines = feedback.split("\n")
    header = re.compile(r"^===\s*REQUIREMENT[S]?\s+UPDATE[S]?\s*===", re.IGNORECASE)
    any_header = re.compile(r"^===\s*.+?\s*===")
    start = next((i for i, l in enumerate(lines) if header.match(l.strip())), None)
    if start is None:
        return ""
    end = next(
        (i for i in range(start + 1, len(lines)) if any_header.match(lines[i].strip())),
        len(lines),
    )
    return "\n".join(lines[start + 1:end])


def validate_conflicts(
    declarations: List[Dict[str, Any]],
    live_ids: Set[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Split declarations into those that cite real items and those that do not.

    The semantic judgment - do these two requirements actually contradict? -
    cannot be checked in code. That an ID exists in the document CAN be, so
    that is what is enforced: a contradiction the Evaluator cannot point at is
    downgraded rather than acted on. Deliberately asymmetric, because a wrongly
    declared conflict discards a requirement while a missed one merely shows up
    later as a verification failure.
    """
    live = set(live_ids or ())
    accepted, downgraded = [], []
    for entry in declarations or []:
        known = [rid for rid in entry.get("conflicts_with") or [] if rid in live]
        record = {**entry, "conflicts_with": known}
        if known:
            accepted.append(record)
        else:
            record["downgrade_reason"] = (
                "names no item in the current document: "
                f"{', '.join(entry.get('conflicts_with') or []) or '(no ID given)'}"
            )
            downgraded.append(record)
    return {"accepted": accepted, "downgraded": downgraded}


def log_conflict_shadow(
    records: List[Dict[str, Any]],
    mode: str,
    iteration: int,
    verdict: str,
    output_dir: Optional[Path] = None,
) -> None:
    """
    Append one record per contradiction verdict, acted on or not.

    Contradiction detection ships in OBSERVE mode: the verdict is recorded and
    nothing else happens. Whether it fires correctly - and, more importantly,
    whether it OVER-fires - is a question about model behaviour that no unit
    test answers, and the cost of a false positive is a discarded requirement.
    So it is measured on real runs first, exactly as convention dedup is.

    Never raises: a measurement must not be able to break the feedback path.
    """
    if not records:
        return
    try:
        out_dir = output_dir or Path("Output/RequirementConflict")
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "shadow.jsonl", "a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps({
                    "iteration": iteration,
                    "mode": mode,
                    "verdict": verdict,
                    "affected": record.get("affected", ""),
                    "recommended": record.get("recommended", ""),
                    "conflicts_with": record.get("conflicts_with", []),
                    "why": record.get("why", ""),
                    "downgrade_reason": record.get("downgrade_reason", ""),
                    "timestamp": datetime.now().isoformat(),
                }, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Warning: requirement conflict shadow log failed: {e}")


def format_conflict_notices(accepted: List[Dict[str, Any]]) -> List[str]:
    """Render each contradiction claim as information, not as a question.

    Deliberately not a question. The Evaluator read two requirements and said
    they cannot both hold; nothing has checked that yet. Demanding a decision
    here would spend the user's attention on a claim that verification may
    refute next iteration - and answering it wrongly would discard a
    requirement before anything examined it.

    So the user is told what was claimed and what happens next: the update is
    applied, and if the solver bears the claim out the item is contested and
    the decision is asked THEN, with evidence attached.
    """
    notices = []
    for entry in accepted or []:
        ids = ", ".join(entry.get("conflicts_with") or [])
        notices.append(
            f"[CONFLICT CLAIMED] The Evaluator says "
            f"\"{(entry.get('recommended') or entry.get('affected') or '').strip()}\" "
            f"cannot hold at the same time as {ids} "
            f"({(entry.get('why') or 'no reason given').strip()}). "
            f"The update is being applied anyway and will be verified: if the "
            f"solver confirms the clash you will be asked which one governs. "
            f"No answer is needed now."
        )
    return notices


# --------------------------------------------------------------------------- #
# Contest resolution
# --------------------------------------------------------------------------- #

_REVERT_WORDS = ("revert", "undo", "rollback", "roll back")
_KEEP_WORDS = ("keep", "retain", "stands", "stand")
# "don't revert R7" must not read as "revert R7". A negated clause decides
# nothing rather than guessing at the intended verb.
_NEGATIONS = ("not ", "n't", "never", "instead of")

# Answering a contest and answering a stall are different decisions with the
# same grammar, so they share one parser and differ only in vocabulary.
_CONTEST_VOCABULARY = {"revert": _REVERT_WORDS, "keep": _KEEP_WORDS}
_STALL_VOCABULARY = {
    "reword": ("reword", "rewrite", "rephrase", "clarify", "diagnose"),
    "drop": ("drop", "remove", "delete", "withdraw"),
    "wait": ("wait", "again", "retry", "try again", "keep waiting"),
}


def format_contest_questions(contested: List[Dict[str, Any]]) -> List[str]:
    """Render each contested update as a `[CONTEST]` user question.

    Each entry is {'req_id', 'op', 'text', 'reason'}. The two answers do
    different things and the question says which: reverting edits the document
    back, keeping leaves the update in place and only withdraws the suspicion.
    """
    questions = []
    for entry in contested or []:
        req_id = entry.get("req_id", "")
        op = (entry.get("op") or "").upper()
        undo = ("delete it from the document again" if op == "ADD"
                else "restore its previous wording")
        questions.append(
            f"[CONTEST] {req_id} ({op or 'update'}) - {entry.get('reason', '')}\n"
            f"      current text: {(entry.get('text') or '(unavailable)').strip()}\n"
            f"      answer `revert {req_id}` to {undo}, or `keep {req_id}` to let "
            f"it stand and clear the contest."
        )
    return questions


def parse_directives(
    answer: Optional[str],
    ids: List[str],
    vocabulary: Dict[str, Tuple[str, ...]],
) -> Dict[str, List[str]]:
    """
    Read a per-item decision out of one line of free text.

    Silence resolves nothing. An empty or unparseable answer decides no item,
    leaving it to be raised again next iteration - acting on silence would make
    an unanswered question indistinguishable from an answered one, which is the
    outcome this whole mechanism exists to prevent.

    Per-ID directives win over a blanket verb, so "revert R7, keep R8" and a
    bare "revert" both work. A clause naming no verb, or more than one, decides
    nothing rather than guessing.

    `vocabulary` maps each canonical verb to the words that mean it, so a
    contest (revert/keep) and a stall (reword/drop/wait) share this grammar
    instead of each growing its own parser.
    """
    result: Dict[str, List[str]] = {verb: [] for verb in vocabulary}
    live = [rid for rid in (ids or []) if rid]
    if not live or not answer or not answer.strip():
        return result

    decided = set()
    blanket = None
    for clause in re.split(r"[,;\n]|\band\b", answer.lower()):
        if not clause.strip():
            continue
        if any(n in clause for n in _NEGATIONS):
            continue
        matched = [verb for verb, words in vocabulary.items()
                   if any(w in clause for w in words)]
        if len(matched) != 1:  # none, or contradictory
            continue
        verb = matched[0]
        named_ids = {t.upper() for t in _ID_TOKEN.findall(clause.upper())}
        named = [rid for rid in live if rid.upper() in named_ids]
        if named:
            for rid in named:
                if rid not in decided:
                    result[verb].append(rid)
                    decided.add(rid)
        elif blanket is None:
            blanket = verb
    if blanket:
        for rid in live:
            if rid not in decided:
                result[blanket].append(rid)
    return result


def format_stall_questions(stalled: List[Dict[str, Any]]) -> List[str]:
    """Render each stalled item as a `[STALLED]` user question.

    Three iterations of directives failed to produce a traceable encoding. That
    is evidence about the REQUIREMENT - it may be unmodelable as stated - which
    is why the question is about rewording it, not about trying again harder.
    Trying again is still offered, because the cause may have been the model.
    """
    questions = []
    for entry in stalled or []:
        req_id = entry.get("req_id", "")
        claimed = ", ".join(entry.get("conflicts_with") or [])
        extra = (f"\n      it was also flagged as contradicting {claimed}, "
                 f"which is still unsettled." if claimed else "")
        questions.append(
            f"[STALLED] {req_id} - {entry.get('reason', 'never encoded')}\n"
            f"      text: {(entry.get('text') or '(unavailable)').strip()}{extra}\n"
            f"      answer `reword {req_id}` to have the Evaluator diagnose it, "
            f"`drop {req_id}` to remove it, or `wait {req_id}` to give the "
            f"modeller another three iterations."
        )
    return questions


def parse_contest_resolution(answer: Optional[str],
                             contested_ids: List[str]) -> Dict[str, List[str]]:
    """A contest answer: {'revert': [...], 'keep': [...]}."""
    return parse_directives(answer, contested_ids, _CONTEST_VOCABULARY)


def parse_stall_resolution(answer: Optional[str],
                           stalled_ids: List[str]) -> Dict[str, List[str]]:
    """A stall answer: {'reword': [...], 'drop': [...], 'wait': [...]}."""
    return parse_directives(answer, stalled_ids, _STALL_VOCABULARY)


def format_outstanding(entries: List[RequirementStatus], max_listed: int = 12) -> str:
    """Render the outstanding set for the convergence prompt / session log."""
    if not entries:
        return ""
    lines = [
        f"UNVERIFIED REQUIREMENT UPDATES: {len(entries)} item(s) have not yet "
        f"completed {PROBATION_ITERATIONS} verified iterations."
    ]
    for entry in entries[:max_listed]:
        marker = format_marker(entry).strip("[]")
        detail = f" - {entry.reason}" if entry.reason else ""
        lines.append(f"  - {entry.req_id} ({entry.op}): {marker}{detail}")
    if len(entries) > max_listed:
        lines.append(f"  (+{len(entries) - max_listed} more)")
    return "\n".join(lines)
