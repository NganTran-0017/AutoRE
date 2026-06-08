# Solution 3: Hybrid Deduplication - Implementation Guide

## Overview

Hybrid approach combines:
1. **Storage-time check**: Prevent obvious duplicates within recent window
2. **Retrieval-time dedup**: Ensure clean output regardless

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    STORAGE TIME                              │
│  Agent emits: [LESSON]: Always check Alloy syntax           │
│         ↓                                                    │
│  Check: Is this in recent lessons? (last N items)           │
│         ↓                                                    │
│  Same session (within 1 hour)?  → Skip (duplicate)          │
│  Different session?              → Store (valid repeat)      │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                   RETRIEVAL TIME                             │
│  Request: get_lessons(agent="RE", action="Build", limit=5)  │
│         ↓                                                    │
│  Fetch: All matching lessons (may have cross-session dupes) │
│         ↓                                                    │
│  Deduplicate: Keep most recent version of each unique text  │
│         ↓                                                    │
│  Return: Clean, unique list of lessons                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Details

### Part 1: Storage-Time Deduplication

**File**: `src/utils/memory_system.py`
**Method**: `LongTermMemorySystem.store()`

**Algorithm**:
```python
def store(self, content, item_type, agent, action, iteration, metadata=None):
    """Store item with recent duplicate checking."""

    # Step 1: Normalize content for comparison
    normalized_content = self._normalize_content(content)

    # Step 2: Check recent items (lightweight window)
    if item_type == "lesson":
        recent_duplicates = self._check_recent_duplicates(
            normalized_content=normalized_content,
            agent=agent,
            action=action,
            item_type=item_type,
            window_size=20,  # Check last 20 lessons for this agent/action
            time_threshold_seconds=3600  # 1 hour
        )

        if recent_duplicates:
            # Duplicate found in recent window - skip storage
            return  # Silent skip (or log debug message)

    # Step 3: No recent duplicate - store normally
    item = MemoryItem(
        content=content,
        type=item_type,
        tags={
            "agent": agent,
            "action": action,
            "iteration": iteration,
            "project": self.project_name
        },
        metadata=metadata or {},
        timestamp=datetime.now().isoformat()
    )
    self.items.append(item)
```

**Helper Methods**:

```python
def _normalize_content(self, content: str) -> str:
    """
    Normalize content for duplicate detection.

    - Strip whitespace
    - Convert to lowercase
    - Collapse multiple spaces
    - Remove common punctuation variations
    """
    normalized = content.strip().lower()
    normalized = re.sub(r'\s+', ' ', normalized)  # Collapse spaces
    normalized = re.sub(r'[.,!?;:]+$', '', normalized)  # Remove trailing punct
    return normalized

def _check_recent_duplicates(
    self,
    normalized_content: str,
    agent: str,
    action: str,
    item_type: str,
    window_size: int = 20,
    time_threshold_seconds: int = 3600
) -> bool:
    """
    Check if normalized content exists in recent items.

    Args:
        normalized_content: Content already normalized
        agent: Agent filter
        action: Action filter
        item_type: Type filter
        window_size: How many recent items to check
        time_threshold_seconds: Time window (default 1 hour)

    Returns:
        True if duplicate found, False otherwise
    """
    from datetime import datetime, timedelta

    # Get recent items for this agent/action/type
    recent_items = self.retrieve(
        agent=agent,
        action=action,
        item_type=item_type,
        limit=window_size
    )

    # Calculate time threshold
    now = datetime.now()
    threshold_time = now - timedelta(seconds=time_threshold_seconds)

    # Check each recent item
    for item in recent_items:
        # Parse timestamp
        item_time = datetime.fromisoformat(item.timestamp)

        # Only check items within time window
        if item_time < threshold_time:
            continue  # Too old, skip

        # Normalize and compare
        item_normalized = self._normalize_content(item.content)
        if item_normalized == normalized_content:
            return True  # Duplicate found

    return False  # No duplicate
```

