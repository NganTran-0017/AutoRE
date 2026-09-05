# AutoRE Workflow — Step by Step (2026-08-08)

High-level description of one run. Two agents do the work: the **RE** (Requirement
Engineer) writes requirements and the Alloy model; the **Evaluator** interprets analyzer
results and produces feedback. Between them sits deterministic workflow code that measures,
tracks and decides what the agents are allowed to do next.

## Setup (once per run)

**Step 1 — Analyze requirements.** The RE turns the raw input into a structured
requirements document: existing-system requirements (`E#`, ground truth) and prospective
requirements (`R#`, under verification). The raw input is preserved unchanged as the anchor
every later update is checked against.

**Step 2 — User clarification.** The user answers open questions before any modeling starts.
Answers are recorded in the Q&A database and reused in later iterations.

**Step 3 — Build the initial Alloy model.** The RE encodes the document: existing-system
rules as facts, prospective requirements as predicates and assertions with their own
`run`/`check` commands. Each construct declares which requirement it encodes.

*(On resume, these three are skipped: prior state is loaded and every log is trimmed back to
the resume point.)*

## Refinement loop

**Step 4 — Run the analyzer and measure.** The Alloy Analyzer runs every command. The
workflow records which predicates were satisfied, which were not, and which assertions
produced counterexamples, then checks the **hard metrics**: no syntax errors, no
counterexamples, all positive run commands satisfied. Deterministic tracking runs here —
error signatures, cross-iteration patterns, how long each semantic issue has persisted, and
whether the previous fix resolved what it targeted. The Evaluator then interprets the
results: what the model allows or forbids, what changed since last iteration, and whether
the cause looks like the encoding or the requirements.

**Steps 5–6 — Feedback and user review.** When an issue has persisted past its thresholds,
the workflow escalates: it runs a deterministic diagnosis (re-run at larger bounds to test
for a scope artifact; disable facts one at a time to find what provably blocks the
predicate) and computes a **strategy** — diagnose the requirements, or repair a model
overconstraint. The interpretation decides the cause; the measurements say where it sits.

The Evaluator then writes the feedback under that strategy: a next-action decision, repair
instructions for the RE, proposed requirement updates, questions for the user, and a
convergence recommendation. The user reviews it. If they respond, the feedback is rewritten
to incorporate their input; requirement changes they reject are removed deterministically.

**Convergence check.** The run stops when the hard metrics pass, the Evaluator agrees, and
no requirement update is still awaiting verification. Otherwise it continues.

**Step 7 — Update requirements.** Approved changes are patched into the document. Every
update enters **probation**: it is provisional until it survives several verified
iterations, and requirement changes stage matching model work (regenerate the constructs
that encode a changed requirement, delete the ones whose requirement is gone).

**Step 8 — Update the model.** The RE rewrites the model in one of three modes, chosen by
the workflow, never by the RE:

- **Mode 1 — Syntax repair.** The model does not parse; make the minimal fix.
- **Mode 2 — Semantic repair.** Apply the repair instructions, with prior failed
  approaches forbidden and any escalation directives in force.
- **Mode 3 — Diagnostic experiments.** The Evaluator could not tell which construct causes
  the failure, so this iteration measures instead of repairing: the RE adds probe predicates
  with their own `run` commands and changes nothing else. Each probe's SAT/UNSAT verdict is
  read against a meaning declared before the run. A diagnostic iteration is never counted as
  a failed fix, and the probes are deleted the following iteration.

The loop returns to Step 4 with the new model.

## What runs alongside every iteration

- **Regression log** — one entry per iteration: what the RE intended, what it predicted,
  what actually changed, and whether the issue was resolved. It is the memory the Evaluator
  reasons from.
- **Traceability and ownership audit** — which construct encodes which requirement.
  Constructs whose requirement no longer exists are removed; requirements nothing encodes
  are flagged, because verification cannot decide them.
- **Lessons and modeling conventions** — durable guidance carried into later prompts,
  suspended when contradicted and confirmed by outcome rather than recency.
- **Q&A database** — user answers, reused so the same question is not asked twice.

## The dividing line

The agents judge; the code decides what survives. The Evaluator chooses *whether* to
diagnose, escalate or repair — but which rulebook reaches it, which experiments are worth
running, which fixes are forbidden, and when a requirement is trusted are all settled
deterministically from measurements. Where the code cannot be sure, it falls back to the
previous behaviour and says so in the log rather than guessing.

