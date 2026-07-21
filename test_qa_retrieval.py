#!/usr/bin/env python3
"""
Debug script to test Q&A retrieval with the fixed parser
"""
from pathlib import Path
from src.utils.qa_database import QADatabase

# Initialize database
db_path = Path("memory/default/qa_database.json")
qa_db = QADatabase(storage_path=db_path)

# Question from iteration 63 (parsed from BLOCKING QUESTIONS)
iteration_63_question = """Is it a requirement that in every possible system instance (regardless of the number or distribution of requests and classifications), the Emergency group-processing scenario (i.e., with at least one pending request at each of High, Medium, and Low classifications and only the High-classification requests being processed in a step) must always be possible and realized, or is this scenario only required to be possible in instances/runs where such a distribution of requests exists?"""

# Test retrieval
print("Testing Q&A retrieval with parsed question from iteration 63...")
print("=" * 60)
print(f"Question: {iteration_63_question[:150]}...")
print()

# Retrieve with different thresholds
for threshold in [0.7, 0.5, 0.3, 0.2, 0.1]:
    relevant_records = qa_db.retrieve_relevant(
        questions=[iteration_63_question],
        current_iteration=63,
        max_results=3,
        similarity_threshold=threshold
    )

    print(f"Threshold {threshold}: Found {len(relevant_records)} relevant Q&A records")

    if relevant_records:
        for record in relevant_records:
            print(f"  - Q{record.iteration}_{record.id.split('_')[1]}: {record.question[:100]}...")

print("\n" + "=" * 60)

# Check if ChromaDB collection has any data
print(f"Total records in database: {len(qa_db.records)}")
print(f"ChromaDB collection count: {qa_db.collection.count()}")

# Show Q61_1 specifically
q61_1 = qa_db.get_record_by_id("Q61_1")
if q61_1:
    print(f"\nQ61_1 question: {q61_1.question[:150]}...")
    print(f"Q61_1 answer: {q61_1.answer[:150]}...")

# Test direct semantic similarity
print("\n" + "=" * 60)
print("Testing direct ChromaDB query for Q61_1...")

results = qa_db.collection.query(
    query_texts=[iteration_63_question],
    n_results=10
)

if results and results['ids'] and results['ids'][0]:
    print(f"Top 10 ChromaDB results:")
    for i, doc_id in enumerate(results['ids'][0]):
        distance = results['distances'][0][i]
        similarity = 1.0 - distance
        print(f"  {doc_id}: similarity={similarity:.3f}, distance={distance:.3f}")
else:
    print("No results from ChromaDB!")