1. InterpretResults

  A. Base prompt — assembled by render_prompt, in this order

  ┌─────┬──────────────────────────────┬─────────┬───────────────────────────────────────┐
  │  #  │    Section (in the .txt)     │ ~tokens │             Why included              │
  ├─────┼──────────────────────────────┼─────────┼───────────────────────────────────────┤
  │ 1   │ Role                         │ 78      │ default (not in actions_without_role) │
  ├─────┼──────────────────────────────┼─────────┼───────────────────────────────────────┤
  │ 2   │ InterpretResults             │ 2083    │ the action section                    │
  ├─────┼──────────────────────────────┼─────────┼───────────────────────────────────────┤
  │ 3   │ AbstractionGuidance          │ 487     │ in actions_with_abstraction           │
  ├─────┼──────────────────────────────┼─────────┼───────────────────────────────────────┤
  │ 4   │ ResponseFormatInterpretation │ 379     │ via action_to_format map              │
  └─────┴──────────────────────────────┴─────────┴───────────────────────────────────────┘

  Deliberately excluded: QualityStandards, ConvergenceCriteria, LearningInstructions (all three list InterpretResults in their exclusion sets).

  B. Sections appended conditionally by run() (evaluation_actions.py:164-208)

  ┌─────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────┬────────────────────────────────────────────────┐
  │         Section         │                                              Condition                                              │                   Variables                    │
  ├─────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────┤
  │ SyntaxError             │ has_syntax_errors                                                                                   │ —                                              │
  ├─────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────┤
  │ InterpretUNSATPred      │ len(unsat_run_commands) > 0                                                                         │ none (reads the base prompt's ownership block) │
  ├─────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────┤
  │ InterpretCounterexample │ has_counterexamples and (no UNSAT runs or all positive runs satisfied or UNSAT stuck ≥2 iterations) │ {{counterexample}}                             │
  └─────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────┴────────────────────────────────────────────────┘

  ⚠️  [SECTION: SyntaxError] does not exist in the file. get_section("Evaluator","SyntaxError") would raise KeyError. It's currently unreachable only because workflow.py:1237 skips InterpretResults
  entirely when syntax errors are present — a landmine, not a working path.

  C. The quality path — a different prompt shape entirely

  When not has_syntax_errors and no_counterexamples and all_positive_satisfied (:218), the base prompt is built and then discarded, and up to two standalone, section-only LLM calls run instead:

  ┌──────┬──────────────────────┬───────────────────────────────────────────────────────────────────────┬──────────────────────────┐
  │ Call │       Section        │                               Variables                               │        Condition         │
  ├──────┼──────────────────────┼───────────────────────────────────────────────────────────────────────┼──────────────────────────┤
  │ 1    │ InterpretSatInstance │ satisfying_instances, alloy_model, requirements_document              │ has_satisfying_instances │
  ├──────┼──────────────────────┼───────────────────────────────────────────────────────────────────────┼──────────────────────────┤
  │ 2    │ VacuityAnalysis      │ analyzer_results, alloy_model, requirements_document, ownership_audit │ always on this path      │
  └──────┴──────────────────────┴───────────────────────────────────────────────────────────────────────┴──────────────────────────┘

  No Role, no response format, no appended sections — the code comments this explicitly ("Do NOT prepend base InterpretResults prompt"). The two responses are concatenated with \n\n---\n\n.

  D. Runtime-injected content — not in the .txt

  ┌─────────────────────────┬───────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │        Variable         │                         Built by                          │                                                    Content                                                    │
  ├─────────────────────────┼───────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ analyzer_results        │ _format_analyzer_results (:416)                           │ SYNTAX ERRORS (line/col/message + code snippet + context) or SYNTAX: OK; COUNTEREXAMPLES FOUND n/total;       │
  │                         │                                                           │ UNSATISFIABLE PREDICATES list; SATISFYING INSTANCES n/total                                                   │
  ├─────────────────────────┼───────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ alloy_model             │ inline (:108-112)                                         │ full model, or "(Full model omitted - syntax errors shown above)"                                             │
  ├─────────────────────────┼───────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ regression_log          │ RegressionLog.format_for_prompt_filtered(count=3)         │ last 3 issue-relevant iterations including full unified model diffs                                           │
  ├─────────────────────────┼───────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ ownership_audit         │ _format_ownership_context (:326)                          │ traceability_store.audit_model() + construct_removal_log.format_for_prompt() + unowned_blockers/streaks       │
  │                         │                                                           │ carried from the previous iteration's localization                                                            │
  ├─────────────────────────┼───────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ deterministic_diagnosis │ workflow._prepare_semantic_escalation →                   │ scope sweep verdict + minimal blocking-fact set + implicated requirement IDs; else "None - no issue has       │
  │                         │ _run_semantic_diagnostics                                 │ persisted long enough…"                                                                                       │
  ├─────────────────────────┼───────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ counterexample          │ _format_counterexamples (:591)                            │ per-check counterexample detail                                                                               │
  ├─────────────────────────┼───────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ satisfying_instances    │ _format_satisfying_instances (:538)                       │ instance detail incl. _find_comprehensive_instance                                                            │
  ├─────────────────────────┼───────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ user_preferences        │ get_user_preferences()                                    │ passed but consumed by no section — dead                                                                      │
  └─────────────────────────┴───────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  ---
  2. GenerateSemanticFeedback

  A. Base prompt — assembled by render_prompt

  ┌─────┬──────────────────────────┬─────────┬──────────────────────────────┐
  │  #  │         Section          │ ~tokens │             Why              │
  ├─────┼──────────────────────────┼─────────┼──────────────────────────────┤
  │ 1   │ Role                     │ 78      │ default                      │
  ├─────┼──────────────────────────┼─────────┼──────────────────────────────┤
  │ 2   │ GenerateSemanticFeedback │ 3125    │ action section               │
  ├─────┼──────────────────────────┼─────────┼──────────────────────────────┤
  │ 3   │ AbstractionGuidance      │ 487     │ in actions_with_abstraction  │
  ├─────┼──────────────────────────┼─────────┼──────────────────────────────┤
  │ 4   │ ResponseFormatFeedback   │ 1643    │ via action_to_format         │
  ├─────┼──────────────────────────┼─────────┼──────────────────────────────┤
  │ 5   │ ConvergenceCriteria      │ 138     │ not excluded for this action │
  └─────┴──────────────────────────┴─────────┴──────────────────────────────┘

  Excluded: QualityStandards, LearningInstructions.

  B. Sections appended by run() (:841-876)

  ┌───────────────────────────┬────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │          Section          │                     Condition                      │                                                        Note                                                        │
  ├───────────────────────────┼────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ QAContextReuseAndUpdate   │ relevant_qa non-empty and ≠ "No relevant prior Q&A │ the RESOLVED/STALE/UNRESOLVED reconciliation                                                                       │
  │                           │  pairs found."                                     │                                                                                                                    │
  ├───────────────────────────┼────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ PersistentIssueEscalation │ persistence_status non-empty                       │ passed through select_binding_rules() first — only one of the two binding-rule blocks survives;                    │
  │                           │                                                    │ {{persistence_status}} substituted after                                                                           │
  ├───────────────────────────┼────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ RequirementChangeTriage   │ always                                             │ the 6-bucket DUPLICATE/MODELING/CONSTRAINT/REQUIREMENT/UNSURE/CONTRADICTS procedure                                │
  └───────────────────────────┴────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  C. Scenario matrix

  There is no branching on issue type inside this action. UNSAT predicates, counterexamples, vacuity and satisfying-instance findings all arrive as prose inside {{interpretation}} — the shape of the
  prompt is identical for all of them. Only three things actually vary:

  ┌─────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                          Scenario                           │                                                             What changes                                                              │
  ├─────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ UNSAT predicates / counterexamples / vacuity                │ nothing structural — differs only in {{interpretation}} content and in which Systematic Unsatisfiability Analysis / UNSAT Matrix      │
  │                                                             │ blocks it carries                                                                                                                     │
  ├─────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Syntax errors ("SYNTAX STATUS: Errors found" in the         │ {{alloy_model}} is replaced by RELEVANT CODE SNIPPETS (faulty sections only) pulled from                                              │
  │ interpretation, :809)                                       │ analyzer_results['analysis']['syntax_errors'][*]['code_snippet']                                                                      │
  ├─────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Persistent issue escalated                                  │ PersistentIssueEscalation appended, reduced to one strategy's rulebook (REQUIREMENTS_DIAGNOSIS or MODEL_OVERCONSTRAINT_REPAIR)        │
  ├─────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Prior Q&A retrieved                                         │ QAContextReuseAndUpdate appended                                                                                                      │
  └─────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  D. Runtime-injected content — not in the .txt

  ┌────────────────────┬──────────────────────────────────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────┐
  │      Variable      │                                       Built by                                       │                                         Content                                         │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ interpretation     │ previous InterpretResults call                                                       │ full text                                                                               │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ alloy_model        │ inline                                                                               │ full model or syntax snippets (above)                                                   │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ lessons            │ get_lessons_for_context(query=interpretation, limit=5)                               │ semantic-memory top-5 ranked against the interpretation                                 │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ relevant_qa        │ qa_database.retrieve_relevant(pending_questions, max_results=3,                      │ === RELEVANT PRIOR CLARIFICATIONS === block; the pending questions come from parsing    │
  │                    │ similarity_threshold=0.3) → format_for_prompt                                        │ BLOCKING QUESTIONS out of the interpretation (workflow.py:1257)                         │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ failed_fix_history │ regression_log.format_failed_fix_history(current_issue, entries)                     │ every prior attempt at this issue                                                       │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ persistence_status │ repair_plateau_detector.build_semantic_escalation()                                  │ persistence counts, fixes already attempted, DETERMINISTIC DIAGNOSIS, EVIDENCE          │
  │                    │                                                                                      │ ALIGNMENT, STRATEGY                                                                     │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ user_preferences   │ hardcoded "" (:778, "Temporarily disabled")                                          │ consumed by no section — dead                                                           │
  └────────────────────┴──────────────────────────────────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────┘

  ---
  3. GenerateSyntaxRepairInstruction

  A. Base prompt — the leanest of the three

  render_prompt contributes exactly one section:

  ┌─────┬──────────────────────────────────────────────────────────────────┬─────────────┬─────────────────────────────────────────────────────────┐
  │  #  │                             Section                              │   ~tokens   │                           Why                           │
  ├─────┼──────────────────────────────────────────────────────────────────┼─────────────┼─────────────────────────────────────────────────────────┤
  │ 1   │ GenerateSyntaxRepairInstruction or RefineSyntaxRepairInstruction │ 2178 / 1199 │ switched at :1155 on whether user_guidance is non-empty │
  └─────┴──────────────────────────────────────────────────────────────────┴─────────────┴─────────────────────────────────────────────────────────┘

  Everything else is excluded by name: Role (actions_without_role), AbstractionGuidance (not in actions_with_abstraction), QualityStandards, ConvergenceCriteria, LearningInstructions. The response format
  resolves to the generic "ResponseFormat", which does not exist for the Evaluator — so response_format is "" and nothing is appended. That is harmless here: both sections carry their own ### OUTPUT
  FORMAT: block inline ([DIAGNOSIS] / [FIX INTENT] / [REPAIR INSTRUCTIONS] / [RATIONALE]).

  No sections are appended by run(). This action is one section plus variables — nothing else.

  B. Runtime-injected content — not in the .txt

  ┌──────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────┬──────────────────┬────────────────┐
  │         Variable         │                                           Source                                           │ Used by Generate │ Used by Refine │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ code_snippet             │ analyzer error → block extraction                                                          │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ error_message            │ analyzer first error                                                                       │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ alloy_model              │ full model                                                                                 │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ lessons                  │ get_lessons_for_context(query=error_message, limit=5)                                      │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ pattern_status           │ RepairPlateauDetector syntax escalation, else "No cross-iteration error pattern detected…" │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ previous_failed_attempts │ formatted in run() (:1119)                                                                 │ ✅               │ ❌ dropped     │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ known_good_approaches    │ formatted in run() (:1132)                                                                 │ ✅               │ ❌ dropped     │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ failed_fix_history       │ format_failed_fix_history                                                                  │ ✅               │ ❌ dropped     │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ user_guidance            │ CLI, after 3 consecutive / 4-in-7 same-error trigger                                       │ ❌               │ ✅             │
  └──────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────┴──────────────────┴────────────────┘

  C. Three call sites (workflow.py)

  ┌──────┬──────────────────────────────────────────┬───────────────┬─────────────────────────────────┐
  │ Line │                   Path                   │ user_guidance │          Section used           │
  ├──────┼──────────────────────────────────────────┼───────────────┼─────────────────────────────────┤
  │ 2855 │ normal repair                            │ —             │ GenerateSyntaxRepairInstruction │
  ├──────┼──────────────────────────────────────────┼───────────────┼─────────────────────────────────┤
  │ 2743 │ error-limit reached, user typed guidance │ ✅            │ RefineSyntaxRepairInstruction   │
  ├──────┼──────────────────────────────────────────┼───────────────┼─────────────────────────────────┤
  │ 3010 │ feedback-too-similar retry with guidance │ ✅            │ RefineSyntaxRepairInstruction   │
  └──────┴──────────────────────────────────────────┴───────────────┴─────────────────────────────────┘

  ---
  Findings worth acting on

  1. RefineSyntaxRepairInstruction silently discards the failure history. run() always computes previous_failed_attempts, known_good_approaches and failed_fix_history, and call site 3010 explicitly passes
  them — but that section has no matching {{…}} placeholders, and _substitute_variables only errors on missing variables, never on extra ones. So the moment a user intervenes because repairs keep
  failing, the record of what already failed is dropped from the prompt. That's the exact opposite of what the escalation is for.
  2. [SECTION: SyntaxError] is referenced but doesn't exist (evaluation_actions.py:166) → KeyError if ever reached.
  3. The quality path throws away a fully-built prompt, including any InterpretUNSATPred section appended just before (negative predicates are legitimately UNSAT while all positive ones pass, so this

  ┌────────────────────┬──────────────────────────────────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────┐
  │      Variable      │                                       Built by                                       │                                         Content                                         │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ interpretation     │ previous InterpretResults call                                                       │ full text                                                                               │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ alloy_model        │ inline                                                                               │ full model or syntax snippets (above)                                                   │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ lessons            │ get_lessons_for_context(query=interpretation, limit=5)                               │ semantic-memory top-5 ranked against the interpretation                                 │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ relevant_qa        │ qa_database.retrieve_relevant(pending_questions, max_results=3,                      │ === RELEVANT PRIOR CLARIFICATIONS === block; the pending questions come from parsing    │
  │                    │ similarity_threshold=0.3) → format_for_prompt                                        │ BLOCKING QUESTIONS out of the interpretation (workflow.py:1257)                         │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ failed_fix_history │ regression_log.format_failed_fix_history(current_issue, entries)                     │ every prior attempt at this issue                                                       │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ persistence_status │ repair_plateau_detector.build_semantic_escalation()                                  │ persistence counts, fixes already attempted, DETERMINISTIC DIAGNOSIS, EVIDENCE          │
  │                    │                                                                                      │ ALIGNMENT, STRATEGY                                                                     │
  ├────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ user_preferences   │ hardcoded "" (:778, "Temporarily disabled")                                          │ consumed by no section — dead                                                           │
  └────────────────────┴──────────────────────────────────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────┘

  ---
  3. GenerateSyntaxRepairInstruction

  A. Base prompt — the leanest of the three

  render_prompt contributes exactly one section:

  ┌─────┬──────────────────────────────────────────────────────────────────┬─────────────┬─────────────────────────────────────────────────────────┐
  │  #  │                             Section                              │   ~tokens   │                           Why                           │
  ├─────┼──────────────────────────────────────────────────────────────────┼─────────────┼─────────────────────────────────────────────────────────┤
  │ 1   │ GenerateSyntaxRepairInstruction or RefineSyntaxRepairInstruction │ 2178 / 1199 │ switched at :1155 on whether user_guidance is non-empty │
  └─────┴──────────────────────────────────────────────────────────────────┴─────────────┴─────────────────────────────────────────────────────────┘

  Everything else is excluded by name: Role (actions_without_role), AbstractionGuidance (not in actions_with_abstraction), QualityStandards, ConvergenceCriteria, LearningInstructions. The response format
  resolves to the generic "ResponseFormat", which does not exist for the Evaluator — so response_format is "" and nothing is appended. That is harmless here: both sections carry their own ### OUTPUT
  FORMAT: block inline ([DIAGNOSIS] / [FIX INTENT] / [REPAIR INSTRUCTIONS] / [RATIONALE]).

  No sections are appended by run(). This action is one section plus variables — nothing else.

  B. Runtime-injected content — not in the .txt

  ┌──────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────┬──────────────────┬────────────────┐
  │         Variable         │                                           Source                                           │ Used by Generate │ Used by Refine │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ code_snippet             │ analyzer error → block extraction                                                          │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ error_message            │ analyzer first error                                                                       │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ alloy_model              │ full model                                                                                 │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ lessons                  │ get_lessons_for_context(query=error_message, limit=5)                                      │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ pattern_status           │ RepairPlateauDetector syntax escalation, else "No cross-iteration error pattern detected…" │ ✅               │ ✅             │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ previous_failed_attempts │ formatted in run() (:1119)                                                                 │ ✅               │ ❌ dropped     │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ known_good_approaches    │ formatted in run() (:1132)                                                                 │ ✅               │ ❌ dropped     │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ failed_fix_history       │ format_failed_fix_history                                                                  │ ✅               │ ❌ dropped     │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼────────────────┤
  │ user_guidance            │ CLI, after 3 consecutive / 4-in-7 same-error trigger                                       │ ❌               │ ✅             │
  └──────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────┴──────────────────┴────────────────┘

  C. Three call sites (workflow.py)

  ┌──────┬──────────────────────────────────────────┬───────────────┬─────────────────────────────────┐
  │ Line │                   Path                   │ user_guidance │          Section used           │
  ├──────┼──────────────────────────────────────────┼───────────────┼─────────────────────────────────┤
  │ 2855 │ normal repair                            │ —             │ GenerateSyntaxRepairInstruction │
  ├──────┼──────────────────────────────────────────┼───────────────┼─────────────────────────────────┤
  │ 2743 │ error-limit reached, user typed guidance │ ✅            │ RefineSyntaxRepairInstruction   │
  ├──────┼──────────────────────────────────────────┼───────────────┼─────────────────────────────────┤
  │ 3010 │ feedback-too-similar retry with guidance │ ✅            │ RefineSyntaxRepairInstruction   │
  └──────┴──────────────────────────────────────────┴───────────────┴─────────────────────────────────┘

  ---
  Findings worth acting on

  1. RefineSyntaxRepairInstruction silently discards the failure history. run() always computes previous_failed_attempts, known_good_approaches and failed_fix_history, and call site 3010 explicitly passes
  them — but that section has no matching {{…}} placeholders, and _substitute_variables only errors on missing variables, never on extra ones. So the moment a user intervenes because repairs keep
  failing, the record of what already failed is dropped from the prompt. That's the exact opposite of what the escalation is for.
  2. [SECTION: SyntaxError] is referenced but doesn't exist (evaluation_actions.py:166) → KeyError if ever reached.
  3. The quality path throws away a fully-built prompt, including any InterpretUNSATPred section appended just before (negative predicates are legitimately UNSAT while all positive ones pass, so this
  really does happen).
  4. user_preferences is plumbed through both InterpretResults and GenerateSemanticFeedback and consumed by nothing.
  5. The comment [SECTION: QualityStandards] // not used in any action is wrong — it is appended to RefineFeedback, which is not in actions_without_quality_standards.
