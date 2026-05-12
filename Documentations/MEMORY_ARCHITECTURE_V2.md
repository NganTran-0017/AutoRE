# Two-Tier Memory Architecture v2.0

## Design Decisions (Based on Discussion)

### 1. Lesson Creation: Explicit Reflection Phase ✅
- **When**: End of each iteration
- **How**: Agent reviews events from current iteration
- **Process**: Extract lessons or refine existing ones

### 2. Event Structure: Soft Link with Lesson Tags ✅
- Events contain `lesson_tags` (categories)
- No lesson text in events (avoid duplication)
- Tags help with pattern detection

### 3. Lesson Evolution: Refinement ✅
- If new events suggest different insight → Refine lesson
- If new events confirm existing lesson → Add to supporting_events only
- Lessons evolve as understanding deepens

### 4. Retrieval Strategy: Hybrid Search ✅
- Search both events and lessons simultaneously
- Rank by relevance
- Return: concrete examples (events) + abstract guidance (lessons)

### 5. Event Granularity: Just Right ✅
- Not too specific: "Changed line 45"
- Not too abstract: "Fixed errors"
- Just right: "Fixed multiplicity error in Room signature by adding 'one'"

### 6. Event-Lesson Linking: Bidirectional ✅
- Events → Lessons (via lesson_tags and contributing_lessons)
- Lessons → Events (via supporting_events)
- Can traverse in both directions

### 7. Multiple Lessons per Event: Yes ✅
- Single event can contribute to multiple lessons
- Example: Syntax error fix contributes to "Alloy syntax" and "Error recovery"

### 8. Lesson Confidence: Event Count ✅
- 1-2 supporting events → Low confidence
- 3-5 supporting events → Medium confidence
- 6+ supporting events → High confidence

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                      Agent Task Execution                       │
└────────────────────────────────────────────────────────────────┘
                              │
                              │ During iteration
                              ▼
                    ┌──────────────────┐
                    │  Record Events   │
                    │   (Granular)     │
                    └────────┬─────────┘
                             │
                    ┌────────▼────────┐
                    │ Event Storage   │
                    │ - problem       │
                    │ - solution      │
                    │ - lesson_tags   │
                    │ - context       │
                    └────────┬────────┘
                             │
                             │ End of iteration
                             ▼
                    ┌──────────────────┐
                    │ Reflection Phase │
                    │ (Extract/Refine) │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         Check Existing   Create New    Update Links
            Lessons        Lessons     (Bidirectional)
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                    ┌─────────────────┐
                    │ Lesson Storage  │
                    │ - lesson text   │
                    │ - confidence    │
                    │ - supporting_   │
                    │   events        │
                    └─────────────────┘
                             │
                             │ Next iteration
                             ▼
                    ┌─────────────────┐
                    │  Hybrid Search  │
                    │ Events + Lessons│
                    └─────────────────┘
