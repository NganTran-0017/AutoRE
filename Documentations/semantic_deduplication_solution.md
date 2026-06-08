# Semantic Deduplication Solution

## Problem: Semantically Similar Lessons

The system stores lessons that are semantically identical but worded differently:

**Example Duplicates**:
```
1. "Always check Alloy syntax before running analyzer"
2. "Verify syntax correctness before executing Alloy"
3. "Ensure model has no syntax errors prior to analysis"
4. "Syntax validation should happen before analyzer execution"
```

All four lessons convey the **same semantic meaning** but text-based deduplication won't catch them.

---

## Current State

### ✅ Infrastructure Already Exists!

AutoRE already has:
- **ChromaDB** installed (v1.5.7) - vector database
- **sentence-transformers** installed (v5.2.0) - embedding generation
- **SemanticMemorySystem** implemented (`src/utils/semantic_memory.py`)
- **Runtime context** supports `use_semantic_memory=True` flag

### ❌ Missing: Deduplication Logic

The `SemanticMemorySystem` currently:
- ✅ Stores lessons with embeddings
- ✅ Retrieves lessons by semantic similarity
- ❌ **Does NOT check for semantic duplicates before storing**

---

## Proposed Solution: Semantic Deduplication

### Approach: **Storage-Time Semantic Check**

Add duplicate detection to `SemanticMemorySystem.store()`:

```python
def store(self, content, item_type, agent, action, iteration, metadata=None):
    """Store memory item with semantic duplicate checking."""

    # STEP 1: Check if semantically similar item already exists
    similar_items = self._check_semantic_duplicates(
        content=content,
        item_type=item_type,
        agent=agent,
        action=action,
        similarity_threshold=0.85  # 85% semantic similarity
    )

    # STEP 2: If duplicate found, skip storage (or update timestamp)
    if similar_items:
        # Option A: Silent skip
        return

        # Option B: Update existing item's timestamp/occurrence
        # self._update_occurrence(similar_items[0]['id'])
        # return

    # STEP 3: No duplicate - store normally
    collection = self._collection_map.get(item_type)
    timestamp = datetime.now().isoformat()
    doc_id = f"{agent}_{action}_{iteration}_{timestamp}"

    collection.add(
        documents=[content],
        metadatas=[{
            "agent": agent,
            "action": action,
            "iteration": iteration,
            "project": self.project_name,
            "timestamp": timestamp,
            "type": item_type,
            **(metadata or {})
        }],
        ids=[doc_id]
    )
```

### Helper Method: Semantic Duplicate Check

```python
def _check_semantic_duplicates(
    self,
    content: str,
    item_type: str,
    agent: str,
    action: str,
    similarity_threshold: float = 0.85
) -> List[Dict]:
    """
    Check if semantically similar content already exists.

    Args:
        content: New content to check
        item_type: Type of memory (lesson, pattern, event)
        agent: Agent name (for filtering)
        action: Action name (for filtering)
        similarity_threshold: Minimum similarity to consider duplicate (0.0-1.0)

    Returns:
        List of similar items found (empty if none)
    """
    collection = self._collection_map.get(item_type)
    if not collection:
        return []

    try:
        # Query for similar items in same agent/action
        results = collection.query(
            query_texts=[content],
            n_results=5,  # Check top 5 most similar
            where={"$and": [
                {"agent": agent},
                {"action": action}
            ]}
        )

        # Check if any result exceeds similarity threshold
        similar_items = []
        if results and results['documents'] and results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                distance = results['distances'][0][i]
                similarity = 1.0 - distance  # Convert distance to similarity

                if similarity >= similarity_threshold:
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
```

---

## Configuration Options

### Option 1: Fixed Threshold (Simple)

```python
SEMANTIC_SIMILARITY_THRESHOLD = 0.85  # 85% similarity = duplicate
```

**Pros**: Simple, consistent
**Cons**: May need tuning per use case

### Option 2: Configurable Per Type

```python
SIMILARITY_THRESHOLDS = {
    "lesson": 0.85,   # Strict for lessons (avoid redundancy)
    "pattern": 0.80,  # Moderate for patterns
    "event": 0.95     # Lenient for events (more specific)
}
```

