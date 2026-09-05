# Snapshots Output/ into ONE dated archive folder, archivedOutput/<SESSION>/:
#
#   archivedOutput/0720/AlloyModels/      <- everything in Output/AlloyModels/
#   archivedOutput/0720/AnalyzerOutput/   <- everything in Output/AnalyzerOutput/
#   archivedOutput/0720/Feedback/         <- everything in Output/Feedback/
#   archivedOutput/0720/ReqsDoc/          <- everything in Output/ReqsDoc/
#   archivedOutput/0720/Logs/             <- every file in Output/outputlog/
#                                            AND Output/RegressionLog/,
#                                            except the always-empty metagpt.log
#
# The session folder is named by the caller, not derived per file. (The previous
# version parsed a date out of each filename and scattered one run across a
# folder per calendar day; it also only walked date-named SUBDIRECTORIES, which
# the current flat layout no longer has, so it archived nothing but logs.)
#
# Copies by default, so Output/ stays intact and a --resume run can continue
# from it. MODE=move empties the source instead.
#
# Usage: SESSION=0720 python3 scripts/reorganize_output.py              # preview
#        SESSION=0720 DRY_RUN=0 python3 scripts/reorganize_output.py    # execute
#        SESSION=0720 DRY_RUN=0 MODE=move ...      # relocate instead of copy
#        SESSION=0720 FORCE=1 ...                  # overwrite what is already archived
#        SESSION=0720 VERBOSE=1 ...                # list every entry, not just counts
import os
import shutil
import sys

ROOT = "/home/nati/autoRE/Output"
ARCHIVE = "/home/nati/autoRE/archivedOutput"

SESSION = os.environ.get("SESSION") or (sys.argv[1] if len(sys.argv) > 1 else "")
DRY_RUN = os.environ.get("DRY_RUN", "1") == "1"
MODE = os.environ.get("MODE", "copy").lower()
FORCE = os.environ.get("FORCE", "0") == "1"
VERBOSE = os.environ.get("VERBOSE", "0") == "1"

# Whole-folder categories: contents land under archivedOutput/<SESSION>/<name>/.
CATEGORIES = ["AlloyModels", "AnalyzerOutput", "Feedback", "ReqsDoc"]
# Both log folders merge into a single Logs/ folder.
LOG_SOURCES = ["outputlog", "RegressionLog"]
# metagpt.log is written empty on every run and carries nothing worth keeping.
SKIP_LOGS = {"metagpt.log"}

if not SESSION:
    sys.exit("SESSION is required, e.g. SESSION=0720 python3 scripts/reorganize_output.py")
if MODE not in ("copy", "move"):
    sys.exit(f"MODE must be 'copy' or 'move', got {MODE!r}")

DEST = os.path.join(ARCHIVE, SESSION)


def entry_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n/1:.1f}{unit}"
        n /= 1024
    return f"{n}B"


actions = []   # (src, dst, bucket)
warnings = []
claimed = {}   # dst -> src, to catch two sources wanting the same archive path


def plan(src, dst, bucket):
    """Queue one entry, unless something already occupies the destination."""
    if dst in claimed:
        warnings.append(
            f"NAME COLLISION, skipped: {os.path.relpath(src, ROOT)} would overwrite "
            f"{os.path.relpath(claimed[dst], ROOT)} at {os.path.relpath(dst, ARCHIVE)}"
        )
        return
    if os.path.exists(dst) and not FORCE:
        warnings.append(
            f"ALREADY ARCHIVED, skipped: {os.path.relpath(dst, ARCHIVE)} "
            f"(set FORCE=1 to overwrite)"
        )
        return
    claimed[dst] = src
    actions.append((src, dst, bucket))


for cat in CATEGORIES:
    srcdir = os.path.join(ROOT, cat)
    if not os.path.isdir(srcdir):
        warnings.append(f"MISSING source folder, skipped: {cat}")
        continue
    for name in sorted(os.listdir(srcdir)):
        plan(os.path.join(srcdir, name), os.path.join(DEST, cat, name), cat)

for src_name in LOG_SOURCES:
    srcdir = os.path.join(ROOT, src_name)
    if not os.path.isdir(srcdir):
        warnings.append(f"MISSING source folder, skipped: {src_name}")
        continue
    for name in sorted(os.listdir(srcdir)):
        if name in SKIP_LOGS:
            continue
        full = os.path.join(srcdir, name)
        if not os.path.isfile(full):
            # A nested folder inside a log directory keeps its own name under
            # Logs/ rather than being flattened, so nothing is silently merged.
            warnings.append(
                f"NESTED FOLDER kept as Logs/{name}: {os.path.relpath(full, ROOT)}"
            )
        plan(full, os.path.join(DEST, "Logs", name), "Logs")


# ---- Report ----
verb = "MOVE" if MODE == "move" else "COPY"
print(f"{'DRY RUN' if DRY_RUN else 'EXECUTING'} — {verb} {len(actions)} entries "
      f"into {os.path.relpath(DEST, os.path.dirname(ARCHIVE))}, "
      f"{len(warnings)} warnings\n")

by_bucket = {}
for src, dst, bucket in actions:
    by_bucket.setdefault(bucket, []).append((src, dst))

grand_total = 0
for bucket in list(CATEGORIES) + ["Logs"]:
    items = by_bucket.get(bucket, [])
    size = sum(entry_size(src) for src, _ in items)
    grand_total += size
    print(f"  {bucket:<16} {len(items):>4} entries  {human(size):>9}")
    if VERBOSE:
        for src, dst in items:
            print(f"      {os.path.relpath(src, ROOT)}  ->  {os.path.relpath(dst, ARCHIVE)}")
print(f"  {'TOTAL':<16} {len(actions):>4} entries  {human(grand_total):>9}")

if warnings:
    print("\n-- WARNINGS --")
    for w in warnings:
        print(" ", w)

if DRY_RUN:
    print("\nPreview only. Re-run with DRY_RUN=0 to execute.")
    sys.exit(0)

for src, dst, _ in actions:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):          # only reachable under FORCE
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        else:
            os.remove(dst)
    if MODE == "move":
        shutil.move(src, dst)
    elif os.path.isdir(src):
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)

print(f"\nDone. {len(actions)} entries {'moved' if MODE == 'move' else 'copied'} "
      f"to {DEST}")
