DATE DOCUMENTED: 08/13/2026
DESCRIPTION: The reference graph tracks helper constructs to identify unowned helpers for removal.

The reference graph is created deterministically from the Alloy model text. It is a lexical graph, not a graph produced by the Alloy
  Analyzer or an Alloy AST.

  ### Graph construction

  The main implementation is src/utils/semantic_diagnostics.py:181.

  1. src/utils/semantic_diagnostics.py:83 identifies named top-level constructs of these kinds:
      - fact
      - pred
      - assert
      - fun

     Brace depth determines each block’s boundaries.

  2. Every construct name becomes a graph node.
  3. Each block is stripped of // comments and tokenized with:

     r'\b[A-Za-z_]\w*\b'

  4. If a token matches another known construct name, an edge is added:

     refs[caller] -> referenced construct

  5. The reverse map is then constructed:

     callers[construct] -> constructs that reference it

  6. Top-level named commands such as run R2_Witness and check assertR1Safety are recorded as entry points. Their line numbers are also
     retained so commands can be removed with their predicates/assertions.

  The result has this shape:

  {
      "refs": {
          "R1_Fact": {"midHelper"},
          "midHelper": {"deepHelper"},
          "deepHelper": set(),
      },
      "callers": {
          "midHelper": {"R1_Fact"},
          "deepHelper": {"midHelper"},
      },
      "entry_points": {"R2_Witness", "assertR1Safety"},
      "commands": {
          "R2_Witness": [line_number],
          "assertR1Safety": [line_number],
      },
  }

  ### How helpers are tracked

  Helpers do not need their own requirement annotation. src/utils/traceability_store.py:172 walks the reverse graph transitively.

  For example:

  fact R1_ModeExclusive
          |
          v
      midHelper
          |
          v
      deepHelper

  Walking upward through callers gives both helpers the derived owner R1.

  src/utils/traceability_store.py:192 combines this graph with the requirement-to-construct map:

  - A called helper gets the union of its transitive callers’ requirement owners.
  - An uncalled fun or non-entry-point pred is classified as dead code.
  - A predicate named by run is protected from being mistaken for dead code.
  - A helper called only by an unowned construct receives no invented owner.

  ### How the graph controls removal

  src/utils/traceability_store.py:336 uses callers to calculate safe cascading deletion.

  - Explicit stale/orphan constructs are removal seeds.
  - A fun or pred is added to the deletion set when all its callers are already being removed.
  - Facts and assertions are not implicitly cascaded.
  - Named run/check entry points are not implicitly cascaded.
  - If a surviving construct still references a target, deletion is blocked.

  Example:

  E5_Orphan ──> auditOnlyHelper       remove both
  E5_Orphan ──> sharedHelper
  R2_Witness ─> sharedHelper          keep sharedHelper

  The workflow runs the ownership audit and stages stale removal in src/workflow.py:3941 and src/workflow.py:3997. On the next model
  update, src/utils/traceability_store.py:395 removes the selected blocks and their associated run/check commands. It rejects the result
  if lexical references to deleted names remain.

  ### Important limitations

  Because the graph is regex-based:

  - It does not resolve Alloy semantics, overloading, module-qualified names, or scoping.
  - Only named fact, pred, assert, and fun blocks are graph nodes; signatures and fields are excluded.
  - A construct name appearing as an ordinary identifier can produce a false edge.
  - Anonymous commands such as run { ... } are not entry points.
  - Brace matching only understands line comments; strings or unusual syntax containing braces could confuse block extraction.