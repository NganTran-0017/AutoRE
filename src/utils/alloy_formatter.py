"""
Utility for formatting Alloy Analyzer results for LLM consumption.

Implements priority-based context building:
1. Syntax errors (highest priority) - no instance data
2. UNSAT predicates - full model analysis
3. Counterexamples - first complete + other names
4. Satisfying instances - most comprehensive (All_Requirements)
"""
import json
from typing import Dict, Any, List, Optional


def find_most_comprehensive_instance(instances: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Find the most comprehensive satisfying instance.

    Priority:
    1. Command name = "All_Requirements"
    2. Command name starts with longest "R" chain (e.g., R1R2R3 > R1R2 > R1)
    4. Last instance

    Args:
        instances: List of instance dictionaries with 'command_name' and 'data'

    Returns:
        Most comprehensive instance or None if list is empty
    """
    if not instances:
        return None

    # Priority 1: Look for "All_Requirements"
    for inst in instances:
        if inst['command_name'] == 'All_Requirements':
            return inst

    # Priority 2: Find longest R-chain (R1R2R3 > R1R2 > R1)
    r_chain_instances = []
    for inst in instances:
        cmd_name = inst['command_name']
        # Count consecutive R digits (R1, R1R2, R1R2R3, etc.)
        if cmd_name.startswith('R') and any(c.isdigit() for c in cmd_name):
            # Count how many R-number pairs
            r_count = cmd_name.count('R')
            r_chain_instances.append((r_count, inst))

    if r_chain_instances:
        # Sort by R-count descending, return highest
        r_chain_instances.sort(key=lambda x: x[0], reverse=True)
        return r_chain_instances[0][1]

    
    return None


def build_priority_context(
    execution_result: Dict[str, Any],
    requirements: str,
    alloy_model: str
) -> Dict[str, Any]:
    """
    Build evaluation context based on priority.

    Priority order:
    1. Syntax errors → Skip counterexample/instance data
    2. UNSAT predicates → Include UNSAT command info
    3. Counterexamples → Include first complete + other assertion names
    4. Satisfying instances → Include most comprehensive (All_Requirements)

    Args:
        execution_result: Results from AlloyExecutor
        requirements: Requirements document
        alloy_model: Alloy model content

    Returns:
        Dictionary with priority-based context for LLM
    """
    analysis = execution_result.get('analysis', {})

    context = {
        'requirements': requirements,
        'alloy_model': alloy_model,
        'has_syntax_errors': analysis.get('has_syntax_errors', False),
        'has_counterexamples': analysis.get('has_counterexamples', False),
        'has_satisfying_instances': analysis.get('has_satisfying_instances', False),
        'has_unsat_runs': len(analysis.get('unsat_run_commands', [])) > 0,
        'has_passing_assertions': len(analysis.get('unsat_check_commands', [])) > 0,
        # Ratios for summary
        'num_syntax_errors': len(analysis.get('syntax_errors', [])),
        'num_counterexamples': len(analysis.get('counterexamples', [])),
        'num_instances': len(analysis.get('instances', [])),
        'num_unsat_runs': len(analysis.get('unsat_run_commands', [])),
        'num_passing_assertions': len(analysis.get('unsat_check_commands', [])),
        'total_run_commands': analysis.get('total_run_commands', 0),
        'total_check_commands': analysis.get('total_check_commands', 0)
    }

    # Priority 1: Syntax Errors (HIGHEST)
    if context['has_syntax_errors']:
        context['priority'] = 'syntax_errors'
        context['syntax_errors'] = analysis.get('syntax_errors', [])
        # DO NOT include counterexamples or instances
        context['include_counterexamples'] = False
        context['include_instances'] = False
        return context

    # Priority 2: UNSAT Run Commands (Overconstraint)
    if context['has_unsat_runs']:
        context['priority'] = 'unsat_runs'
        context['unsat_run_commands'] = analysis.get('unsat_run_commands', [])
        context['include_counterexamples'] = False
        context['include_instances'] = False
        return context

    # Priority 3: Counterexamples
    if context['has_counterexamples']:
        context['priority'] = 'counterexamples'
        counterexamples = analysis.get('counterexamples', [])

        # Include first complete counterexample (as JSON)
        if counterexamples:
            context['first_counterexample'] = {
                'assertion_name': counterexamples[0]['command_name'],
                'file': counterexamples[0]['file'],
                'data': counterexamples[0]['data']  # Keep as JSON
            }

            # Include names of other failed assertions
            if len(counterexamples) > 1:
                context['other_failed_assertions'] = [
                    ce['command_name'] for ce in counterexamples[1:]
                ]

        context['include_counterexamples'] = True
        context['include_instances'] = False
        return context

    # Priority 4: Satisfying Instances (LOWEST)
    if context['has_satisfying_instances']:
        context['priority'] = 'satisfying_instances'
        instances = analysis.get('instances', [])

        # Find most comprehensive instance (All_Requirements)
        most_comprehensive = find_most_comprehensive_instance(instances)

        if most_comprehensive:
            context['comprehensive_instance'] = {
                'command_name': most_comprehensive['command_name'],
                'file': most_comprehensive['file'],
                'data': most_comprehensive['data']  # Keep as JSON
            }

            # Include names of other instance commands
            other_instances = [
                inst['command_name'] for inst in instances
                if inst['command_name'] != most_comprehensive['command_name']
            ]
            if other_instances:
                context['other_instance_commands'] = other_instances

        context['include_counterexamples'] = False
        context['include_instances'] = True
        return context

    # No issues found - just requirements and model
    context['priority'] = 'no_issues'
    context['include_counterexamples'] = False
    context['include_instances'] = False
    return context


def format_context_for_prompt(context: Dict[str, Any]) -> str:
    """
    Format priority context into text for LLM prompt.

    Args:
        context: Context dictionary from build_priority_context()

    Returns:
        Formatted text for inclusion in LLM prompt
    """
    lines = []

    # Always include summary with ratios
    lines.extend([
        "ANALYSIS CONTEXT:",
        f"Priority: {context['priority'].upper().replace('_', ' ')}",
        ""
    ])
    
    # Primary issue summary (based on priority)
    if context['priority'] == 'syntax_errors':
        lines.append(f"PRIMARY ISSUE: {context['num_syntax_errors']} Syntax Error(s)")
    elif context['priority'] == 'unsat_runs':
        lines.append(f"PRIMARY ISSUE: {context['num_unsat_runs']}/{context['total_run_commands']} Run Commands UNSAT (Overconstraint)")
    elif context['priority'] == 'counterexamples':
        lines.append(f"PRIMARY ISSUE: {context['num_counterexamples']}/{context['total_check_commands']} Assertion(s) Failed (Counterexamples)")
    elif context['priority'] == 'satisfying_instances':
        lines.append(f"PRIMARY ISSUE: Validating {context['num_instances']}/{context['total_run_commands']} Satisfying Instance(s)")
    else:
        lines.append("PRIMARY ISSUE: None (All checks passed)")
    
    lines.append("")
    
    # Secondary issues summary (always show)
    lines.append("SECONDARY ISSUES:")
    lines.append(f"- Syntax Errors: {context['num_syntax_errors']}")
    lines.append(f"- Overconstraint (run UNSAT): {context['num_unsat_runs']}/{context['total_run_commands']}")
    lines.append(f"- Failed Assertions (counterexamples): {context['num_counterexamples']}/{context['total_check_commands']}")
    lines.append(f"- Passing Assertions (check UNSAT): {context['num_passing_assertions']}/{context['total_check_commands']}")
    lines.append(f"- Satisfying Instances (run SAT): {context['num_instances']}/{context['total_run_commands']}")
    lines.append("")

    # Priority 1: Syntax Errors
    if context['priority'] == 'syntax_errors':
        lines.append("SYNTAX ERRORS (MUST FIX FIRST!):")
        lines.append("")
        for i, err in enumerate(context['syntax_errors'], 1):
            if isinstance(err, dict):
                lines.append(f"{i}. Line {err.get('line', '?')}, Column {err.get('column', '?')}")
                if err.get('message'):
                    lines.append(f"   {err['message']}")
                if err.get('context'):
                    lines.append(f"   Context: {err['context']}")
            else:
                lines.append(f"{i}. {str(err)}")
        lines.append("")
        lines.append("NOTE: Counterexamples and instances not shown - fix syntax errors first.")
        lines.append("")

    # Priority 2: UNSAT Run Commands (Overconstraint)
    elif context['priority'] == 'unsat_runs':
        lines.append("OVERCONSTRAINT DETECTED (run commands cannot find instances):")
        lines.append("")
        for cmd in context['unsat_run_commands']:
            lines.append(f"- {cmd['type']} {cmd['name']} (command #{cmd['number']})")
        lines.append("")
        lines.append("TASK: Analyze the Alloy model to identify over-constraints.")
        lines.append("These predicates cannot produce any valid instances - the model is too restrictive.")
        lines.append("")

    # Priority 3: Counterexamples
    elif context['priority'] == 'counterexamples':
        lines.append("COUNTEREXAMPLE ANALYSIS:")
        lines.append("")

        if 'first_counterexample' in context:
            ce = context['first_counterexample']
            lines.append(f"Failed Assertion: {ce['assertion_name']}")
            lines.append(f"File: {ce['file']}")
            lines.append("")
            lines.append("Counterexample Instance (JSON):")
            lines.append(json.dumps(ce['data'], indent=2))
            lines.append("")

        if 'other_failed_assertions' in context:
            lines.append("Other Failed Assertions:")
            for name in context['other_failed_assertions']:
                lines.append(f"- {name}")
            lines.append("")

        lines.append("TASK: Analyze why this counterexample violates the assertion.")
        lines.append("Describe the scenario, why it's wrong, and how to fix the model.")
        lines.append("")

    # Priority 4: Satisfying Instances
    elif context['priority'] == 'satisfying_instances':
        lines.append("SATISFYING INSTANCE ANALYSIS:")
        lines.append("")

        if 'comprehensive_instance' in context:
            inst = context['comprehensive_instance']
            lines.append(f"Most Comprehensive Instance: {inst['command_name']}")
            lines.append(f"File: {inst['file']}")
            lines.append("")
            lines.append("Instance Data (JSON):")
            lines.append(json.dumps(inst['data'], indent=2))
            lines.append("")

        if 'other_instance_commands' in context:
            lines.append("Other Instance Commands (incremental verification):")
            for name in context['other_instance_commands']:
                lines.append(f"- {name}")
            lines.append("")

        lines.append("TASK: Check if this instance reflects intended behavior.")
        lines.append("Look for:")
        lines.append("- Trivial/degenerate cases")
        lines.append("- Missing scenarios")
        lines.append("- Vacuity (assertions passing for wrong reasons)")
        lines.append("- Underspecification (model allows invalid states)")
        lines.append("")

    return "\n".join(lines)


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Count actual tokens in text using tiktoken.
    
    Falls back to approximation if tiktoken not available.

    Args:
        text: Text to count tokens for
        model: Model name (for tiktoken encoding)

    Returns:
        Token count
    """
    try:
        import tiktoken
        
        # Get encoding for model
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            # Fallback to cl100k_base for GPT-4 and newer models
            encoding = tiktoken.get_encoding("cl100k_base")
        
        return len(encoding.encode(text))
    
    except ImportError:
        # Fallback: Use better approximation
        # GPT-4 tokenizer: ~1 token per 4 characters on average
        # But this varies significantly by content type
        
        # More accurate heuristic:
        # - Average English word: ~1.3 tokens
        # - Code/JSON: ~1 token per 3-4 characters
        # - Whitespace is usually separate tokens
        
        # Simple approximation: count words and characters
        words = len(text.split())
        chars = len(text)
        
        # Weighted estimate:
        # - Word-based: words * 1.3
        # - Char-based: chars / 4
        # Take average of both
        word_estimate = words * 1.3
        char_estimate = chars / 4
        
        return int((word_estimate + char_estimate) / 2)