**Configuration Parameters**:
```python
# In __init__ or config
self.storage_dedup_config = {
    "enabled": True,
    "window_size": 20,        # Check last N items
    "time_threshold": 3600,   # Within 1 hour
    "apply_to_types": ["lesson"]  # Only deduplicate lessons, not events
}
```

---

### Part 2: Retrieval-Time Deduplication

**File**: `src/utils/memory_system.py`
**Method**: `LongTermMemorySystem.get_lessons()`

**Algorithm**:
```python
def get_lessons(
    self,
    agent: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 10
) -> List[str]:
    """
    Get lessons with deduplication.

    Retrieves more items than needed, deduplicates, then returns up to limit.
    """
    # Step 1: Retrieve more than needed (to account for duplicates)
    retrieval_multiplier = 3  # Retrieve 3x limit to ensure enough unique items
    items = self.retrieve(
        agent=agent,
        action=action,
        item_type="lesson",
        limit=limit * retrieval_multiplier  # Fetch more than needed
    )

    # Step 2: Deduplicate while preserving order (most recent first)
    unique_items = self._deduplicate_items(items)

    # Step 3: Limit to requested amount
    limited_items = unique_items[:limit]

    # Step 4: Return content only
    return [item.content for item in limited_items]

def _deduplicate_items(self, items: List[MemoryItem]) -> List[MemoryItem]:
    """
    Deduplicate items by normalized content, keeping most recent.

    Args:
        items: List of memory items (already sorted by timestamp desc)

    Returns:
        Deduplicated list (preserves order)
    """
    seen = {}
    unique = []

    for item in items:
        normalized = self._normalize_content(item.content)

        if normalized not in seen:
            seen[normalized] = True
            unique.append(item)

    return unique
```

**Advanced Option** (Fuzzy Deduplication):
```python
def _deduplicate_items_fuzzy(
    self,
    items: List[MemoryItem],
    similarity_threshold: float = 0.90
) -> List[MemoryItem]:
    """
    Fuzzy deduplication using sequence matching.

    Args:
        items: List of memory items
        similarity_threshold: 0.0-1.0, how similar to consider duplicate

    Returns:
        Deduplicated list
    """
    from difflib import SequenceMatcher

    unique = []

    for item in items:
        is_duplicate = False
        item_normalized = self._normalize_content(item.content)

        # Compare against already-accepted unique items
        for unique_item in unique:
            unique_normalized = self._normalize_content(unique_item.content)

            # Calculate similarity ratio
            similarity = SequenceMatcher(
                None,
                item_normalized,
                unique_normalized
            ).ratio()

            if similarity >= similarity_threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            unique.append(item)

    return unique
```

---

## Configuration Management

**File**: `src/utils/memory_system.py`

```python
@dataclass
class DeduplicationConfig:
    """Configuration for hybrid deduplication."""

    # Storage-time settings
    storage_enabled: bool = True
    storage_window_size: int = 20
    storage_time_threshold: int = 3600  # 1 hour in seconds
    storage_apply_to: List[str] = field(default_factory=lambda: ["lesson"])

    # Retrieval-time settings
    retrieval_enabled: bool = True
    retrieval_method: str = "exact"  # "exact" or "fuzzy"
    retrieval_similarity_threshold: float = 0.90  # For fuzzy mode
    retrieval_multiplier: int = 3  # Fetch this many times limit

class LongTermMemorySystem:
    def __init__(self, project_name: str, dedup_config: Optional[DeduplicationConfig] = None):
        self.project_name = project_name
        self.storage_path = Path(f"memory/{project_name}/")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Deduplication configuration
        self.dedup_config = dedup_config or DeduplicationConfig()

        self.items: List[MemoryItem] = []
        self._load()
```

---

## Testing Strategy

### Test File: `test/test_hybrid_deduplication.py`

**Test Cases**:

