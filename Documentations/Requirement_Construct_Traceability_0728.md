
# Requirement→Construct Traceability: Stale-Encoding Detection and Removal

Five mechanisms over one traceability map, covering a construct's lifecycle from
"which requirement does this encode?" to "that requirement is gone — delete it,"
and finally telling the Evaluator what was deleted and why.

## Problem

A construct can outlive the requirement it encodes:
- a requirement is **changed** and its old encoding is left behind (runs
  072126/072226: `MODIFY R6`);
- a requirement is **removed** and its constructs remain;
- a construct encodes an **obsolete original requirement** that never survived
  refinement (`fact EmergencyUniqueness` encodes original R1 *"can only enter
  Emergency mode once"*; refined R1 permits multiple Emergency periods).

The leftover silently over-constrains the model into UNSAT, and the diagnosis
blames the *model* — at iteration 37 the Evaluator recommended *"weaken fact
EmergencyUniqueness to an assertion"* rather than removing it.

## Foundation: TraceabilityStore

`{requirement_id: {construct_names}}`, rebuilt against the actual model every
iteration so the map itself cannot go stale. Three sources:

- **Deterministic** — IDs carried in names (`fact R1R2_x`, `assert assertR6`,
  `fact E1_ClearanceAssignment`). Both families are traced: **R#** (emergency
  module) and **E#** (existing system).
- **Annotation** — `//@req R2, E3` on the declaration line, for constructs whose
  name cannot carry the ID.
- **Ownerless declaration** — `//@req none:frame` (well-formedness),
  `//@req none:harness` (scope/universe scaffolding), or `//@req none:probe`
  (an exploratory or edge-case check that encodes no requirement).

## Fix A — prevention (requirement changed)

At step 7 the patch log's changes are routed **by operation**:

| Op | Route | Why |
|---|---|---|
| `MODIFY` | `REGENERATE_PREDICATES` | rebuild the construct from the new text |
| `REMOVE` | `REMOVE_STALE_CONSTRUCTS` | requirement is gone — nothing to rebuild from |

Both are staged in the same step 7, so the RE never receives "rebuild" and
"delete" for the same construct in consecutive iterations.

## Fix B — attribution (diagnosis safety net)

For constructs Fix A misses, the two-key evidence gate adds the
`stale_requirement_encoding` verdict when a requirement changed in the last 3
iterations owns the construct causing the UNSAT — either:

- the diagnosed predicate itself (`internal_contradiction`), or
- a **fact blocking it** (`localized` → `blocking_facts`).

The verdict counts as REQUIREMENT evidence, so the escalation stays
`REQUIREMENTS_DIAGNOSIS` instead of vetoing to `MODEL_OVERCONSTRAINT_REPAIR`.

## Mechanism A — ownership classification

Every construct is classified each iteration, by **what it can do to the model**
rather than by whether it looks important:

| Role | Ownership | Risk if undeclared |
|---|---|---|
| `fact` | **must** declare (name or `//@req`) | **high** — constrains every run, can force UNSAT |
| `assert`, run-invoked `pred` | *should* declare | low — interrogative; asks a question, cannot over-constrain |
| helper `fun` / uncalled `pred` | derived from the reference graph | none — inert unless called |

This asymmetry drives every downstream decision. Deleting a fact only *relaxes*
the model; deleting an assertion silently removes verification coverage. An
assertion that encodes no requirement is therefore a documentation gap, not a
defect — a deliberate edge-case probe is legitimate.

Buckets: `declared`, `derived`, `ownerless`, **`orphan`** (names only
requirements that no longer exist), **`dead`** (helper with no caller and no
`run`/`check`), **`unclassified`** (a *fact* that declares nothing),
**`undeclared_checks`** (an assertion or run-predicate that declares nothing —
reported, never actioned).

Unlike Fix A/B this is **state-based, not event-based** — no recency window, so
a construct orphaned many iterations ago is still caught.

### Discipline classification (cross-cutting)

Two rules apply on top of the buckets, because a construct can be correctly
*declared* and still be wrong:

1. **A fact declaring `R#` is wrong by construction.** Facts hold only
   existing-system requirements (`E#`) and promoted assumptions; a prospective
   requirement is a predicate or assertion. Such a fact lands in
   `discipline_violations` even when its owner is live — so it is *not* counted
   in `summary['total']`, which stays a partition of the buckets. The repair is
   conversion to a predicate, never weakening.
2. **A construct may legitimately own nothing, but must say so.** `//@req
   none:frame` (well-formedness), `none:harness` (scope/universe setup),
   `none:probe` (exploratory check — assertions and run predicates only, never a
   fact). An undeclared *assertion* is a documentation gap; an undeclared *fact*
   is `unclassified` and actionable.