Regression Log + Requirement Update Log
                    ↓
          Trajectory analysis
                    ↓
       Identify important transitions
                    ↓
Integrated Convergence + Co-evolution Map
                    ↓
            STRUCTURED TEXT 
                    ↓
               Evaluator

CURRENT TARGET ISSUE
Issue ID: UNSAT_EmergencyBypassFIFOScenario
Current iteration: 21
Current status: UNRESOLVED
Issue type: UNSAT predicate

CURRENT VERIFICATION RESULT
EmergencyBypassFIFOScenario: UNSAT
Syntax/type errors: None


=== LONGITUDINAL CO-EVOLUTION TRAJECTORY ===

[ITERATION 18]
Target issue: EmergencyBypassFIFOScenario — UNSAT
Requirement change: R3Δ [brief description].
Fix intent: Strengthen the emergency request-ordering constraint.
Model change: [Diff between the model in Iteration 18 and Iteration 17]
Verification transition: SAT -> UNSAT
Status: Regression.

[ITERATION 19]
Target issue: EmergencyBypassFIFOScenario — UNSAT
Requirement change: No requirement change since iteration 18.
Fix intent: Rewrite temporal ordering logic.
Model change: [Diff between the model in Iteration 19 and Iteration 18]
Verification transition: UNSAT -> UNSAT
Status: No improvement.

[ITERATION 20]
Target issue: EmergencyBypassFIFOScenario — UNSAT
Requirement change: No requirement change since iteration 18.
Fix intent: modify constraint C2.
Verification transition: UNSAT -> UNSAT
Model change: [Diff between the model in Iteration 20 and Iteration 19]
Status: Strategy changed, no improvement.


I18
Fix intent:rewrite EmergencyOrdering using TO/next
Diff: ...
syntax_error = true
unsat_predicate = unknown
counterexample = unknown
requirement_issue = unknown

Persistent issue: UNSAT_P1 
Relevant iterations: 19, 20, 21.

I19
Fix intent: Requirement R3 changed, modify predicate P1
Diff: ...
syntax_error = false
unsat_predicate = false
counterexample = true
requirement_change = no


I20
Fix intent: delete and rewrite ordering predicate 
Diff: ...
syntax_error = false
unsat_predicate = false
counterexample = true
requirement_change = no


I21
Fix intent: modify constraint C2
Diff: ...
syntax_error = false
unsat_predicate = false
counterexample = true
requirement_change = no


             Iteration
            I18    |  I19   |   I20

Requirement  -    |  -    |   R3Δ   -     -
  change                    

Fix mode    syntax  |  - | requirement   F3   F4   F5
            repair  |    | change
Model       M1 → M2 → M3 → M4 → M5

Issue       S1   S1   P1   P1   P1

Verify      ERR  SAT  UNS  UNS  SAT

CURRENT TARGET ISSUE
Issue ID: UNSAT_EmergencyBypassFIFOScenario
Current iteration: 21
Current status: UNRESOLVED
Issue type: UNSAT predicate

                    ITERATION / TIME  ─────────────────────────────►

                 I18            I19          I20

REQUIREMENTS
                 R3Δ          unchanged    unchanged
                  │              │             │

FEEDBACK /
FIX INTENT      Strengthen     Rewrite       Modify C2
                ordering       temporal
                  │              │             │
                  ▼              ▼             ▼

MODEL
                Δ Model 18    Δ Model 19      Δ Model 20
                  │              │             │

TARGET ISSUE
UNSAT_EmergencyBypassFIFOScenario
                  ●──────────────●──────────────●
                UNSAT          UNSAT          UNSAT

VERIFICATION
              SAT → UNSAT    UNSAT → UNSAT  UNSAT → UNSAT

TRAJECTORY
STATE           REGRESSION    NO CHANGE      STRATEGY CHANGE


I1
    Issue: Syntax error S1
    Fix intent: repair open statement...
    Requirement change: None
    Verify: ERR
I2
    Issue: Syntax error S1
    Fix intent: repair predicate P1
    Requirement change: None
    Verify: UNSAT P1
I3
    Issue: Semantic error in predicate P1
    Fix intent: repair predicate P1 
    Requirement change: None
    Verify: UNSAT P1
I4
    Issue: Semantic error P1
    Fix intent: change requirement and constraint C1
    Requirement change: R3Δ
    Verify: SAT P1, Counterexample CEX1
I5
    ...
I21 (current iteration)
    Issue: UNSAT P1
    Fix intent: modify constraint C2
    Requirement change: None
    Verify: Counterexample CEX1     