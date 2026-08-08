# Unfinished Edges (as of 2026-08-05)

Everything below is on branch `feature/enhanced-syntax-error-handling`, all uncommitted. This is the standing list of operations that are *declared* by a design but not, or only partly, *performed* by the code — the failure mode being that a mechanism reads as complete in its own document while a path through it does nothing.

Ordered by consequence, not by feature.

---

## 1. Nothing has been validated on a live run

**Every** feature below — requirement probation, the contest and revert path, contradiction triage in active mode, lesson conflict lifecycle, traceability Fix A/B — has only unit tests. No run has exercised any of them end to end.

The validation run must start from **iteration 65, not 23**: trimming to 23
permanently truncates 24–65. Before it, add `//@req R6` to the model so Fix B has
something to trace.

What to watch, per feature:

| Feature | Signal that it works | Signal that it misfires |
|---|---|---|
| probation | `[PROVISIONAL since it.N, k/3]` markers render in both agents' documents | markers appear inside requirement *text* (means a marker reached `DocItem.raw`) |
| encode ladder | `ENCODE_PROVISIONAL` fires, item becomes traceable within 3 | same item re-listed every iteration → the directive is not landing |
| contest | a contest names one requirement with real evidence | contests on unrelated requirements → the unique-culprit rule is not tight enough |
| conflict (active) | `[CONFLICT CLAIMED]` notice appears, update still applies, claim shows up in the contest question if verification implicates it | the update is missing from the document → something is still withholding on a claim |
| convergence gate | run refuses to converge with items outstanding, `converge` overrides | run never converges → probation is extending past every change |
| stall resolution | `[STALLED]` appears at 3 unencoded iterations, `reword` produces a diagnosis next iteration | item stays stalled after an answer → the queue is not clearing |
| convention dedup | the injected convention list stops growing monotonically; `verdict` in `Output/ConventionDedup/shadow.jsonl` matches your own reading of each pair | a rule the builder was obeying disappears from the prompt → a CONTRADICTORY call was wrong, or a merge dropped a constraint |

---

## 2. Contradiction handling — reworked 2026-08-04

A `CONTRADICTS` verdict is the Evaluator's reading of two pieces of English. Nothing consulted the solver. The first cut treated it as a finding: the whole `=== REQUIREMENT UPDATES ===` section was withheld and the user was asked, before iteration, which requirement governed — so the cost of a wrong claim was a discarded requirement, paid before anything had checked whether the conflict was real.

**Now the claim is reported, and verification settles it.**

- **Nothing is withheld, in either mode.** The update is applied, encoded, and verified like any other. The Evaluator prompt says so explicitly, so a declaration is not read as a licence to soften or omit the change.
- **`active` means the user is told**, as a `[CONFLICT CLAIMED]` notice that asks for nothing, and the claimed IDs are attached to the update after the patch (`_attach_declared_conflicts` → `note_conflict`, `acknowledged=False`). `observe` records to the shadow log and shows nothing.
- **Attachment is unambiguous or absent.** The claim names its candidate in prose, so it is matched to an applied ID when the prose contains one, otherwise only when the iteration applied exactly one update. Attaching it to the wrong item would later supersede a requirement that was never in the conflict.
- **The decision is asked when the solver bears the claim out.** The item is contested through the ordinary probation path, and the contest question now says what else the answer does: `revert` removes the update from document and model; `keep` puts the requirement it contradicted into `PENDING_REMOVAL`.
- **`keep` is where supersession happens** (`_stage_conflict_supersession`) — two independent things agree by then: the Evaluator claimed they cannot coexist, and the solver produced a failure consistent with that. The loser is deferred, not deleted: text stays marked, encoding goes, three verified iterations before it is gone. The link to the surviving update is **exact**, because the contest named it.
- **Reverting is the mirror.** `_perform_requirement_reverts` handles a `PENDING_REMOVAL` (model-side only — the text never left), and reverting the surviving update cascades through `displaced_by` to restore what it displaced, cancelling a deletion already scheduled for the same iteration.
- **Settlement is durable.** `acknowledge_conflict` writes to every member of the set, keyed on the sorted ID tuple, so a restart does not re-report a decided conflict and the Evaluator's write order cannot defeat the match. `trim_to_iteration` forgets a settlement given at or after the resume point.

