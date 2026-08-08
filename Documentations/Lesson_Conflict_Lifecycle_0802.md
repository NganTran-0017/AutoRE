
# Contradicting Lessons: Suspend, Then Let the Outcome Decide

## Problem

Lesson storage banded on cosine similarity alone: `≥ 0.91` drop the new one,
`0.7–0.91` merge, `< 0.7` store as new. **Similarity is not agreement.** "Model
duration with a State signature, not a time index" and "model duration with a
time index rather than a State signature" are near-identical texts that cannot
both be followed — so a contradiction landed squarely in the *merge* band, and
`MergeLessons` ("combine these lessons into ONE brief sentence") folded it into a
single sentence that silently picked a side. That sentence was then re-injected
every iteration, with no way for the agent to tell it had been handed a
reconciliation rather than a rule.

Conventions already had a policy for this — `MergeConventions` keeps both halves
(`"; also: "`) and `[CONVENTION_RETRACT]` drives a probationary withdrawal.
Lessons had neither.

## The constraint

Neither simple answer is available:

- **Recency cannot decide.** A new lesson may be unverified — it came out of a
  fix that has not been shown to work.
- **Deletion cannot decide.** An old lesson may still be right; the new one may
  be the wrong turn.

So the **run's outcome** adjudicates, and nothing is deleted while it does.

## Mechanism

### 1. Detect, at store time

`MergeLessons` now classifies before merging:

| Verdict | Meaning | Action |
|---|---|---|
| `SAME` | one rephrases or narrows the other | merge as before |
| `COMPLEMENTARY` | different details, all followable at once | merge as before |
| `CONTRADICTORY` | following one violates the other | **do not merge** |

Judged by *can both be obeyed*, not by how differently they are worded. This
costs no extra LLM call — the merge band already invoked the MemoryAssistant.

Detection is at store time rather than agent-declared (no `[LESSON_RETRACT]`
marker). An agent that had noticed the contradiction would not have written it;
automatic detection also covers every agent at once.

### 2. Suspend, never delete

On `CONTRADICTORY` both rows survive. The older is set `status:
pending_withdrawn` with `superseded_by` pointing at the newer — it stops being
injected immediately but is not judged wrong, only set aside while the lesson
that contradicts it is on trial. The newer is stored as its own row.

### 3. Resolve by outcome

`store(verified=True)` is passed from exactly one place —
`_store_confirmed_lessons`, which runs only after a lesson's target issue stayed
resolved for the required clean iterations. That is what entitles a lesson to
retire another:

| New lesson | Outcome | Result |
|---|---|---|
| verified (passed probation) | — | old → `superseded` immediately |
| unverified | fix held | old → `superseded` |
| unverified | fix did not hold | old → `active`, **new → `superseded`** |

`resolve_lesson_conflicts(resolved=...)` is wired into both existing discard
paths, alongside the `revert_convention_retractions` calls it mirrors. Superseded
rows stay on disk for audit.

## Two things that are easy to break

1. **Suppressed rows are filtered in Python, not in the Chroma `where` clause.**
   A metadata predicate does not match rows lacking the key, and every lesson
   written before the `status` field existed has none — a `where` filter would
   have blacklisted the entire pre-existing lesson store. **Absence of `status`
   must read as active.** Applies to both `get_lessons` and `retrieve_similar`.
2. **`parse_lesson_merge` defaults to `COMPLEMENTARY`** on a reply with no
   verdict line. A parse miss degrades to the old merge-everything behaviour
   rather than suspending a lesson on no evidence.

## Known gaps

1. **Verdict quality is unvalidated.** Whether `CONTRADICTORY` fires correctly —
   and more importantly whether it *over*-fires — is an LLM-behaviour question no
   unit test answers. A false positive suspends a good lesson. Watch for
   `⚔️ Contradicting lesson` in a live run.
2. **A short resume cannot exercise the full path.** Suspensions resolve through
   the probation gate, which needs 3 consecutive clean iterations; a short run
   leaves entries sitting in `pending_lesson_conflicts`.
3. **Events are write-only.** `record_event` stores to a collection that
   `get_events` never reads from anywhere in `src/`, so events can neither
   conflict nor help.
4. **The Evaluator still cannot retract anything explicitly** —
   `[CONVENTION_RETRACT]` exists only in the RE prompt.

## Surviving a restart

The suspension is persisted (on the row); the *list* of pending conflicts is
derived. `load_pending_lesson_conflicts()` rebuilds it in `__init__` by querying
`status == "pending_withdrawn"` — no side file, since `superseded_by` and
`retract_pending_iteration` already carry everything the resolver reads.

Note the asymmetry with the read-path filter: there, absence of `status` must
read as *active*, so filtering happens in Python. Here requiring the key is
correct — only a row written by this lifecycle can be `pending_withdrawn`.

Without this, an interrupted run left the old lesson withdrawn with nothing left
to restore it. The failure was **biased**: the suspension happens before the
verdict, so a crash always favoured the newer, unverified lesson — exactly the
"recency wins" outcome the design exists to prevent.

**On resume**, `discard_lesson_conflicts_from(resume_point)` restores any lesson
suspended at or after the resume point: the rerun derives its own lessons and
re-decides, so carrying the old verdict would withdraw a lesson on evidence the
run has discarded. Same rule as the audit-log trim, and it runs *before* that
method's early return — a suspension can outlive a run even when no log entry
does. A conflict with no recorded iteration is left pending rather than guessed
at; the path is biased toward restoring throughout.

**On a fresh start**, semantic memory is wiped: `clear_all()` now runs alongside
the three audit-log clears. A "fresh" run previously inherited every lesson,
convention and pending suspension from the previous one — including probation
verdicts whose window no longer existed. Contents are snapshotted to
`Output/MemorySnapshot/` first, since ChromaDB is the only copy and this is
strictly more destructive than trimming one log's tail.

`clear_all()` also had a latent bug: it re-ran `__init__(project_name)` with no
config, silently reverting merge/drop thresholds and `convention_mode` to
defaults. Now that a fresh start calls it every run, that would have meant no run
ever honoured `config.yaml`'s dedup settings. Settings are now carried over.

## Key files

| Concern | File |
|---|---|
| Classify + parse verdict | `src/actions/memory_assistant_action.py` |
| Classification prompt | `prompts/MemoryAssistant_prompt.txt` (`MergeLessons`) |
| Status lifecycle, conflict registration, read filters, rebuild, `clear_all` | `src/utils/semantic_memory.py` |
| `record_lesson(verified=)`, `resolve_lesson_conflicts` | `src/utils/learning_system.py` |
| Probation gate, verified store, discard paths, fresh-start wipe, resume reconcile | `src/workflow.py` |
| Signature parity for the non-semantic backend | `src/utils/memory_system.py` |
| Tests (29) | `test/test_lesson_conflict_lifecycle.py` |

Its Chroma fixture chdirs **once per module** with a unique project per test —
per-test chdir breaks `PersistentClient`'s path cache (`no such table:
collections`).