```

---

## Data Structures

### Event Structure

```python
{
    # Identity
    "event_id": "event_2_1713876000",

    # Core content (NO lesson text - that's in lessons collection)
    "problem": "Syntax error in Room signature at line 45: undefined multiplicity for 'occupant: Person'",
    "solution": "Added 'one' multiplicity keyword: 'sig Room { occupant: one Person }'",

    # Soft link to lessons (categories only)
    "lesson_tags": ["alloy_syntax", "multiplicity"],

    # Bidirectional link (populated during reflection)
    "contributing_lessons": ["lesson_alloy_syntax_1", "lesson_error_recovery_3"],

    # Context
    "context": {
        "file": "AlloyModel__2.als",
        "line": 45,
        "error_type": "multiplicity_error",
        "iteration": 2,
        "alloy_message": "There are 38 such fields"
    },

    # Metadata
    "outcome": "success",  # success/partial/failed
    "timestamp": "2026-04-22T10:30:00",
    "agent": "RE"
}
```

### Lesson Structure

```python
{
    # Identity
    "lesson_id": "lesson_alloy_syntax_1",

    # Core content (abstract, high-level)
    "lesson": "Always specify multiplicity (one/lone/some/set) in Alloy relation declarations",

    # Category
    "category": "alloy_syntax",

    # Confidence (based on supporting events count)
    "confidence": "high",  # low/medium/high

    # Bidirectional link to events
    "supporting_events": [
        "event_2_1713876000",
        "event_4_1713876100",
        "event_7_1713876200"
    ],

    # Provenance
    "created_from": "pattern_detection",  # pattern_detection/agent_insight/user_guidance

    # Evolution tracking
    "created_at": "2026-04-22T10:35:00",
    "last_refined": "2026-04-22T11:20:00",
    "refinement_count": 2,
    "previous_versions": [
        "Specify multiplicity in Alloy",  # Version 1
        "Always specify multiplicity in Alloy relations"  # Version 2
    ]
}
```

---

## Agent Workflow

### Phase 1: During Iteration - Record Events

```python
class RequirementEngineer(AutoREBaseAgent):

    def _act(self):
        # Agent performs task (e.g., fixing syntax error)
        result = self._fix_syntax_error(error)

        # Record event (NOT lesson - that comes during reflection)
        self.record_event(
            problem="Syntax error: undefined multiplicity in Room signature at line 45",
            solution="Added 'one' multiplicity keyword to occupant relation",
            lesson_tags=["alloy_syntax", "multiplicity"],
            context={
                "file": "AlloyModel__2.als",
                "line": 45,
                "error_type": "multiplicity_error"
            },
            outcome="success"
        )

        return result
```

### Phase 2: End of Iteration - Reflection

```python
class AutoREBaseAgent(Role):

    def end_iteration(self):
        """
        Called at the end of each iteration to reflect and extract lessons.
        """
        print(f"[{self.agent_name}] 🤔 Starting reflection phase for iteration {self.current_iteration}...")

        # 1. Get events from current iteration
        iteration_events = self.long_term_memory.get_events(
            iteration=self.current_iteration
        )

        print(f"[{self.agent_name}] 📊 Reviewing {len(iteration_events)} events...")

        # 2. Extract or refine lessons
        lessons_created, lessons_refined = self.reflect_and_extract_lessons(iteration_events)

        print(f"[{self.agent_name}] ✨ Reflection complete:")
        print(f"   - Created {lessons_created} new lessons")
        print(f"   - Refined {lessons_refined} existing lessons")

        # 3. Store iteration summary
        self.long_term_memory.store_iteration_summary(
            iteration=self.current_iteration,
            summary=self._create_iteration_summary(iteration_events),
            key_outcomes=[event['problem'] for event in iteration_events[:3]]
        )

        # 4. Increment iteration
        self.current_iteration += 1
```

### Phase 3: Reflection Logic

```python
def reflect_and_extract_lessons(
    self,
    events: List[Dict[str, Any]]
) -> tuple[int, int]:
    """
    Review events and extract/refine lessons.

    Returns:
        (lessons_created, lessons_refined)
    """
    created_count = 0
    refined_count = 0

    # Group events by lesson_tags
    events_by_tag = self._group_events_by_tags(events)

    for tag, tag_events in events_by_tag.items():
        # Get existing lessons in this category
        existing_lessons = self.long_term_memory.get_lessons_by_category(tag)

        if existing_lessons:
            # Check each existing lesson for potential refinement
            for lesson in existing_lessons:
                if self._should_refine_lesson(lesson, tag_events):
                    # Events suggest a refinement
                    self._refine_lesson(lesson, tag_events)
                    refined_count += 1
                else:
                    # Just add supporting events (strengthen confidence)
                    self._add_supporting_events(lesson, tag_events)
        else:
            # No existing lesson in this category - create new
            if len(tag_events) >= 1:  # At least 1 event to create lesson
                self._create_lesson_from_events(tag, tag_events)
                created_count += 1

    return created_count, refined_count