`note_conflict` now creates a record when the item has none — the item on the losing side is usually original-source and by design carries no status entry, so the old early-return meant the common case was never written. `Requirement_Probation_0803.md` gap 3 ("written, but only once the update is applied") is obsolete.

**What is still open:**

1. **A supersession can only be undone by reverting its cause.** Keeping the new requirement *and* restoring the old one — coherent if they turn out not to actually contradict — has no path. A `pending_removal` is never routed to `contested`, so `_resolve_requirement_contests` never sees one. (A stalled `pending_removal` now *is* askable, via `wait`/`drop` — but that is about encoding, not about changing your mind.)
2. **The window is three iterations.** The cascade fires only while the surviving update is contestable; once it passes probation it is `ACTIVE`, and the supersession completes at about the same time. Inherent to deferred removal, but "revertible" means "revertible while on probation".
3. **A claim that is never attached is never asked about.** If the iteration applied several updates and the prose named none, the contest proceeds without citing the conflict, and `keep` supersedes nothing. Mitigated 2026-08-04 by prompt: bucket 6 must name BOTH sides, `Target kind & placement` must carry a concrete id (`new R7`, not `new R#`), the id must be repeated in `Recommended Update` (the field `_claim_target` actually reads), and `UpdateRequirements` must use the id the entry names rather than picking `R<next>`. Prompt-only, so it is a strong convention and not a guarantee — the code still degrades to "unattached, logged" rather than guessing. The matcher upgrade (text-overlap against the patch log's applied text) is still open.
4. **A substantive answer still bypasses screening.** Review text that is neither `accept` nor `reject` goes to `RefineFeedback`, which can write a fresh `REQUIREMENT UPDATES` section — and screening runs once, on the draft. That section is applied unscreened. Now much less costly (screening no longer withholds anything, so the only loss is the notice and the attachment), but the asymmetry remains.

### 2c. The claim now steers verification — added 2026-08-04

A claim that nothing acted on was also a claim nothing *checked*. Two cases where verification confirmed a contradiction and no question was ever asked:

- **The failure lands on the old requirement.** R7 is encoded as a fact, so the clash surfaces as a counterexample to R2's assertion. `evaluate_probation` built the failing set from R7's own constructs only, found none, credited R7 clean — and R2 is `ACTIVE`, so it was never in the probation pool. R7 was **promoted** three iterations later with the counterexample still there. Now the failing test also covers the constructs of the IDs the item claims to contradict, while the claim is unsettled.
- **Two provisional items implicated together.** The unique-culprit rule contested neither and the pair sat implicated every iteration forever. A claim now breaks the tie: if exactly one implicated item carries an unsettled claim, it is the one asked about. Two claimants, or none, still holds all — the tie-break needs a unique suspect or it just moves the guess up a level.

The claim decides only where to look; the verdict is still the solver's failure and the decision is still the user's. `_unsettled_claim` returns nothing once acknowledged, so a settled conflict stops steering anything.

## 3. ~~`stalled` is a status nobody acts on~~ — CLOSED 2026-08-04

A stalled item used to get a log line and a `🚧` print. No escalation was built, no question was asked, and it sat blocking convergence with nothing offering a way out — the same dead end a contest used to be, and the only status that could hang a run indefinitely.

It now has a resolution round (`_resolve_requirement_stalls`), asked after the contest and on its own input:

- **`reword`** → `build_unmodelable_requirement_diagnosis` produces the `REQUIREMENTS_DIAGNOSIS` the design always specified, delivered through `semantic_escalation['directive']` — the channel the Evaluator already reads — and the item returns to probation so it does not block convergence while its wording is being fixed. Delivered once, then cleared.
- **`drop`** → a deferred removal on the ordinary `PENDING_REMOVAL` path, reviewable and revertible like every other.
- **`wait`** → streaks reset, another full window (`resume_probation`). A `REMOVE` returns to `pending_removal`, not `provisional`.
- Silence decides nothing; the stall is raised again.

The queue is rebuilt from the store each iteration (`_pending_decisions`, generalised from `_pending_contests`), so a restart cannot strand a stalled item any more than a contested one. The parser is shared too: `parse_directives` takes its vocabulary as a parameter, so contest (`revert`/`keep`) and stall (`reword`/`drop`/`wait`) differ only in words, not in grammar — same per-ID matching, word-boundary handling and negation guard, already tested.

If the stalled item also carries an unsettled contradiction claim, the question says so — a contradiction the modeller cannot encode is a likely cause of the stall, and the diagnosis carries that to the Evaluator.

---

## 4. The contradiction verdict's quality is still unmeasured

`Output/RequirementConflict/shadow.jsonl` exists and has been accumulating since
2026-08-04 (3.4 KB as of today). **Nobody has read it**, and
`scripts/analyze_convention_shadow.py` still has no equivalent for it.

This is now the cheapest unclaimed value on the list: three mechanisms act on an
LLM's judgment — bucket 6 CONTRADICTS, the lesson CONTRADICTORY verdict, and the
convention one added 2026-08-05 — and all three ship on the assumption that the
judgment is good enough. Two of the three have a log written and unread; the
third (`Output/LessonDedup/shadow.jsonl`) is written but empty until a run. The
work is reading, not coding.

This matters much less than it did. Since 2026-08-04 a claim withholds nothing — it produces a notice and an attached record — so a false positive costs the user one line of attention and, at worst, a contest question that cites a conflict which is not real. The user still answers that question on solver evidence, not on the claim.

The two deterministic guards remain: a CONTRADICTS naming no ID, or an ID absent from the document, is downgraded to UNSURE.

Worth reading after the first live run to see whether the Evaluator declares conflicts at all, and whether the ones it declares are the ones verification later implicates. That correlation is the real measure, and it is now cheap to collect.

---

## 5. ~~Convention dedup has never left observe mode~~ — CLOSED 2026-08-05

Conventions now share the lessons' mechanism, and the band they share is no
longer a *merge* band — it is a **classify** band. In `[floor, drop)` the
MemoryAssistant decides before anything is written: SAME/COMPLEMENTARY fold into
one row, CONTRADICTORY keeps both rows and suspends the older, no answer changes
nothing. Previously `_merge_and_update_item` hardcoded `COMPLEMENTARY` for
anything that was not a lesson, so two contradicting conventions were both
injected forever, or fused into one sentence carrying a rule and its own
replacement.

Design points worth not re-deriving:

- **The new item is active immediately**, on merge and on contradiction alike.
  Symmetric quarantine was considered and rejected: an item that is never
  injected can never demonstrate it helped, so nothing could ever settle it.
- **A merge is revertible.** `prior_text` holds the pre-merge wording and
  `restore_merge()` puts it back. Merge used to be a one-way door while
  suspension was reversible — backwards, since merge is the commoner verdict. A
  second merge before the first settles keeps the *original* `prior_text`: the
  intermediate wording never survived probation and is not what a revert owes.
- **Action is confined to the gated (defer/confirm) path.** A merge or conflict
  is staged onto `pending['retractions']` and settled by
  `apply_/revert_convention_retractions`, dispatching on `kind`
  (`retract` | `merge` | `conflict`). No new lifecycle: that list already
  carried convention-only pendings correctly.
- **Nothing is left pending where nothing can settle it** (`store(gated=…)`). On
  the `Build` path a contradiction is logged and both conventions stay active,
  because an item withdrawn while waiting on an outcome nobody will report is
  withdrawn forever. Cost is nil in practice: `Build` wrote 7 conventions in a
  68-iteration run, **all with no prior match** — it fills an empty collection.
- **A self-standing clean-iterations counter was rejected.** Conventions have no
  construct-ownership link (nothing like `TraceabilityStore.constructs_for`), so
  "clean" would degrade to *the run did not get worse*, which passes almost
  always. Probation that always passes is worse than none — it launders a bad
  merge with a veneer of verification.

**The floor is 0.78, not the lessons' 0.7, and it is evidence-based.** From 31
store-path records in `Output/ConventionDedup/shadow.jsonl`: below ~0.78 every
observed pair was the same *topic* under a different *rule* (an eligibility
condition against an encoding style for the same predicate) and must not be
fused; above it every pair was one rule restated or one rule superseding another
— the two cases the classifier exists to separate. Max store-path similarity ever
observed is **0.8747**, so the 0.93 drop band has never fired: the classifier's
quality *is* the mechanism. Do not copy 0.78 to lessons — lessons are scoped per
`{agent, action}` and conventions are model-wide, so the distributions are not
comparable.

Three destructive defaults were reversed at the same time, all of which chose the
newer wording on no evidence: `parse_lesson_merge` returned `COMPLEMENTARY` on an
unparseable reply (now `UNPARSED`, which routes to "keep both"); a failed LLM
call replaced the existing row with the new content (now `UNPARSED` —
`_simple_update_item` is deleted, because replacing is a *decision*); and the
exact-text guard folded case and whitespace but not punctuation, so a trailing
period cost a full semantic comparison to catch at 0.9869.

`scripts/analyze_convention_shadow.py` now excludes the retraction matcher's
lookups from the store-decision statistics — counting them together once put
three punctuation-only lookups in the WOULD DROP column and made the drop band
look exercised when nothing stored had ever come near it — prints the classifier
verdict per pair, and lists the pairs just *below* the floor so the recall cost
of the threshold stays visible.

`convention_mode: "observe"` still exists and still keeps detection and logging
while acting on nothing. That is the fallback if the classifier turns out to be
wrong on a live run.

---

### 5b. A restart strands a convention suspension or a pending merge — found 2026-08-05

The convention lifecycle settles through `pending['retractions']`, which lives on
`pending_re_fix_lesson` / `pending_evaluator_feedback_lesson` — plain attributes
on `SharedRuntimeContext` (`runtime_context.py:103-104`). `save_state()` persists
memory and user preferences only (`:190-199`), so that list does not survive a
restart, and **nothing rebuilds it**: `load_pending_lesson_conflicts` queries the
*lessons* collection, and `_discard_future_lesson_conflicts` is lessons-only.
There is no convention equivalent of either.

So a crash or resume between staging and confirmation leaves the older
convention `pending_withdrawn` forever — never injected again, never superseded —
or a merged row `merge_pending` forever, holding a `prior_text` nothing will ever
restore. This is exactly the failure §6b just bounded for lessons, on the
collection where it costs more, since a convention is binding on the model
builder.

It pre-dates today: the RE's `[CONVENTION_RETRACT]` path stages the same way and
has always been exposed. What changed is the blast radius — the list now carries
every merge and every contradiction, not just an explicit retraction marker.

The fix is the one lessons already have, and both halves of it exist on the row
already: recover from disk by querying the conventions collection for
`status: pending_withdrawn` or `merge_pending: True`, and sweep with the same
bounded wait using `retract_pending_iteration` / `merged_at_iteration` as the
clock. Missing are the query and the sweep, not the data.

---

## 6. The lesson CONTRADICTORY verdict is unvalidated

`Lesson_Conflict_Lifecycle_0802.md`: contradicting lessons suspend
(`active → pending_withdrawn`), the outcome decides, never recency, nothing is
deleted. The lifecycle is implemented and unit-tested.

What is unvalidated is the *verdict* — whether the agent's CONTRADICTORY call is
right often enough to act on. Same gap as bucket 6, and the precedent that
justified shipping bucket 6 in observe mode. Watch for `⚔️ Contradicting lesson`
false positives on the live run.

Now measurable rather than only watchable: `Output/LessonDedup/shadow.jsonl` was
added 2026-08-05 and records, per stored lesson, the top match, which band it
landed in, and **what the classifier said**. The lesson floor (0.7) has never been
calibrated against anything; this is what would calibrate it.

### 6b. ~~The lesson conflict queue can never be settled~~ — CLOSED 2026-08-05

The lifecycle above is correct for a lesson that arrives through the defer/confirm
gate. It is **not reachable** for one that does not, and 8 of the 11 lesson store
sites do not (`requirement_actions.py:53,99,155`,
`evaluation_actions.py:238,275,293,1252` store immediately; only `:254`, `862`
and `1175` defer).

Two defects, one root cause:

1. **`resolve_lesson_conflicts(resolved=True)` is never called in production.**
   Both workflow call sites (`:1058`, `:1111`) pass `resolved=False`. Nothing
   finalizes a suspension when the fix *does* hold, so a conflict raised by an
   unverified lesson sits in `pending_lesson_conflicts` indefinitely with the old
   lesson stuck at `pending_withdrawn` — suspended in practice, never
   `superseded`, and rebuilt from the row on every restart by
   `load_pending_lesson_conflicts`.
2. **`source_iteration` does not identify a lesson.** Conflicts are keyed by the
   iteration passed to `store()`; resolution passes the *probation item's*
   `source_iteration`. For an unverified lesson those coincide only by accident,
   so a conflict is either never settled or settled by an unrelated deferred
   lesson that happened to fail in the same iteration.

The root cause is that an unverified lesson has no outcome of its own to wait
for. §5 answers that for conventions by never suspending where nothing can
settle it (`store(gated=…)`). **Lessons keep the provisional window and bound it
instead**, by explicit decision — the capability is worth keeping, it just must
not be unbounded.

**Fixed, in three parts:**

1. **The wait is bounded.** `expire_stale_lesson_conflicts(current_iteration)`
   runs once per iteration from the workflow, right after the pending-lesson
   loop. Past `lesson_conflict_max_wait` (default **5**) the older lesson is
   restored to active and the pair leaves the queue. It fails toward
   *restoring*, the bias `discard_lesson_conflicts_from` already states: an old
   lesson is never deleted on suspicion. The newer lesson stays active — nothing
   has been shown about either, so both are injected and the contradiction is at
   least visible to the agent rather than settled by silence.
   The default must **exceed the 3-iteration probation window**, or the sweep
   would pre-empt the answer it is waiting for. A suspension with no recorded
   iteration is expired too: every row this lifecycle writes carries
   `retract_pending_iteration`, so a missing one is a pre-lifecycle row, which is
   the likeliest to have sat longest. The clock is on the row, so expiry works
   after a restart the same way the suspension itself does.
2. **Conflicts are keyed by the lesson that raised them.**
   `resolve_lesson_conflicts(lesson_texts=…)` takes precedence over
   `source_iteration`, which is kept only for suspensions recovered from disk
   (those rows carry an iteration and no lesson identity). Both workflow call
   sites now pass `pending['lessons']`. Text, not id, because that is what the
   workflow has in hand and what a CONTRADICTORY row stores verbatim; matching
   ignores case and whitespace.
3. **The positive direction is wired.** `_store_confirmed_lessons` calls
   `resolve_lesson_conflicts(resolved=True, lesson_texts=pending['lessons'])`.
   This had to land *after* part 2 — under the iteration key it would have
   retired an unrelated old lesson on evidence that was never about it.

**Every decision is now recorded with both texts.** `_log_conflict_decision`
writes `suspended | retired_on_verified | finalized | restored | expired` to
`Output/LessonDedup/decisions.jsonl` (and the convention equivalent), each with
the full new item, the full old item, the similarity, and the reason — then
echoes all of it to the console. This is the only path in memory that takes
guidance the run was already following *out* of circulation, and the row itself
keeps just a 120-character excerpt of its accuser in `retract_reason`, so before
this there was no record of which two items were weighed or which way it went.

---

## 7. Question load is uncapped

In one iteration the user can now face: `[CONTEST]` (its own input),
`[CONFLICT]`, `[CLASSIFICATION]`, the requirement decision gate, and the Q&A
round. Nothing caps or orders them beyond the contest going first.

Intended priority, not yet enforced: contested/stalled > conflict >
classification > gate.

The contest question is the newest addition and the most likely to make this
acute, because it is asked on a separate input rather than folded into the
feedback review.

---

## 8. Smaller edges

- **Two staged queues are in-memory only.** `pending_deferred_removals` and
  `pending_requirement_diagnosis` are not derived from the store, unlike the
  contest and stall queues. Losing a staged `drop` is safe (the item is still
  `STALLED`, so it is asked again); losing a staged **diagnosis** is silent —
  `reword` already returned the item to probation, so it simply re-stalls three
  iterations later with no record that the user asked for anything.
- **`reword` can loop.** The item goes back on probation so it does not block
  convergence while its wording is fixed; if the diagnosis produces nothing
  encodable it stalls again at +3. Each pass does re-ask, so it is a slow loop
  rather than a silent one — but nothing counts the passes.
- **The diagnosis is delivered on the semantic path only.** A syntax-error
  iteration skips it and it stays queued, which is correct, but nothing tells
  the user it is being held.
- **`MODIFY-SECTION` is never actually verified.** It counts clean every analyzed
  iteration (a section blob has no ID to trace), so probation for it is pure
  delay — it cannot stall and cannot be contested. Correct given the primitive,
  but it means a section-level rewrite gets a verification badge it did not earn.
- ~~**`protected_ids` uses R-only prefixes**~~ — CLOSED 2026-08-04. Existing-system
  items are now protected by **text** (`existing_system_texts`), not by ID: `E#`
  is positional, so an ID captured at iteration 0 stops denoting the same bullet
  as soon as one is inserted above it. Baseline is the iteration-0 document,
  falling back to the current one. Only ORIGINAL bullets are covered — a bullet
  the run added stays removable, matching how R behaves. **Workflow-authored
  removals (`_perform_staged_removals`) bypass `apply_patch` and therefore bypass
  this protection**; a supersession or a `drop` can still retire an original E.
- **Reverting a `pending_removal` is implemented** (2026-08-04, needed by the
  supersession path) but reachable only via the cascade from reverting the
  update that displaced it — see §2, open item 1.
- **A lesson merge records its original but nothing reverts it.** `prior_text` and
  `restore_merge()` work for both collections, but lessons only reach `store()`
  from `_store_confirmed_lessons` (`verified=True`, after their fix already
  held), so no later signal can trigger the revert. The record is there; the
  probation half applies to conventions on the gated path only. Same root cause
  as §6b.
- **Three stale snapshot files** contain test-fixture data and should be deleted:
  `Output/RequirementPatchLog/patchlog_0730_01PM.log`, `patchlog_0730_06PM.log`,
  `patchlog_0731_05PM.log`.
- **`test/test_prompt_context_hygiene.py`** was proposed for the prompt-clash
  fixes and never written.
- **Dead code** listed in `Documentations/UNUSED_CODE.txt`, plus the unused
  `AnalysisPrinciples` prompt section, are still present.

---

## 9. Nothing is committed

~50 uncommitted paths across probation, traceability, lesson lifecycle, contest
resolution, construct pruning and memory dedup. The suite is **594 passed / 30
failed / 1 error**, where the 30 + 1 are a pre-existing baseline unrelated to this work
(`AutoRELogger.__init__` kwarg drift, QA-parsing drift, an async dedup test with
no asyncio plugin) — they were failing before any of it and fail identically now.

Committing is blocked on nothing but a decision.

---

## Where to pick up (2026-08-06)

In this order, and the reasoning matters more than the order:

1. **§5b — the stranded convention suspension.** The only item here that can
   silently lose a binding rule the model builder was obeying, and the only one
   that today's work made worse. Both halves of the fix already exist on the row;
   what is missing is a recovery query against the conventions collection and a
   bounded sweep, mirroring what §6b just built for lessons. Comparable size.
2. **Commit.** ~50 paths have been uncommitted for weeks across six features. The
   suite is green against its baseline and every mechanism here is now either
   closed or explicitly documented as open — there is no state left that a commit
   would freeze prematurely.
3. **The live run** (§1), from iteration 65, with `//@req R6` added first. Watch
   the table at the top.
4. **Read the three shadow logs** (§4, §6) after that run. Every remaining item
   below this line is a question the run answers better than more unit tests
   will — which is the argument for not building anything else first.

Deliberately NOT next, and why: the `DIAGNOSING` status (§8) is designed and
justified but still unapproved; the claim-matcher upgrade (§2 open item 3) is
prompt-mitigated and may prove unnecessary once the run shows how often the
Evaluator actually names both sides; and the question cap (§7) cannot be tuned
sensibly before anyone has seen how many questions one real iteration produces.
