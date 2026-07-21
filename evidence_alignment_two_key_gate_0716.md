# Two-Key Evidence Gate for Semantic Escalation (0716)

## Problem

In iteration 68 (`Output/outputlog/071626.log`), `InterpretResults` correctly diagnosed a
**modeling overconstraint** (baseline newly UNSAT, classified `unintended_regression`, "no
question needed"), yet the generated feedback declared **requirement inconsistencies** and
proposed requirement updates. Cause: the `SemanticIssueTracker` escalates on symptom counts
alone (3 consecutive UNSAT iterations), *before* InterpretResults runs, and the old
`PersistentIssueEscalation` prompt Rule 1 unconditionally mandated
"decision MUST be `escalate to requirement clarification`" — overriding both the
interpretation and the measured diagnostics.

## Change

A requirement-level diagnosis is now only mandated when **both** evidence sources support it
(the **two-key rule**). After the deterministic diagnostics run, the workflow computes an
**evidence alignment** and rewrites the escalation strategy accordingly.

| Interpretation cause | Diagnostics verdict | Strategy |
|---|---|---|
| requirement | requirement conflict (≥2 requirement IDs implicated) | `REQUIREMENTS_DIAGNOSIS` |
| requirement | absent / inconclusive | `REQUIREMENTS_DIAGNOSIS` (interpretation alone decides) |
| requirement | modeling evidence | `MODEL_OVERCONSTRAINT_REPAIR` |
| model / mixed / unknown | anything | `MODEL_OVERCONSTRAINT_REPAIR` |

Diagnostics verdicts per predicate: `scope_artifact` (SAT at enlarged bounds) and
`internal_contradiction` (UNSAT with all facts disabled) are modeling evidence;
`localized` blocking sets count as requirement evidence only when they implicate **≥2**
requirements (one requirement cannot be inconsistent with itself).

### Touched components

- `src/utils/repair_plateau_detector.py` — `MODEL_OVERCONSTRAINT_REPAIR` constant;
  `summarize_interpretation_cause()` (parses `Likely Cause:` / `Classification:` lines);
  `summarize_diagnostics_evidence()` (categorical per-predicate verdicts);
  `apply_evidence_alignment()` (the gate: rewrites `strategy` and the directive's
  `STRATEGY:` line, appends an `EVIDENCE ALIGNMENT (computed)` block, stores the structured
  result on `semantic_escalation['evidence_alignment']`; best-effort on error).
- `src/workflow.py` `_step7` — calls `apply_evidence_alignment(semantic_escalation,
  interpretation)` right after `_run_semantic_diagnostics`; logs `[EVIDENCE_ALIGNMENT]`.
- `prompts/Evaluator_prompt.txt` — `PersistentIssueEscalation` section rewritten (below);
  DECISION POLICY in `GenerateSemanticFeedback` gained a dual-evidence line.
- `test/test_evidence_alignment.py` — 11 tests incl. an iteration-68 replay
  (real logged interpretation + diagnostics → `MODEL_OVERCONSTRAINT_REPAIR`).

## Decision-making guidance for the Evaluator (GenerateSemanticFeedback)

The prompt now guides the next-action decision in two layers:

**Every iteration (DECISION POLICY):** base the decision on BOTH the result
interpretation's causal analysis and any deterministic diagnosis evidence. Never choose
`escalate to requirement clarification` when the interpretation attributes the failure to
the model/encoding; a requirement-level conclusion needs support from the interpretation
and (when present) the diagnostics.

**Escalated iterations (PersistentIssueEscalation):** the directive carries the computed
`STRATEGY:` line plus the `EVIDENCE ALIGNMENT` block (interpretation verdict, per-issue
diagnostics verdicts, binding conclusion). The Evaluator must not override it.

- **STRATEGY: REQUIREMENTS_DIAGNOSIS** (both keys support requirements) — decision MUST be
  `escalate to requirement clarification`; full per-issue diagnosis in POTENTIAL
  REQUIREMENT ISSUES (inconsistency / ambiguity / gap, with evidence); concrete replacement
  wording in REQUIREMENT UPDATES that passes the ABSTRACTION GATE; user-confirmation
  questions. Escape hatch retained: provably pure `model overconstraint` goes to REPAIR
  INSTRUCTIONS instead.
- **STRATEGY: MODEL_OVERCONSTRAINT_REPAIR** (either key shows a modeling cause) — decision
  MUST be a model-repair action (`refine/narrow fix`, `partially revert`, or
  `adjust scope/trace and rerun`); REPAIR INSTRUCTIONS must target the measured evidence
  (named blocking facts, or the predicate body / sig declarations for an internal
  contradiction) and be materially different from every attempted fix; adding these issues
  to POTENTIAL REQUIREMENT ISSUES or REQUIREMENT UPDATES is FORBIDDEN.
- Per-issue overrides still apply within a REQUIREMENTS_DIAGNOSIS escalation: a measured
  `scope_artifact` issue must get `adjust scope/trace and rerun`; a `MINIMAL BLOCKING FACT
  SET: NONE` issue is classified as model overconstraint.

**Prompt evidence granularity:** the directive gives the Evaluator (1) the full
`DETERMINISTIC DIAGNOSIS` block — swept commands, named blocking facts, implicated
requirement IDs, run counts — for grounding the repair/diagnosis, and (2) the categorical
`EVIDENCE ALIGNMENT` block — one classified verdict per issue plus the conclusion — which
fixes the decision.

## Fallback rule (user-confirmed)

When diagnostics produced no verdict for an issue (assertion counterexamples, the
2-predicate diagnosis cap, failed variant runs), the interpretation alone decides.

## Out of scope

Regression veto (baseline newly UNSAT suspends escalation), cause-fingerprint persistence
counting, and deterministic post-stripping of REQUIREMENT UPDATES from LLM output remain
future work; the rung-5 user gate still guards actual requirement application.
