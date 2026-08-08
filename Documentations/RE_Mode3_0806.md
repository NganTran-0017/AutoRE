# RE Mode 3 — Diagnostic Experiments (plan, 2026-08-06)

All phases (0–5) and TODO items T1–T6 implemented 2026-08-07, unit-tested, **not yet run
live**. Before the first live run, revert `AlloyModel__67.als`'s two diagnostic relaxations
(see Risks) — every probe would otherwise be measured against a corrupted control.
Everything below is evidence from the 080626 run (iterations 65–67).

## Why

A diagnostic iteration is not a repair iteration, but the system has no way to say so.
Four consequences, all measured:

1. **Diagnostics poison the repair ladder.** `collect_failed_fixes`
   (`repair_plateau_detector.py:190`) pulls `fix_intent` from every following entry with
   no filter on kind. Iteration 67's entry — `fix_intent: "Relax credential update flag
   reset timing … per diagnostic feedback"`, `resolved_target_issue: False` — will be
   listed to the Evaluator from iteration 68 on under *"Fixes already attempted (ALL
   FAILED)"*. Mode 2 then forbids re-applying it, **including as the permanent repair the
   experiment was meant to validate**. And `resolved_target_issue: False` feeds
   `SemanticIssueTracker` persistence, so diagnosing carefully makes the ladder climb
   faster toward rewriting requirements.

2. **Temporary relaxations become permanent.** `AlloyModel__67.als` carries two
   `// DIAGNOSTIC RELAXATION` edits from iteration 66. R6.1 says the flag resets in the
   second Normal state; the model now says the first. `AdminEligibleForEmergencyTrigger`
   still carries `//@req R1.4, coR1.1`, so the ownership audit reports it as encoding a
   requirement it stopped encoding. Every iteration since verifies a diagnostic variant.

3. **The instruction set is unroutable.** Iteration 66's `=== REPAIR INSTRUCTIONS ===`
   held **11 numbered items**: three adopted experiments, two meta-rules, then the
   verbatim `_inject_diagnostic_experiments` block restating three of them in different
   words plus one never adopted. The RE applied two mutations at once — violating item 4,
   *"alter only one gating constraint at a time"* — and skipped the rest. Item 5,
   *"Record results of each diagnostic experiment"*, asks for something the RE has no
   place to write.

4. **Experiments are run that cannot discriminate.** `fact EmergencyUnique`
   (`AlloyModel__67.als:126`) forbids a Normal state between two Emergency states, and
   every `Scenario_MultiEmg_*` needs `E→N→N→E`. It is a **fact**, so it constrains any
   probe too — iteration 66's experiments 1 and 2 were both predicate-level and would
   have returned UNSAT whether or not their hypothesis was right. Iteration 67 read that
   as "the approach failed" rather than "the experiment could not answer."

## Principle

A diagnostic iteration's deliverable is **evidence**, not a better model.

- the production model changes only by **addition**;
- each experiment is a named `run` command, so its verdict is independently attributable;
- **nobody records anything** — a probe is a run command, so SAT/UNSAT already lands in
  `VerificationResult.satisfied_predicates`. Express the experiment as something the
  Analyzer answers and the recording problem disappears.

