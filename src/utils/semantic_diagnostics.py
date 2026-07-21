"""
Deterministic diagnosis of persistent UNSAT predicates - rungs 2-3 of the
semantic escalation ladder.

When a predicate stays UNSAT past the SemanticIssueTracker thresholds, the
Evaluator previously had to GUESS which constraints conflict. These routines
make the Alloy Analyzer answer empirically before the LLM explains:

  Rung 2 - scope/trace sweep: re-run the stuck predicate alone at enlarged
      bounds. If it becomes SAT, the "persistent UNSAT" was a bounded-search
      artifact and the correct action is scope adjustment, NOT a requirements
      escalation.

  Rung 3 - fact localization (delta debugging): greedily disable facts and
      re-run until the MINIMAL set of facts that block the predicate remains.
      Because this codebase prefixes facts/predicates with requirement IDs
      (fact R1R2..., pred R3...), the minimal blocking set directly names the
      conflicting requirements - a PROVEN conflict, not a hypothesis.

Deterministic and LLM-free. Every Alloy run goes through an injected
`check(model_text, predicate) -> Optional[bool]` callable (True=SAT,
False=UNSAT, None=variant failed), so the logic is unit-testable without
Alloy; `make_alloy_sat_checker` provides the production adapter.
"""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


CheckFn = Callable[[str, str], Optional[bool]]

_DIAG_MARKER = "//DIAG "


def _strip_line_comment(line: str) -> str:
    return line.split("//", 1)[0]


def _find_block_end(lines: List[str], start: int) -> int:
    """Index of the line closing the brace block opened at/after `start`."""
    depth = 0
    started = False
    for j in range(start, len(lines)):
        code = _strip_line_comment(lines[j])
        for ch in code:
            if ch == '{':
                depth += 1
                started = True
            elif ch == '}':
                depth -= 1
        if started and depth <= 0:
            return j
    return start


def extract_fact_blocks(model_text: str) -> List[Dict[str, Any]]:
    """List the model's named fact blocks: [{'name', 'start', 'end'}] (line indices, inclusive)."""
    lines = model_text.splitlines()
    facts = []
    for i, line in enumerate(lines):
        m = re.match(r'\s*fact\s+(\w+)', _strip_line_comment(line))
        if m:
            facts.append({'name': m.group(1), 'start': i, 'end': _find_block_end(lines, i)})
    return facts


def disable_facts(model_text: str, fact_names: List[str]) -> str:
    """Comment out the named fact blocks (marker-prefixed, so it's reversible/greppable)."""
    if not fact_names:
        return model_text
    lines = model_text.splitlines()
    for fact in extract_fact_blocks(model_text):
        if fact['name'] in fact_names:
            for i in range(fact['start'], fact['end'] + 1):
                lines[i] = _DIAG_MARKER + lines[i]
    return "\n".join(lines)


def isolate_run_command(model_text: str, predicate: str) -> Optional[str]:
    """
    Keep only `run <predicate>`; comment out every other run/check command so a
    diagnostic variant executes exactly one command. Returns None if the
    predicate has no run command.
    """
    lines = model_text.splitlines()
    found = False
    for i, line in enumerate(lines):
        m = re.match(r'\s*(run|check)\s+([A-Za-z_]\w*)', _strip_line_comment(line))
        if not m:
            continue
        if m.group(1) == 'run' and m.group(2) == predicate:
            found = True
        else:
            lines[i] = _DIAG_MARKER + lines[i]
    return "\n".join(lines) if found else None


def enlarge_run_scope(model_text: str, predicate: str, factor: int = 2, cap: int = 16) -> Optional[Dict[str, str]]:
    """
    Double every numeric bound on the predicate's run command (capped); if the
    command has no bounds, append ` for 8`. Returns {'model_text', 'command'}
    or None if the run command is not found.
    """
    lines = model_text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r'(\s*)run\s+' + re.escape(predicate) + r'\b', _strip_line_comment(line))
        if not m:
            continue
        code = _strip_line_comment(line).rstrip()
        # Only rewrite bounds in the scope clause - predicate names may
        # themselves contain digits (R1R2_x per the naming convention).
        m_for = re.search(r'\bfor\b', code)
        if m_for:
            head, scope = code[:m_for.start()], code[m_for.start():]
            new_line = head + re.sub(
                r'\d+', lambda n: str(min(int(n.group(0)) * factor, cap)), scope)
        else:
            new_line = code + " for 8"
        lines[i] = new_line
        return {'model_text': "\n".join(lines), 'command': new_line.strip()}
    return None


