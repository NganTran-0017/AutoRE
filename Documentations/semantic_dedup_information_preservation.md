# Semantic Deduplication: Information Preservation Strategies

## Problem: Losing Additional Information

When a new lesson is semantically similar to an existing one BUT contains extra valuable information, naive deduplication would reject it and lose that information.

### Example Scenarios

#### Scenario 1: Additional Detail
```
Existing: "Always check Alloy syntax before running analyzer"
New:      "Always check Alloy syntax before running analyzer, and verify multiplicities are correct"

Similarity: 0.88 (high)
Issue: New lesson adds "multiplicities" information - we can't lose this!
```

#### Scenario 2: Additional Context
```
Existing: "Use temporal operators for state transitions"
New:      "Use temporal operators (next, always, eventually) for state transitions"

Similarity: 0.90 (high)
Issue: New lesson adds specific operator examples - valuable!
```

#### Scenario 3: Refinement
```
Existing: "Don't use undefined predicates in assertions"
New:      "Don't use undefined predicates in assertions - causes syntax errors on line X"

Similarity: 0.92 (high)
Issue: New lesson adds debugging hint - helpful!
```

---

## Solution Approaches

### ✅ Solution A: Update Strategy (Recommended)

**Concept**: When new lesson is similar but contains more information, **update** the existing lesson instead of rejecting.

**Algorithm**:
```python
def store(self, content, item_type, agent, action, iteration, metadata=None):
    # Step 1: Check for semantic duplicates
    similar_items = self._check_semantic_duplicates(
        content, item_type, agent, action,
        similarity_threshold=0.85
    )

    if similar_items:
        most_similar = similar_items[0]

        # Step 2: Compare information content
        should_update = self._should_update_existing(
            existing=most_similar['content'],
            new=content,
            similarity=most_similar['similarity']
        )

        if should_update == "UPDATE":
            # New lesson has more info - update existing
            self._update_lesson(
                doc_id=most_similar['id'],
                new_content=content,
                new_metadata={
                    "updated_iteration": iteration,
                    "updated_timestamp": datetime.now().isoformat(),
                    "update_reason": "enhanced_with_additional_info"
                }
            )
            return

        elif should_update == "KEEP_BOTH":
            # Sufficiently different - store both
            pass  # Continue to normal storage

        else:  # "REJECT"
            # True duplicate - skip
            return

    # Step 3: No duplicate or sufficiently different - store normally
    # ... normal storage code ...
```

**Helper Method**:
```python
def _should_update_existing(
    self,
    existing: str,
    new: str,
    similarity: float
) -> str:
    """
    Determine if new lesson should update, coexist, or be rejected.

    Returns:
        "UPDATE": Replace existing with new (more complete)
        "KEEP_BOTH": Store both (sufficiently different)
        "REJECT": True duplicate (discard new)
    """
    # Criterion 1: Length difference
    existing_len = len(existing.split())
    new_len = len(new.split())
    length_ratio = new_len / existing_len if existing_len > 0 else 1.0

    # Criterion 2: Information containment
    existing_lower = existing.lower()
    new_lower = new.lower()

    new_contains_existing = existing_lower in new_lower
    existing_contains_new = new_lower in existing_lower

    # Decision logic
    if similarity >= 0.95:
        # Very high similarity (95%+)
        if new_contains_existing and length_ratio > 1.2:
            # New is 20%+ longer and contains all of existing
            return "UPDATE"  # New is enhancement of existing
        elif existing_contains_new:
            return "REJECT"  # New is subset of existing
        else:
            return "UPDATE"  # Safer to keep newer version

    elif similarity >= 0.85:
        # High similarity (85-95%)
        if new_contains_existing and length_ratio > 1.3:
            # New is 30%+ longer and contains existing
            return "UPDATE"  # Likely enhancement
        elif length_ratio < 0.8 or length_ratio > 1.5:
            # Length difference >20% in either direction
            return "KEEP_BOTH"  # Might be different aspects
        else:
            return "REJECT"  # Likely true duplicate

    else:
        # Lower similarity (<85%)
        return "KEEP_BOTH"  # Different enough to store both

def _update_lesson(self, doc_id: str, new_content: str, new_metadata: dict):
    """Update an existing lesson with new content."""
    collection = self._collection_map.get("lesson")

    # Get existing metadata
    existing = collection.get(ids=[doc_id])
    if existing and existing['metadatas']:
        old_metadata = existing['metadatas'][0]

        # Preserve original metadata, add update info
        updated_metadata = {
            **old_metadata,
            **new_metadata,
            "original_timestamp": old_metadata.get("timestamp"),
            "version": old_metadata.get("version", 1) + 1
        }

        # Delete old entry
        collection.delete(ids=[doc_id])

        # Add updated entry
        collection.add(
            documents=[new_content],
            metadatas=[updated_metadata],
            ids=[doc_id]  # Keep same ID for consistency
        )
```

