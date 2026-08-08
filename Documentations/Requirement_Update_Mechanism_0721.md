Here's the actual end-to-end determination chain. The key insight: deciding the document needs an update is a multi-gate funnel, and an actual edit happens only at the very last stage — the duplicate/misplacement issue you raised lives at that terminal stage, which trusts that everything upstream already vetted the change.

  The funnel — each gate can stop the update

  Stage 0 — Convergence check (workflow.py:287)
  If hard metrics pass and both agent and user assess convergence, the loop breaks — no update. Requirement updates only ever happen on a non-converged iteration: _step7_update_requirements runs (:306) only after the loop decides to continue.

  Stage 1 — Interpret results (_step4_evaluate_model → InterpretResults)
  Alloy runs; hard metrics come back (syntax / counterexamples / UNSAT predicates / satisfying instances). InterpretResults may populate === POTENTIAL REQUIREMENT ISSUES ===. But mentioning a requirement issue here does not yet mean a document update — it's just a hypothesis.

  Stage 2 — Gate: is it a requirement problem, or an encoding problem? (the ABSTRACTION GATE)
  By default an issue is treated as an encoding problem → it goes to REPAIR INSTRUCTIONS (fix the model), not to a requirement update.
  The prompt is explicit (Evaluator_prompt.txt:597): if the true fix is "which variable/construct to use," it is not a requirement update.

  Stage 3 — Gate: persistence escalation (RepairPlateauDetector → PersistentIssueEscalation, :569)
  A requirement-level diagnosis becomes mandatory only when an issue survives repeated repair attempts. A single failure is repaired at the model level; only a plateau escalates to "maybe the requirement itself is wrong."

  Stage 4 — Gate: two-key rule (:582)
  Even when escalated, a requirement update is valid only when both independent sources agree: (a) the InterpretResults causal analysis and (b) the deterministic Alloy diagnosis (scope sweep/minimal-blocking-fact-set). If the deterministic diagnosis says "SATISFIABLE at enlarged bounds" or "model overconstraint," STRATEGY flips to MODEL_OVERCONSTRAINT_REPAIR and requirement updates are forbidden
  that iteration (:605-609).

  Stage 5 — Feedback emits the proposal (GenerateSemanticFeedback)
  Only if Stages 2–4 pass does the feedback carry a populated === REQUIREMENT UPDATES === section with concrete proposed wording (:1158). Otherwise: "None — no requirement updates justified."

  Stage 6 — Gate: user decision (_apply_requirement_gate, :1076)
  For escalated changes, the user accepts / edits / rejects. Rejected → remove_requirement_updates() deterministically strips the section (:1134) so it cannot reach step 7. Accepted/edited/provisional → recorded as a confirmed Q&A and flows on.

  Stage 7 — The actual determination (_extract_requirement_updates, :2140 / _step7, :2227)
  Step 7 extracts only the REQUIREMENT UPDATES section. If it's missing/empty/"None," step 7 returns immediately and the requirements file is reused byte-for-byte (:2230-2235). So the operational answer to "does the doc need an update?" is exactly:
  ▎ Is there a non-empty REQUIREMENT UPDATES section that survived all the gates above?

  Stage 8 — Apply the edit (UpdateRequirements.run → apply_patch)
  Only now is the document actually mutated, via patch ops (ADD/MODIFY/REMOVE). Everything not named is copied verbatim; REMOVE of an original requirement is blocked.

  Where your earlier issue sits

  The R6-duplicates-R4.3 / R7-should-be-a-constraint problems all occur at Stage 8 (and its Stage 5 source). By the time an update reaches Stage 8, the pipeline has already decided "a requirement change is warranted" — but it has not decided "what kind" (new R# vs sub-requirement vs constraint) or "is it already covered." Stages 2–6 gate whether to touch requirements; nothing gates where the change lands or whether it duplicates. That missing classify + dedup + placement step is exactly the triage procedure done by the Evaluator (from my previous proposal) — and it's cleanest to insert right at Stage 8's choke point, with the Target kind field mirrored back into Stage 5's
  REQUIREMENT UPDATES.

  One more path worth noting: direct user feedback (user_feedback / user_preferences) also flows straight into Stage 8's UpdateRequirements.run (:2242) — this is the "user gives feedback and the Evaluator turns it into requirements" path from your original report. It bypasses Stages 1–4 entirely, which is why the ask-when-unsure gate matters most there: user feedback arrives unclassified, and the agent currently assumes "requirement."