def requirement_ids(names: List[str]) -> List[str]:
    """Extract requirement IDs from R-prefixed construct names (R1R2_x -> R1, R2)."""
    ids: List[str] = []
    for name in names:
        for rid in re.findall(r'R\d+', name or ''):
            if rid not in ids:
                ids.append(rid)
    return sorted(ids, key=lambda r: int(r[1:]))


def scope_sweep(model_text: str, predicate: str, check: CheckFn) -> Dict[str, Any]:
    """Rung 2: is the UNSAT a bounded-search artifact? (1 Alloy run)"""
    isolated = isolate_run_command(model_text, predicate)
    if isolated is None:
        return {'performed': False, 'reason': f"no run command found for '{predicate}'"}
    enlarged = enlarge_run_scope(isolated, predicate)
    if enlarged is None:
        return {'performed': False, 'reason': f"run command for '{predicate}' not found for scope rewrite"}
    verdict = check(enlarged['model_text'], predicate)
    return {
        'performed': verdict is not None,
        'sat_at_larger_scope': verdict,
        'swept_command': enlarged['command'],
    }


def localize_blocking_facts(
    model_text: str,
    predicate: str,
    check: CheckFn,
    max_runs: int = 12,
) -> Dict[str, Any]:
    """
    Rung 3: greedy destructive minimization of the fact set blocking `predicate`.

    Starting from all facts (known UNSAT), each fact is tentatively disabled;
    if the predicate is STILL UNSAT without it, the fact is not part of the
    conflict and stays disabled. What remains is a 1-minimal blocking set.

    Returns a dict with 'verdict':
      'localized'              -> 'blocking_facts', 'implicated_requirements'
      'internal_contradiction' -> UNSAT even with ALL facts disabled (the
                                  conflict is inside the predicate body or
                                  signature declarations/multiplicities)
      'no_facts' / 'error'
    plus 'runs' and 'approximate' (budget exhausted or variants failed).
    """
    result: Dict[str, Any] = {'verdict': 'error', 'runs': 0, 'approximate': False}
    isolated = isolate_run_command(model_text, predicate)
    if isolated is None:
        result['reason'] = f"no run command found for '{predicate}'"
        return result

    all_names = [f['name'] for f in extract_fact_blocks(isolated)]
    if not all_names:
        result['verdict'] = 'no_facts'
        return result

    runs = 0

    # Baseline: everything disabled. Still UNSAT -> the conflict is internal.
    baseline = check(disable_facts(isolated, all_names), predicate)
    runs += 1
    if baseline is None:
        result.update({'runs': runs, 'reason': 'baseline variant failed to execute'})
        return result
    if baseline is False:
        result.update({'verdict': 'internal_contradiction', 'runs': runs})
        return result

    suspects = list(all_names)
    approximate = False
    for name in list(suspects):
        if runs >= max_runs:
            approximate = True
            break
        trial_disabled = [n for n in all_names if n not in suspects or n == name]
        verdict = check(disable_facts(isolated, trial_disabled), predicate)
        runs += 1
        if verdict is False:
            # Still UNSAT without this fact -> not needed for the conflict
            suspects.remove(name)
        elif verdict is None:
            approximate = True  # variant failed; keep the fact conservatively

    result.update({
        'verdict': 'localized',
        'blocking_facts': suspects,
        'implicated_requirements': requirement_ids(suspects + [predicate]),
        'runs': runs,
        'approximate': approximate,
    })
    return result


