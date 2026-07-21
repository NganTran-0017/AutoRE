# Sorts Output/{AlloyModels,AnalyzerOutput,Feedback,ReqsDoc,outputlog,RegressionLog}
# into archivedOutput/MMDD[_HHAM/PM]/{AlloyModels,AnalyzerOutput,Feedback,ReqsDoc,Logs}.
# Skips AnalyzerOutput/0-9 and /draft (current in-progress session) plus loose
# undated files (metagpt.log, regression_log.json) -- leaves those in place.
# Usage: DRY_RUN=1 python3 scripts/reorganize_output.py   # preview
#        DRY_RUN=0 python3 scripts/reorganize_output.py   # execute
import os
import re
import shutil
from collections import defaultdict

ROOT = "/home/nati/autoRE/Output"
ARCHIVE = "/home/nati/autoRE/archivedOutput"
DRY_RUN = os.environ.get("DRY_RUN", "1") == "1"

CATEGORIES = ["AlloyModels", "AnalyzerOutput", "Feedback", "ReqsDoc"]
SKIP_ANALYZER_DIRS = {"0","1","2","3","4","5","6","7","8","9","draft"}

TIME_RE = re.compile(r'^_?(\d{1,2})(AM|PM|am|pm)$')

def normalize_time(suffix):
    m = TIME_RE.match(suffix)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}"
    return None

def normalize_session_name(name):
    """Return (normalized_name, had_meaningful_suffix)"""
    m6 = re.match(r'^(\d{2})(\d{2})(\d{2})(?:_(.+))?$', name)
    if m6:
        mm, dd, yy, suffix = m6.groups()
        base = mm + dd
        if suffix:
            t = normalize_time("_" + suffix)
            if t:
                return f"{base}_{t}"
        return base
    m4 = re.match(r'^(\d{4})(?:_(.+))?$', name)
    if m4:
        base, suffix = m4.groups()
        if suffix:
            t = normalize_time("_" + suffix)
            if t:
                return f"{base}_{t}"
            # non-time suffix (e.g. repeatedErrors) -> merge into base date
            return base
        return base
    return None  # doesn't match a date pattern at all

actions = []  # (src, dst, kind)
warnings = []

# ---- Step 1: session folders across the 4 categories ----
session_map = {}  # original (cat, name) -> normalized
for cat in CATEGORIES:
    catdir = os.path.join(ROOT, cat)
    for name in sorted(os.listdir(catdir)):
        full = os.path.join(catdir, name)
        if not os.path.isdir(full):
            continue
        if cat == "AnalyzerOutput" and name in SKIP_ANALYZER_DIRS:
            continue
        norm = normalize_session_name(name)
        if norm is None:
            warnings.append(f"UNRECOGNIZED folder pattern, left in place: {cat}/{name}")
            continue
        dst = os.path.join(ARCHIVE, norm, cat)
        actions.append((full, dst, "session_dir"))
        session_map[(cat, name)] = norm

normalized_session_set = sorted(set(v for v in session_map.values()))

# ---- Step 2: logs ----
LOG_SOURCES = []
for f in sorted(os.listdir(os.path.join(ROOT, "outputlog"))):
    full = os.path.join(ROOT, "outputlog", f)
    if os.path.isfile(full):
        LOG_SOURCES.append(full)
for sub in ["archive", "archiveMay"]:
    subdir = os.path.join(ROOT, "outputlog", sub)
    if os.path.isdir(subdir):
        for f in sorted(os.listdir(subdir)):
            full = os.path.join(subdir, f)
            if os.path.isfile(full):
                LOG_SOURCES.append(full)
for f in sorted(os.listdir(os.path.join(ROOT, "RegressionLog"))):
    full = os.path.join(ROOT, "RegressionLog", f)
    if os.path.isfile(full) and (f.startswith("regression") and f.endswith(".log") or f.startswith("SimilarIssues_")):
        LOG_SOURCES.append(full)

LOG_DATE_RE = re.compile(r'^(?:regression)?(\d{2})(\d{2})(\d{2})?(?:[-_](.+?))?(?:\.log|\.json)?$')
SIMILAR_RE = re.compile(r'^SimilarIssues_(\d{4})\.json$')

def parse_log(fname):
    """Return (mmdd, time_suffix_or_None) or None if undatable."""
    base = fname
    m = SIMILAR_RE.match(base)
    if m:
        return m.group(1), None
    stem = re.sub(r'\.(log|json)$', '', base)
    stem = re.sub(r'^regression', '', stem)
    # 6-digit date at start = MMDDYY, 4-digit = MMDD
    m6 = re.match(r'^(\d{2})(\d{2})(\d{2})(?:[-_](.+))?$', stem)
    if m6:
        mm, dd, yy, suffix = m6.groups()
        mmdd = mm + dd
        t = normalize_time("_" + suffix) if suffix else None
        return mmdd, t
    m4 = re.match(r'^(\d{4})(?:[-_](.+))?$', stem)
    if m4:
        mmdd, suffix = m4.groups()
        t = normalize_time("_" + suffix) if suffix else None
        return mmdd, t
    return None

for full in LOG_SOURCES:
    fname = os.path.basename(full)
    if fname == "metagpt.log" or fname == "regression_log.json":
        warnings.append(f"UNDATABLE, left in place: {os.path.relpath(full, ROOT)}")
        continue
    parsed = parse_log(fname)
    if parsed is None:
        warnings.append(f"UNPARSEABLE date, left in place: {os.path.relpath(full, ROOT)}")
        continue
    mmdd, tsuffix = parsed
    candidates = [s for s in normalized_session_set if s == mmdd or s.startswith(mmdd + "_")]
    if tsuffix and f"{mmdd}_{tsuffix}" in candidates:
        targets = [f"{mmdd}_{tsuffix}"]
    elif len(candidates) >= 1:
        targets = candidates
    else:
        targets = [mmdd]
    for t in targets:
        dst = os.path.join(ARCHIVE, t, "Logs", fname)
        kind = "log_move" if len(targets) == 1 else "log_copy"
        actions.append((full, dst, kind))
    if len(targets) > 1:
        warnings.append(f"AMBIGUOUS date, duplicated into {targets}: {os.path.relpath(full, ROOT)}")

# ---- Execute / print plan ----
print(f"{'DRY RUN' if DRY_RUN else 'EXECUTING'} — {len(actions)} actions, {len(warnings)} warnings\n")

by_target_date = defaultdict(list)
for src, dst, kind in actions:
    date_folder = os.path.relpath(dst, ARCHIVE).split(os.sep)[0]
    by_target_date[date_folder].append((src, dst, kind))

for date_folder in sorted(by_target_date):
    print(f"== {date_folder} ==")
    for src, dst, kind in by_target_date[date_folder]:
        print(f"  [{kind}] {os.path.relpath(src, ROOT)}  ->  {os.path.relpath(dst, ARCHIVE)}")

print("\n-- WARNINGS --")
for w in warnings:
    print(" ", w)

if not DRY_RUN:
    moved_sources = []
    for src, dst, kind in actions:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if kind == "session_dir":
            shutil.move(src, dst)
        elif kind == "log_move":
            shutil.move(src, dst)
        elif kind == "log_copy":
            shutil.copy2(src, dst)
            moved_sources.append(src)
    # remove originals that were copied (not moved) to multiple targets, once all copies exist
    for src, dst, kind in actions:
        if kind == "log_copy" and os.path.exists(src):
            os.remove(src)
    print("\nDone.")
