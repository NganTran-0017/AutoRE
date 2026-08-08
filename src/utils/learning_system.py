"""
Learning system for coordinating learning across agents.
"""
from typing import List, Optional
import re
from .memory_system import LongTermMemorySystem


class LearningSystem:
    """
    Coordinates learning across agents and actions.

    Responsibilities:
    - Parse learning signals from agent outputs
    - Store in memory with proper tagging
    - Provide formatted learning summaries for prompts

    Learning signals in agent output:
        [LESSON]: Don't use undefined predicates in assertions
        [PATTERN]: Counterexamples often indicate missing constraints
        [EVENT]: User requested focus on security properties
    """

    def __init__(self, memory: LongTermMemorySystem):
        """
        Initialize learning system.

        Args:
            memory: Long-term memory system to store learning
        """
        self.memory = memory

    def parse_and_record(
        self,
        agent_output: str,
        agent_name: str,
        action_name: str,
        iteration: int,
        defer_storage: bool = False
    ):
        """
        Parse agent output for learning signals, store them, and return cleaned output.

        Looks for patterns:
        - [LESSON]: <text>
        - [EVENT]: <text>

        Args:
            agent_output: The agent's output text
            agent_name: Name of the agent
            action_name: Name of the action
            iteration: Current iteration number
            defer_storage: If True, extract lessons without storing them (caller
                stages them until a later confirmation decides whether to store).
                Events are always stored immediately regardless of this flag.

        Returns:
            Cleaned output with learning markers removed (defer_storage=False),
            or a (cleaned_output, lessons, retractions) tuple (defer_storage=True)
        """
        # Extract lessons; store immediately unless deferred
        lessons = self._extract_marked_content(agent_output, "LESSON")
        if not defer_storage:
            for lesson in lessons:
                self.memory.store(
                    content=lesson,
                    item_type="lesson",
                    agent=agent_name,
                    action=action_name,
                    iteration=iteration
                )

        # Extract and store modeling conventions (project-specific encoding
        # decisions). Stored immediately - never deferred - because the model
        # builder must be able to rely on them every subsequent iteration.
        conventions = self._extract_marked_content(agent_output, "CONVENTION")
        convention_decisions = []
        for convention in conventions:
            _stored, decision = self._store_convention_if_new(
                convention, agent_name, action_name, iteration, gated=defer_storage
            )
            if decision:
                convention_decisions.append(decision)

        # Extract convention retractions: the RE signalling that a previously
        # recorded binding convention is now outdated/incorrect. Retractions are
        # ONLY honoured on the deferred path (UpdateAlloyModel) and ride the same
        # defer/confirm gate as lessons. Staging immediately marks the matched
        # convention "pending_withdrawn" so it stops being injected while the fix
        # is on probation; the workflow later finalizes it to "superseded" (fix
        # confirmed) or restores it to "active" (fix discarded). Non-deferred
        # actions never retract (no convention exists at the initial build step).
        retractions = self._stage_retractions(agent_output, iteration) if defer_storage else []

        # A merge or a suspension decided while storing a convention rides the
        # SAME defer/confirm gate as an explicit retraction - both are "this
        # convention changed because of a fix that has not proven itself yet",
        # and both are undone by the same signal. Carrying them in one list
        # means the workflow needs no new plumbing to settle them.
        retractions.extend(convention_decisions)

        # Extract and store events (never deferred)
        events = self._extract_marked_content(agent_output, "EVENT")
        for event in events:
            self.memory.store(
                content=event,
                item_type="event",
                agent=agent_name,
                action=action_name,
                iteration=iteration
            )

        # Remove learning markers from output
        cleaned_output = self._remove_learning_markers(agent_output)

        if defer_storage:
            return cleaned_output, lessons, retractions
        return cleaned_output

    def _parse_retractions(self, text: str) -> List[dict]:
        """
        Extract [CONVENTION_RETRACT] markers into {'text', 'reason'} dicts.

        Format: [CONVENTION_RETRACT]: <quote of the wrong convention> || <why>
        The quoted text is used for a semantic match against stored conventions;
        the reason is kept for the audit trail.
        """
        parsed = []
        for raw in self._extract_marked_content(text, "CONVENTION_RETRACT"):
            body, _, reason = raw.partition("||")
            if body.strip():
                parsed.append({'text': body.strip(), 'reason': reason.strip()})
        return parsed

    def _stage_retractions(self, agent_output: str, iteration: int) -> List[dict]:
        """
        Parse retraction markers and provisionally withdraw the matched
        conventions (status -> "pending_withdrawn"), so they stop being injected
        while the motivating fix is on probation. Each returned dict carries the
        matched convention `id` (None if no confident match) for the workflow to
        later finalize (-> superseded) or revert (-> active).
        """
        can_mark = hasattr(self.memory, "mark_convention_pending_withdrawn")
        staged = []
        for r in self._parse_retractions(agent_output):
            conv_id = (
                self.memory.mark_convention_pending_withdrawn(
                    r['text'], r['reason'], iteration)
                if can_mark else None
            )
            staged.append({**r, 'id': conv_id})
        return staged

    def apply_convention_retractions(self, retractions: List[dict], iteration: int) -> None:
        """
        Finalize everything staged against the confirmed fix.

        Called from the workflow's defer/confirm gate once the fix that
        motivated these changes is confirmed to have resolved the issue - so a
        convention is only permanently withdrawn, and a merge only made
        permanent, when the change that superseded it stuck.

        Three kinds ride this list (`kind`, defaulting to "retract" for the
        records that predate the others):
          retract  - the RE said an existing convention is outdated
          conflict - a new convention contradicted an existing one
          merge    - a new convention was folded into an existing one
        """
        if not retractions or not hasattr(self.memory, "finalize_convention_retraction"):
            return
        for r in retractions:
            kind = r.get('kind', 'retract')
            item_type = r.get('item_type', 'convention')
            conv_id = r.get('id')
            if not conv_id:
                continue
            try:
                if kind == 'merge':
                    self.memory.finalize_merge(conv_id, item_type)
                else:
                    # retract and conflict both end the same way: the item that
                    # was set aside is now permanently superseded.
                    self.memory.finalize_retraction(conv_id, iteration, item_type)
            except Exception as e:
                print(f"Warning: convention {kind} finalize failed: {e}")

    def revert_convention_retractions(self, retractions: List[dict]) -> None:
        """
        Undo everything staged against a fix that did not hold.

        Called when the fix is discarded (issue unresolved or recurred on
        probation). Each kind is undone in the direction that restores what the
        run was relying on before the fix: a withdrawn convention goes back into
        circulation, a merged row goes back to its pre-merge wording, and a
        contradiction puts the OLD convention back and withdraws the new one -
        the new one never earned its place, and leaving it active would keep
        injecting the reading that just failed.
        """
        if not retractions or not hasattr(self.memory, "restore_convention"):
            return
        for r in retractions:
            kind = r.get('kind', 'retract')
            item_type = r.get('item_type', 'convention')
            conv_id = r.get('id')
            if not conv_id:
                continue
            try:
                if kind == 'merge':
                    self.memory.restore_merge(conv_id, item_type)
                    continue
                self.memory.restore_item(conv_id, item_type)
                if kind == 'conflict' and r.get('new_id'):
                    self.memory.finalize_retraction(
                        r['new_id'], r.get('iteration', 0), item_type
                    )
            except Exception as e:
                print(f"Warning: convention {kind} revert failed: {e}")

    def _extract_marked_content(self, text: str, marker: str) -> List[str]:
        """
        Extract content marked with [MARKER]: syntax.

        Handles both the single-line format (**[LESSON]: text) and the
        multi-line bulleted format (**[LESSON]:**\\n- item\\n- item) that
        agents also emit. The multi-line block is consumed first so its
        header line isn't re-matched by the single-line pattern (which
        would otherwise capture the trailing "**" as a bogus lesson).

        Args:
            text: Text to search
            marker: Marker name (e.g., "LESSON", "PATTERN")

        Returns:
            List of extracted content strings
        """
        results: List[str] = []

        def _consume_block(match: re.Match) -> str:
            for bullet_line in match.group(1).splitlines():
                content = re.sub(r'^\s*[-*]\s+', '', bullet_line).strip()
                if content:
                    results.append(content)
            return ''

        multi_line_pattern = rf'^\s*\*?\*?\[{marker}\]:\*?\*?\s*\n((?:^\s*[-*]\s+.+$\n?)+)'
        text = re.sub(multi_line_pattern, _consume_block, text, flags=re.MULTILINE)

        single_line_pattern = rf'\[{marker}\]:\s*(.+?)(?:\n|$)'
        for match in re.finditer(single_line_pattern, text, re.MULTILINE):
            content = match.group(1).strip()
            # Skip empty captures and markdown-punctuation-only junk (e.g. "**")
            if content and not re.fullmatch(r'[\*\-\s]*', content):
                results.append(content)

        return results

    def _remove_learning_markers(self, text: str) -> str:
        """
        Remove all learning markers from text.

        Removes:
        - [LESSON]: <single line text>
        - [LESSON]: <multi-line with bullets>
        - [EVENT]: <single line text>
        - [EVENT]: <multi-line with bullets>
        - [PATTERN]: <text> (legacy, no longer used but cleaned for backward compatibility)

        Args:
            text: Text with learning markers

        Returns:
            Text with markers removed
        """
        # Remove learning markers and their content
        # Handles both single-line and multi-line (bullet list) formats.
        # The multi-line pattern must run first: its header line
        # (**[LESSON]:**) is also a valid match for the single-line
        # pattern, which would otherwise strip the header and leave the
        # multi-line pattern nothing to anchor on, orphaning the bullets.

        # Pattern 1: Multi-line format: **[LESSON]:** followed by bullet points
        # Remove marker line followed by consecutive lines starting with - or *
        text = re.sub(
            r'^\s*\*?\*?\[LESSON\]:\*?\*?\s*\n(^\s*[-*]\s+.+$\n?)+',
            '',
            text,
            flags=re.MULTILINE
        )
        text = re.sub(
            r'^\s*\*?\*?\[EVENT\]:\*?\*?\s*\n(^\s*[-*]\s+.+$\n?)+',
            '',
            text,
            flags=re.MULTILINE
        )
        text = re.sub(
            r'^\s*\*?\*?\[PATTERN\]:\*?\*?\s*\n(^\s*[-*]\s+.+$\n?)+',
            '',
            text,
            flags=re.MULTILINE
        )
        text = re.sub(
            r'^\s*\*?\*?\[CONVENTION\]:\*?\*?\s*\n(^\s*[-*]\s+.+$\n?)+',
            '',
            text,
            flags=re.MULTILINE
        )
        text = re.sub(
            r'^\s*\*?\*?\[CONVENTION_RETRACT\]:\*?\*?\s*\n(^\s*[-*]\s+.+$\n?)+',
            '',
            text,
            flags=re.MULTILINE
        )

        # Pattern 2: Single-line format: **[LESSON]: text on same line
        text = re.sub(r'^\s*\*?\*?\[LESSON\]:\s*.+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\*?\*?\[EVENT\]:\s*.+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\*?\*?\[PATTERN\]:\s*.+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\*?\*?\[CONVENTION_RETRACT\]:\s*.+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\*?\*?\[CONVENTION\]:\s*.+$', '', text, flags=re.MULTILINE)

        # Clean up excessive blank lines (more than 2 consecutive)
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def get_lessons_for_prompt(
        self,
        agent_name: str,
        action_name: str,
        limit: int = 10
    ) -> str:
        """
        Format recent lessons for prompt inclusion.

        Args:
            agent_name: Agent to get lessons for
            action_name: Action to get lessons for
            limit: Maximum number of lessons

        Returns:
            Formatted string ready for prompt insertion
        """
        lessons = self.memory.get_lessons(
            agent=agent_name,
            action=action_name,
            limit=limit
        )

        if not lessons:
            return ""

        lines = ["Previous Lessons Learned:"]
        for i, lesson in enumerate(lessons, 1):
            lines.append(f"{i}. {lesson}")

        return "\n".join(lines)

    @staticmethod
    def _normalize_convention(text: str) -> str:
        """
        Fold the differences that make two conventions the same rule.

        Case and whitespace, plus trailing punctuation: the shadow log's only
        near-identical pair differed by a single trailing period, which slipped
        past this guard and cost a full semantic comparison to catch at 0.99.
        """
        return ' '.join((text or '').lower().split()).rstrip('.;:,!').strip()

    def _store_convention_if_new(
        self,
        convention: str,
        agent_name: str,
        action_name: str,
        iteration: int,
        gated: bool = False
    ) -> tuple:
        """
        Store a modeling convention unless an exact-text match already exists.

        The exact check runs first and is deliberate: it is deterministic and
        free, so a convention repeated verbatim every iteration never reaches
        the classifier at all. What survives it goes through the same banded
        dedup lessons use - drop / classify-and-merge / new.

        Args:
            gated: True on the defer/confirm path, where the caller can settle a
                merge or a suspension once the motivating fix is judged.

        Returns:
            (stored, decision) - `stored` False when skipped as an exact
            duplicate; `decision` a dict the caller must settle later, or None.
        """
        normalized = self._normalize_convention(convention)
        try:
            existing = self.memory.get_conventions(limit=200)
        except Exception:
            existing = []
        for item in existing:
            if self._normalize_convention(item) == normalized:
                return False, None

        kwargs = dict(
            content=convention,
            item_type="convention",
            agent=agent_name,
            action=action_name,
            iteration=iteration,
        )
        # The traditional store has no gated lifecycle. Test for the parameter
        # rather than catching TypeError, which would also swallow a genuine
        # signature error inside store() and then write the convention twice.
        if gated and self._store_accepts_gated():
            kwargs["gated"] = True
        return True, self.memory.store(**kwargs)

    def _store_accepts_gated(self) -> bool:
        """True when the memory backend's store() can defer a decision."""
        import inspect

        try:
            return 'gated' in inspect.signature(self.memory.store).parameters
        except (TypeError, ValueError):
            return False

    def get_conventions_for_prompt(
        self,
        agent_name: str = None,
        action_name: str = None,
        limit: int = 50
    ) -> str:
        """
        Format ALL modeling conventions for prompt inclusion.

        Conventions are model-wide encoding decisions injected in full every
        iteration (not semantically filtered), so agent/action default to None
        and the limit is generous.

        Returns:
            Formatted string ready for prompt insertion (empty if none).
        """
        conventions = self.memory.get_conventions(
            agent=agent_name,
            action=action_name,
            limit=limit
        )

        if not conventions:
            return ""

        lines = ["Established Modeling Conventions (binding - apply all):"]
        for i, convention in enumerate(conventions, 1):
            lines.append(f"{i}. {convention}")

        return "\n".join(lines)

    def get_patterns_for_prompt(
        self,
        agent_name: str,
        action_name: str,
        limit: int = 5
    ) -> str:
        """
        Format recent patterns for prompt inclusion.

        Args:
            agent_name: Agent to get patterns for
            action_name: Action to get patterns for
            limit: Maximum number of patterns

        Returns:
            Formatted string ready for prompt insertion
        """
        patterns = self.memory.get_patterns(
            agent=agent_name,
            action=action_name,
            limit=limit
        )

        if not patterns:
            return ""

        lines = ["Observed Patterns:"]
        for i, pattern in enumerate(patterns, 1):
            lines.append(f"{i}. {pattern}")

        return "\n".join(lines)

    def get_all_learning_for_prompt(
        self,
        agent_name: str,
        action_name: str,
        lesson_limit: int = 10,
        pattern_limit: int = 5
    ) -> str:
        """
        Get all learning (lessons + patterns) formatted for prompt.

        Args:
            agent_name: Agent name
            action_name: Action name
            lesson_limit: Max lessons to include
            pattern_limit: Max patterns to include

        Returns:
            Formatted string with both lessons and patterns
        """
        sections = []

        # Add lessons
        lessons_str = self.get_lessons_for_prompt(
            agent_name, action_name, lesson_limit
        )
        if lessons_str:
            sections.append(lessons_str)

        # Add patterns
        patterns_str = self.get_patterns_for_prompt(
            agent_name, action_name, pattern_limit
        )
        if patterns_str:
            sections.append(patterns_str)

        return "\n\n".join(sections) if sections else ""

    def get_lessons_semantic(
        self,
        query: str,
        agent_name: str,
        action_name: str,
        limit: int = 10
    ) -> str:
        """
        Get lessons using semantic search based on query context.

        If semantic memory is available, retrieves lessons similar to the query.
        Otherwise, falls back to tag-based retrieval.

        Args:
            query: Query text describing current context/problem
            agent_name: Agent to get lessons for
            action_name: Action to get lessons for
            limit: Maximum number of lessons

        Returns:
            Formatted string ready for prompt insertion
        """
        # Check if semantic memory is available
        if hasattr(self.memory, 'retrieve_similar'):
            # Use semantic search
            lessons = self.memory.get_lessons(
                agent=agent_name,
                action=action_name,
                limit=limit,
                query=query
            )
        else:
            # Fall back to tag-based retrieval
            lessons = self.memory.get_lessons(
                agent=agent_name,
                action=action_name,
                limit=limit
            )

        if not lessons:
            return ""

        lines = ["Previous Lessons Learned:"]
        for i, lesson in enumerate(lessons, 1):
            lines.append(f"{i}. {lesson}")

        return "\n".join(lines)

    def record_lesson(
        self,
        lesson: str,
        agent_name: str,
        action_name: str,
        iteration: int,
        verified: bool = False
    ):
        """
        Directly record a lesson (without parsing).

        Useful for programmatically adding lessons.

        Args:
            lesson: Lesson text
            agent_name: Agent name
            action_name: Action name
            iteration: Current iteration
            verified: True when the lesson already cleared the probation gate.
                Only then may it retire a lesson it contradicts.
        """
        self.memory.store(
            content=lesson,
            item_type="lesson",
            agent=agent_name,
            action=action_name,
            iteration=iteration,
            verified=verified
        )

    def resolve_lesson_conflicts(
        self, resolved: bool, iteration: int,
        source_iteration: Optional[int] = None,
        lesson_texts: Optional[List[str]] = None
    ) -> int:
        """
        Settle lesson contradictions raised while storing unverified lessons.

        Mirrors apply_/revert_convention_retractions: the run's outcome decides
        which of two contradicting lessons survives, never which arrived later.
        Pass `lesson_texts` to settle only the conflicts THESE lessons raised -
        an iteration is not an identity, and two lessons written in the same
        iteration have unrelated fates.

        No-op on memory backends without the lifecycle (the traditional store).
        """
        if not hasattr(self.memory, "resolve_lesson_conflicts"):
            return 0
        try:
            return self.memory.resolve_lesson_conflicts(
                resolved, iteration, source_iteration, lesson_texts
            )
        except TypeError:
            # A backend on the older signature, without the per-lesson key.
            return self.memory.resolve_lesson_conflicts(
                resolved, iteration, source_iteration
            )
        except Exception as e:
            print(f"Warning: lesson conflict resolution failed: {e}")
            return 0

    def expire_lesson_conflicts(self, current_iteration: int) -> int:
        """
        Undo suspensions that have waited past the configured window.

        The provisional window is kept, but bounded: without this a conflict
        raised by a lesson that has no outcome to wait for leaves the older
        lesson withdrawn for the rest of the run, and across every restart after
        it. Returns how many were restored.
        """
        if not hasattr(self.memory, "expire_stale_lesson_conflicts"):
            return 0
        try:
            return self.memory.expire_stale_lesson_conflicts(current_iteration)
        except Exception as e:
            print(f"Warning: lesson conflict expiry failed: {e}")
            return 0

    def record_convention(
        self,
        convention: str,
        agent_name: str,
        action_name: str,
        iteration: int
    ) -> bool:
        """
        Directly record a modeling convention (without parsing), skipping
        exact-duplicate content.

        Returns:
            True if stored, False if skipped as a duplicate.
        """
        stored, _decision = self._store_convention_if_new(
            convention, agent_name, action_name, iteration
        )
        return stored

    def record_pattern(
        self,
        pattern: str,
        agent_name: str,
        action_name: str,
        iteration: int
    ):
        """
        Directly record a pattern (without parsing).

        Args:
            pattern: Pattern text
            agent_name: Agent name
            action_name: Action name
            iteration: Current iteration
        """
        self.memory.store(
            content=pattern,
            item_type="pattern",
            agent=agent_name,
            action=action_name,
            iteration=iteration
        )

    def record_event(
        self,
        event: str,
        agent_name: str,
        action_name: str,
        iteration: int
    ):
        """
        Directly record an event (without parsing).

        Args:
            event: Event text
            agent_name: Agent name
            action_name: Action name
            iteration: Current iteration
        """
        self.memory.store(
            content=event,
            item_type="event",
            agent=agent_name,
            action=action_name,
            iteration=iteration
        )

    def __repr__(self) -> str:
        stats = self.memory.get_stats()
        return (
            f"LearningSystem("
            f"lessons={stats['by_type'].get('lesson', 0)}, "
            f"patterns={stats['by_type'].get('pattern', 0)}, "
            f"events={stats['by_type'].get('event', 0)})"
        )


