import json
import os
import sys
from collections import Counter

# USAGE: python scripts/analyze_convention_shadow.py [shadow.jsonl] [drop] [merge]
#   Analyzes the convention dedup shadow log written in observe mode
#   (Output/ConventionDedup/shadow.jsonl) so drop/merge thresholds can be tuned
#   before enabling convention_mode="active".
#
#   Prints: a similarity histogram, and every pair that WOULD be dropped or
#   merged at the given candidate thresholds so you can eyeball whether the two
#   conventions are truly the same binding rule (safe to merge) or distinct
#   (must stay separate). Set `drop` just above the highest sim of any pair you
#   judge distinct; set `merge` where pairs are reliably same-intent.

DEFAULT_LOG = os.path.join("Output", "ConventionDedup", "shadow.jsonl")


def _bucket(sim: float) -> str:
    lo = int(sim * 10) / 10.0
    return f"{lo:.1f}-{lo + 0.1:.1f}"


def main():
    log_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG
    drop = float(sys.argv[2]) if len(sys.argv) > 2 else 0.93
    merge = float(sys.argv[3]) if len(sys.argv) > 3 else 0.7

    if not os.path.exists(log_path):
        print(f"No shadow log at {log_path} (run in observe mode first).")
        return

    records = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    # Only records written on the STORE path are threshold evidence. The same
    # log also carries the retraction matcher's lookups ("retract-pending",
    # "retract-miss"), which are a different question at a different threshold -
    # counting them as store decisions once put three punctuation-only lookups
    # in the WOULD DROP column and made the drop band look exercised when no
    # stored convention had ever come close to it.
    store_kinds = {"new", "drop", "merge"}
    store = [r for r in records if r.get("would") in store_kinds]
    retract = [r for r in records if r.get("would") not in store_kinds]

    with_match = [r for r in store if r.get("top_sim") is not None]
    print(f"Records: {len(records)} total - {len(store)} store decisions, "
          f"{len(retract)} retraction lookups (excluded)")
    print(f"          {len(with_match)} store decisions had a prior match")
    print(f"Candidate thresholds: drop>={drop}  merge>=[{merge},{drop})\n")

    # Histogram of top similarities
    hist = Counter(_bucket(r["top_sim"]) for r in with_match)
    print("Top-similarity histogram:")
    for band in sorted(hist):
        print(f"  {band}: {'#' * hist[band]} ({hist[band]})")
    print()

    would_drop = sorted((r for r in with_match if r["top_sim"] >= drop),
                        key=lambda r: -r["top_sim"])
    would_merge = sorted((r for r in with_match if merge <= r["top_sim"] < drop),
                         key=lambda r: -r["top_sim"])
    below = sorted((r for r in with_match if r["top_sim"] < merge),
                   key=lambda r: -r["top_sim"])

    def _dump(title, rows):
        print(f"{title}: {len(rows)}")
        for r in rows:
            verdict = r.get("verdict")
            said = f", classifier said {verdict}" if verdict else ""
            print(f"  sim={r['top_sim']}  (iter {r.get('iteration')}, "
                  f"{r.get('action')}{said})")
            print(f"    NEW : {r['new']}")
            print(f"    PRIOR: {r['top_match']}")
        print()

    _dump("WOULD DROP (sim >= drop)", would_drop)
    _dump("WOULD CLASSIFY (merge band)", would_merge)
    # The pairs just under the floor are what a LOWER threshold would pull in,
    # and they are the only way to see what recall the current floor costs.
    _dump("BELOW THE FLOOR (nearest 8 - would a lower floor help?)", below[:8])

    verdicts = Counter(r["verdict"] for r in with_match if r.get("verdict"))
    if verdicts:
        print("Classifier verdicts on pairs it actually saw:")
        for verdict, count in verdicts.most_common():
            print(f"  {verdict}: {count}")
        print()

    print("Tuning: a pair in the classify band that is actually DISTINCT (same "
          "topic, different rule) means the floor is too low - raise it above "
          "that pair's sim. A pair below the floor that is the SAME rule "
          "restated means the floor is too high.")


if __name__ == "__main__":
    main()
