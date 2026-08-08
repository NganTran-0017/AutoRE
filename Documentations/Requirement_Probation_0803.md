# Provisional Requirements: Every Update Earns Its Place

## Problem

A requirement update became official the instant `apply_patch` wrote it.
`DocItem` is `{id, raw}` (`requirements_store.py:51`) — no status, no history, no
relation to any other requirement. Three consequences:

1. **User feedback became a requirement unverified.** The user can confirm
   *wording*; they cannot confirm *consistency with the rest of the document*.
   That is what the solver is for. The sharpest case was `gate_decision ==
   'provisional'` — the user timed out and the update was applied as if
   confirmed.
2. **Nothing detected a contradiction.** The triage had DUPLICATE / MODELING /
   CONSTRAINT / REQUIREMENT / UNSURE — no bucket for "this cannot hold at the
   same time as R6". A contradictory candidate was filed as a new requirement,
   both were encoded, and `All_Requirements` went UNSAT.
3. **The document had no memory of its own change.** `MODIFY R6` overwrote R6 in
   place; only the patch log knew it ever said anything else.

This is the July "Out of scope (optional Fix C)" item — supersession status on
`DocItem` plus a triage CONTRADICTS bucket — deferred then because the observed
failure (`EmergencyUnique`) was model-side and closed by Fix A/Fix B. It returns
because both halves need the same missing primitive: **a requirement that is
written but not yet trusted.**

## Rule

Every applied patch operation — ADD, MODIFY, MODIFY-SECTION, REMOVE, with or
without user confirmation — is provisional until it survives **3 consecutive
analyzed iterations**. No operation and no gate decision buys an exemption.

## Where the status lives

`src/utils/requirement_status_store.py`, a side store — *not* a field in the
document. `render_document` reproduces `item.raw` byte-for-byte, so a marker
written into `raw` becomes part of the requirement. Markers are injected at
prompt-render time only, exactly like the `[E#]` addressing markers.

```
R5: Session timeout            [ACTIVE]
R6: Emergency recording        [PENDING REMOVAL since it.21, 1/3]
R7: Audit trail                [PROVISIONAL since it.23, 2/3]
```

Persisted like the three audit logs (load on init, trim on resume, snapshot to
`Output/`). Reconciled against `doc.all_item_ids()` each iteration; drops are
**logged**, because a status that vanished and one that was confirmed both leave
an item unmarked.

## Lifecycle

```
              ┌─ 3 clean iterations ──────────────► active
provisional ──┼─ implicated ──────────────────────► contested ──► user decides
              └─ 3 iterations unencoded ──────────► stalled   ──► user decides

pending_removal ─ 3 clean ─► deleted from the document
                └ failure ─► back to active
```

Nothing is auto-deleted. Same principle as the lesson and convention lifecycles:
the outcome raises, the user decides.

### REMOVE is deferred, not performed

`apply_patch(..., defer_removals=True)` records the op and leaves the item in the
document. Its *encoding* is deleted at once (the op still appears in `applied`,
which is what stages `REMOVE_STALE_CONSTRUCTS`), so the removal is verified
against a model that no longer contains it while the text stays available to
review and revert. `remove_item()` performs the deletion once probation closes.

A deferred-only patch reports `changed=False` — the document really is
byte-identical, and claiming otherwise would have the caller store the old
document as new.

### What counts as a clean iteration