**Pros**: Flexible, type-aware
**Cons**: More complex to tune

### Option 3: Agent/Action Specific

```python
# In config file or runtime_context
semantic_dedup_config = {
    "RE": {
        "BuildAlloyModel": {"threshold": 0.85, "enabled": True},
        "UpdateAlloyModel": {"threshold": 0.85, "enabled": True}
    },
    "Evaluator": {
        "AnalyzeAlloyModel": {"threshold": 0.80, "enabled": True}
    }
}
```

**Pros**: Maximum control
**Cons**: Complex, requires maintenance

**Recommendation**: Start with **Option 2** (per-type thresholds)

---

## Similarity Threshold Guidelines

| Threshold | Meaning | Example |
|-----------|---------|---------|
| 0.95-1.0 | Nearly identical | "Check syntax" vs "Check the syntax" |
| 0.85-0.95 | Same core meaning | "Check syntax" vs "Verify syntax correctness" |
| 0.70-0.85 | Related but different | "Check syntax" vs "Ensure no runtime errors" |
| 0.50-0.70 | Loosely related | "Check syntax" vs "Use temporal operators" |
| 0.0-0.50 | Unrelated | "Check syntax" vs "User requested feature X" |

**Recommended for lessons**: **0.85** (catches semantic duplicates, avoids false positives)

---

## Implementation Steps

### Phase 1: Add Semantic Dedup to Store (2-3 hours)

**File**: `src/utils/semantic_memory.py`

1. Add `_check_semantic_duplicates()` method
2. Modify `store()` to check before storing
3. Add configuration parameters
4. Test with example lessons

**Changes Required**:
- Lines 67-112: Modify `store()` method
- Add new helper method (~40 lines)
- Add config constants at top of file

### Phase 2: Add Retrieval Dedup (Optional Safety Net) (1-2 hours)

Even with storage dedup, add retrieval-time dedup as safety net:

```python
def get_lessons(self, agent=None, action=None, limit=10, query=None):
    """Get lessons with semantic deduplication."""

    # Retrieve more than needed
    if query:
        results = self.retrieve_similar(
            query=query,
            item_type="lesson",
            agent=agent,
            action=action,
            limit=limit * 2  # Get more, then deduplicate
        )
    else:
        # ... existing code ...

    # Deduplicate semantically similar results
    unique_results = self._deduplicate_results(results, threshold=0.85)

    return [r['content'] for r in unique_results[:limit]]

def _deduplicate_results(self, results: List[Dict], threshold: float = 0.85) -> List[Dict]:
    """Remove semantically similar items from results."""
    from sentence_transformers import SentenceTransformer, util

    if not results or len(results) <= 1:
        return results

    # Load model
    model = SentenceTransformer('all-MiniLM-L6-v2')

    # Get embeddings
    texts = [r['content'] for r in results]
    embeddings = model.encode(texts)

    # Keep track of unique items
    unique = []
    unique_embeddings = []

    for i, result in enumerate(results):
        is_duplicate = False

        # Compare against already-selected unique items
        for j, unique_emb in enumerate(unique_embeddings):
            similarity = util.cos_sim(embeddings[i], unique_emb).item()
            if similarity >= threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            unique.append(result)
            unique_embeddings.append(embeddings[i])

    return unique
```

### Phase 3: Monitoring & Tuning (Ongoing)

Add logging to track deduplication effectiveness:

```python
def store(self, content, item_type, agent, action, iteration, metadata=None):
    # ... duplicate check ...

    if similar_items:
        # Log the duplicate
        if hasattr(self, '_debug_mode') and self._debug_mode:
            print(f"[DEDUP] Skipped duplicate {item_type}:")
            print(f"  New: {content[:60]}...")
            print(f"  Existing: {similar_items[0]['content'][:60]}...")
            print(f"  Similarity: {similar_items[0]['similarity']:.2f}")
        return
```

---

## Testing Strategy

### Test File: `test/test_semantic_deduplication.py`