## Mechanism D — removal

Stale constructs are **deleted deterministically**, not requested.
`prune_constructs` removes each block, its `run`/`check` command lines, and the
comment lines attached above it — applied to the model the RE is *about to
edit*. The RE is then told the constructs were already removed and must not be
re-introduced.

**What gets deleted depends on how strong the evidence is:**

| Path | Evidence | Deletes |
|---|---|---|
| Ownership audit | *inferred* — owner absent from the parsed requirements | orphaned **facts** and dead helpers only |
| Patch log `REMOVE` | *proven* — an explicit requirement removal | every kind, assertions included |

The audit path is fail-open by design: a formatting variation that makes
`parse_original_requirement_ids` miss an ID must not silently delete a working
check. Orphaned assertions and run-predicates are reported and left in place.

- **Cascade** — helpers stranded by the deletion go in the same pass.
- **Reference safety** — anything still referenced by a survivor is reported as
  `blocked` and kept.
- **Fail-safe** — any validation failure returns the original text unchanged and
  falls back to instructing the RE.
- **Audit trail** — `ConstructRemovalLog` records the deletion as
  workflow-authored, distinct from RE-authored edits. Persisted to
  `memory/<project>/construct_removal_log.json` and copied to
  `Output/ConstructRemovalLog/`, because the workflow is normally restarted with
  `resume_iteration=N` and an in-memory record would start empty every time.

Instruction-only was rejected because the observed failure *was*
non-compliance: the RE weakened the stale fact instead of removing it.

Never deleted: `unclassified` facts (unlabelled ≠ proven stale),
`undeclared_checks`, orphaned non-facts, and `blocked` constructs.

### Resume safety

Resuming to N re-runs iteration N onward, so all three audit logs
(regression, requirement-patch, construct-removal) are trimmed to
`iteration_id < N`; history before the resume point is kept, and the discarded
tail is archived to `Output/` first. Two bugs made this necessary beyond the
removal log: `RegressionLog.add_entry` appends while `get_entry` returns the
first match, so a surviving entry N permanently shadows the rerun's; and
`changed_requirement_ids_since` — which drives Fix B — would report requirement
changes from iterations the run has not reached.

## Mechanism E — Evaluator delivery

The audit was computed, logged, and discarded; nothing reached the agent that
makes the weaken-or-remove call. One ~270-token block (ownership buckets +
deliberate-removal history + three lines on how to read them) now renders into
`InterpretResults` and `VacuityAnalysis`.

| Section | Carries the block | Why |
|---|---|---|
| `InterpretResults` | yes | regression analysis lives here — a pruned construct must not read as a regression |
| `VacuityAnalysis` | yes | `Reduce Assumptions` now requires an `Encodes:` field per fact; `NONE` routes to *declare or remove*, never *weaken* |
| `InterpretUNSATPred` | refers to it | appended to the base prompt, which already carries it; its step 3 gained a seventh root cause — *stale construct* |
| `GenerateSemanticFeedback` | **no** | consumes `{{interpretation}}` and is told not to re-diagnose; the conclusion arrives through the interpretation |

The audit is recomputed in-action when `context.ownership_audit` is empty — true
on the first iteration and after every resume, since it is otherwise populated at
the end of step 8.

### Context hygiene in the Evaluator prompt

Delivering more evidence into a prompt that already contradicted itself just
raises the odds the new block is the one ignored. Six defects were removed, each
scoped to what actually co-occurs in one *rendered request* — several sections
are sent as standalone LLM calls, where their copy is the only one:

| Defect | Fix |
|---|---|
| **Clash.** `ResponseFormatInterpretation` said "return exactly these sections and nothing else", while the three appended analysis blocks each say "Add this section to the output" | the format now admits the appended sections; `GenerateSemanticFeedback` task 8 hard-depends on the UNSAT Matrix existing |
| **Clash.** DECISION POLICY "3+ iterations → reassess the requirements" is the exact opposite of `MODEL_OVERCONSTRAINT_REPAIR` rule 3 — and persistence is what *produces* that strategy, so both were always active together | the heuristic now yields to a computed STRATEGY line |
| **Clash.** The unowned-blocker mandate is appended *before* the EVIDENCE ALIGNMENT block, so `REQUIREMENTS_DIAGNOSIS` read as overriding it | declared strategy-independent in three places, including the finding text itself |
| **Distraction.** `ConvergenceCriteria` rendered into `InterpretResults`, which has no convergence field | excluded; the recommendation is made once, by `GenerateSemanticFeedback` |
| **Redundancy.** MODELING DISCIPLINE restated inside single requests | `InterpretUNSATPred` and `InterpretCounterexample` now cite it; the standalone sections keep their own copy |
| **Redundancy.** `AbstractionGuidance` and the ABSTRACTION GATE both derived the WHAT/HOW distinction | the test is named and stated once in `AbstractionGuidance`; the GATE cites it and contributes only the wording rules for a requirement update |