| Op | Clean means |
|---|---|
| ADD / MODIFY (R#) | a construct owned by the ID exists, and the ID is not implicated — not in `unsatisfied_predicates`, `counterexamples`, or `blocking_facts` |
| ADD / MODIFY (E#) | as above, plus `baseline` is SAT — the signature symptom of an inconsistent existing-system fact |
| REMOVE | no surviving construct is owned by the ID, and the prune was not blocked |
| MODIFY-SECTION | model analyzed — a section blob has no ID to trace, so no encoding can be demanded of it |

Two rules that are easy to get wrong:

- **The clock only advances on an iteration whose model compiled.** A syntax
  error is evidence about syntax, not about whether a requirement is consistent.
  It neither credits nor debits.
- **A failure implicating two provisional items identifies neither.** Credit is
  withheld from both; nothing is contested. Contesting the wrong requirement is
  worse than waiting.

Reverting needs no new machinery: the patch log already records before/after per
op, so a provisional ADD reverts by `REMOVE` (never protected — it was not in the
original source) and a MODIFY by re-applying `prior_text`.

## The anti-stall ladder

The failure this closes: the RE never encodes a provisional requirement, or names
its construct untraceably. No evidence can arrive, the item sits forever, and
convergence stays blocked. **Waiting quietly is the one response that cannot
resolve it.**

The ownership audit already separates the two causes, and their remedies are
opposite:

| Cause | Signature | Remedy |
|---|---|---|
| not encoded | nothing names or annotates the ID | BUILD it |
| encoded but unattributable | constructs exist that declare nothing | add one `//@req` line — **not** a second construct |

`build_encode_provisional` emits an `ENCODE_PROVISIONAL` directive through the
existing `repair_escalation` channel, stating which remedy each item needs. It
opens by saying it is a *traceability obligation, not a repair* — the model may
be entirely healthy, and the RE must not "fix" anything to satisfy it. On a
repeat it names the repeat, so the RE does not redeliver what already failed
(the same rule the unowned-blocking-facts finding uses). After 3 iterations it
stops guessing: status → `stalled`, escalated to the user as
`REQUIREMENTS_DIAGNOSIS` — three failures to encode is itself evidence the
requirement is unmodelable as stated.

## Contradiction triage (bucket 6)

Triage gained CONTRADICTS: name the **minimal** set of existing IDs that cannot
hold at the same time, in a `Conflicts with:` field on the updates entry.

**It ships in observe mode** (`config.yaml: requirements.conflict_mode`). The
verdict is written to `Output/RequirementConflict/shadow.jsonl` and nothing else
happens. Whether it over-fires is a question about model behaviour that no unit
test answers, and a false positive discards a requirement — possibly the user's
own words — with no downstream way to recover it. Same playbook as convention
dedup, and earned: the analogous CONTRADICTORY verdict for lessons is still
unvalidated.

Two guards that do not depend on trusting the verdict:

- a CONTRADICTS naming no ID, or an ID absent from the document, is downgraded to
  UNSURE deterministically — the semantic judgment cannot be checked, but whether
  it points at something real can;
- on any uncertainty, **admit and let probation watch**. A missed contradiction
  resurfaces with solver evidence; a false block has no recovery path.

In active mode a `[CONFLICT]` question asks which item governs and the updates
section is withheld for that iteration. Withholding is deliberately coarse — the
whole section, not just the conflicting entry — because a partial strip leaves it
half-applied, and the triage re-runs every iteration, so a non-conflicting update
it takes along costs one iteration, not the update. On override,
`conflict_acknowledged` records the user's standing decision; **without that flag
the same conflict is re-raised every iteration and the gate becomes unusable.**

## Convergence

Convergence is withheld while any item is `provisional`, `pending_removal`,
`contested` or `stalled`. The outstanding set is printed and the user may type
`converge` to finish anyway.

Both halves matter. Without the gate, a run declares success on a document
containing requirements nobody verified. Without the override, a run whose
requirements keep changing can never finish — probation always extends 3
iterations past the last change.

## Known gaps

1. **Verdict quality is unvalidated** for bucket 6, exactly as for contradicting
   lessons. That is what observe mode is for; read the shadow log before going
   active.
2. **Attribution is still contested** when several changes are in flight. The
   unique-culprit rule prevents a wrong accusation but cannot produce a right one
   — those iterations simply yield no verdict.
3. **`acknowledged_conflicts` is in-memory only.** A restart re-raises a conflict
   the user already decided. The durable half (`conflict_acknowledged` on the
   record) is written, but only once the update is applied.
4. **Question load.** `[CLASSIFICATION]`, `[CONFLICT]`, the requirement gate and
   the Q&A round all compete for the same user attention in one iteration.
   Nothing caps them yet; priority should be contested/stalled > conflict >
   classification.
5. **Every run is up to 3 iterations longer** past its last requirement change.
   Accepted deliberately; the convergence override is the release valve.

## Key files

| Concern | File |
|---|---|
| Status, lifecycle, probation rules, conflict parsing | `src/utils/requirement_status_store.py` |
| Deferred removal, status markers, `remove_item` | `src/utils/requirements_store.py` |
| Recording every applied op | `src/actions/evaluation_actions.py` (`UpdateRequirements.run`) |
| Annotated document for both agents | `src/actions/lesson_aware_action.py` (`annotate_requirements`) |
| Probation round, stall ladder, conflict screen, convergence gate | `src/workflow.py` |
| `ENCODE_PROVISIONAL` directive | `src/utils/repair_plateau_detector.py` |
| Bucket 6, `Conflicts with:` field | `prompts/Evaluator_prompt.txt` |
| `ENCODE_PROVISIONAL` handling | `prompts/RE_prompt.txt` |
| Tests (46 + 45) | `test/test_requirement_status_store.py`, `test/test_requirement_probation.py` |