def _group_events_by_tags(
    self,
    events: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Group events by their lesson_tags."""
    grouped = {}
    for event in events:
        for tag in event.get('lesson_tags', []):
            if tag not in grouped:
                grouped[tag] = []
            grouped[tag].append(event)
    return grouped


def _should_refine_lesson(
    self,
    lesson: Dict[str, Any],
    new_events: List[Dict[str, Any]]
) -> bool:
    """
    Determine if lesson should be refined based on new events.

    Refinement criteria:
    - New events suggest more specific principle
    - New events suggest broader principle
    - New events add important nuance
    """
    # Use LLM to check if new events suggest refinement
    prompt = f"""
Current Lesson: {lesson['lesson']}

New Events:
{self._format_events_for_analysis(new_events)}

Question: Do these new events suggest the lesson should be refined to be more accurate or complete?
- If they simply confirm the existing lesson, answer NO
- If they suggest important changes or additions, answer YES and explain how

Answer (YES/NO and explanation):
"""

    response = self._llm_call(prompt)
    return response.strip().upper().startswith('YES')


def _refine_lesson(
    self,
    lesson: Dict[str, Any],
    new_events: List[Dict[str, Any]]
):
    """Refine an existing lesson based on new events."""

    # Use LLM to generate refined lesson
    prompt = f"""
Current Lesson: {lesson['lesson']}
Supporting Events: {len(lesson['supporting_events'])} previous events

New Events:
{self._format_events_for_analysis(new_events)}

Task: Refine the lesson to incorporate insights from the new events while preserving the core truth.
Keep it concise and actionable.

Refined Lesson:
"""

    refined_text = self._llm_call(prompt).strip()

    # Update lesson in long-term memory
    self.long_term_memory.refine_lesson(
        lesson_id=lesson['lesson_id'],
        refined_text=refined_text,
        new_supporting_events=[e['event_id'] for e in new_events]
    )

    print(f"[{self.agent_name}] 🔄 Refined lesson: {lesson['category']}")
    print(f"   Before: {lesson['lesson'][:60]}...")
    print(f"   After:  {refined_text[:60]}...")


def _create_lesson_from_events(
    self,
    category: str,
    events: List[Dict[str, Any]]
):
    """Create a new lesson from a group of events."""

    # Use LLM to extract general principle
    prompt = f"""
Events from category '{category}':

{self._format_events_for_analysis(events)}

Task: Extract a general, reusable lesson from these events.
The lesson should be:
- Abstract enough to apply to future situations
- Specific enough to be actionable
- Concise (1-2 sentences)

Lesson:
"""

    lesson_text = self._llm_call(prompt).strip()

    # Store in long-term memory
    self.long_term_memory.store_lesson(
        lesson=lesson_text,
        category=category,
        supporting_events=[e['event_id'] for e in events],
        created_from="pattern_detection",
        confidence=self._calculate_confidence(len(events))
    )

    print(f"[{self.agent_name}] ✨ Created new lesson: {category}")
    print(f"   {lesson_text}")
```

---

## LongTermMemory API Updates

### Core Methods

```python
class LongTermMemory:

    # ===== EVENT METHODS =====

    def store_event(
        self,
        problem: str,
        solution: str,
        lesson_tags: List[str],
        context: Optional[Dict[str, Any]] = None,
        outcome: str = "success",
        iteration: Optional[int] = None
    ) -> str:
        """
        Store an event (problem + solution).
        NO lesson text - that's extracted during reflection.

        Args:
            problem: What went wrong
            solution: How it was resolved
            lesson_tags: Categories/tags (e.g., ["alloy_syntax", "multiplicity"])
            context: Additional context
            outcome: success/partial/failed
            iteration: Iteration number

        Returns:
            event_id
        """

    def get_events(
        self,
        iteration: Optional[int] = None,
        lesson_tag: Optional[str] = None,
        outcome: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get events filtered by criteria."""

    def retrieve_relevant_events(
        self,
        query: str,
        top_k: int = 5,
        lesson_tag_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Semantic search for relevant events."""

    def update_event_contributing_lessons(
        self,
        event_id: str,
        lesson_ids: List[str]
    ):
        """Update bidirectional link: event → lessons."""

    # ===== LESSON METHODS =====

    def store_lesson(
        self,
        lesson: str,
        category: str,
        supporting_events: List[str],
        created_from: str = "pattern_detection",
        confidence: str = "low",
        iteration: Optional[int] = None
    ) -> str:
        """
        Store a lesson (abstract principle).

        Args:
            lesson: The lesson text (high-level)
            category: Category (e.g., "alloy_syntax")
            supporting_events: List of event IDs that support this lesson
            created_from: pattern_detection/agent_insight/user_guidance
            confidence: low/medium/high (based on # of supporting_events)
            iteration: When lesson was created

        Returns:
            lesson_id
        """

    def get_lessons_by_category(
        self,
        category: str
    ) -> List[Dict[str, Any]]:
        """Get all lessons in a category."""

    def retrieve_relevant_lessons(
        self,
        query: str,
        top_k: int = 5,
        category_filter: Optional[str] = None,
        min_confidence: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Semantic search for relevant lessons."""

    def refine_lesson(
        self,
        lesson_id: str,
        refined_text: str,
        new_supporting_events: List[str]
    ):
        """
        Refine an existing lesson.

        - Updates lesson text
        - Adds new supporting events
        - Updates confidence based on total event count
        - Tracks previous versions
        """

    def add_supporting_events(
        self,
        lesson_id: str,
        event_ids: List[str]
    ):
        """
        Add supporting events to lesson without changing text.
        Updates confidence if threshold crossed.
        """

    # ===== HYBRID SEARCH =====

    def hybrid_search(
        self,
        query: str,
        top_k_events: int = 3,
        top_k_lessons: int = 3
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Search both events and lessons simultaneously.

        Returns:
            {
                'events': [...],     # Concrete examples
                'lessons': [...]     # Abstract guidance
            }
        """
```

---

## Example: Complete Workflow

### Iteration 2: Agent Encounters Syntax Errors

```python
# Agent working on model
model = self.create_alloy_model(requirements)

# Try to run analyzer - gets syntax errors
result = self.alloy_executor.execute(model)

# Error 1: Multiplicity issue
self.record_event(
    problem="Syntax error line 45: 'sig Room { occupant: Person }' - undefined multiplicity",
    solution="Added 'one' multiplicity: 'sig Room { occupant: one Person }'",
    lesson_tags=["alloy_syntax", "multiplicity"],
    context={"file": "AlloyModel__2.als", "line": 45},
    outcome="success"
)

# Error 2: Quantifier issue
self.record_event(
    problem="Syntax error line 62: unbound variable 'p' in predicate",
    solution="Added quantification: 'all p: Person | ...'",
    lesson_tags=["alloy_syntax", "quantification"],
    context={"file": "AlloyModel__2.als", "line": 62},
    outcome="success"
)

# End of iteration 2
self.end_iteration()
```

### Reflection Phase (End of Iteration 2)

```python
# Agent reflects on 2 events
events = [
    {event_id: "event_2_001", lesson_tags: ["alloy_syntax", "multiplicity"], ...},
    {event_id: "event_2_002", lesson_tags: ["alloy_syntax", "quantification"], ...}
]

# Group by tags
# "alloy_syntax": [event_2_001, event_2_002]
# "multiplicity": [event_2_001]
# "quantification": [event_2_002]

# For "alloy_syntax" - 2 events
# No existing lesson → Create new
store_lesson(
    lesson="Check Alloy syntax carefully: specify multiplicities and quantify variables",
    category="alloy_syntax",
    supporting_events=["event_2_001", "event_2_002"],
    confidence="low"  # Only 2 events
)

# For "multiplicity" - 1 event
# No existing lesson → Create new
store_lesson(
    lesson="Always specify multiplicity (one/lone/some/set) in Alloy relations",
    category="multiplicity",
    supporting_events=["event_2_001"],
    confidence="low"  # Only 1 event
)

# Update bidirectional links
update_event_contributing_lessons(
    "event_2_001",
    ["lesson_alloy_syntax_1", "lesson_multiplicity_1"]
)
```

### Iteration 4: More Syntax Errors

```python
# Another multiplicity error
self.record_event(
    problem="Syntax error line 72: 'sig Building { rooms: Room }' - missing multiplicity",
    solution="Added 'set' multiplicity: 'sig Building { rooms: set Room }'",
    lesson_tags=["alloy_syntax", "multiplicity"],
    context={"file": "AlloyModel__4.als", "line": 72},
    outcome="success"
)

# End of iteration 4
self.end_iteration()
```

### Reflection Phase (End of Iteration 4)

```python
# Events with "multiplicity" tag
new_events = [{event_id: "event_4_001", ...}]

# Existing lesson in "multiplicity"
existing_lesson = {
    lesson_id: "lesson_multiplicity_1",
    lesson: "Always specify multiplicity (one/lone/some/set) in Alloy relations",
    supporting_events: ["event_2_001"],
    confidence: "low"
}

# Should refine?
# LLM: "NO - new event confirms existing lesson, no refinement needed"

# Just add supporting event
add_supporting_events(
    "lesson_multiplicity_1",
    ["event_4_001"]
)

# Update confidence: 2 events → still "low"
```

### Iteration 7: Yet Another Multiplicity Error

```python
self.record_event(
    problem="Syntax error: missing multiplicity in Person.friends relation",
    solution="Added 'set' multiplicity for many-to-many relationship",
    lesson_tags=["alloy_syntax", "multiplicity"],
    ...
)

# After reflection:
# Now 3 supporting events → confidence becomes "medium"
```

---

## Benefits Summary

✅ **No Duplication**
- Events store problem+solution
- Lessons store abstract principle
- No overlap in content

✅ **Rich Context**
- Events: Detailed, specific
- Lessons: Abstract, reusable
- Bidirectional linking preserves both

✅ **Natural Evolution**
- Lessons refined based on new evidence
- Confidence grows with more events
- Previous versions tracked

✅ **Effective Learning**
- Pattern detection through tags
- Deliberate reflection phase
- Evidence-based lesson creation

✅ **Practical Retrieval**
- Hybrid search for both concrete & abstract
- Confidence filtering
- Category-based organization

✅ **Clear Agent Behavior**
- During task: Record events
- End of iteration: Reflect and extract
- Next iteration: Use both events and lessons

---

## Implementation Checklist

- [ ] Update `LongTermMemory.store_event()` - remove lesson text, add lesson_tags
- [ ] Remove auto-lesson creation from `store_event()`
- [ ] Add `LongTermMemory.refine_lesson()` method
- [ ] Add `LongTermMemory.add_supporting_events()` method
- [ ] Add `LongTermMemory.hybrid_search()` method
- [ ] Update `AutoREBaseAgent.record_event()` to use lesson_tags
- [ ] Add `AutoREBaseAgent.end_iteration()` method
- [ ] Add `AutoREBaseAgent.reflect_and_extract_lessons()` method
- [ ] Add helper methods: `_group_events_by_tags()`, `_should_refine_lesson()`, etc.
- [ ] Update `AutoREWorkflow` to call `agent.end_iteration()` at end of each iteration
- [ ] Update confidence calculation based on event count
- [ ] Add bidirectional linking in both store and update methods
- [ ] Test complete workflow with example scenario
- [ ] Update documentation and examples

---

**Version**: 2.0
**Status**: Design Complete - Ready for Implementation
**Date**: 2026-04-22
