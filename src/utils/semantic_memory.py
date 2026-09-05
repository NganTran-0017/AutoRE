"""
Semantic memory system using ChromaDB for vector-based retrieval.

This enhances the existing JSON-based memory system with semantic search
capabilities while maintaining backward compatibility.
"""
import chromadb
from chromadb.config import Settings
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import json


class SemanticMemorySystem:
    """
    Semantic memory system using ChromaDB for vector-based similarity search.

    Stores memories with embeddings and retrieves them using semantic similarity
    rather than just exact tag matching.
    """

    def __init__(
        self,
        project_name: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        enable_dedup: bool = True,
        dedup_config: Optional[Dict] = None
    ):
        """
        Initialize semantic memory system.

        Args:
            project_name: Project identifier for isolation
            embedding_model: Sentence transformer model for embeddings
                           (default: all-MiniLM-L6-v2 - fast and efficient)
            enable_dedup: Enable semantic deduplication (default: True)
            dedup_config: Deduplication configuration dict
        """
        self.project_name = project_name
        self.storage_path = Path(f"memory/{project_name}_semantic/")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Deduplication configuration
        self.enable_dedup = enable_dedup
        self.dedup_config = dedup_config or {
            "merge_threshold": 0.7,
            "drop_threshold": 0.91,
            "merge_similar_lessons": True
        }

        # Convention dedup settings. The merge floor is 0.78 rather than the
        # lessons' 0.7: calibrated on Output/ConventionDedup/shadow.jsonl, every
        # observed pair below ~0.78 was "same topic, different rule" (an
        # eligibility CONDITION against an encoding STYLE for the same
        # predicate), which must not be fused, while every pair above it was
        # either one rule restated or one rule superseding another - the two
        # cases the classifier exists to separate.
        #
        # Setting convention_mode="observe" keeps detection and shadow logging
        # but acts on nothing, which is the fallback if the classifier turns out
        # to be wrong on a real run.
        self.dedup_config.setdefault("convention_mode", "active")
        self.dedup_config.setdefault("convention_drop_threshold", 0.93)
        self.dedup_config.setdefault("convention_merge_threshold", 0.78)

        # How many iterations a suspension may wait for an outcome before it is
        # undone by default. A suspension that nothing ever settles is a silent
        # permanent deletion - it survives restarts, and the older lesson simply
        # stops being injected forever. This bounds the wait instead of removing
        # the provisional window.
        #
        # It must EXCEED the lesson probation window (3 clean iterations), or the
        # sweep would pre-empt the very answer it is waiting for.
        self.dedup_config.setdefault("lesson_conflict_max_wait", 5)

        # Initialize MemoryAssistant for merging (lazy loaded)
        self._memory_assistant = None

        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(self.storage_path),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        # Create or get collections for different memory types
        self.lessons_collection = self.client.get_or_create_collection(
            name="lessons",
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity
        )

        self.patterns_collection = self.client.get_or_create_collection(
            name="patterns",
            metadata={"hnsw:space": "cosine"}
        )

        self.events_collection = self.client.get_or_create_collection(
            name="events",
            metadata={"hnsw:space": "cosine"}
        )

        # Project-specific modeling conventions (encoding decisions for THIS
        # model, e.g. "use one variable for time steps"). Distinct from lessons
        # (universal Alloy syntax) - kept separate so they can be always-injected
        # into model building rather than semantically retrieved.
        self.conventions_collection = self.client.get_or_create_collection(
            name="conventions",
            metadata={"hnsw:space": "cosine"}
        )

        self._collection_map = {
            "lesson": self.lessons_collection,
            "pattern": self.patterns_collection,
            "event": self.events_collection,
            "convention": self.conventions_collection
        }

        # Lesson suspensions awaiting an outcome: [{existing_id, new_id,
        # iteration, ...}]. A contradiction suspends the OLD lesson immediately
        # (it stops being injected) but retires it only once the new lesson's
        # change is confirmed to have held - see resolve_lesson_conflicts.
        # Rebuilt from disk rather than started empty: the suspension itself is
        # persisted on the row, so a list that reset on every construction would
        # leave the old lesson withdrawn with nothing left to restore it.
        self.pending_lesson_conflicts: List[Dict[str, Any]] = []
        self.load_pending_lesson_conflicts()

    @property
    def memory_assistant(self):
        """Lazy load MemoryAssistant with config."""
        if self._memory_assistant is None:
            from ..actions.memory_assistant_action import MemoryAssistant
            # Pass memory assistant config if available
            assistant_config = self.dedup_config.get('memory_assistant_config', {})
            self._memory_assistant = MemoryAssistant(config=assistant_config)
        return self._memory_assistant

    def _check_semantic_duplicates(
        self,
        content: str,
        item_type: str,
        agent: str,
        action: str
    ) -> List[Dict]:
        """
        Check if semantically similar content already exists.

        Args:
            content: New content to check
            item_type: Type of memory (lesson, pattern, event)
            agent: Agent name
            action: Action name

        Returns:
            List of similar items (empty if none found)
        """
        collection = self._collection_map.get(item_type)
        if not collection:
            return []

        # Floor at the merge band's lower edge: items below this are treated
        # as genuinely new (not similar enough to merge or drop).
        if item_type == "convention":
            threshold = self.dedup_config.get("convention_merge_threshold", 0.78)
        else:
            threshold = self.dedup_config.get("merge_threshold", 0.7)

        # Conventions are model-wide (written from multiple agents/actions and
        # injected in full every iteration), so they must dedup across the whole
        # collection - NOT scoped to a single agent/action the way lessons are.
        if item_type == "convention":
            where = None
        else:
            where = {"$and": [{"agent": agent}, {"action": action}]}

        try:
            # Query for similar items
            results = collection.query(
                query_texts=[content],
                n_results=5,
                where=where
            )

            similar_items = []
            if results and results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    distance = results['distances'][0][i]
                    similarity = 1.0 - distance

                    if similarity >= threshold:
                        similar_items.append({
                            'id': results['ids'][0][i],
                            'content': doc,
                            'similarity': similarity,
                            'metadata': results['metadatas'][0][i]
                        })

            return similar_items

        except Exception as e:
            print(f"Warning: Error checking duplicates: {e}")
            return []

    async def _merge_and_update_item(
        self,
        existing_id: str,
        existing_content: str,
        new_content: str,
        new_iteration: int,
        item_type: str = "lesson"
    ):
        """
        Merge two items using MemoryAssistant and update the existing entry.

        Works for any collection in _collection_map (lessons and conventions).

        Args:
            existing_id: ID of existing item
            existing_content: Content of existing item
            new_content: Content of new item
            new_iteration: Iteration number of new item
            item_type: Which collection the item lives in ("lesson"/"convention")
        """
        collection = self._collection_map[item_type]

        # Both collections are classified before merging - a contradiction must
        # never be folded into one sentence, whichever collection it is in.
        if item_type == "lesson":
            verdict, merged = await self.memory_assistant.merge_lessons_classified(
                existing_content, new_content
            )
        else:
            verdict, merged = await self.memory_assistant.merge_conventions_classified(
                existing_content, new_content
            )

        if verdict == "CONTRADICTORY":
            # Leave the existing row untouched; store() suspends it and keeps
            # the new item as a separate row instead.
            return "CONTRADICTORY"

        if verdict == "UNPARSED" or not merged:
            # The classifier did not answer. Take the branch that changes
            # nothing: store() falls through and writes the new item on its own
            # row. Merging here would rewrite a surviving rule on no evidence.
            return "UNPARSED"

        # Get existing metadata
        existing = collection.get(ids=[existing_id])
        if existing and existing['metadatas']:
            old_metadata = existing['metadatas'][0]

            # Keep the pre-merge wording so the merge can be undone. When a
            # merge is already pending on this row, the ORIGINAL prior_text is
            # kept rather than overwritten: it is the last wording that actually
            # survived probation, and that is what a revert has to restore.
            prior_text = (
                old_metadata.get("prior_text")
                if old_metadata.get("merge_pending")
                else existing_content
            )

            # Update metadata
            updated_metadata = {
                **old_metadata,
                "updated_iteration": new_iteration,
                "updated_timestamp": datetime.now().isoformat(),
                "version": old_metadata.get("version", 1) + 1,
                "update_reason": "merged_with_new_information",
                "prior_text": prior_text or existing_content,
                "merged_at_iteration": new_iteration,
            }

            # Delete old entry
            collection.delete(ids=[existing_id])

            # Add merged item
            collection.add(
                documents=[merged],
                metadatas=[updated_metadata],
                ids=[existing_id]
            )
        return verdict

    def _merge_blocking(
        self,
        existing_id: str,
        existing_content: str,
        new_content: str,
        new_iteration: int,
        item_type: str = "lesson"
    ):
        """
        Run the async classify-and-merge to completion synchronously.

        The previous implementation fired `asyncio.create_task(...)` and returned
        without keeping a reference, so the merge was garbage-collected and never
        persisted (confirmed lessons were silently lost). This blocks until the
        verdict - and the merged row, when there is one - is written to ChromaDB.

        Args:
            existing_id: ID of the existing (similar) item
            existing_content: Content of the existing item
            new_content: Content of the new item to classify against it
            new_iteration: Iteration number of the new item
            item_type: Which collection the pair lives in

        Returns:
            One of SAME / COMPLEMENTARY / CONTRADICTORY / UNPARSED. Only the
            first two wrote anything.
        """
        import asyncio
        import concurrent.futures

        coro = self._merge_and_update_item(
            existing_id=existing_id,
            existing_content=existing_content,
            new_content=new_content,
            new_iteration=new_iteration,
            item_type=item_type
        )
        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No event loop running on this thread - run directly.
                return asyncio.run(coro)
            # An event loop is already running here (the async workflow): run
            # the coroutine on a fresh loop in a worker thread and block on it.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, coro).result()
        except Exception as e:
            # The LLM call failed, so there is no verdict. Report it as
            # unparsed rather than replacing the existing row with the new
            # content: that old fallback silently discarded the existing
            # wording on an infrastructure error, and for a convention it
            # discarded a rule the model builder was still obeying. The caller
            # stores the new item on its own row, which loses nothing.
            print(f"Warning: {item_type} merge failed ({e}); keeping both items")
            return "UNPARSED"

    def store(
        self,
        content: str,
        item_type: str,
        agent: str,
        action: str,
        iteration: int,
        metadata: Optional[Dict] = None,
        verified: bool = False,
        gated: bool = False
    ):
        """
        Store memory item with semantic deduplication and merging.

        Note: This is a sync wrapper that handles async merging internally.

        Args:
            content: The actual content to remember
            item_type: "lesson", "pattern", or "event"
            agent: Agent name (e.g., "RE", "Evaluator")
            action: Action name (e.g., "AnalyzeRequirements")
            iteration: Current iteration number
            metadata: Additional arbitrary data
            verified: True when this lesson already passed the probation gate
                (its change was confirmed to have held). Only a verified lesson
                may retire a lesson it contradicts; an unverified one suspends
                the old lesson provisionally, pending the same outcome check.
            gated: True when the CALLER can settle this write later - i.e. it is
                on the defer/confirm path and will call apply_/revert_ with the
                returned decision. A merge or a suspension is only left pending
                when someone can end the wait; otherwise it is settled now,
                because an item waiting on an outcome nobody will report is
                withdrawn forever.

        Returns:
            A decision dict for the caller to settle later (kind "merge" or
            "conflict"), or None when nothing is left pending.
        """
        collection = self._collection_map.get(item_type)
        if not collection:
            raise ValueError(f"Unknown item_type: {item_type}")

        if self.enable_dedup and item_type in ("lesson", "convention"):
            handled, decision = self._banded_store(
                content, item_type, agent, action, iteration,
                metadata, verified, gated
            )
            if handled:
                return decision

        # No duplicate or dedup disabled - store normally
        self._add_new_item(content, item_type, agent, action, iteration, metadata)
        return None

    def _banded_store(
        self,
        content: str,
        item_type: str,
        agent: str,
        action: str,
        iteration: int,
        metadata: Optional[Dict],
        verified: bool,
        gated: bool,
    ):
        """
        Banded semantic dedup, shared by lessons and conventions:

            sim >= drop_threshold         -> drop the new item (adds nothing)
            merge_threshold <= sim < drop -> ask the MemoryAssistant whether the
                                             two are one rule or opposing rules,
                                             and act on the verdict
            sim < merge_threshold         -> unrelated enough to leave alone

        The bands are per-collection because the collections behave differently:
        lessons are scoped to one {agent, action} and conventions are model-wide
        (see _check_semantic_duplicates), so their similarity distributions are
        not comparable and must not share a threshold.

        Returns (handled, decision). `handled` False means the caller should
        store the item as a new row - which is the outcome for every branch that
        decides to change nothing, including observe mode and an unparseable
        verdict.
        """
        if item_type == "convention":
            drop_threshold = self.dedup_config.get("convention_drop_threshold", 0.93)
            mode = self.dedup_config.get("convention_mode", "active")
        else:
            drop_threshold = self.dedup_config.get("drop_threshold", 0.91)
            mode = self.dedup_config.get("lesson_mode", "active")

        similar_items = self._check_semantic_duplicates(
            content, item_type, agent, action
        )
        top = similar_items[0] if similar_items else None

        if not top:
            self._log_dedup_shadow(
                item_type, content, None, "new", None, agent, action, iteration
            )
            return False, None

        if top['similarity'] >= drop_threshold:
            # Near-identical to something already stored. Nothing to classify:
            # a duplicate cannot contradict what it duplicates.
            self._log_dedup_shadow(
                item_type, content, top, "drop", None, agent, action, iteration
            )
            return (mode == "active"), None

        if not self.dedup_config.get("merge_similar_lessons", True):
            # Merging disabled - treat a near-match as a duplicate and drop it.
            self._log_dedup_shadow(
                item_type, content, top, "drop", None, agent, action, iteration
            )
            return (mode == "active"), None

        if mode != "active":
            # Observe mode: classify nothing, act on nothing, but record what
            # the band was so thresholds stay tunable from a real run.
            self._log_dedup_shadow(
                item_type, content, top, "merge", None, agent, action, iteration
            )
            return False, None

        verdict = self._merge_blocking(
            existing_id=top['id'],
            existing_content=top['content'],
            new_content=content,
            new_iteration=iteration,
            item_type=item_type,
        )
        self._log_dedup_shadow(
            item_type, content, top, "merge", verdict, agent, action, iteration
        )

        if verdict in ("SAME", "COMPLEMENTARY"):
            # The row now holds the merged text and its pre-merge wording. Leave
            # it pending only when the caller can end the wait.
            if gated:
                self._update_item_metadata(
                    top['id'], {"merge_pending": True}, item_type
                )
                return True, {
                    "kind": "merge",
                    "item_type": item_type,
                    "id": top['id'],
                    "prior_text": top['content'],
                    "iteration": iteration,
                }
            return True, None

        if verdict == "CONTRADICTORY":
            return self._handle_contradiction(
                top, content, item_type, agent, action,
                iteration, metadata, verified, gated
            )

        # UNPARSED - the classifier did not answer. Keep both items.
        return False, None

    def _handle_contradiction(
        self,
        top: Dict,
        content: str,
        item_type: str,
        agent: str,
        action: str,
        iteration: int,
        metadata: Optional[Dict],
        verified: bool,
        gated: bool,
    ):
        """
        Two items that cannot both be obeyed: keep both rows, suspend the older.

        Merging would silently pick a side; dropping either would lose guidance
        that may still be right. So the new item goes in active (it is the
        agent's current reading, and withholding it would mean nothing can ever
        demonstrate it was right) and the older one stops being injected while
        the outcome is decided.

        A contradiction is only ACTED on when something can settle it: a
        verified item settles it now, a gated caller settles it later, and the
        lesson queue settles the remaining lesson case. Outside those, the
        verdict is recorded and both items simply coexist - suspending an item
        that nothing will ever restore is worse than leaving it in place.
        """
        settleable = verified or gated or item_type == "lesson"
        if not settleable:
            print(
                f"  ⚔️  Contradicting {item_type} recorded (no outcome gate on "
                f"this path): both kept active"
            )
            return False, None

        new_id = self._add_new_item(
            content, item_type, agent, action, iteration, metadata
        )
        self._register_conflict(
            existing_id=top['id'],
            existing_content=top['content'],
            new_id=new_id,
            new_content=content,
            similarity=top['similarity'],
            iteration=iteration,
            verified=verified,
            item_type=item_type,
            queue=(item_type == "lesson" and not gated),
        )
        if gated and not verified:
            return True, {
                "kind": "conflict",
                "item_type": item_type,
                "id": top['id'],
                "new_id": new_id,
                "iteration": iteration,
            }
        return True, None

    def _add_new_item(
        self,
        content: str,
        item_type: str,
        agent: str,
        action: str,
        iteration: int,
        metadata: Optional[Dict] = None
    ) -> str:
        """Write one item as a new row and return its id (no dedup)."""
        collection = self._collection_map[item_type]
        timestamp = datetime.now().isoformat()
        doc_id = f"{agent}_{action}_{iteration}_{timestamp}"

        meta = {
            "agent": agent,
            "action": action,
            "iteration": iteration,
            "project": self.project_name,
            "timestamp": timestamp,
            "type": item_type,
            "version": 1
        }
        # Conventions and lessons carry an explicit lifecycle status so they can
        # be soft-retracted (superseded) without deleting the row. The read paths
        # skip suppressed statuses. Stamping at write time means the field always
        # exists on new rows; rows written before the lifecycle existed have no
        # status and are treated as active, so the filter must not require it.
        if item_type in ("convention", "lesson"):
            meta["status"] = "active"
        if metadata:
            meta.update(metadata)

        collection.add(
            documents=[content],
            metadatas=[meta],
            ids=[doc_id]
        )
        return doc_id

    def _register_conflict(
        self,
        existing_id: str,
        existing_content: str,
        new_id: str,
        new_content: str,
        similarity: float,
        iteration: int,
        verified: bool,
        item_type: str = "lesson",
        queue: bool = True,
    ) -> None:
        """
        Suspend the older of two contradicting items, and decide when it dies.

        A verified new item (its change already passed probation) settles the
        conflict now. An unverified one only suspends, and who ends that wait
        depends on the collection: lessons go on `pending_lesson_conflicts`
        (`queue`), conventions are settled by the caller's defer/confirm gate
        through the decision `store` returns. Either way the old item comes back
        if the change that contradicted it does not hold.
        """
        reason = (
            f"contradicted by a newer {item_type} (similarity {similarity:.2f}): "
            f"{new_content[:120]}"
        )
        self.mark_item_pending_withdrawn(
            existing_id, reason, iteration, item_type, superseded_by=new_id
        )
        conflict = {
            "existing_id": existing_id,
            "existing_content": existing_content,
            "new_id": new_id,
            "new_content": new_content,
            "similarity": similarity,
            "iteration": iteration,
        }
        if verified:
            self.finalize_retraction(existing_id, iteration, item_type)
        elif queue:
            self.pending_lesson_conflicts.append(conflict)
        self._log_conflict_decision(
            decision="retired_on_verified" if verified else "suspended",
            item_type=item_type,
            iteration=iteration,
            new_id=new_id,
            new_content=new_content,
            existing_id=existing_id,
            existing_content=existing_content,
            similarity=similarity,
            reason=(
                "the new item already passed probation, so it may retire what it "
                "contradicts" if verified else
                "the new item is unverified, so the older one is only set aside "
                "until an outcome decides"
            ),
        )

    # The lesson-only name this had before conventions shared the lifecycle.
    _register_lesson_conflict = _register_conflict

    # `_simple_update_item` lived here: a deterministic "replace the existing
    # row with the new content" used when the LLM merge threw. It is gone
    # because replacing is a DECISION - it picks the newer wording - and making
    # that decision on an infrastructure error is exactly the failure mode the
    # classifier exists to prevent. A failed call now returns UNPARSED and both
    # items are kept.

    # Where each collection's dedup shadow log is written.
    _SHADOW_DIRS = {
        "convention": "Output/ConventionDedup",
        "lesson": "Output/LessonDedup",
    }

    def _log_dedup_shadow(
        self,
        item_type: str,
        content: str,
        top: Optional[Dict],
        would: str,
        verdict: Optional[str],
        agent: str,
        action: str,
        iteration: int
    ):
        """
        Append one shadow record per stored lesson/convention.

        Records the top semantic match, which band it landed in, and - once the
        classifier runs - what it said. The band is tunable only against this
        log: it is the sole record of the pairs the thresholds decided between,
        and `verdict` is the only evidence of whether the classifier is right,
        which is the part no unit test can assert. Logging happens in every
        mode, so switching to "observe" costs detection but not evidence.
        """
        try:
            prefix = "convention_" if item_type == "convention" else ""
            record = {
                "iteration": iteration,
                "item_type": item_type,
                "agent": agent,
                "action": action,
                "mode": self.dedup_config.get(f"{item_type}_mode", "active"),
                "drop_threshold": self.dedup_config.get(
                    f"{prefix}drop_threshold", 0.93 if prefix else 0.91),
                "merge_threshold": self.dedup_config.get(
                    f"{prefix}merge_threshold", 0.78 if prefix else 0.7),
                "would": would,
                "verdict": verdict,
                "top_sim": round(top['similarity'], 4) if top else None,
                "new": content,
                "top_match": top['content'] if top else None,
                "timestamp": datetime.now().isoformat(),
            }
            out_dir = Path(self._SHADOW_DIRS.get(item_type, "Output/MemoryDedup"))
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / "shadow.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            # Shadow logging must never break the store path.
            print(f"Warning: {item_type} shadow log failed: {e}")

    def _log_convention_shadow(
        self,
        content: str,
        top: Optional[Dict],
        would: str,
        agent: str,
        action: str,
        iteration: int
    ):
        """Convention-only shadow entry (the retraction path's matcher)."""
        self._log_dedup_shadow(
            "convention", content, top, would, None, agent, action, iteration
        )

    def _log_conflict_decision(
        self,
        decision: str,
        item_type: str,
        iteration: int,
        new_id: Optional[str],
        new_content: str,
        existing_id: Optional[str],
        existing_content: str,
        similarity: Optional[float] = None,
        reason: str = "",
    ) -> None:
        """
        Record one contradiction decision, with BOTH items' full text.

        Every other outcome in this lifecycle is inspectable after the fact; a
        contradiction was not. The row that stops being injected keeps only a
        120-character excerpt of its accuser in `retract_reason`, and once the
        pair is settled there is nothing left to say which two items were
        weighed or which way it went. That matters more here than anywhere else
        in memory, because this is the only path that takes guidance the run was
        already following OUT of circulation.

        Decisions: suspended | retired_on_verified | finalized | restored |
        expired. Written to Output/<Collection>Dedup/decisions.jsonl beside the
        band-and-verdict shadow log, and echoed to the console.
        """
        try:
            record = {
                "iteration": iteration,
                "item_type": item_type,
                "decision": decision,
                "reason": reason,
                "similarity": round(similarity, 4) if similarity is not None else None,
                "new_id": new_id,
                "new_item": new_content,
                "old_id": existing_id,
                "old_item": existing_content,
                "timestamp": datetime.now().isoformat(),
            }
            out_dir = Path(self._SHADOW_DIRS.get(item_type, "Output/MemoryDedup"))
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / "decisions.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            # Logging must never break the lifecycle it is recording.
            print(f"Warning: {item_type} conflict decision log failed: {e}")

        print(f"  ⚔️  {item_type} conflict -> {decision.upper()} (it.{iteration})")
        print(f"       new: {(new_content or '')[:160]}")
        print(f"       old: {(existing_content or '')[:160]}")
        if reason:
            print(f"       why: {reason}")

    def finalize_merge(self, item_id: str, item_type: str = "convention") -> bool:
        """
        Confirm a merge: the merged wording stands, the wait ends.

        `prior_text` is deliberately KEPT on the row. It is the record of what
        the item said before the merge, which is the only trace that two items
        were ever folded into this one.
        """
        return self._update_item_metadata(item_id, {
            "merge_pending": False,
            "merge_confirmed": True,
        }, item_type)

    def restore_merge(self, item_id: str, item_type: str = "convention") -> bool:
        """
        Undo a merge: put `prior_text` back and discard the merged wording.

        The change that motivated the merge did not hold, so the item the run
        was already relying on is restored verbatim. Returns False when the row
        has no pre-merge text to go back to, rather than guessing - a merge
        recorded before `prior_text` existed cannot be undone, and pretending
        otherwise would blank the row.
        """
        collection = self._collection_map.get(item_type)
        if collection is None:
            return False
        try:
            existing = collection.get(ids=[item_id])
            if not existing or not existing['metadatas']:
                return False
            old_metadata = existing['metadatas'][0] or {}
            prior_text = old_metadata.get("prior_text")
            if not prior_text:
                return False
            collection.delete(ids=[item_id])
            collection.add(
                documents=[prior_text],
                metadatas=[{
                    **old_metadata,
                    "prior_text": "",
                    "merge_pending": False,
                    "merge_reverted": True,
                    "update_reason": "merge_reverted_outcome_did_not_hold",
                }],
                ids=[item_id],
            )
            return True
        except Exception as e:
            print(f"Warning: {item_type} merge revert failed: {e}")
            return False

    def _update_item_metadata(self, item_id: str, updates: dict,
                              item_type: str = "convention") -> bool:
        """Merge `updates` into one item's metadata (row kept, never deleted)."""
        collection = self._collection_map.get(item_type)
        if collection is None:
            return False
        try:
            existing = collection.get(ids=[item_id])
            old_metadata = (
                existing['metadatas'][0]
                if existing and existing['metadatas'] else {}
            )
            collection.update(
                ids=[item_id],
                metadatas=[{**old_metadata, **updates}],
            )
            return True
        except Exception as e:
            print(f"Warning: {item_type} metadata update failed: {e}")
            return False

    def _update_convention_metadata(self, conv_id: str, updates: dict) -> bool:
        """Merge `updates` into one convention's metadata (kept, not deleted)."""
        return self._update_item_metadata(conv_id, updates, "convention")

    def mark_item_pending_withdrawn(
        self,
        item_id: str,
        reason: str,
        iteration: int,
        item_type: str = "lesson",
        superseded_by: Optional[str] = None,
    ) -> bool:
        """
        Provisionally withdraw one item BY ID: status -> "pending_withdrawn".

        The suspended item stops being injected but is not deleted and is not
        judged wrong - only set aside while the item that contradicts it is on
        trial. `finalize_retraction` or `restore_item` decides which survives,
        from the run's outcome rather than from which arrived later.
        """
        return self._update_item_metadata(item_id, {
            "status": "pending_withdrawn",
            "retract_reason": reason,
            "retract_pending_iteration": iteration,
            "superseded_by": superseded_by or "",
        }, item_type)

    def finalize_retraction(self, item_id: str, iteration: int,
                            item_type: str = "convention") -> bool:
        """Confirm a pending retraction: pending_withdrawn -> superseded (final)."""
        return self._update_item_metadata(item_id, {
            "status": "superseded",
            "retracted_at_iteration": iteration,
            "retracted_timestamp": datetime.now().isoformat(),
        }, item_type)

    def restore_item(self, item_id: str, item_type: str = "convention") -> bool:
        """Revert a pending retraction: pending_withdrawn -> active."""
        return self._update_item_metadata(item_id, {"status": "active"}, item_type)

    def mark_convention_pending_withdrawn(
        self,
        text: str,
        reason: str,
        iteration: int,
        threshold: float = 0.85
    ) -> Optional[str]:
        """
        Provisionally withdraw a convention the RE has flagged as outdated.

        Semantically matches `text` against the convention collection; if the
        closest match is at/above `threshold`, flip its status to
        "pending_withdrawn" so get_conventions (which only returns "active"
        ones) stops injecting it immediately, WITHOUT permanently retracting it.
        The retraction is finalized (-> "superseded") or reverted (-> "active")
        later by the defer/confirm gate. If there is no confident match, this is
        a logged no-op - retraction must never guess and nuke the wrong rule.

        Returns:
            The matched convention id (to finalize/revert later), or None.
        """
        if not text or not text.strip():
            return None

        matches = self._check_semantic_duplicates(
            text, "convention", agent=None, action=None
        )
        top = matches[0] if matches else None

        if not top or top['similarity'] < threshold:
            self._log_convention_shadow(
                text, top, "retract-miss", "RE", "retract", iteration
            )
            return None

        ok = self._update_convention_metadata(top['id'], {
            "status": "pending_withdrawn",
            "retract_reason": reason,
            "retract_pending_iteration": iteration,
        })
        if not ok:
            return None
        self._log_convention_shadow(
            text, top, "retract-pending", "RE", "retract", iteration
        )
        return top['id']

    def finalize_convention_retraction(self, conv_id: str, iteration: int) -> bool:
        """Confirm a pending retraction: pending_withdrawn -> superseded (final)."""
        return self.finalize_retraction(conv_id, iteration, "convention")

    def restore_convention(self, conv_id: str) -> bool:
        """Revert a pending retraction whose fix didn't stick: -> active again."""
        return self.restore_item(conv_id, "convention")

    # ------------------------------------------------- lesson conflicts #

    SUPPRESSED_STATUSES = ("pending_withdrawn", "superseded")

    @classmethod
    def _is_suppressed(cls, metadata: Optional[Dict]) -> bool:
        """True for an item withdrawn or superseded.

        Absence of `status` means active: lessons stored before the lifecycle
        existed carry no status field, and must keep being injected.
        """
        return (metadata or {}).get("status") in cls.SUPPRESSED_STATUSES

    def load_pending_lesson_conflicts(self) -> int:
        """
        Rebuild the pending-conflict list from the suspended rows themselves.

        Everything `resolve_lesson_conflicts` reads is already on the row
        (`superseded_by`, `retract_pending_iteration`), so no side file is
        needed - only a query. Note the deliberate asymmetry with the read-path
        filter: there, absence of `status` must read as ACTIVE, so filtering
        happens in Python. Here requiring the key is exactly right, because only
        a row written by this lifecycle can be "pending_withdrawn".

        Returns how many suspensions were recovered.
        """
        self.pending_lesson_conflicts = []
        try:
            rows = self.lessons_collection.get(
                where={"status": "pending_withdrawn"}
            )
        except Exception as e:
            print(f"Warning: could not reload pending lesson conflicts: {e}")
            return 0

        ids = (rows or {}).get('ids') or []
        documents = (rows or {}).get('documents') or []
        metadatas = (rows or {}).get('metadatas') or []
        for i, row_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            self.pending_lesson_conflicts.append({
                "existing_id": row_id,
                "existing_content": documents[i] if i < len(documents) else "",
                # Empty when the suspension predates the link, or the newer
                # lesson is gone: resolution then restores without retiring.
                "new_id": (meta or {}).get("superseded_by") or None,
                "new_content": "",
                "similarity": None,
                "iteration": (meta or {}).get("retract_pending_iteration"),
            })
        return len(self.pending_lesson_conflicts)

    def discard_lesson_conflicts_from(self, min_iteration: int) -> int:
        """
        Undo suspensions raised at or after `min_iteration` (a resume point).

        A suspension caused by an iteration the run is about to re-run belongs
        to a discarded timeline - the rerun derives its own lessons and decides
        again. Mirrors the audit-log trim, and fails toward restoring: a
        conflict with no recorded iteration is left pending rather than guessed
        at. Returns how many were restored.
        """
        kept, restored = [], 0
        for conflict in self.pending_lesson_conflicts:
            at = conflict.get("iteration")
            if at is None or at < min_iteration:
                kept.append(conflict)
                continue
            self.restore_item(conflict["existing_id"], "lesson")
            restored += 1
        self.pending_lesson_conflicts = kept
        return restored

    @staticmethod
    def _same_text(left: str, right: str) -> bool:
        """Compare two lesson bodies ignoring case and whitespace only."""
        return ' '.join((left or '').lower().split()) == ' '.join((right or '').lower().split())

    def resolve_lesson_conflicts(self, resolved: bool, iteration: int,
                                 source_iteration: Optional[int] = None,
                                 lesson_texts: Optional[List[str]] = None) -> int:
        """
        Settle suspensions raised by a contradicting lesson, by OUTCOME.

        `resolved=True` - the change the new lesson came from held, so the old
        lesson is finalized as superseded (kept on disk, never injected again).
        `resolved=False` - it did not hold, so the old lesson is restored to
        active and the new lesson is the one withdrawn. Recency never decides:
        an unverified new lesson cannot retire an old one, and an old lesson is
        never deleted on suspicion.

        Scope, in order of precedence:
          `lesson_texts` - settle only conflicts raised by THESE lessons. This is
            the correct key: a conflict belongs to the lesson that raised it, not
            to the iteration it was raised in. Keying on the iteration meant an
            unrelated lesson failing in the same iteration settled someone else's
            conflict, in the direction "restore the old, retire the new", on
            evidence that was never about it.
          `source_iteration` - the older, coarser key, kept for suspensions
            recovered from disk, whose rows carry an iteration and no lesson id.
          neither - settle everything pending.

        Returns how many were settled.
        """
        settled = 0
        remaining = []
        for conflict in self.pending_lesson_conflicts:
            if lesson_texts is not None:
                if not any(self._same_text(conflict.get("new_content", ""), text)
                           for text in lesson_texts):
                    remaining.append(conflict)
                    continue
            elif source_iteration is not None and conflict.get("iteration") != source_iteration:
                remaining.append(conflict)
                continue
            if resolved:
                self.finalize_retraction(conflict["existing_id"], iteration, "lesson")
            else:
                self.restore_item(conflict["existing_id"], "lesson")
                if conflict.get("new_id"):
                    self.mark_item_pending_withdrawn(
                        conflict["new_id"],
                        "contradicted an existing lesson and its fix did not hold",
                        iteration,
                        "lesson",
                    )
                    self.finalize_retraction(conflict["new_id"], iteration, "lesson")
            self._log_conflict_decision(
                decision="finalized" if resolved else "restored",
                item_type="lesson",
                iteration=iteration,
                new_id=conflict.get("new_id"),
                new_content=conflict.get("new_content", ""),
                existing_id=conflict.get("existing_id"),
                existing_content=conflict.get("existing_content", ""),
                similarity=conflict.get("similarity"),
                reason=(
                    "the change the new lesson came from held"
                    if resolved else
                    "the change the new lesson came from did not hold, so the "
                    "older lesson goes back into circulation"
                ),
            )
            settled += 1
        self.pending_lesson_conflicts = remaining
        return settled

    def expire_stale_lesson_conflicts(self, current_iteration: int,
                                      max_wait: Optional[int] = None) -> int:
        """
        Undo suspensions that have waited too long for an outcome.

        Not every lesson has an outcome to wait for: 8 of the 11 lesson store
        sites write immediately, with no probation item and no fix whose fate
        could ever settle the conflict they raise. Those suspensions used to wait
        forever - and because `load_pending_lesson_conflicts` rebuilds them from
        the row, forever survived restarts. A suspension nobody lifts is a silent
        permanent deletion wearing the word "provisional".

        So the wait is bounded rather than removed. Past `max_wait` iterations
        the older lesson is restored and the pair is dropped from the queue,
        failing toward RESTORING - the same bias `discard_lesson_conflicts_from`
        applies, and the one the design has always stated: an old lesson is never
        deleted on suspicion. The newer lesson is left active; nothing has been
        shown about either, so both are injected and the contradiction is at
        least visible to the agent instead of resolved by silence.

        A suspension with no recorded iteration is expired too: every row this
        lifecycle writes carries `retract_pending_iteration`, so a missing one
        means a row that predates it - exactly the suspension most likely to have
        been sitting unsettled the longest.

        Returns how many were restored.
        """
        if max_wait is None:
            max_wait = self.dedup_config.get("lesson_conflict_max_wait", 5)

        kept, expired = [], 0
        for conflict in self.pending_lesson_conflicts:
            raised_at = conflict.get("iteration")
            if raised_at is not None and current_iteration - raised_at < max_wait:
                kept.append(conflict)
                continue
            self.restore_item(conflict["existing_id"], "lesson")
            self._log_conflict_decision(
                decision="expired",
                item_type="lesson",
                iteration=current_iteration,
                new_id=conflict.get("new_id"),
                new_content=conflict.get("new_content", ""),
                existing_id=conflict.get("existing_id"),
                existing_content=conflict.get("existing_content", ""),
                similarity=conflict.get("similarity"),
                reason=(
                    f"no outcome arrived within {max_wait} iterations of it."
                    f"{raised_at}; restoring the older lesson rather than "
                    f"letting a provisional suspension become permanent"
                ),
            )
            expired += 1
        self.pending_lesson_conflicts = kept
        return expired

    def retrieve_similar(
        self,
        query: str,
        item_type: Optional[str] = None,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 10,
        similarity_threshold: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Retrieve memories semantically similar to the query.

        Args:
            query: Query text to find similar memories
            item_type: Filter by type ("lesson", "pattern", "event")
            agent: Filter by agent name
            action: Filter by action name
            limit: Maximum number of results
            similarity_threshold: Minimum similarity score (0-1)

        Returns:
            List of dicts with 'content', 'metadata', and 'similarity' keys
        """
        # Determine which collections to search
        if item_type:
            collections = [self._collection_map.get(item_type)]
            if not collections[0]:
                return []
        else:
            collections = [
                self.lessons_collection,
                self.patterns_collection,
                self.events_collection
            ]

        all_results = []

        for collection in collections:
            # Build metadata filter
            where_filter = {}
            if agent:
                where_filter["agent"] = agent
            if action:
                where_filter["action"] = action

            # Query collection
            try:
                results = collection.query(
                    query_texts=[query],
                    n_results=limit,
                    where=where_filter if where_filter else None
                )

                # Process results
                if results and results['documents'] and results['documents'][0]:
                    for i, doc in enumerate(results['documents'][0]):
                        # ChromaDB returns distance, convert to similarity
                        # For cosine distance: similarity = 1 - distance
                        distance = results['distances'][0][i]
                        similarity = 1.0 - distance

                        metadata = results['metadatas'][0][i]
                        # A withdrawn or superseded item must never come back
                        # through semantic retrieval. Filtered here rather than
                        # in the `where` clause: a metadata predicate does not
                        # match rows lacking the key, which would hide every
                        # lesson written before the status field existed.
                        if self._is_suppressed(metadata):
                            continue

                        if similarity >= similarity_threshold:
                            all_results.append({
                                'content': doc,
                                'metadata': metadata,
                                'similarity': similarity
                            })
            except Exception as e:
                print(f"Warning: Error querying collection {collection.name}: {e}")
                continue

        # Sort by similarity (highest first) and limit
        all_results.sort(key=lambda x: x['similarity'], reverse=True)
        return all_results[:limit]

    def get_lessons(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 10,
        query: Optional[str] = None
    ) -> List[str]:
        """
        Get lessons, optionally using semantic search.

        Args:
            agent: Filter by agent
            action: Filter by action
            limit: Maximum number
            query: If provided, use semantic search with this query

        Returns:
            List of lesson strings
        """
        if query:
            # Use semantic search
            results = self.retrieve_similar(
                query=query,
                item_type="lesson",
                agent=agent,
                action=action,
                limit=limit
            )
            return [r['content'] for r in results]
        else:
            # Fall back to retrieving recent lessons using query with filters
            where_filter = None
            if agent and action:
                where_filter = {"$and": [{"agent": agent}, {"action": action}]}
            elif agent:
                where_filter = {"agent": agent}
            elif action:
                where_filter = {"action": action}

            try:
                # Over-fetch: suppressed rows are dropped below, and filtering
                # in the `where` clause would hide status-less legacy rows.
                results = self.lessons_collection.get(
                    where=where_filter,
                    limit=limit * 3 if limit else None
                )

                if results and results['documents']:
                    metadatas = results.get('metadatas') or []
                    kept = [
                        doc for i, doc in enumerate(results['documents'])
                        if not self._is_suppressed(
                            metadatas[i] if i < len(metadatas) else None
                        )
                    ]
                    return kept[:limit] if limit else kept
            except Exception as e:
                print(f"Warning: Error getting lessons: {e}")

            return []

    def get_patterns(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 5,
        query: Optional[str] = None
    ) -> List[str]:
        """
        Get patterns, optionally using semantic search.

        Args:
            agent: Filter by agent
            action: Filter by action
            limit: Maximum number
            query: If provided, use semantic search

        Returns:
            List of pattern strings
        """
        if query:
            results = self.retrieve_similar(
                query=query,
                item_type="pattern",
                agent=agent,
                action=action,
                limit=limit
            )
            return [r['content'] for r in results]
        else:
            where_filter = None
            if agent and action:
                where_filter = {"$and": [{"agent": agent}, {"action": action}]}
            elif agent:
                where_filter = {"agent": agent}
            elif action:
                where_filter = {"action": action}

            try:
                results = self.patterns_collection.get(
                    where=where_filter,
                    limit=limit
                )

                if results and results['documents']:
                    return results['documents']
            except Exception as e:
                print(f"Warning: Error getting patterns: {e}")
            
            return []

    def get_events(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 10,
        query: Optional[str] = None
    ) -> List[str]:
        """
        Get events, optionally using semantic search.

        Args:
            agent: Filter by agent
            action: Filter by action
            limit: Maximum number
            query: If provided, use semantic search

        Returns:
            List of event strings
        """
        if query:
            results = self.retrieve_similar(
                query=query,
                item_type="event",
                agent=agent,
                action=action,
                limit=limit
            )
            return [r['content'] for r in results]
        else:
            where_filter = None
            if agent and action:
                where_filter = {"$and": [{"agent": agent}, {"action": action}]}
            elif agent:
                where_filter = {"agent": agent}
            elif action:
                where_filter = {"action": action}

            try:
                results = self.events_collection.get(
                    where=where_filter,
                    limit=limit
                )

                if results and results['documents']:
                    return results['documents']
            except Exception as e:
                print(f"Warning: Error getting events: {e}")
            
            return []

    def get_conventions(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 50,
        query: Optional[str] = None
    ) -> List[str]:
        """
        Get modeling conventions. Unlike lessons, conventions are meant to be
        injected in full every iteration, so callers typically omit `query` and
        pass a generous `limit` to retrieve all of them.

        Args:
            agent: Filter by agent (usually omitted - conventions are model-wide)
            action: Filter by action (usually omitted)
            limit: Maximum number
            query: If provided, use semantic search with this query

        Returns:
            List of convention strings
        """
        if query:
            results = self.retrieve_similar(
                query=query,
                item_type="convention",
                agent=agent,
                action=action,
                limit=limit
            )
            return [r['content'] for r in results]

        # Only inject active conventions - superseded (retracted) ones are kept
        # in the collection for audit but must not reach the prompt.
        conditions = [{"status": "active"}]
        if agent:
            conditions.append({"agent": agent})
        if action:
            conditions.append({"action": action})
        where_filter = conditions[0] if len(conditions) == 1 else {"$and": conditions}

        try:
            results = self.conventions_collection.get(
                where=where_filter,
                limit=limit
            )
            if results and results['documents']:
                return results['documents']
        except Exception as e:
            print(f"Warning: Error getting conventions: {e}")

        return []

    def save_copy_to_output(self, output_dir: Optional[Path] = None) -> Optional[Path]:
        """
        Snapshot every collection to Output/ before an irreversible wipe.

        Mirrors the audit logs' save_copy_to_output. Clearing ChromaDB destroys
        lessons and conventions accumulated across ALL previous runs, which is
        strictly more destructive than trimming one log's tail - so the contents
        are dumped first. Best-effort: a failed snapshot must not block the wipe.
        """
        try:
            from .file_manager import run_snapshot_stamp

            output_dir = output_dir or Path("Output/MemorySnapshot")
            output_dir.mkdir(parents=True, exist_ok=True)
            # Stamped with the run's start hour, so a run spanning an hour
            # boundary keeps writing the same file instead of starting a second.
            out = output_dir / f"memory_{self.project_name}_{run_snapshot_stamp()}.json"

            dump = {}
            for name, collection in self._collection_map.items():
                rows = collection.get()
                dump[name] = [
                    {"id": rid,
                     "content": (rows.get('documents') or [])[i],
                     "metadata": (rows.get('metadatas') or [])[i]}
                    for i, rid in enumerate(rows.get('ids') or [])
                ]

            with open(out, "w", encoding="utf-8") as f:
                json.dump(dump, f, indent=2, ensure_ascii=False)
            total = sum(len(v) for v in dump.values())
            print(f"  🧠 Semantic memory snapshot ({total} items) saved to: {out}")
            return out
        except Exception as e:
            print(f"Warning: semantic memory snapshot failed: {e}")
            return None

    def clear_all(self, snapshot: bool = True):
        """
        Clear all collections.

        `snapshot=True` archives the contents to Output/ first - this is the
        only copy, and a fresh start calls it on memory built over many runs.
        """
        if snapshot:
            self.save_copy_to_output()

        self.client.delete_collection("lessons")
        self.client.delete_collection("patterns")
        self.client.delete_collection("events")
        self.client.delete_collection("conventions")

        # Recreate collections. The dedup settings MUST be carried over:
        # re-running __init__ with the project name alone silently reverted
        # merge/drop thresholds and convention_mode to their defaults, so a
        # cleared run no longer honoured config.yaml.
        self.__init__(
            self.project_name,
            enable_dedup=self.enable_dedup,
            dedup_config=self.dedup_config,
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about stored memories.

        Returns format compatible with LongTermMemorySystem for workflow summary.
        """
        lesson_count = self.lessons_collection.count()
        pattern_count = self.patterns_collection.count()
        event_count = self.events_collection.count()
        convention_count = self.conventions_collection.count()

        return {
            "total": lesson_count + pattern_count + event_count + convention_count,
            "by_type": {
                "lesson": lesson_count,
                "pattern": pattern_count,
                "event": event_count,
                "convention": convention_count
            }
        }

    def save(self):
        """
        Save memory state to disk.

        ChromaDB PersistentClient automatically persists data to disk,
        so this method is a no-op. Provided for interface compatibility
        with LongTermMemorySystem.
        """
        # ChromaDB auto-persists, no explicit save needed
        pass

    def __repr__(self) -> str:
        stats = self.get_stats()
        by_type = stats['by_type']
        return (
            f"SemanticMemorySystem(project='{self.project_name}', "
            f"lessons={by_type['lesson']}, "
            f"patterns={by_type['pattern']}, "
            f"events={by_type['event']})"
        )
