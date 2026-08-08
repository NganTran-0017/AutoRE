# Deterministic Semantic Diagnostic

Rungs 2–3 of the semantic escalation ladder. When a predicate stays UNSAT past
the `SemanticIssueTracker` thresholds, this replaces the Evaluator's *guess* at
which constraints conflict with an empirical answer measured by the Alloy
Analyzer itself — deterministic and LLM-free.

Implementation: `src/utils/semantic_diagnostics.py`
Invoked from: `WorkflowOrchestrator._run_semantic_diagnostics` (`src/workflow.py:1024`)

---

## Scope: what it runs on

Only escalated issues with `kind == 'unsat_predicate'`. Assertion
counterexamples (`kind == 'counterexample'`, names like `assert…`) are **not**
handled — there is no counterexample-oriented diagnostic, so for those the
evidence-alignment gate falls back to the interpretation verdict alone and the
log reads `diagnostics: not run`.

Caps: at most **2 predicates** per iteration (`max_predicates`), **12 Alloy
runs** per predicate (`max_runs_per_predicate`).

---

## The injected check callable

Every Alloy run goes through one seam so the logic is unit-testable without the
Analyzer:

```
check(model_text, predicate) -> Optional[bool]
    True  = SAT
    False = UNSAT
    None  = variant failed (syntax error, tool failure, timeout)
```

`make_alloy_sat_checker` is the production adapter: it writes each model variant
to `…/diagnostics/diag_N.als`, runs it through `AlloyExecutor`, and maps the
result — predicate in `unsat_run_commands` → `False`; `has_results` → `True`;
anything else (including syntax errors in the variant) → `None`.

---

## Rung 2 — scope sweep (`scope_sweep`, 1 run)

*Is the "persistent UNSAT" just a bounded-search artifact?*

1. `isolate_run_command` — comment out every `run`/`check` except `run <predicate>`
   (marker `//DIAG `), so exactly one command executes.
2. `enlarge_run_scope` — double every numeric bound in the scope clause (capped
   at 16); if the command has no `for` clause, append `for 8`. Only digits
   *after* `for` are rewritten, since predicate names can contain digits
   (`R1R2_x`).
3. `check` the enlarged variant.

- **SAT at enlarged bounds** → bounded-search artifact. Verdict recorded, rung 3
  skipped — the fix is scope adjustment, not a requirements escalation.
- **Still UNSAT** → genuine over-constraint; proceed to rung 3.

---

## Rung 3 — fact localization / delta debugging (`localize_blocking_facts`)

*Which facts actually block the predicate?* Greedy 1-minimization of the fact
set.

1. **Baseline**: disable *all* facts and re-run.
   - Still UNSAT → `internal_contradiction`: the conflict is inside the
     predicate body or the sig declarations/multiplicities, not in any fact.
     Stop.
   - SAT → at least one fact is responsible; continue.
2. **Greedy pass**: for each fact, tentatively disable it *on top of* the
   already-removed ones and re-run.
   - Still UNSAT without it → that fact isn't part of the conflict; leave it
     disabled.
   - Becomes SAT → the fact is needed; keep it in the suspect set.
   - Variant failed (`None`) → keep the fact conservatively, mark result
     `approximate`.
3. What remains is a **1-minimal blocking set**. Because facts/predicates are
   prefixed with requirement IDs (`fact R1R2…`, `pred R3…`),
   `requirement_ids(...)` maps that set directly to the implicated requirements
   — a *proven* conflict, not a hypothesis.

`disable_facts` comments blocks with the reversible/greppable `//DIAG ` marker;
`extract_fact_blocks` + `_find_block_end` locate named `fact` blocks by
brace-depth counting.

Budget: if the 12-run cap is hit before the pass completes, the result is
flagged `approximate` (a superset of the true minimal set).

---

## Output (`diagnose_unsat_predicates`)

Returns `{'directive_text', 'results'}`:

- **`directive_text`** — human-readable evidence lines appended to the
  escalation directive (data only; interpretation rules live in the
  `PersistentIssueEscalation` prompt section). Examples:
  - `SCOPE VERDICT: SATISFIABLE at enlarged bounds (…) -> bounded-search artifact`
  - `MINIMAL BLOCKING FACT SET: R1R2_x, R3_y -> implicated requirements: R1, R2, R3 (proven by N Analyzer runs)`
  - `MINIMAL BLOCKING FACT SET: NONE … contradiction is INSIDE the predicate body`
- **`results`** — structured `{predicate: {scope_sweep, localization}}`, stored
  on `semantic_escalation['diagnostics']` and consumed by
  `apply_evidence_alignment`.

Predicates beyond `max_predicates` are logged as capped, not silently dropped.

---

## How the verdict feeds escalation

`apply_evidence_alignment` (`src/utils/repair_plateau_detector.py`) is a
two-key gate. Requirements diagnosis stays mandated only when **both** the
InterpretResults causal analysis **and** these diagnostics point at the
requirements (a blocking set implicating ≥2 requirements). Modeling/scope
evidence — or an interpretation that blames the model — redirects the escalation
to `MODEL_OVERCONSTRAINT_REPAIR`. If diagnostics didn't run (e.g. a
counterexample-only escalation) the interpretation verdict decides alone.