def diagnose_unsat_predicates(
    model_text: str,
    predicates: List[str],
    check: CheckFn,
    max_predicates: int = 2,
    max_runs_per_predicate: int = 12,
    logger=None,
) -> Dict[str, Any]:
    """
    Run rungs 2-3 for the escalated UNSAT predicates and render the evidence
    as directive-ready text (data only - the interpretation rules live in the
    PersistentIssueEscalation prompt section).
    """
    lines: List[str] = []
    results: Dict[str, Any] = {}
    skipped = predicates[max_predicates:]

    for predicate in predicates[:max_predicates]:
        sweep = scope_sweep(model_text, predicate, check)
        entry: Dict[str, Any] = {'scope_sweep': sweep}

        if sweep.get('performed') and sweep.get('sat_at_larger_scope') is True:
            lines.append(
                f"  - '{predicate}' SCOPE VERDICT: SATISFIABLE at enlarged bounds "
                f"({sweep['swept_command']}) -> bounded-search artifact, NOT a requirement conflict."
            )
            results[predicate] = entry
            continue

        if sweep.get('performed'):
            lines.append(
                f"  - '{predicate}' SCOPE VERDICT: still UNSAT at enlarged bounds "
                f"({sweep['swept_command']}) -> genuine over-constraint."
            )

        localization = localize_blocking_facts(
            model_text, predicate, check, max_runs=max_runs_per_predicate)
        entry['localization'] = localization

        if localization['verdict'] == 'localized':
            facts_list = ', '.join(localization['blocking_facts']) or '(none)'
            req_list = ', '.join(localization['implicated_requirements']) or 'none identifiable from names'
            qualifier = ' (approximate - run budget hit)' if localization['approximate'] else ''
            lines.append(
                f"  - '{predicate}' MINIMAL BLOCKING FACT SET{qualifier}: {facts_list} "
                f"-> implicated requirements: {req_list} "
                f"(proven by {localization['runs']} Analyzer runs: disabling this set makes the predicate SAT)"
            )
        elif localization['verdict'] == 'internal_contradiction':
            lines.append(
                f"  - '{predicate}' MINIMAL BLOCKING FACT SET: NONE - the predicate is UNSAT even "
                f"with ALL facts disabled. The contradiction is INSIDE the predicate body or the "
                f"signature declarations/multiplicities it uses."
            )
        results[predicate] = entry

        if logger and hasattr(logger, 'log'):
            logger.log(f"[SEMANTIC_DIAGNOSTICS] {predicate}: {entry}")

    if skipped:
        lines.append(f"  - (diagnosis capped: not run for {', '.join(skipped)})")

    text = ""
    if lines:
        text = ("DETERMINISTIC DIAGNOSIS (Alloy Analyzer experiments - measured, "
                "not hypothesized):\n" + "\n".join(lines))
    return {'directive_text': text, 'results': results}


def make_alloy_sat_checker(executor, work_dir: Path, timeout: int = 120, logger=None) -> CheckFn:
    """
    Production adapter: run a model variant through AlloyExecutor and report
    the target predicate's satisfiability. True=SAT, False=UNSAT, None=the
    variant failed (syntax error, tool failure, or timeout).
    """
    work_dir = Path(work_dir)
    counter = {'n': 0}

    def check(model_text: str, predicate: str) -> Optional[bool]:
        counter['n'] += 1
        work_dir.mkdir(parents=True, exist_ok=True)
        model_file = work_dir / f"diag_{counter['n']}.als"
        model_file.write_text(model_text)
        result = executor.execute(
            model_path=model_file,
            output_dir=work_dir / f"diag_{counter['n']}_out",
            timeout=timeout,
        )
        if not result.get('success'):
            return None
        analysis = result.get('analysis', {})
        if analysis.get('has_syntax_errors'):
            if logger and hasattr(logger, 'log'):
                logger.log(f"[SEMANTIC_DIAGNOSTICS] variant {counter['n']} has syntax errors - skipping")
            return None
        unsat_names = {u.get('name') for u in analysis.get('unsat_run_commands', [])}
        if predicate in unsat_names:
            return False
        if analysis.get('has_results'):
            return True
        return None

    return check