**Pros**:
- ✅ Preserves additional information
- ✅ Keeps single, most complete version of each lesson
- ✅ Tracks evolution via metadata (versions)
- ✅ No information loss

**Cons**:
- ❌ More complex logic
- ❌ Might update when shouldn't (edge cases)
- ❌ Loses original wording (though metadata preserves history)

---

### Solution B: LLM-Based Decision (Most Accurate)

**Concept**: Use an LLM to compare lessons and decide if new one adds value.

**Algorithm**:
```python
def _check_if_adds_information(self, existing: str, new: str) -> bool:
    """
    Use LLM to check if new lesson adds information beyond existing.

    Args:
        existing: Existing lesson text
        new: New lesson text

    Returns:
        True if new lesson contains additional valuable information
    """
    prompt = f"""Compare these two lessons and determine if Lesson B contains important information that is NOT in Lesson A.

Lesson A (existing): {existing}

Lesson B (new): {new}

Does Lesson B contain important new information, details, or clarifications that are missing from Lesson A?

Answer only "YES" if B adds significant value, or "NO" if B is essentially the same as A.

Answer:"""

    # Call LLM (using existing MetaGPT infrastructure)
    response = await self._aask(prompt)  # Assuming access to LLM

    return "YES" in response.upper()


async def store_with_llm_check(self, content, item_type, agent, action, iteration):
    """Store with LLM-based duplicate checking."""

    similar_items = self._check_semantic_duplicates(content, item_type, agent, action)

    if similar_items:
        most_similar = similar_items[0]

        # Ask LLM if new lesson adds information
        adds_info = await self._check_if_adds_information(
            existing=most_similar['content'],
            new=content
        )

        if adds_info:
            # New lesson adds value - update existing
            self._update_lesson(most_similar['id'], content, {...})
        else:
            # True duplicate - reject
            return

    # No duplicate - store normally
    # ...
```

**Pros**:
- ✅ Most accurate decision
- ✅ Can handle complex cases
- ✅ Understands semantic nuances

**Cons**:
- ❌ Requires LLM call per storage (expensive)
- ❌ Adds latency (~1-2 seconds per store)
- ❌ Requires async handling
- ❌ Token costs

---

### Solution C: Hybrid Heuristic (Balanced)

**Concept**: Use lightweight heuristics to make quick decisions, fall back to LLM for uncertain cases.

**Algorithm**:
```python
def _determine_action(
    self,
    existing: str,
    new: str,
    similarity: float
) -> tuple[str, float]:
    """
    Determine action using heuristics with confidence score.

    Returns:
        (action, confidence) where:
        - action: "UPDATE", "KEEP_BOTH", "REJECT"
        - confidence: 0.0-1.0 (how confident in decision)
    """
    existing_words = set(existing.lower().split())
    new_words = set(new.lower().split())

    # Calculate metrics
    new_unique_words = new_words - existing_words
    existing_unique_words = existing_words - new_words

    new_word_count = len(new.split())
    existing_word_count = len(existing.split())

    unique_word_ratio = len(new_unique_words) / new_word_count if new_word_count > 0 else 0

    # Decision rules with confidence
    if similarity >= 0.95:
        if len(new_unique_words) > 3:
            # New has 3+ unique words - likely adds info
            return ("UPDATE", 0.8)
        elif new_word_count > existing_word_count * 1.3:
            # New is 30%+ longer
            return ("UPDATE", 0.7)
        elif new_word_count < existing_word_count * 0.9:
            # New is shorter - likely subset
            return ("REJECT", 0.9)
        else:
            # Very similar - likely duplicate
            return ("REJECT", 0.8)

    elif similarity >= 0.85:
        if len(new_unique_words) > 5:
            # Significant new vocabulary
            return ("KEEP_BOTH", 0.7)
        elif unique_word_ratio > 0.3:
            # >30% of new lesson is unique words
            return ("KEEP_BOTH", 0.6)
        else:
            return ("REJECT", 0.7)

    else:
        # Lower similarity - probably different
        return ("KEEP_BOTH", 0.9)


async def store_hybrid(self, content, item_type, agent, action, iteration):
    """Store with hybrid heuristic + LLM approach."""

    similar_items = self._check_semantic_duplicates(content, item_type, agent, action)

    if similar_items:
        most_similar = similar_items[0]

        # Use heuristics first
        action, confidence = self._determine_action(
            existing=most_similar['content'],
            new=content,
            similarity=most_similar['similarity']
        )

        # If low confidence, use LLM
        if confidence < 0.75:
            adds_info = await self._check_if_adds_information(
                most_similar['content'], content
            )
            action = "UPDATE" if adds_info else "REJECT"

        # Execute action
        if action == "UPDATE":
            self._update_lesson(most_similar['id'], content, {...})
            return
        elif action == "REJECT":
            return
        # else KEEP_BOTH: continue to normal storage

    # Store normally
    # ...
```