```python
class TestHybridDeduplication(unittest.TestCase):

    def test_storage_prevents_same_session_duplicate(self):
        """Same lesson within 1 hour should not be stored twice."""
        memory = LongTermMemorySystem("test")

        # Store lesson
        memory.store("Check syntax", "lesson", "RE", "Build", 1)
        assert len(memory.items) == 1

        # Try to store same lesson (within time window)
        memory.store("Check syntax", "lesson", "RE", "Build", 1)
        assert len(memory.items) == 1  # Still 1, duplicate prevented

    def test_storage_allows_cross_session_duplicate(self):
        """Same lesson from different session (>1 hour) should be stored."""
        memory = LongTermMemorySystem("test")

        # Store lesson
        memory.store("Check syntax", "lesson", "RE", "Build", 1)

        # Manually set old timestamp (simulate old session)
        memory.items[0].timestamp = "2026-01-01T10:00:00"

        # Store same lesson now (new session)
        memory.store("Check syntax", "lesson", "RE", "Build", 2)
        assert len(memory.items) == 2  # Both stored

    def test_retrieval_deduplicates_cross_session(self):
        """Retrieval should deduplicate even if storage allowed it."""
        memory = LongTermMemorySystem("test")

        # Manually add duplicates (simulating cross-session)
        memory.items.append(MemoryItem(
            content="Check syntax",
            type="lesson",
            tags={"agent": "RE", "action": "Build"},
            metadata={},
            timestamp="2026-01-01T10:00:00"
        ))
        memory.items.append(MemoryItem(
            content="Check syntax",
            type="lesson",
            tags={"agent": "RE", "action": "Build"},
            metadata={},
            timestamp="2026-01-02T10:00:00"
        ))

        # Retrieve should return only 1
        lessons = memory.get_lessons(agent="RE", action="Build", limit=10)
        assert len(lessons) == 1
        assert lessons[0] == "Check syntax"

    def test_normalization_handles_variations(self):
        """Normalization should catch case/whitespace variations."""
        memory = LongTermMemorySystem("test")

        memory.store("Check syntax", "lesson", "RE", "Build", 1)
        memory.store("  check   syntax  ", "lesson", "RE", "Build", 1)
        memory.store("Check Syntax.", "lesson", "RE", "Build", 1)

        # All three are duplicates after normalization
        assert len(memory.items) == 1

    def test_different_lessons_not_deduplicated(self):
        """Genuinely different lessons should not be removed."""
        memory = LongTermMemorySystem("test")

        memory.store("Check syntax", "lesson", "RE", "Build", 1)
        memory.store("Use temporal operators", "lesson", "RE", "Build", 1)

        assert len(memory.items) == 2

        lessons = memory.get_lessons(agent="RE", action="Build")
        assert len(lessons) == 2

    def test_events_not_deduplicated(self):
        """Events should not be deduplicated (config: apply_to=['lesson'])."""
        memory = LongTermMemorySystem("test")

        # Store same event twice
        memory.store("Fixed syntax error", "event", "RE", "Build", 1)
        memory.store("Fixed syntax error", "event", "RE", "Build", 1)

        # Events should both be stored (no dedup for events)
        events = memory.get_events(agent="RE")
        assert len(events) == 2

    def test_fuzzy_matching(self):
        """Fuzzy mode should catch similar but not identical lessons."""
        config = DeduplicationConfig(
            retrieval_method="fuzzy",
            retrieval_similarity_threshold=0.85
        )
        memory = LongTermMemorySystem("test", dedup_config=config)

        # Manually add similar lessons (bypassing storage dedup for test)
        memory.dedup_config.storage_enabled = False
        memory.store("Always check Alloy syntax before running", "lesson", "RE", "Build", 1)
        memory.store("Always check Alloy syntax before execution", "lesson", "RE", "Build", 1)

        # Retrieval with fuzzy should return 1 (>85% similar)
        lessons = memory.get_lessons(agent="RE", action="Build")
        assert len(lessons) == 1
```

---

## Performance Considerations

### Storage-Time Impact

**Best Case**: O(1) - no recent items to check
**Average Case**: O(W) - check W items in window (W=20)
**Worst Case**: O(W) - always checks full window

**Mitigation**:
- Small window size (20 items)
- Only checks recent items (already in memory)
- Early exit on first match
- Only applied to lessons (not all item types)