`//@req none:probe` is already defined in both prompt files ("exploratory check;
assertions and run predicates only, never a fact") and used **zero times**.

## Phase 0 — move the injected candidates out of REPAIR INSTRUCTIONS ✅ done

Shipped alone; removes the duplicate-instruction hazard immediately, independent of the
rest.

`_inject_diagnostic_experiments` no longer searches for the REPAIR INSTRUCTIONS header.
It appends one trailing section, `DIAGNOSTIC_CANDIDATES_HEADER` (`workflow.py`, module
level):

```
=== DIAGNOSTIC CANDIDATES (verbatim from InterpretResults - NOT adopted) ===
```

The safety net keeps its guarantee — nothing is lost when the Evaluator drops the
experiments, which was the reason it exists — but the RE stops reading unadopted
suggestions as work orders. Since Phase 0 ships without prompt changes, the block itself
carries the instruction ("Reference material, not a work order … Do NOT apply them as
model edits"), and no line inside it may start with `===` or `_extract_section` would cut
the block in half. Injection is now idempotent, and placement no longer depends on
REPAIR INSTRUCTIONS existing at all — the old special-case fallback is gone.

Tests: `test/test_diagnostic_candidates.py` (7). Suite 617 passed / 30 failed + 1 error
(unchanged pre-existing baseline).

## Phase 1 — the decision is the signal ✅ done

Presence of the injected text cannot select the mode: it is raw *candidates*, not a
decision (at iteration 66 the Evaluator adopted 3 of 6 Steps; the injection re-added all
6), and it fires whenever there are UNSAT predicates.

- Sixth `NEXT ACTION DECISION` value: **`run diagnostic experiments`**.
- Required `=== DIAGNOSTIC PLAN ===` when chosen. Per item: construct, hypothesis,
  **level** (`predicate` | `fact` | `scope`), and the reading, declared before the run
  (`SAT ⇒ confirmed`) so it cannot become post-hoc.
- Mode 3 triggers on that decision **plus** a non-empty surviving plan, parsed the same
  deterministic way the decision already is.

This also forces the Evaluator to choose. Iteration 66 emitted repair instructions and
experiments together, so neither the RE nor the ladder knew which iteration it was in.
The DECISION POLICY now says an iteration is *either* a repair *or* a measurement, and
the response format tells it to write REPAIR INSTRUCTIONS as "None" when it measures.

**As built.** Parsers live in `repair_plateau_detector.py` beside the other deterministic
feedback readers: `parse_next_action_decision` (normalizes the `Decision:` line against
`NEXT_ACTION_DECISIONS`; returns None on an echoed template, an unfilled placeholder, or
any wording outside the enum), `parse_diagnostic_plan` (returns `items` + `dropped`,
each drop carrying a reason — a missing reading is a drop, since a reading settled after
the result measures nothing), and `should_run_diagnostic_iteration` (both conditions, else
Mode 2). `workflow._evaluate_diagnostic_signal` computes it at the mode-selection site and
stores it on `context.diagnostic_signal` (Phase 3 turns that into `mode = "diagnostic"`).

Two things Phase 1 surfaced that were not in the original plan:

- `RefineFeedback` does not carry `ResponseFormatFeedback` — it only asks the model to
  keep the draft's structure. Since the signal is read from the *final* feedback, the
  decision and the plan needed an explicit preservation rule there (objective 7), phrased
  like objective 5: the user's review may override the choice, nothing else may.
- Prompt cost: **+~395 tokens** on the GenerateSemanticFeedback template, against the
  −888 the earlier condensation removed. Still net negative, but Mode 3 is not free.

Tests: `test/test_diagnostic_decision.py` (17). Suite 634 passed / 30 failed + 1 error
(unchanged pre-existing baseline).

## Phase 2 — guard-rail the plan in code ✅ done

Deterministic downgrade, same pattern as CONTRADICTS-with-an-unknown-ID. The Evaluator
judges *whether* to diagnose; code decides *what survives*.

| plan item | action | why |
|---|---|---|
| level `fact` | **drop** | the localizer already tests it by disabling facts — this is what catches `EmergencyUnique` |
| level `scope` | **drop** when `scope_sweep.performed` | already measured; at it.67 `sat_at_larger_scope: False` |
| names a construct absent from the model | drop | untestable as written |
| plan empty after filtering | **not a diagnostic iteration** — fall back to Mode 2 | |

Log every drop. Never silent.

**As built.** `filter_diagnostic_plan(items, model_text, diagnostics)` in
`repair_plateau_detector.py`, applied inside `should_run_diagnostic_iteration` between
parsing and the Mode-2 fallback. Evidence comes from the previous iteration — the model
the probes would run on, and `repair_escalation['diagnostics']` off that iteration's
regression entry — because that is the state the plan was written about. **With neither,
nothing is dropped:** absent evidence must not discard a plan.

Two deliberate weakenings of the table:

- A `scope` item survives when the sweep never touched that construct. A larger-scope
  probe is a *new* `run` command, so it stays additive and is still worth running; only a
  question already answered is refused.
- "Absent from the model" is the weakest test that is still true — declared block
  (`fact`/`pred`/`assert`/`fun`/`sig`) or any whole-word occurrence. A false drop turns a
  measurement into a repair silently, which is worse than letting through a name that
  appears only in a comment: that probe simply never reports, and T1's manifest calls it
  `not run`.

**Dropped items report back with what was already measured.** A drop is not a refusal —
the Evaluator asked a question that code declined to re-ask *because the answer exists*,
so `build_diagnostic_status_block` renders each dropped item with the deterministic
verdict beside it:

```
=== DIAGNOSTIC ITEMS NOT RUN (already measured) ===
- Construct: EmergencyUnique
  Not run: fact-level hypothesis: the deterministic localizer already tests facts by
           disabling them, and a fact constrains the probe too
  Measured: deterministic localizer: proven to block Scenario_MultiEmg_A
```

It rides on the signal as `status_block`; Phase 3 delivers it with the Mode 3 section and
requires the RE to echo it under `DIAGNOSTIC EXECUTION` (`Executed: no` + the reason), so
the status reaches the Evaluator through the regression entry rather than vanishing. A
drop with *no* measurement says so in those words — "untestable as written, not as
already answered" — because the two lead to opposite next steps.

### Known failure modes

- **A dropped item is a question the Evaluator will ask again.** Nothing tells it that
  fact-level hypotheses are answered elsewhere except one DECISION POLICY line. *Example:*
  it proposes `Level: fact` on `EmergencyUnique` at iteration 68, code drops it, the plan
  empties, the iteration silently becomes Mode 2 — and at 69 it proposes the same thing.
  The status block is the intended escape (the localizer verdict comes back as evidence),
  but only once Phase 3 delivers it; until then the loop is possible.
- **Stale diagnostics.** The sweep verdict is from iteration *N*−1. If the RE changed the
  scope in between, `scope_sweep.performed` still drops a `scope` item whose answer is now
  out of date. *Example:* the sweep runs at `for 12` and returns UNSAT; the RE then narrows
  a predicate so the scenario needs only 8 states; a fresh scope question at 8 is refused
  on 12's evidence.
- **Whole-word existence over-admits.** A construct named only in a comment
  (`// removed EmergencyUnique`) passes the existence test. It costs one probe that never
  reports; T1 must classify it `not run` rather than reading the absence as UNSAT.
- **`sig` detection is regex-based** (`one sig`, `abstract sig`, plain `sig`).
  `extract_all_blocks` covers only fact/pred/assert/fun, so an unusual signature
  declaration falls through to the whole-word test — over-admitting, never over-dropping.

## Phase 3 — `UpdateAlloyModel_Mode3_Diagnostic` ✅ done

Third sibling to `Mode1_SyntaxRepair` / `Mode2_SemanticRepair`; the mode mechanism
already exists, so no new machinery.

Rules: additive probes only; **never mutate a construct carrying `//@req R#`/`E#`**; one
hypothesis per probe; probes marked `//@req none:probe`; a probe is reachable only from
its own `run` and never appears in `All_Requirements` or an R-chain; report which numbered
instructions were executed and which were not, with a one-line reason.

Two of iteration 66's instructions become properties of the form rather than advice:
"alter only one gating constraint at a time" (separate predicates under separate `run`
commands cannot interact) and "record results" (the Analyzer records).

Honest cost: Alloy cannot parameterise over predicates, so a probe duplicates the scenario
body. Duplication drifts — which is why probes live exactly one iteration.

**As built.** `mode = "diagnostic"` is now set at the mode-selection site when the signal
fires, and `_build_prompt` appends `UpdateAlloyModel_Mode3_Diagnostic` — *instead of* Mode
2, never alongside it. That exclusivity is load-bearing: Mode 2 explicitly permits
"Revise, add, or remove facts" and "Relax overconstraints causing unsat predicates", which
is exactly what Mode 3 forbids, so shipping both would leave the RE to pick.

The forbidden list is stated in terms of what turns a measurement into an undeclared
repair — no modification of *any* existing construct (not scopes, not run commands), no
deletion, no fixing the failing scenario even when the cause becomes obvious while writing
the probe. Probes are named `probe<N>_<Target>` so Phase 5 can find their verdicts by
prefix.

`DIAGNOSTIC EXECUTION` **replaces** `FIX INTENT` rather than joining it —
`swap_fix_intent_for_diagnostic_execution` splices the block into the shared response
format between the `FIX INTENT` and `SOURCE REFERENCE` markers, and appends if the markers
drift so the field is never silently lost. Asking for both would ship two contradicting
instructions ("state what you are fixing" / "this iteration fixes nothing"), the same
mistake `select_binding_rules` exists to prevent.

Phase 2's `status_block` is delivered on the escalation directive, and the rulebook tells
the RE to copy each entry into its report as `Executed: no` with the measured reason.

**T3's parser half is done too:** `parse_re_response_for_regression` extracts
`DIAGNOSTIC EXECUTION`, returns it as its own field, and fills `fix_intent` with
`DIAGNOSTIC EXECUTION: <report collapsed to one line>` when no `FIX INTENT` was written.
Blank was the real risk — `fix_intent` renders in the failed-fix history, the Evaluator's
regression view and the similarity clustering, so an empty value erases the iteration from
all three. An explicitly written `FIX INTENT` still wins, and the raw report is kept
either way.

### Known failure modes

- **"Don't fix it" is the hardest instruction to follow.** The RE writes a probe that
  makes the scenario SAT, which is a working fix sitting one line away. *Example:*
  `probe1_ScenarioMultiEmgA` relaxes the flag-reset guard and returns SAT; the tempting
  next step is to apply the same relaxation to `CredentialUpdatePerfomedSeq` in the same
  response — and then the iteration is a repair nobody approved, the control is gone, and
  Phase 5 measures a model that already contains the change it was testing. Nothing in
  code enforces additive-only yet; a diff check (no existing block's text changed) is the
  obvious guard and is not built.
- **Probe drift.** A probe duplicates the scenario body. If the RE paraphrases instead of
  copying, the probe and the scenario differ in more than the hypothesised constraint, and
  the verdict answers a question nobody asked. *Example:* the scenario needs `E→N→N→E`, the
  probe writes `E→N→E`; UNSAT then proves nothing about the flag reset. One-iteration
  retirement bounds the damage; it does not detect it.
- **The swap depends on two literal markers.** If `ResponseFormatUpdateAlloyModel` is
  reworded so `=== FIX INTENT ===` or `=== SOURCE REFERENCE ===` moves, the block is
  appended instead of substituted and the RE sees both fields — back to two rulebooks. The
  degradation is deliberate (losing the field would be worse) but silent; the test pins the
  markers.
- ~~**A Mode 3 iteration still reaches the analyzer as an ordinary one.**~~ Closed by
  Phase 4 and T2.

## Phase 4 — mark the entry, un-poison the ladder ✅ done

The change that matters most; the prompt alone does not fix consequence 1.

`RegressionLogEntry.kind = "diagnostic"`, and then:

- `collect_failed_fixes` skips it — an experiment is not an attempted fix;
- `SemanticIssueTracker` does not count it toward persistence;
- `resolved_target_issue` records `n/a`, not `False`.

**As built.** `kind` (default `"repair"`) plus `diagnostic_execution` and
`diagnostic_plan` on the entry, all three serialized with a `"repair"` default so entries
written before Mode 3 load unchanged. The workflow sets `kind` from the mode it just ran.

- `collect_failed_fixes` skips a `kind == "diagnostic"` follower.
- `SemanticIssueTracker` skips it **twice**: the current iteration returns no issues when
  it is diagnostic, and a diagnostic entry inside the window is not counted as measurable —
  so a diagnostic detour neither advances a streak nor resets one. It is the same treatment
  a syntax-broken iteration gets, for the same reason: no repair was attempted, so there is
  no evidence either way.
- `resolved_target_issue` stays `None` rather than literally `"n/a"` — the field is
  `Optional[bool]` and `None` already means "no answer"; every consumer tests `is True` /
  `is False`, so nothing reads it as failure. What the doc asked for (never `False`) holds;
  the string would have violated the type. The *rendered* form says so explicitly, via a
  new `diagnostic_measurement:` outcome classification and an `Iteration kind: DIAGNOSTIC`
  line in both history views — otherwise the entry fell through to `unclassified`, which
  reads as a failure to classify rather than as nothing to classify.

**T2 (probes leave the UNSAT population) shipped with it.** `is_probe_name` lives in
`semantic_diagnostics.py` — the naming convention is the contract, so it belongs with the
construct helpers, not with the escalation logic. Two exclusions:

- `alloy_executor`'s `positive_run_commands` / `satisfied_positive_runs` skip probes, so a
  probe's UNSAT cannot hold convergence open. This is code, not prompt, because it is a
  hard metric.
- `SemanticIssueTracker` drops probe names from the tracked issues.

Probes are deliberately **not** stripped from `satisfied_predicates` /
`unsatisfied_predicates`: Phase 5's readback reads them from there.

## Phase 5 — readback and retirement ✅ done

- **Readback**: filter `satisfied_predicates` / `unsatisfied_predicates` by the
  `probe<N>_` prefix, join against the declared hypotheses, append the verdict table to
  the escalation directive as *measured* evidence alongside `blocking_facts`. Pure code.
  Readings: E1 SAT + E2 UNSAT → flag-reset timing is the blocker; both UNSAT → **both
  encodings exonerated**, which is itself a requirement-level signal; both SAT → each
  independently sufficient, ask the user which matches intent.
- **Retirement**: a probe that has reported is deleted the next iteration via the existing
  `ConstructRemovalLog` / `REMOVE_STALE_CONSTRUCTS` path. No probe survives more than one
  iteration.

**As built.** `read_back_probe_verdicts(plan, satisfied, unsatisfied)` matches probe *i+1*
to plan item *i* and returns three statuses — `confirmed` / `refuted` / **`not_run`** —
which is T1's manifest rule. `build_probe_verdict_block` renders construct, hypothesis,
declared reading, probe and verdict, and states "all refuted" only when every item actually
ran.

**Delivery is through the regression log, not the escalation directive.** The plan said
directive; the directive only exists when persistence escalated, and Phase 4 just stopped
diagnostic iterations from advancing persistence — so on the very iteration the verdicts
matter, there may be no directive to attach them to. The entry always exists and is always
rendered into `{{regression_log}}`, which `InterpretResults` already receives, so
`format_probe_verdicts` renders the table there. That also satisfies **T4's** "carry the
experiment context" half with no new prompt slot.

**T4's other half** is an `InterpretResults` block: a probe's UNSAT is a completed
experiment, never a defect and never a repair target; read each verdict against its
declared reading; `NOT RUN` is unanswered, not refuted; all-refuted-and-all-ran is a
requirement-level finding; and the probes' disappearance next iteration is not a regression.

**Retirement** stages the spent probes on `pending_stale_removal`, the existing
`REMOVE_STALE_CONSTRUCTS` channel, so step 8 prunes them deterministically and the
`ConstructRemovalLog` records the deletion as workflow-authored — otherwise a later
diagnosis would read it as the RE dropping a construct.

### Known failure modes

- **Positional matching.** Item *i* owns `probe<i+1>_*`. If the RE numbers probes by its
  own order — writing `probe1_` for the item it found easiest — every verdict is attributed
  to the wrong hypothesis, and the readback reports confidently wrong results rather than
  failing. *Example:* the plan lists `CredentialUpdatePerfomedSeq` then
  `AdminEligibleForEmergencyTrigger`; the RE probes eligibility first and calls it
  `probe1_`; the block then reports "flag reset timing CONFIRMED" from an experiment about
  eligibility. Matching on the construct name in the probe suffix would be more robust and
  is not built.
- **A missing entry loses the manifest.** `diagnostic_plan` is read off
  `context.diagnostic_signal` and persisted by `add_entry`'s `_save_to_file`, so an
  ordinary resume keeps it. The window is a crash between `save_alloy_model` and
  `add_entry`: the probes are on disk, the entry is not. Step 4 then builds a placeholder
  (`kind="repair"`, no manifest), so `format_probe_verdicts` returns "" and the probe
  verdicts reach `InterpretResults` as bare names with no hypothesis and no declared
  reading — and retirement never fires, so the probes survive into the next iteration.
  Silent in both directions.
- **Retirement is unconditional on reporting.** Probes are retired the iteration after they
  appear, whether or not they produced verdicts. A probe that failed to compile is deleted
  before it ever measures anything — the plan item ends as `not_run`, which T1's re-issue
  now asks for once more, but the deleted probe itself is not preserved for inspection.
- **`is_probe_name` is a naming convention, not an annotation check.** A construct the RE
  names `probe1_X` without `//@req none:probe` is still treated as a probe everywhere —
  excluded from convergence, from persistence, and retired next iteration. A requirement
  encoding that happens to match the pattern would silently stop counting.

## TODO — gaps found while building phases 0–1

Each item names the phase it lands in. None is optional: T1–T4 are ways a
diagnostic iteration can produce a *wrong* conclusion rather than merely a wasted one.
T1–T6 are all done.

**T1 — treat the parsed plan as a manifest ✅ done (Phase 5).** Nothing today compares what the
RE returned against what was planned; the plan is parsed, stored on
`context.diagnostic_signal`, and read by nobody. A skipped experiment is therefore
invisible — the same hole that let iteration 67 skip instruction 3 and experiments 4–5
unnoticed. Under Mode 3 it is worse than under Mode 2, because the readback joins probe
verdicts *by prefix*: a probe never written produces no row, and no row is
indistinguishable from "not measured". The plan's own reading — *both UNSAT ⇒ both
encodings exonerated, a requirement-level signal* — can then fire on one probe.
Required: persist the plan, and classify every item three ways at readback —
`confirmed` / `refuted` / **`not run`**. A `not run` item contributes to no reading and
is re-issued exactly once through the escalation channel (the quote-the-previous-directive
rule `ENCODE_PROVISIONAL` already uses).

**Re-issue, as built.** `_stage_diagnostic_reissue` runs at readback beside retirement and
counts attempts per construct. First miss → `build_diagnostic_reissue` stages a
`RERUN_DIAGNOSTIC_PROBES` directive quoting the item's own hypothesis and declared reading;
second miss → **abandoned**, named in the directive under "NOT RETRIED … neither confirmed
nor refuted" so its silence is on the record rather than looking like it was never planned.
Two failures to express the same hypothesis say something about the hypothesis, not about
the RE's diligence, so `REISSUE_LIMIT = 2` is the whole loop bound.

Three decisions worth keeping:

- **A fresh decision outranks an outstanding retry.** The retry is merged into the next
  plan only while the Evaluator is *still* diagnosing; the moment it decides anything else,
  the retry is dropped and logged. A retry that survived a change of direction would
  reappear indefinitely.
- **Merged, not just delivered.** The re-issued item is appended *after* the new plan's
  items, so the manifest keeps probe numbering stable, and it is skipped if the Evaluator
  already re-planned it (no duplicate probe for one hypothesis).
- **Numbering had to be stated.** The retry arrives on the escalation directive, not in the
  `DIAGNOSTIC PLAN` section the RE is told to work from — so both the directive and the
  Mode 3 rulebook say it belongs to this iteration's plan and continues its numbering.
  Without that the RE would number it `probe1_` and every verdict would be attributed to
  the wrong hypothesis.

Tests: `test/test_diagnostic_reissue.py` (11).

**T2 — probes must leave the UNSAT population ✅ done (Phase 4, code not prompt).** A probe is a
`run` command, so its verdict lands in `satisfied_predicates` / `unsatisfied_predicates`
(`workflow.py:4455-4459`, no name filter). Three consumers then read a deliberate UNSAT as
a defect:
- `InterpretUNSATPred` diagnoses it as "modeling error, overconstraint, missing
  assumption, insufficient scope, requirement conflict…" and recommends repairing the
  probe;
- `SemanticIssueTracker` (`semantic_issue_tracker.py:106`) opens a persistence counter on
  it, which climbs the escalation ladder — Phase 4 covers the regression-log entry, not
  this;
- convergence hard metric 3 plus "any UNSAT predicate forces FALSE" means one probe
  blocks convergence.
Exclusion goes in code, keyed on the `probe<N>_` prefix / `//@req none:probe` — a hard
metric cannot be guarded by a prompt rule. The interpretation half is T4.

**T3 — `DIAGNOSTIC EXECUTION` replaces `FIX INTENT` in the RE's Mode 3 response ✅ done.** Both modes currently receive the same `ResponseFormatUpdateAlloyModel`
(`requirement_actions.py:479`), whose fields are repair-shaped. Not a second format — an
addendum the Mode 3 section carries, so the return-the-whole-model rules stay in one place.

```
=== DIAGNOSTIC EXECUTION ===
- Experiment: [the plan item, restated: construct + hypothesis + declared reading]
- Probe: [probe1_ScenarioMultiEmgA, or "none"]
- Executed: [yes / no]
- Reason: [one line, required when Executed is no]
```

- **`FIX INTENT` is replaced, not reworded.** A diagnostic iteration intends no fix, and
  the field feeds `RegressionLogEntry.fix_intent` — the exact value that poisons
  `collect_failed_fixes` (consequence 1). Emitting a fix-shaped sentence there is what
  created the problem at iteration 67.
- **The report restates the plan from the immediately preceding iteration**, one entry per
  planned item, so it is self-contained: readable without fetching feedback *N*−1, and
  checkable item-by-item against the plan T1 persisted.
- **Items the Phase 2 guard rails dropped are reported too**, as `Executed: no` with the
  drop reason and the measured verdict from `status_block` (already built —
  `build_diagnostic_status_block`). Without this the Evaluator sees its `fact`-level
  hypothesis simply not come back and re-proposes it next iteration; with it, the answer
  the deterministic localizer already had reaches the Evaluator as the experiment's result.
  The Mode 3 section delivers the block and requires it echoed verbatim.
- `EXPECTED IMPACT` stays and becomes mandatory in Mode 3 — `unsatToSat: probe1_…` *is*
  the declared reading, pre-registered. It was empty on both iterations 66 and 67.
- **`fix_intent` is never left blank — it carries the execution report.** On a Mode 3
  iteration the field records

  ```
  DIAGNOSTIC EXECUTION: <experiment items>
  ```

  one item per planned experiment (construct, probe name, executed yes/no, reason when
  not). The field is the entry's human- and prompt-facing summary, so a blank would erase
  the iteration from every view built on it; the `DIAGNOSTIC EXECUTION:` prefix is what
  marks it as a measurement rather than an attempted fix, and pairs with
  `RegressionLogEntry.kind = "diagnostic"` (Phase 4) — the prefix reads, the `kind` filters.
- Parser work, not just prompt: `parse_re_response_for_regression`
  (`regression_log.py:2138-2168`) returns `fix_intent: ""` when the section is absent, and
  `workflow.py:4323`'s default does not fire on an empty string — so without this the entry
  ships blank. It must parse `=== DIAGNOSTIC EXECUTION ===` and write the prefixed summary
  into `fix_intent`; the three `Fix Intent:` renderers (`regression_log.py:487`, `:721`,
  `:1937`) then print the execution report unchanged, with no per-renderer special case.
- The report is evidence *about* the RE, never the measurement itself: a claim that an
  experiment ran with no matching `run` in the model is itself a signal, so T1 verifies
  against the model and the analyzer results, never against the report.

**T4 — `InterpretResults` must read a diagnostic iteration as a measurement ✅ done (Phase 4/5).**
Today it would classify iteration *N*+1 by `OUTCOME CLASSIFICATION` (`expected_improvement`
/ `unintended_regression` / `spec_clarification`) and by `ROOT CAUSE CATEGORIES`, against a
regression entry whose intent reads like a fix. A probe that is UNSAT *because the
hypothesis was wrong* is a successful experiment; interpreted as a repair it becomes a
failed fix, and the Evaluator proposes another fix for it — the loop this whole mode
exists to break.

Two halves:

- **Suppress the repair reading.** A diagnostic iteration is neither an improvement nor a
  regression: it has no `resolved_target_issue` and no intended impact beyond the probes.
  Say so explicitly — do not classify a probe verdict as a regression, do not open a root
  cause on it, do not write repair instructions against a probe. The next step is decided
  by the *declared reading*, not by SAT/UNSAT alone.
- **Carry the experiment context.** The verdicts are meaningless without the hypothesis and
  the reading that were declared before the run. The delivery vehicle already exists and
  needs no new prompt slot: T3's `DIAGNOSTIC EXECUTION` is stored on the regression entry
  and rendered into `{{regression_log}}`, which `InterpretResults` already receives
  (`Evaluator_prompt.txt:207`). Pair each verdict with its hypothesis and reading there, and
  add the three-way status from T1 — a `not run` item must be visibly unmeasured, never read
  as UNSAT.

Then the Evaluator's next-step feedback follows the reading it committed to: confirmed →
the repair that experiment validated (and Phase 4 is what keeps that repair legal);
refuted → the construct is exonerated, look elsewhere; all refuted → the encodings are
sound and the defect is requirement-level, which is a `REQUIREMENTS_DIAGNOSIS` signal;
`not run` → re-issue once, conclude nothing.

**T5 — make the signal survive `RefineFeedback` deterministically ✅ done.**
Objective 7 was an instruction, not a guarantee: `RefineFeedback` rewrites the whole blob
and does not carry `ResponseFormatFeedback`, and objective 2 ("maintain the structure")
was already too weak to be trusted — that is why `_inject_diagnostic_experiments` re-runs
after the refine. `preserve_diagnostic_signal(draft, refined)` now runs in the same place,
immediately after it, and the distinction it draws is the whole point:

| refined decision | action |
|---|---|
| any other recognized decision | **overridden** — the user's review may say "stop experimenting, just fix it"; left alone |
| diagnostic, plan present | intact |
| diagnostic, plan missing | restore the plan (before REPAIR INSTRUCTIONS, where the schema puts it) |
| unparseable / absent | restore the decision line and the plan |

A decision that **changed** is the user's; one that **vanished** is a rewrite artefact.
Only the second is repaired.

*Known failure mode:* the rule reads an override off the decision line alone. If the user
writes "just fix it" in the review and the refine keeps `Decision: run diagnostic
experiments` while replacing the plan with repair instructions, the plan is restored on
top — the iteration then carries both, the state Phase 1 exists to prevent. The user's
review text is not consulted, deliberately: classifying free text is exactly the judgement
this module refuses to make.

**T6 — a missing entry loses the manifest ✅ done.** `diagnostic_plan` is read off
`context.diagnostic_signal` and persisted by `add_entry`'s `_save_to_file`, so an ordinary
resume keeps it. The window is a crash between `save_alloy_model` and `add_entry` in
step 8: the probes are on disk, the entry is not.

*Example.* Iteration 68 runs Mode 3; the RE returns a model containing
`probe1_ScenarioMultiEmgA` and `probe2_ScenarioMultiEmgA`; `AlloyModel__68.als` is written;
the process dies before `add_entry`. On resume, step 4 finds no entry for 68 and builds a
placeholder (`kind="repair"`, `diagnostic_plan=None`). The analyzer reports probe 1 SAT and
probe 2 UNSAT. `format_probe_verdicts` returns `""`, so `InterpretResults` sees two probe
names with no hypothesis and no declared reading — SAT and UNSAT that mean nothing. And
because the entry says `repair`, retirement never fires, so both probes survive into
iteration 69 and start drifting from the scenario they duplicate. T2 still holds throughout
(probes are excluded by *name*, not by entry kind), so convergence and persistence are
unaffected — only the measurement is lost, and nothing says so.

**As built.** `_recover_diagnostic_placeholder` runs before the placeholder is added in
step 4. The plan is genuinely unrecoverable, but the probe *names* are still in the model,
so the loss is detectable: the entry is marked `kind="diagnostic"` — which restores
retirement and keeps the iteration off the repair ladder — and `diagnostic_execution`
records `MANIFEST LOST … their verdicts must not be read as evidence either way`. The
alternative fix (write the entry before the model file) would shrink the window rather than
handle it, and reorders a step-8 sequence several other things depend on.

## Files

| file | change |
|---|---|
| `src/workflow.py` | Phase 0 injection target; Mode 3 routing; Phase 2 guard rails; Phase 5 readback + retirement |
| `src/utils/regression_log.py` | `kind` field (Phase 4) |
| `src/utils/repair_plateau_detector.py` | `collect_failed_fixes` skips diagnostics; probe-verdict block builder |
| `src/utils/semantic_issue_tracker.py` | diagnostic iterations do not advance persistence |
| `prompts/Evaluator_prompt.txt` | sixth decision value; `DIAGNOSTIC PLAN` schema in `ResponseFormatFeedback`; write experiments as probes, never as edits to annotated constructs |
| `prompts/RE_prompt.txt` | `UpdateAlloyModel_Mode3_Diagnostic` |

## Verification

- **Unit**: a `fact`-level plan item is dropped and logged; a `scope` item is dropped when
  the sweep ran; an empty filtered plan falls back to Mode 2; a diagnostic entry never
  appears in `collect_failed_fixes` and never advances persistence; probe verdicts parse
  out of `satisfied_predicates` by prefix.
- **Prompt**: the sixth decision value and the `DIAGNOSTIC PLAN` schema render (string
  assertions only, as `test_requirement_change_triage.py` already does).
- **E2E**: replay iteration 66 → the `EmergencyUnique` fact-level hypothesis is dropped
  before reaching the RE, and the surviving predicate-level probes leave
  `CredentialUpdatePerfomedSeq` and `AdminEligibleForEmergencyTrigger` byte-identical.

## Risks

- **Iteration cost.** A diagnostic iteration produces no repair by design. Phase 4 stops
  it counting as a failed one, but it still costs a turn.
- **Probe pollution.** A probe that escapes retirement lands in future runs. Phase 5's
  one-iteration rule plus the never-in-`All_Requirements` invariant are the whole defence.
- **Evaluator judgment.** Choosing to diagnose is a model decision, like the other five.
  Phase 2 bounds the damage; it does not eliminate a wasted iteration.
- **Pre-existing debt.** `AlloyModel__67.als` still carries iteration 66's two
  relaxations. **Revert them before any Mode 3 run** — otherwise every probe is measured
  against a corrupted control.

## Questions:
1/ what happens when the RE misses 1 step in the diagnostis experiment? Ans: no check is performed to make sure the RE performs all steps in the diagnostic experiment. For now, prompt the RE to report which items in the Diagnostic Experiments were executed. Potential solution: perform checks against the model and the analyzer results, not the RE's report. 
  
2/ Do we need to update the instruction to the Evaluator when interpreting the results that is based on the RE's diagnostic experiment?  This is different from evaluating the results of a repair solution. Ans: TODO* Yes, we need to update the Evaluator's way of InterpretResults when receiving Diagnostic Experiment result so it doesn't classify it as failed fix and propose another fix for this. Be sure to include the context of the Diagnostic Experiment that leads to these results. 

3/ Did we provide an instruction for the RE to format the response after conducting the diagnostic experiment? Should it be different from repairing based on Semantic Feedback? Ans: TODO* Treat this as the experiment report and cross-check it with the model for the matching run statements. 