**Pros**:
- ✅ Fast for clear cases (heuristics)
- ✅ Accurate for uncertain cases (LLM)
- ✅ Balanced cost/accuracy tradeoff

**Cons**:
- ❌ Most complex implementation
- ❌ Still requires LLM access for some cases

---

### Solution D: Keep Both with Merging (Conservative)

**Concept**: Store both but provide merged view when retrieving.

**Algorithm**:
```python
def store_with_linking(self, content, item_type, agent, action, iteration):
    """Store with linking to similar lessons."""

    similar_items = self._check_semantic_duplicates(content, item_type, agent, action)

    # Always store, but track relationships
    doc_id = f"{agent}_{action}_{iteration}_{datetime.now().isoformat()}"

    metadata = {
        "agent": agent,
        "action": action,
        "iteration": iteration,
        "timestamp": datetime.now().isoformat()
    }

    if similar_items:
        # Link to similar lesson
        metadata["similar_to"] = similar_items[0]['id']
        metadata["similarity_score"] = similar_items[0]['similarity']

    self.lessons_collection.add(
        documents=[content],
        metadatas=[metadata],
        ids=[doc_id]
    )


def get_lessons_merged(self, agent, action, limit=10):
    """Retrieve lessons with similar ones merged."""

    all_lessons = self.get_lessons(agent=agent, action=action, limit=limit*2)

    # Group similar lessons
    merged = []
    seen_ids = set()

    for lesson in all_lessons:
        if lesson['id'] in seen_ids:
            continue

        # Find all similar lessons
        similar = [l for l in all_lessons
                  if l.get('metadata', {}).get('similar_to') == lesson['id']]

        if similar:
            # Merge content
            merged_content = self._merge_lesson_contents(
                [lesson['content']] + [s['content'] for s in similar]
            )
            merged.append(merged_content)

            seen_ids.add(lesson['id'])
            seen_ids.update(s['id'] for s in similar)
        else:
            merged.append(lesson['content'])
            seen_ids.add(lesson['id'])

    return merged[:limit]


def _merge_lesson_contents(self, lessons: List[str]) -> str:
    """Merge multiple similar lessons into one comprehensive lesson."""
    # Use LLM to intelligently merge
    prompt = f"""Merge these similar lessons into a single, comprehensive lesson that preserves all important information:

{chr(10).join(f"{i+1}. {lesson}" for i, lesson in enumerate(lessons))}

Provide a single merged lesson:"""

    merged = await self._aask(prompt)
    return merged
```

**Pros**:
- ✅ Never loses information
- ✅ Provides best of both worlds at retrieval
- ✅ Safe and conservative

**Cons**:
- ❌ Database grows larger
- ❌ Requires merging logic at retrieval (slower)
- ❌ Complex to maintain

---

## Recommended Approach

### 🎯 **Recommendation: Solution A (Update Strategy) with Simple Heuristics**

**Why**:
1. ✅ Solves the information loss problem
2. ✅ Keeps single best version (clean database)
3. ✅ No LLM calls needed (fast, free)
4. ✅ Moderate complexity
5. ✅ Tracks evolution via metadata