class LessonProbation:
    """
    Holds resolved-issue lessons on probation until their target issue stays
    resolved for several consecutive iterations.

    Previously a staged lesson was confirmed the moment its target issue was
    observed resolved for a SINGLE iteration - so in an oscillating error loop
    (A, B, A, B...) the lesson for "fixing A" was stored at the B iteration
    even though A came right back. Probation defers confirmation and discards
    the lesson if the issue recurs while on probation.

    Deterministic and non-persistent (like the pending_* staging attributes,
    probation state lives only for the current run).
    """

    def __init__(self, required_clean_iterations: int = 3, logger=None):
        """
        Args:
            required_clean_iterations: How many consecutive iterations the
                target issue must be observed absent (counting the iteration
                where resolution was first seen) before the lesson is stored.
            logger: Optional logger with a .log(str) method.
        """
        self.required_clean_iterations = required_clean_iterations
        self.items = []
        self.logger = logger

    def add(self, pending, target_issue, target_signature, resolved_at_iteration,
            target_fingerprint=None):
        """
        Place a staged lesson on probation.

        Args:
            pending: The pending-lesson dict ({'lessons', 'agent_name',
                'action_name', 'source_iteration'}).
            target_issue: The issue string the lesson's fix targeted (the
                source iteration's entry.issue).
            target_signature: The normalized error signature of the target
                issue (from ErrorNormalizer), or None for semantic issues.
            resolved_at_iteration: Iteration where resolution was first seen
                (counts as the first clean iteration).
            target_fingerprint: The target error's fine-grained detail
                fingerprint (operand type + nearby token), used to avoid
                treating a different same-signature error as a recurrence.
        """
        self.items.append({
            'pending': pending,
            'target_issue': target_issue or '',
            'target_signature': target_signature,
            'target_fingerprint': target_fingerprint,
            'resolved_at': resolved_at_iteration,
            'clean_count': 1,
        })

    def evaluate(self, current_iteration, current_issue, current_signature, syntax_ok,
                 current_fingerprint=None):
        """
        Advance probation by one iteration.

        An item is DISCARDED if its target issue recurred (same normalized
        signature, or overlapping issue components). It progresses only on
        iterations where its absence is observable: syntax-error iterations
        cannot show whether a semantic issue (unsat predicate/counterexample)
        is still present, so they neither advance nor break semantic items.

        Returns:
            (confirmed, discarded): lists of probation items removed this
            iteration. Confirmed items are ready to be stored in memory.
        """
        confirmed, discarded, keep = [], [], []
        for item in self.items:
            if self._recurred(item, current_issue, current_signature, current_fingerprint):
                discarded.append(item)
                continue
            semantic_target = ('unsat predicate' in item['target_issue']
                               or 'counterexample' in item['target_issue'])
            observable = syntax_ok or not semantic_target
            if observable:
                item['clean_count'] += 1
            if item['clean_count'] >= self.required_clean_iterations:
                confirmed.append(item)
            else:
                keep.append(item)
        self.items = keep

        for item in confirmed:
            self._log_item(item, f"✅ confirmed after {item['clean_count']} clean iterations")
        for item in discarded:
            self._log_item(item, f"🗑️ discarded - target issue recurred at iteration {current_iteration}")
        return confirmed, discarded

    def flush(self):
        """Remove and return all remaining probation items (e.g. to confirm
        them on convergence, when hard metrics prove no issues remain)."""
        items, self.items = self.items, []
        return items

    def _recurred(self, item, current_issue, current_signature, current_fingerprint=None):
        from .regression_log import issues_match
        return issues_match(
            item['target_issue'], item['target_signature'],
            current_issue, current_signature,
            item.get('target_fingerprint'), current_fingerprint
        )

    def _log_item(self, item, suffix):
        if self.logger and hasattr(self.logger, "log"):
            pending = item['pending']
            self.logger.log(
                f"⏳ Probation lesson from {pending['agent_name']}/{pending['action_name']} "
                f"(iteration {pending['source_iteration']}, target: '{item['target_issue'][:80]}'): {suffix}"
            )