Two prompt defects were fixed alongside: the `RE-DIAGNOSE the root cause …
analyze the current error context and code snippet independently` bullet had been
copied into `GenerateSemanticFeedback` from the syntax-repair section, where
`{{code_snippet}}` actually exists — it told the agent to work independently of
the interpretation it exists to consume, contradicting the DECISION POLICY three
lines above. It is now scoped to distrusting failed fixes. The RE prompt's
ownership rule was likewise too strong, demanding a requirement for every
assertion; it now demands one only for facts.

## Mechanism F — unowned blocking facts

The audit says a fact declares nothing; `localize_blocking_facts` proves a fact
blocks a scenario. Either alone is dismissible — 15 facts declare nothing, 14
block a given scenario. **Their intersection is not**: a fact that constrains
real behaviour while claiming to encode nothing has no defensible status. This
is the first mechanism that isolates `EmergencyUnique` from the noise, cutting
15 undeclared facts to the 8 that provably block.

`find_unowned_blockers` joins the two and ranks most-implicated-first.

### The four resolutions

Naming the fact was not enough — the Evaluator was told to "resolve every one"
with no criteria for choosing, and no way to detect that it hadn't. Three
additions closed that:

1. **A decision per fact is required output.** `=== UNOWNED BLOCKING FACT
   DECISIONS ===` sits *before* `=== REPAIR INSTRUCTIONS ===` in
   `ResponseFormatFeedback` and takes Fact / Resolution / Requirement /
   Rationale. `_check_blocker_decisions` parses the draft feedback and logs any
   fact left undecided — non-compliance becomes visible the moment it happens
   rather than an iteration later. The heading is one constant
   (`BLOCKER_DECISION_HEADING`) shared by the format, the finding, and the
   parser, so the three cannot drift.
2. **Criteria, not just options.** Existing-system guarantee → declare `E#`;
   well-formedness → `none:frame`; scope setup → `none:harness`; prospective
   behaviour → convert to a predicate; unnameable → delete. Never *weaken*: a
   weakened fact that still encodes nothing is still unowned and will block
   again. The annotation vocabulary itself was only ever defined in the RE
   prompt; the Evaluator was being told to recommend syntax it had never seen.
3. **Persistence.** `track_blocker_persistence` counts consecutive iterations
   per fact, reading history back out of
   `regression_log.entries[*].repair_escalation['unowned_blockers']` — already
   persisted and already resume-trimmed, so a streak cannot count iterations a
   rewind discarded. A gap resets it: an un-flagged iteration is evidence the
   agent acted. At streak ≥ 2 the finding adds an ESCALATION line: the previous
   instruction demonstrably failed, so pick a *different* resolution.

### Two audiences, two wordings

The same join reaches two prompts at different freshness, so
`format_unowned_blockers(..., stale=)` renders it twice:

| Consumer | Freshness | Wording |
|---|---|---|
| `GenerateSemanticFeedback` (via the escalation directive) | measured this iteration | mandate: resolve every one, record a decision each |
| `InterpretResults` / `VacuityAnalysis` (via the ownership block) | **previous** iteration, previous model | prior: confirm against the current model, propose nothing |

The split is forced by ordering: localization runs *after* `InterpretResults`
(`workflow.py:1060` → `:1920`), so the interpretation can only ever see last
iteration's list — measured against a model step 8 has since rewritten. Labelling
it as a prior is the fix; moving localization earlier is not, because
`apply_evidence_alignment` needs the interpretation's causal analysis to be
formed *independently* of the deterministic diagnosis. Showing the interpretation
the measured answer first collapses the two-key gate into one key.

The stale copy also drops the decision mandate: `ResponseFormatInterpretation`
has no section to record decisions in.

### Scope

Advisory, not enforcing. Nothing deletes the fact and nothing rejects
non-compliant feedback — deterministic deletion runs on the separate
`pending_stale_removal` → `prune_constructs` path, which requires *proven*
evidence (owner absent, or an explicit `REMOVE` in the patch log). The teeth here
are re-flagging with a rising streak.

`_flag_unowned_blockers` is reachable only from inside the already-escalated
branch, so `escalation_level > 0` holds by construction and the directive reaches
the RE without a level bump.

## Patch log: what changed, not only that it changed