**Implementation**:
```python
DEDUP_CONFIG = {
    "similarity_threshold": 0.85,
    "update_length_threshold": 1.2,  # New must be 20%+ longer to update
    "unique_word_threshold": 3       # New must have 3+ unique words
}

def _should_update_existing(existing, new, similarity):
    """Use simple length + containment heuristics."""

    existing_len = len(existing.split())
    new_len = len(new.split())
    length_ratio = new_len / existing_len if existing_len > 0 else 1.0

    # Check if new contains existing (substring)
    new_contains_existing = existing.lower() in new.lower()

    if similarity >= 0.90 and new_contains_existing and length_ratio > 1.2:
        return "UPDATE"  # New is clearly an extension
    elif similarity >= 0.85 and length_ratio > 1.5:
        return "UPDATE"  # New is much longer
    elif similarity >= 0.95:
        return "REJECT"  # Too similar without added length
    else:
        return "KEEP_BOTH"  # Different enough
```

**Fallback Enhancement** (Optional Phase 2):
- Add LLM check for medium-confidence cases (similarity 0.85-0.90)
- Only call LLM when heuristics are uncertain

---

## Testing Strategy

### Test Cases for Information Preservation

```python
def test_enhancement_updates_existing():
    """New lesson with additional info should update existing."""
    memory = SemanticMemorySystem("test")

    # Store initial lesson
    memory.store(
        "Always check Alloy syntax before running",
        "lesson", "RE", "Build", 1
    )

    # Store enhanced version
    memory.store(
        "Always check Alloy syntax before running, and verify multiplicities in signatures",
        "lesson", "RE", "Build", 2
    )

    # Should have 1 lesson (updated)
    lessons = memory.get_lessons(agent="RE", action="Build")
    assert len(lessons) == 1
    assert "multiplicities" in lessons[0]  # New info preserved
    assert "syntax" in lessons[0]          # Old info preserved


def test_subset_rejected():
    """Shorter lesson that's subset of existing should be rejected."""
    memory = SemanticMemorySystem("test")

    # Store comprehensive lesson
    memory.store(
        "Always check syntax and verify multiplicities before running",
        "lesson", "RE", "Build", 1
    )

    # Try to store subset
    memory.store(
        "Check syntax before running",
        "lesson", "RE", "Build", 2
    )

    # Should still have 1 lesson (original)
    lessons = memory.get_lessons(agent="RE", action="Build")
    assert len(lessons) == 1
    assert "multiplicities" in lessons[0]  # Original preserved


def test_different_aspect_both_stored():
    """Different aspects of same topic should both be stored."""
    memory = SemanticMemorySystem("test")

    memory.store(
        "Check syntax before running analyzer",
        "lesson", "RE", "Build", 1
    )

    memory.store(
        "Check syntax errors typically occur on line numbers shown in output",
        "lesson", "RE", "Build", 2
    )

    # Should have 2 lessons (different aspects)
    lessons = memory.get_lessons(agent="RE", action="Build")
    assert len(lessons) == 2
```

---

## Configuration

```python
# src/utils/semantic_memory.py

SEMANTIC_DEDUP_CONFIG = {
    "enabled": True,
    "similarity_threshold": 0.85,

    # Update strategy settings
    "allow_updates": True,
    "update_min_length_ratio": 1.2,   # New must be 20%+ longer
    "update_min_unique_words": 3,      # New must have 3+ unique words

    # When to keep both
    "keep_both_length_diff": 0.5,      # >50% length difference
    "keep_both_similarity_max": 0.85,  # Below this, always keep both

    # LLM fallback (optional)
    "use_llm_for_uncertain": False,
    "llm_confidence_threshold": 0.75
}
```

---

## Summary

**Problem**: Naive semantic dedup loses information when new lessons enhance existing ones.

**Solution**: Smart update strategy that:
1. Detects when new lesson contains existing + additional info
2. Updates existing lesson with more complete version
3. Tracks evolution via metadata (versions, timestamps)
4. Rejects true duplicates
5. Keeps both when sufficiently different

**Implementation Priority**:
- Phase 1: Update strategy with simple heuristics (length + containment)
- Phase 2 (optional): Add LLM fallback for uncertain cases
- Phase 3 (optional): Add merged view at retrieval time

**Result**: Best of both worlds - no duplicates AND no information loss!