**Estimated overhead**: < 1ms per store operation

### Retrieval-Time Impact

**Best Case**: O(N) - single pass deduplication
**Average Case**: O(N) - where N = limit * multiplier
**Worst Case**: O(N²) - for fuzzy matching (compare each to each)

**Mitigation**:
- Use exact matching by default (O(N))
- Only fetch 3x limit (not entire database)
- Items already sorted (no extra sort needed)
- Fuzzy mode optional (opt-in)

**Estimated overhead**: < 5ms for typical retrieval (limit=10)

---

## Migration Path

### Phase 1: Add Storage-Time Check
1. Add `_normalize_content()` helper
2. Add `_check_recent_duplicates()` method
3. Modify `store()` to check before storing
4. Test with existing memory files (no migration needed)

### Phase 2: Add Retrieval-Time Dedup
1. Add `_deduplicate_items()` helper
2. Modify `get_lessons()` to deduplicate
3. Test with existing memory files
4. Monitor performance

### Phase 3: Configuration & Tuning
1. Add `DeduplicationConfig` dataclass
2. Make parameters configurable
3. Add fuzzy matching option
4. Tune window size and thresholds based on usage

---

## Configuration File Example

**File**: `config/memory_dedup.yaml` (optional)

```yaml
memory:
  deduplication:
    # Storage-time settings
    storage:
      enabled: true
      window_size: 20
      time_threshold_seconds: 3600  # 1 hour
      apply_to_types:
        - lesson

    # Retrieval-time settings
    retrieval:
      enabled: true
      method: exact  # exact | fuzzy
      similarity_threshold: 0.90  # For fuzzy mode
      retrieval_multiplier: 3
```

---

## Advantages of Hybrid Approach

| Feature | Solution 1 Only | Solution 2 Only | Solution 3 (Hybrid) |
|---------|-----------------|-----------------|---------------------|
| Prevents same-session dupes | ✅ | ❌ | ✅ |
| Handles cross-session dupes | ❌ | ✅ | ✅ |
| Clean database | ✅ | ❌ | 🟡 (mostly) |
| Preserves history | ❌ | ✅ | ✅ |
| Prompt always clean | 🟡 | ✅ | ✅ |
| Storage overhead | Medium | None | Low |
| Retrieval overhead | None | Medium | Medium |
| Backward compatible | ✅ | ✅ | ✅ |

---

## Potential Issues & Solutions

### Issue 1: Time Threshold Too Strict
**Problem**: 1-hour window might be too short for long sessions
**Solution**: Make configurable, suggest 2-3 hours for RE workflows

### Issue 2: Window Size Too Small
**Problem**: Window of 20 might miss duplicates further back
**Solution**: Increase to 50, or use time-based window instead (e.g., "last 1000 iterations")

### Issue 3: Normalization Too Aggressive
**Problem**: Might merge genuinely different lessons
**Solution**: Keep normalization conservative (case + whitespace only)

### Issue 4: Fuzzy Mode False Positives
**Problem**: 90% similarity might be too strict/loose
**Solution**: Make threshold configurable per agent/action, default to exact mode

---

## Summary

**Key Implementation Files**:
1. `src/utils/memory_system.py` - Both storage and retrieval changes
2. `test/test_hybrid_deduplication.py` - Comprehensive test suite
3. `config/memory_dedup.yaml` - Optional configuration

**Estimated Implementation Time**:
- Core logic: 2-3 hours
- Testing: 1-2 hours
- Documentation: 1 hour
- **Total**: 4-6 hours

**Risk Level**: Medium
- Two points of failure (storage + retrieval)
- More complex than Solution 2
- But backward compatible and well-tested

**Recommended If**:
- You want best balance of efficiency and effectiveness
- Database size is a concern
- You're willing to invest in more complex implementation
- You want cross-session historical patterns preserved

**Not Recommended If**:
- You want quickest implementation (use Solution 2)
- Database size not a concern (use Solution 2)
- You want simplest maintenance (use Solution 2)