`applied: ["MODIFY R6"]` cannot distinguish a wording clarification from a
reversal of meaning — and reversal is exactly what invalidates an encoding.
`apply_patch` now also returns `changes: [{op, target, before, after}]`, captured
for MODIFY (both sides), REMOVE (before only — the deleted text exists nowhere
else), ADD and MODIFY-SECTION. `changed_requirement_ids_since` answers *which*;
the new `changes_since` answers *how*. `applied` keeps its string form, so Fix A/B
are unaffected.

A latent bug was fixed alongside: a MODIFY body that omitted the `R#:` prefix
dissolved the item into the previous one — `_R_ITEM_START` is what makes an item
addressable on the next parse, so the ID vanished from the document while the
patch log, the traceability map and every `//@req` annotation still referenced
it. `_ensure_r_id_prefix` re-attaches it using the item's own separator and
indent, mirroring the bullet-marker guard already used for `E#` items.

## Known gaps

1. **Declared-but-contradicting — the original failure remains uncaught.**
   Ownership catches "the owner is gone," not "the owner exists but the
   construct contradicts it." `EmergencyUniqueness` would most likely be
   annotated `//@req R1`; R1 is live, so it passes the audit while still
   forbidding what R1 permits. Partially mitigated: it currently surfaces as an
   `unclassified` fact, which the Evaluator is now told to remove or declare
   rather than weaken — and, since Mechanism F, as an *unowned blocking* fact
   with a proof that it blocks and a required per-fact decision. Still an
   accident of it having gone undeclared; a declared one would slip through.
2. **Supersession list not implemented** (deferred). Diff
   `original_requirements.txt` against the refined document and feed superseded
   clauses to the RE as negative constraints. Root-cause fix for gap 1 — the RE
   encoded original wording that was still in its context.
3. **Unclassified backlog** — 12 of 63 facts in `AlloyModel__43.als` and 15 of 78
   in `__65` declare nothing. The prompt shrinks this over time; nothing enforces
   it. (Earlier counts of 28/38 conflated facts with assertions.)
4. **No live-run validation** — unit-tested only (180 tests across the suites
   below), never executed against a real LLM/Alloy run. Resume from **23**
   exercises prevention, **65** exercises removal (`E5_RequestProcessorAudit`);
   run **65 first**, since trimming to 23 permanently truncates 24–65. Watch for
   `[UNOWNED_BLOCKERS] no decision recorded for:` — it is the trigger for gap 6.
5. **Trim is not applied retroactively** --> FIXED — `trim_to_iteration` was dead code on
   the regression and patch logs until now, so logs written by earlier runs may
   already contain post-resume entries. The first trim on resume clears them.
6. **No hard stop on a persistent blocker** (deferred pending gap 4). The streak
   escalation *asks* for a different resolution; `_check_blocker_decisions`
   observes but never rejects. Candidate: force removal at streak 3 through the
   `pending_stale_removal` prune path, gated on an Analyzer run of the pruned
   model — `prune_constructs` validates only textually today (block boundaries,
   reference graph), so a prune that parses but regresses a passing assertion
   ships unverified.

## Key files

| Concern | File |
|---|---|
| Map, audit, closure, prune, prompt block, blocker join + streaks | `src/utils/traceability_store.py` |
| Blocks, reference graph, ID extraction, `localize_blocking_facts` | `src/utils/semantic_diagnostics.py` |
| Directive builders, verdicts, evidence gate | `src/utils/repair_plateau_detector.py` |
| Staging, routing, prune wiring, log trimming, `_flag_unowned_blockers`, `_check_blocker_decisions` | `src/workflow.py` |
| Removal record + persistence | `src/utils/construct_removal_log.py` |
| Changed-ID source, `changes_since` | `src/utils/requirement_patch_log.py` |
| Live requirement IDs, before/after capture, R-ID guard | `src/utils/requirements_store.py` |
| Ownership + blocker block delivery | `src/actions/evaluation_actions.py` (`InterpretResults`) |
| Section composition, per-action inclusion lists | `src/utils/prompt_manager.py` |
| Ownership + `REMOVE_STALE_CONSTRUCTS` rules | `prompts/RE_prompt.txt` |
| `Encodes:` field, stale-construct root cause, decision format, WHAT/HOW test | `prompts/Evaluator_prompt.txt` |

Tests (180): `test_ownership_audit.py`, `test_construct_pruning.py`,
`test_stale_construct_removal.py`, `test_requirement_change_routing.py`,
`test_requirement_change_regeneration.py`, `test_traceability_store.py`,
`test_construct_removal_log.py`, `test_resume_log_trimming.py`,
`test_ownership_prompt_delivery.py`, `test_unowned_blockers.py`,
`test_requirements_patch.py`.

The memory-side counterpart — how contradicting *lessons* are suspended rather than merged — is in `Documentations/Lesson_Conflict_Lifecycle_0802.md`.
