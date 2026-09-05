"""
Requirement -> Alloy-construct traceability.

Maps each requirement ID (R1, R6, ...) to the model constructs that encode it,
so that when a requirement changes the exact constructs it invalidated can be
found and regenerated (instead of leaving a stale encoding that silently
conflicts). The map is rebuilt/reconciled against the ACTUAL current model every
iteration, so the map itself cannot go stale.

Two layers:
  - deterministic: construct names carry requirement IDs by convention
    (fact R1R2_x -> R1,R2; assert assertR6 -> R6), extracted with requirement_ids.
  - annotation: the RE declares `//@req R#[,R#]` on the construct's line for
    constructs whose NAME does not carry the ID (e.g. `fact EmergencyUnique {...}
    //@req R2`). Because the annotation lives in the model text next to the
    construct, it is re-parsed on every rebuild and auto-reconciles: if the
    construct (and its comment) is deleted, the mapping disappears with it.

Deterministic and LLM-free except for the RE-supplied `//@req` comments, which
are always re-read from the model in hand.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .semantic_diagnostics import (
    build_reference_graph,
    extract_all_blocks,
    requirement_ids,
)


_REQ_ANNOTATION = re.compile(r'//\s*@req\s+([\w.,:\s]+)', re.IGNORECASE)

# Both requirement families are traced: R# = emergency-module requirements,
# E# = the existing system's requirements (E1_ClearanceAssignment -> E1).
_ID_PREFIXES = ('R', 'E')


class TraceabilityStore:
    """A reconciled {requirement_id: set(construct_names)} map for one model."""

    def __init__(self):
        # requirement_id -> set of construct names
        self._by_req: Dict[str, Set[str]] = {}
        # construct name -> kind (fact/pred/assert/fun), for reference/debugging
        self._construct_kind: Dict[str, str] = {}
        # construct name -> declared ownerless category ('frame', 'harness', ...)
        self._ownerless: Dict[str, str] = {}

    def rebuild(self, model_text: str, annotations: Optional[Dict[str, List[str]]] = None) -> None:
        """
        Recompute the map from the current model text. Idempotent - fully
        replaces prior state so a construct deleted from the model disappears
        from the map.

        Sources, in order:
          1. deterministic R-prefix extraction from construct names;
          2. `//@req R#` annotations parsed from each construct's own line
             (auto-reconciled: they live with the construct in the model text);
          3. optional explicit `annotations` {construct: [req_id]} - validated
             against the model (constructs absent from the model are dropped).
             Mainly for tests/programmatic use.
        """
        by_req: Dict[str, Set[str]] = {}
        construct_kind: Dict[str, str] = {}
        ownerless: Dict[str, str] = {}
        lines = model_text.splitlines()

        blocks = extract_all_blocks(model_text)
        present = {b['name'] for b in blocks}

        for b in blocks:
            name = b['name']
            construct_kind[name] = b['kind']
            # 1. deterministic layer: names that carry requirement IDs.
            for rid in requirement_ids([name], prefixes=_ID_PREFIXES):
                by_req.setdefault(rid, set()).add(name)
            # 2. in-model //@req annotation on the construct's declaration line,
            #    which either names requirements or declares the construct
            #    deliberately ownerless (//@req none:frame).
            decl = lines[b['start']] if b['start'] < len(lines) else ""
            rids, category = self._parse_annotation(decl)
            for rid in rids:
                by_req.setdefault(rid, set()).add(name)
            if category and not rids:
                ownerless[name] = category

        # 3. explicit annotations, validated against the model.
        for name, rids in (annotations or {}).items():
            if name not in present:
                continue  # reconcile away stale annotations
            for rid in rids:
                by_req.setdefault(rid, set()).add(name)

        self._by_req = by_req
        self._construct_kind = construct_kind
        self._ownerless = ownerless

    @staticmethod
    def _parse_annotation(line: str) -> Tuple[List[str], Optional[str]]:
        """Parse a `//@req ...` annotation into (requirement_roots, ownerless_category).

        `//@req R2, R3.1`     -> (['R2', 'R3'], None)
        `//@req E1`           -> (['E1'], None)
        `//@req none:frame`   -> ([], 'frame')      well-formedness scaffolding
        `//@req none:harness` -> ([], 'harness')    scope/universe scaffolding

        An explicit ownerless category is what separates "deliberately encodes
        no requirement" from "nobody said" - silence is what let a stale fact
        survive unnoticed.
        """
        m = _REQ_ANNOTATION.search(line)
        if not m:
            return [], None
        raw = [t for t in re.split(r'[,\s]+', m.group(1).strip()) if t]
        category: Optional[str] = None
        ids: List[str] = []
        for token in raw:
            low = token.lower()
            if low == 'none' or low.startswith('none:'):
                category = low.split(':', 1)[1] if ':' in low else 'unspecified'
            else:
                ids.append(token)
        # normalize to roots (R3.1 -> R3), dedup
        return requirement_ids(ids, prefixes=_ID_PREFIXES), category

    def ownerless_category(self, construct_name: str) -> Optional[str]:
        """The declared ownerless category ('frame'/'harness'/...), if any."""
        return self._ownerless.get(construct_name)

    def construct_kind(self, construct_name: str) -> Optional[str]:
        """The construct's kind (fact/pred/assert/fun) in the current model."""
        return self._construct_kind.get(construct_name)

    def constructs_for(self, requirement_ids_: List[str]) -> List[str]:
        """All construct names encoding any of the given requirement IDs (sorted, deduped)."""
        out: Set[str] = set()
        for rid in requirement_ids_:
            out |= self._by_req.get(rid, set())
        return sorted(out)

    def requirements_for(self, construct_name: str) -> List[str]:
        """Which requirement IDs a construct encodes (via the current map)."""
        return sorted(rid for rid, names in self._by_req.items() if construct_name in names)

    def as_dict(self) -> Dict[str, List[str]]:
        """Snapshot the map as plain {req_id: [construct, ...]} (e.g. for artifacts)."""
        return {rid: sorted(names) for rid, names in self._by_req.items()}