```python
import unittest
from src.utils.semantic_memory import SemanticMemorySystem

class TestSemanticDeduplication(unittest.TestCase):

    def setUp(self):
        self.memory = SemanticMemorySystem("test_dedup")
        self.memory.clear_all()

    def test_exact_duplicate_prevented(self):
        """Exact duplicate should be prevented."""
        self.memory.store("Check syntax", "lesson", "RE", "Build", 1)
        self.memory.store("Check syntax", "lesson", "RE", "Build", 2)

        lessons = self.memory.get_lessons(agent="RE", action="Build")
        self.assertEqual(len(lessons), 1)

    def test_semantic_duplicate_prevented(self):
        """Semantically similar lessons should be prevented."""
        self.memory.store(
            "Always check Alloy syntax before running analyzer",
            "lesson", "RE", "Build", 1
        )
        self.memory.store(
            "Verify syntax correctness before executing Alloy",
            "lesson", "RE", "Build", 2
        )
        self.memory.store(
            "Ensure model has no syntax errors prior to analysis",
            "lesson", "RE", "Build", 3
        )

        lessons = self.memory.get_lessons(agent="RE", action="Build")
        # Should only have 1 lesson (all 3 are semantically similar)
        self.assertEqual(len(lessons), 1)

    def test_different_lessons_both_stored(self):
        """Genuinely different lessons should both be stored."""
        self.memory.store(
            "Always check Alloy syntax before running",
            "lesson", "RE", "Build", 1
        )
        self.memory.store(
            "Use temporal operators for state transitions",
            "lesson", "RE", "Build", 2
        )

        lessons = self.memory.get_lessons(agent="RE", action="Build")
        self.assertEqual(len(lessons), 2)

    def test_cross_agent_duplicates_allowed(self):
        """Same lesson from different agents should be stored separately."""
        self.memory.store("Check syntax", "lesson", "RE", "Build", 1)
        self.memory.store("Check syntax", "lesson", "Evaluator", "Analyze", 1)

        re_lessons = self.memory.get_lessons(agent="RE", action="Build")
        eval_lessons = self.memory.get_lessons(agent="Evaluator", action="Analyze")

        self.assertEqual(len(re_lessons), 1)
        self.assertEqual(len(eval_lessons), 1)

    def test_threshold_sensitivity(self):
        """Test that threshold controls what's considered duplicate."""
        # These are somewhat similar but not identical in meaning
        lesson1 = "Use multiplicities carefully in signatures"
        lesson2 = "Be careful with cardinality constraints"

        # With high threshold (0.95), both should be stored
        memory_strict = SemanticMemorySystem("test_strict")
        memory_strict.dedup_threshold = 0.95
        memory_strict.store(lesson1, "lesson", "RE", "Build", 1)
        memory_strict.store(lesson2, "lesson", "RE", "Build", 2)

        lessons_strict = memory_strict.get_lessons(agent="RE", action="Build")
        self.assertEqual(len(lessons_strict), 2)  # Both stored

        # With low threshold (0.70), second should be blocked
        memory_lenient = SemanticMemorySystem("test_lenient")
        memory_lenient.dedup_threshold = 0.70
        memory_lenient.store(lesson1, "lesson", "RE", "Build", 1)
        memory_lenient.store(lesson2, "lesson", "RE", "Build", 2)

        lessons_lenient = memory_lenient.get_lessons(agent="RE", action="Build")
        self.assertEqual(len(lessons_lenient), 1)  # Duplicate blocked
```

---

## Performance Impact

### Storage Operation

**Before**: ~2-5ms (ChromaDB add with embedding generation)
**After**: ~10-15ms (+ similarity query for top 5 existing lessons)

**Breakdown**:
- Duplicate check query: +5-8ms
- Embedding comparison: ~2ms
- Total overhead: +7-10ms per store

**Mitigation**:
- Only checks top 5 most similar (not entire database)
- Uses ChromaDB's optimized vector search
- Cached embeddings (ChromaDB handles this)

### Retrieval Operation

**No change** if only using storage-time dedup
**+5-10ms** if also using retrieval-time dedup

### Memory Usage

**Minimal increase**: ChromaDB embeddings already generated and stored

---

## Migration & Rollout

### Step 1: Enable for New Sessions Only

```python
# In runtime_context.py
def __init__(self, project_name="default", logger=None,
             use_semantic_memory=True,
             enable_semantic_dedup=True):  # NEW FLAG

    if use_semantic_memory:
        self.memory = SemanticMemorySystem(
            project_name,
            enable_deduplication=enable_semantic_dedup
        )
```

### Step 2: No Migration Needed

Existing duplicate lessons in database will remain (historical data preserved).
New lessons will be checked against all existing lessons (including old duplicates).

### Step 3: Optional Cleanup (Advanced)

If you want to clean up existing duplicates:

```python
# Utility script: scripts/cleanup_semantic_duplicates.py
def cleanup_duplicates(memory_system, similarity_threshold=0.85):
    """Remove semantic duplicates from existing database."""

    # Get all lessons
    all_lessons = memory_system.lessons_collection.get()

    if not all_lessons or not all_lessons['documents']:
        return

    # Track duplicates to remove
    to_remove = []
    seen = []

    for i, doc in enumerate(all_lessons['documents']):
        is_duplicate = False
        doc_id = all_lessons['ids'][i]

        # Compare against seen lessons
        for seen_doc in seen:
            # Query similarity
            results = memory_system.lessons_collection.query(
                query_texts=[doc],
                n_results=1,
                where={"id": seen_doc['id']}
            )

            if results and results['distances'][0]:
                distance = results['distances'][0][0]
                similarity = 1.0 - distance

                if similarity >= similarity_threshold:
                    is_duplicate = True
                    to_remove.append(doc_id)
                    break

        if not is_duplicate:
            seen.append({'id': doc_id, 'content': doc})

    # Remove duplicates
    if to_remove:
        memory_system.lessons_collection.delete(ids=to_remove)
        print(f"Removed {len(to_remove)} duplicate lessons")
```

---

## Comparison with Previous Solutions

| Feature | JSON-based (Sol 2/3) | Semantic (Proposed) |
|---------|---------------------|---------------------|
| Catches exact duplicates | ✅ | ✅ |
| Catches semantic duplicates | ❌ | ✅ |
| Implementation complexity | Low | Medium |
| Storage overhead | ~1ms | ~10ms |
| Infrastructure needed | None (exists) | ChromaDB (exists) |
| Accuracy for problem | Low | **High** ✅ |
| False positives | Low | Low (tunable) |

**Verdict**: Semantic solution is the **correct approach** for this problem.

---

## Recommended Configuration

```python
# src/utils/semantic_memory.py

# Deduplication configuration
SEMANTIC_DEDUP_CONFIG = {
    "enabled": True,
    "thresholds": {
        "lesson": 0.85,   # Strict - avoid redundant lessons
        "pattern": 0.80,  # Moderate - patterns can be more varied
        "event": 0.95     # Lenient - events are specific occurrences
    },
    "check_top_n": 5,     # Only check top 5 most similar items
    "cross_agent": False  # Don't deduplicate across different agents
}
```

---

## Summary & Recommendation

### ✅ Recommended Solution: Semantic Deduplication at Storage Time

**Why**:
1. Infrastructure already exists (ChromaDB + sentence-transformers)
2. Directly addresses the semantic similarity problem
3. Moderate implementation effort (~3-4 hours)
4. Tunable threshold for precision/recall balance
5. Minimal performance impact (~10ms per store)
6. Backward compatible (no migration needed)

**Implementation Priority**:
1. **Phase 1** (Essential): Add `_check_semantic_duplicates()` to `SemanticMemorySystem.store()`
2. **Phase 2** (Optional): Add retrieval-time dedup as safety net
3. **Phase 3** (Nice-to-have): Add monitoring and historical cleanup

**Next Steps**:
1. Implement `_check_semantic_duplicates()` method
2. Modify `store()` to check before storing
3. Add configuration with threshold=0.85 for lessons
4. Test with real lesson examples
5. Monitor and tune threshold based on results

Would you like me to proceed with the implementation?