# --------------------------------------------------------------------------- #
# Ownership audit
# --------------------------------------------------------------------------- #

# Only a fact restricts the universe unconditionally, so only a fact MUST name
# what it encodes - an undeclared one is a defect.
#
# An assertion (and a run-invoked predicate) is interrogative: it asks the
# Analyzer a question and cannot over-constrain the model or cause UNSAT. It
# should still declare its requirement so a stale check can be found, but an
# undeclared one is a documentation gap, not a defect - and an assertion may
# legitimately encode NO requirement (an exploratory or edge-case probe), which
# is declared as `//@req none:probe`.
#
# A fun (and a pred nobody runs) is inert until called: ownership is DERIVED
# from the constructs that call it.
_CONSTRAINING_KINDS = ('fact',)
_CHECK_KINDS = ('assert',)


def _derived_owners(
    name: str,
    callers: Dict[str, Set[str]],
    store: 'TraceabilityStore',
    live: Set[str],
) -> List[str]:
    """Requirements a helper serves = union of its (transitive) callers' owners."""
    seen: Set[str] = set()
    stack = [name]
    owners: Set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        owners.update(store.requirements_for(current))
        stack.extend(callers.get(current, ()))
    return sorted(o for o in owners if not live or o in live)


def audit_ownership(
    model_text: str,
    live_requirement_ids: Optional[Set[str]] = None,
    annotations: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """
    Classify every construct in the model by requirement ownership.

    Buckets:
      declared          construct naming a live requirement
      derived           helper serving requirements, resolved via the call graph
      ownerless         deliberately encodes no requirement
                        (//@req none:frame / none:harness / none:probe)
      orphan            names ONLY requirements that no longer exist
      dead              helper with no caller and no run/check -> dead code
      unclassified      a FACT that declares nothing -> defect (it constrains
                        every run)
      undeclared_checks an assertion / run-invoked predicate that declares
                        nothing -> documentation gap, NOT a defect: it cannot
                        over-constrain the model, and it may be a deliberate
                        edge-case probe

    Also returns 'kinds' so callers can gate destructive actions by construct
    kind (deleting a fact only relaxes the model; deleting an assertion removes
    verification coverage).

    `live_requirement_ids` should be the roots currently in the requirements
    document (R1, E4, ...); pass None to skip liveness checks (structure only).
    """
    live = {r.split('.', 1)[0] for r in (live_requirement_ids or set())}
    store = TraceabilityStore()
    store.rebuild(model_text, annotations=annotations)
    graph = build_reference_graph(model_text)
    callers, entry_points = graph['callers'], graph['entry_points']

    result: Dict[str, Any] = {
        'declared': {}, 'derived': {}, 'ownerless': {},
        'orphan': {}, 'dead': [], 'unclassified': [], 'undeclared_checks': [],
        'kinds': {},
        # Cross-cutting: a fact may be correctly 'declared' and still violate
        # the modelling discipline. Not counted in summary['total'].
        'discipline_violations': {},
    }

    for block in sorted(extract_all_blocks(model_text), key=lambda b: b['name']):
        name, kind = block['name'], block['kind']
        result['kinds'][name] = kind
        is_entry = name in entry_points
        constraining = kind in _CONSTRAINING_KINDS
        is_check = kind in _CHECK_KINDS or (kind == 'pred' and is_entry)
        owners = store.requirements_for(name)
        category = store.ownerless_category(name)

        # Facts hold ONLY the existing system's requirements (E#) and promoted
        # assumptions. A prospective requirement (R#) is modelled as a predicate
        # or assertion and is never a fact - so a fact declaring R# is wrong by
        # construction, whether or not that requirement is still live.
        if kind == 'fact':
            prospective = [o for o in owners if o.startswith('R')]
            if prospective:
                result['discipline_violations'][name] = prospective

        if not constraining and not is_check and not callers.get(name) and not is_entry:
            # Inert and unreachable: nothing runs it, nothing calls it.
            result['dead'].append(name)
        elif category:
            result['ownerless'][name] = category
        elif owners:
            live_owners = [o for o in owners if o in live] if live else list(owners)
            if live and not live_owners:
                result['orphan'][name] = list(owners)
            else:
                result['declared'][name] = live_owners
        elif constraining:
            result['unclassified'].append(name)
        elif is_check:
            result['undeclared_checks'].append(name)
        else:
            result['derived'][name] = _derived_owners(name, callers, store, live)

    result['summary'] = {
        'total': len(store._construct_kind),
        'declared': len(result['declared']),
        'derived': len(result['derived']),
        'ownerless': len(result['ownerless']),
        'orphan': len(result['orphan']),
        'dead': len(result['dead']),
        'unclassified': len(result['unclassified']),
        'undeclared_checks': len(result['undeclared_checks']),
        # Cross-cutting; deliberately excluded from the total-sum invariant.
        'discipline_violations': len(result['discipline_violations']),
    }
    return result


def find_unowned_blockers(audit: Optional[Dict[str, Any]],
                          diagnostics: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Undeclared facts that provably block an UNSAT predicate.

    Two signals already computed each iteration, joined for the first time:
      - `localize_blocking_facts` proves a fact blocks a scenario;
      - the ownership audit shows the fact declares no requirement.

    Either alone is dismissible - 14 facts block a given scenario, and 15 facts
    declare nothing. Their intersection is not: a fact that constrains real
    behaviour while claiming to encode nothing has no defensible status. It is
    an E#/frame/harness encoding missing its label, or a prospective constraint
    that should never have been a fact.

    Returns {fact_name: [predicates it blocks]}.
    """
    if not audit or not diagnostics:
        return {}

    undeclared = set(audit.get('unclassified') or [])
    if not undeclared:
        return {}

    blockers: Dict[str, List[str]] = {}
    for predicate, entry in (diagnostics or {}).items():
        localization = (entry or {}).get('localization') or {}
        for fact in localization.get('blocking_facts') or []:
            if fact in undeclared:
                blockers.setdefault(fact, [])
                if predicate not in blockers[fact]:
                    blockers[fact].append(predicate)
    # Most-implicated first: a fact blocking several predicates is the better
    # suspect. Localization is approximate, so this ranks rather than isolates.
    return {k: blockers[k] for k in sorted(blockers, key=lambda n: (-len(blockers[n]), n))}


def audit_model(model_text: str, requirements_text: str) -> Dict[str, Any]:
    """Audit a model against a requirements document.

    Wraps the live-ID parse so callers that hold both documents don't each
    repeat it - and don't each have to remember that BOTH families count as
    live: R# (emergency module) and E# (the existing system).
    """
    from .requirements_store import parse_original_requirement_ids

    live = parse_original_requirement_ids(requirements_text or "", prefixes=("R", "E"))
    return audit_ownership(model_text, live)


def compute_removable_closure(
    model_text: str,
    seeds: List[str],
    protect: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    What can safely be deleted if `seeds` (orphans / dead helpers) are deleted.

    Deleting a stale fact strands the helpers only it used, so removal cascades:
    a helper whose every remaining caller is itself being removed becomes dead
    in the same pass. Only helpers cascade - facts, asserts and run/check entry
    points are never swept in implicitly.

    Safety: a construct still referenced by a SURVIVING construct is reported in
    'blocked' and kept, because deleting it would break the model.

    Returns {'remove', 'seeds', 'cascaded', 'blocked'}.
    """
    protect = set(protect or ())
    blocks = extract_all_blocks(model_text)
    kinds = {b['name']: b['kind'] for b in blocks}
    graph = build_reference_graph(model_text)
    callers, entry_points = graph['callers'], graph['entry_points']

    seed_set = {s for s in (seeds or []) if s in kinds and s not in protect}
    blocked: Dict[str, List[str]] = {}
    removal: Set[str] = set(seed_set)

    # Recomputed from scratch each pass so un-blocking a construct also
    # un-cascades the helpers that were only reachable through it.
    for _ in range(len(kinds) + 2):
        removal = set(seed_set) - set(blocked)
        while True:
            added = {
                name for name, kind in kinds.items()
                if name not in removal and name not in protect and name not in blocked
                and kind in ('fun', 'pred') and name not in entry_points
                and callers.get(name) and callers[name] <= removal
            }
            if not added:
                break
            removal |= added
        newly_blocked = {
            name: sorted(callers.get(name, set()) - removal)
            for name in removal
            if callers.get(name, set()) - removal
        }
        if not newly_blocked:
            break
        blocked.update(newly_blocked)

    return {
        'remove': sorted(removal),
        'seeds': sorted(seed_set & removal),
        'cascaded': sorted(removal - seed_set),
        'blocked': blocked,
    }


def prune_constructs(model_text: str, names: List[str]) -> Dict[str, Any]:
    """
    Delete `names` from the model deterministically, and validate the result.

    Removes each construct's block, its own run/check command lines (a command
    naming a deleted construct will not parse), and the comment lines attached
    directly above it - a leftover comment still states the superseded rule and
    invites the RE to re-add it.

    Validation is fail-safe: on any inconsistency the ORIGINAL text is returned
    with ok=False, so the caller falls back to instructing the RE instead of
    saving a model this function may have broken.

    Returns {'model_text', 'removed', 'dropped_lines', 'ok', 'reason'}.
    """
    result: Dict[str, Any] = {
        'model_text': model_text, 'removed': [], 'dropped_lines': 0,
        'ok': False, 'reason': '',
    }
    try:
        targets = set(names or [])
        if not targets:
            result['reason'] = 'nothing to remove'
            return result

        lines = model_text.splitlines()
        blocks = {b['name']: b for b in extract_all_blocks(model_text)}
        missing = sorted(targets - set(blocks))
        if missing:
            result['reason'] = f"not in model: {', '.join(missing)}"
            return result

        graph = build_reference_graph(model_text)
        drop: Set[int] = set()
        for name in targets:
            block = blocks[name]
            drop.update(range(block['start'], block['end'] + 1))
            drop.update(graph['commands'].get(name, ()))
            # Comment lines directly above the declaration belong to it.
            j = block['start'] - 1
            while j >= 0 and lines[j].strip().startswith('//'):
                drop.add(j)
                j -= 1

        pruned = "\n".join(l for i, l in enumerate(lines) if i not in drop)
        if model_text.endswith("\n"):
            pruned += "\n"

        # --- validation -----------------------------------------------------
        remaining = {b['name'] for b in extract_all_blocks(pruned)}
        still_present = sorted(targets & remaining)
        if still_present:
            result['reason'] = f"still present after prune: {', '.join(still_present)}"
            return result
        expected_survivors = set(blocks) - targets
        lost = sorted(expected_survivors - remaining)
        if lost:
            result['reason'] = f"prune would also drop: {', '.join(lost)}"
            return result
        dangling = sorted(
            name for name in targets
            if any(re.search(r'\b' + re.escape(name) + r'\b', _strip_comment(l))
                   for l in pruned.splitlines())
        )
        if dangling:
            result['reason'] = f"references remain to: {', '.join(dangling)}"
            return result

        result.update({
            'model_text': pruned,
            'removed': sorted(targets),
            'dropped_lines': len(drop),
            'ok': True,
        })
        return result
    except Exception as e:
        result['reason'] = f"prune failed: {e}"
        return result


def _strip_comment(line: str) -> str:
    return line.split('//', 1)[0]


def format_ownership_report(audit: Dict[str, Any], max_listed: int = 12,
                            include_checks: bool = True) -> str:
    """Render an audit as a short report for the log / RE directive.

    include_checks=False keeps the undeclared-check COUNT in the summary line
    but drops the name list. It is the largest and least actionable bucket
    (assertions cannot over-constrain), so the names are not worth their tokens
    in a prompt that is rendered every iteration.
    """
    s = audit['summary']
    kinds = audit.get('kinds') or {}
    lines = [
        f"OWNERSHIP AUDIT: {s['total']} constructs - "
        f"{s['declared']} declared, {s['derived']} derived, {s['ownerless']} ownerless, "
        f"{s['orphan']} ORPHAN, {s['dead']} DEAD, {s['unclassified']} UNCLASSIFIED, "
        f"{s.get('undeclared_checks', 0)} undeclared checks"
    ]
    if audit['orphan']:
        lines.append("  Orphaned (requirement no longer exists):")
        for name, owners in list(audit['orphan'].items())[:max_listed]:
            kind = kinds.get(name, '?')
            note = "remove" if kind == 'fact' else f"{kind}: report only"
            lines.append(f"    - {name} (declared {', '.join(owners)}) [{note}]")
    if audit.get('discipline_violations'):
        lines.append("  DISCIPLINE VIOLATION - fact encoding a PROSPECTIVE requirement "
                     "(R# is modelled as a predicate/assertion, never a fact):")
        for name, ids in list(audit['discipline_violations'].items())[:max_listed]:
            lines.append(f"    - {name} (declares {', '.join(ids)}) [convert to pred/assert]")
    if audit['dead']:
        lines.append(f"  Dead helpers (no caller, no run/check): "
                     f"{', '.join(audit['dead'][:max_listed])}")
    if audit['unclassified']:
        shown = audit['unclassified'][:max_listed]
        more = len(audit['unclassified']) - len(shown)
        lines.append(f"  Unclassified FACTS (constrain every run, declare nothing): "
                     f"{', '.join(shown)}" + (f" (+{more} more)" if more > 0 else ""))
    if audit.get('undeclared_checks') and include_checks:
        shown = audit['undeclared_checks'][:max_listed]
        more = len(audit['undeclared_checks']) - len(shown)
        lines.append(f"  Undeclared checks (assertion/run predicate; may be probes): "
                     f"{', '.join(shown)}" + (f" (+{more} more)" if more > 0 else ""))
    return "\n".join(lines)


# A fact flagged this many consecutive iterations has already survived at least
# one delivered instruction to resolve it, so the finding stops being
# informational: repeating the same four options is what demonstrably failed.
BLOCKER_ESCALATION_THRESHOLD = 2

# Heading the Evaluator must emit one decision under, per flagged fact. Named
# here because three places depend on the exact string: the response format that
# requests it, the finding that points at it, and the parser that checks it.
BLOCKER_DECISION_HEADING = "=== UNOWNED BLOCKING FACT DECISIONS ==="


def track_blocker_persistence(
    current: Dict[str, List[str]],
    history: Optional[List[Dict[str, Any]]],
) -> Dict[str, int]:
    """Consecutive iterations each current blocker has gone unresolved.

    A fact that is flagged, ignored, and flagged again is precisely the failure
    this mechanism exists to catch - the Evaluator was handed the finding once
    and weakened the fact anyway. Counting the streak is what separates "the
    agent has not seen this yet" from "the agent saw it and declined", which
    need different guidance.

    `history` is prior iterations' blocker maps, MOST RECENT FIRST. The streak
    stops at the first iteration that did not flag the fact: a fact resolved and
    later regressed starts over, because the gap is evidence the agent did act.
    """
    streaks: Dict[str, int] = {}
    for fact in current or {}:
        streak = 1
        for previous in history or []:
            if fact not in (previous or {}):
                break
            streak += 1
        streaks[fact] = streak
    return streaks


def format_unowned_blockers(blockers: Dict[str, List[str]],
                            streaks: Optional[Dict[str, int]] = None) -> str:
    """Render the audit x localization join as a ranked finding - DATA ONLY.

    How to resolve the finding is prompt text: it lives in the Evaluator's
    `UnownedBlockingFacts` section, which the caller appends. Keeping it there
    means the rules can be edited in the prompt file rather than in Python.

    There is no "stale" variant. Localization runs BEFORE InterpretResults (see
    workflow._prepare_semantic_escalation), so every list rendered here was
    measured against the model the reader is looking at. A list that is NOT from
    the current iteration is not labelled - it is withheld; the caller checks the
    measurement stamp.
    """
    if not blockers:
        return ""
    streaks = streaks or {}
    lines = [
        "UNOWNED BLOCKING FACTS - each constrains the model into UNSAT while "
        "declaring no requirement:"
    ]
    for fact, predicates in blockers.items():
        streak = streaks.get(fact, 1)
        age = (f" UNRESOLVED for {streak} consecutive iterations."
               if streak >= BLOCKER_ESCALATION_THRESHOLD else "")
        lines.append(
            f"  - {fact} blocks {', '.join(predicates)} and encodes no requirement.{age}"
        )
    persistent = sorted(f for f, n in streaks.items()
                        if n >= BLOCKER_ESCALATION_THRESHOLD and f in blockers)
    if persistent:
        lines.append(f"  ESCALATION: {', '.join(persistent)}.")
    return "\n".join(lines)


def parse_blocker_decisions(feedback: str) -> Dict[str, str]:
    """Facts the Evaluator recorded a decision for, {fact: resolution}.

    The finding tells the agent to resolve every listed fact; without reading
    back what it actually decided, "every" is unenforceable - which is how the
    stale fact survived being flagged the first time. Deliberately lenient about
    formatting: a decision stated in a recognisable shape counts, because the
    check exists to catch silent omission, not to police punctuation.
    """
    if not feedback or BLOCKER_DECISION_HEADING not in feedback:
        return {}

    body = feedback.split(BLOCKER_DECISION_HEADING, 1)[1]
    # Stop at the next `=== SECTION ===` heading so a later section's prose
    # cannot be mistaken for a decision.
    next_heading = re.search(r"^\s*===\s", body[1:], re.MULTILINE)
    if next_heading:
        body = body[: next_heading.start() + 1]

    decisions: Dict[str, str] = {}
    current_fact = None
    for line in body.splitlines():
        stripped = line.strip().lstrip('-').strip()
        fact_match = re.match(r"(?i)^fact\s*:\s*(.+)$", stripped)
        if fact_match:
            current_fact = fact_match.group(1).strip().strip('`*[]')
            decisions.setdefault(current_fact, "")
            continue
        resolution = re.match(r"(?i)^resolution\s*:\s*(.+)$", stripped)
        if resolution and current_fact:
            decisions[current_fact] = resolution.group(1).strip()
    return decisions


def missing_blocker_decisions(blockers: Dict[str, List[str]],
                              feedback: str) -> List[str]:
    """Flagged facts the feedback left undecided, in the finding's own order."""
    if not blockers:
        return []
    decided = {name.lower() for name in parse_blocker_decisions(feedback)}
    return [fact for fact in blockers if fact.lower() not in decided]


def format_ownership_for_prompt(audit: Optional[Dict[str, Any]],
                                removals: Optional[str] = None,
                                max_listed: int = 8,
                                blockers: Optional[Dict[str, List[str]]] = None,
                                streaks: Optional[Dict[str, int]] = None) -> str:
    """Ownership evidence for the Evaluator's interpretation prompts.

    The Evaluator is asked to map a blocking construct to a requirement, and to
    name the requirement a fact encodes before proposing to weaken it. Neither
    is answerable from construct names alone: a name says `E5`, but only the
    audit knows whether E5 is still a live requirement.
    """
    if not audit:
        block = (
            "OWNERSHIP AUDIT: unavailable for this iteration. Infer ownership "
            "from construct names and say that you did."
        )
    else:
        block = format_ownership_report(audit, max_listed=max_listed,
                                        include_checks=False)
        block += (
            "\n  How to read this:"
            "\n  - ORPHAN and UNCLASSIFIED facts encode no live requirement. They are "
            "leftovers to remove or declare, NOT over-restrictive constraints to weaken."
            "\n  - Undeclared checks are assertions or run predicates. They cannot "
            "over-constrain the model, and an exploratory check may legitimately encode "
            "no requirement - a missing declaration there is not a defect."
            "\n  - A fact may only encode an existing-system requirement (E#) or a "
            "promoted assumption. A fact encoding a prospective requirement (R#) is a "
            "discipline violation - convert it to a predicate/assertion."
            "\n  - Declared and derived constructs have a live owner; treat them normally."
        )

    # Highest-signal finding first: proven to block, proven to own nothing.
    # The caller only passes `blockers` when they were measured THIS iteration,
    # so this is current evidence about the model shown alongside it.
    joined = format_unowned_blockers(blockers or {}, streaks)
    if joined:
        block = joined + "\n\n" + block

    if removals:
        block += "\n\n" + removals
    return block
