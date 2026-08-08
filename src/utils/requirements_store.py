"""
Patch-based requirements document store - the anti-drift layer for
UpdateRequirements.

Previously UpdateRequirements asked the LLM to regenerate the ENTIRE
requirements document each iteration. Over many iterations that compounds
paraphrase drift: original requirements mutate, existing-system statements
silently vanish, and verification scaffolding inflates into pseudo-
requirements (observed: Reqs_0 vs Reqs_68).

This module makes the document a structured, deterministically-rendered
artifact:

  parse_requirements_document()  text -> sections -> addressable items
                                 (R-ids for prospective requirements, E-ids
                                 for existing-system/assumption bullets)
  annotate_for_prompt()          render with [E#] markers so the LLM can
                                 address bullets precisely
  parse_patch()                  parse the LLM's === REQUIREMENT PATCH ===
                                 delta output (MODIFY/ADD/REMOVE/
                                 MODIFY-SECTION/NO-CHANGE)
  apply_patch()                  validate + apply deltas in code; items not
                                 named in the patch are copied byte-for-byte,
                                 so unaffected requirements cannot drift
  parse_original_requirement_ids()  requirement IDs in the immutable source
                                 input; REMOVE of these is blocked (must go
                                 through an explicit user decision instead)

Parse/render is identity-preserving: render(parse(text)) == text.
Deterministic and LLM-free, in the ErrorNormalizer/RepairPlateauDetector
style.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


_R_ID = r"R\d+(?:\.\d+)*"
_R_ITEM_START = re.compile(r"^\s*(" + _R_ID + r")\s*[:.]")
_BULLET_START = re.compile(r"^(\s*)(-\s+|•\s+|\d+\.\s+)")
_SECTION_UNDERLINE = re.compile(r"^={3,}\s*$")
_PATCH_OP = re.compile(
    r"^\s*\[(MODIFY-SECTION|MODIFY|ADD|REMOVE|NO-CHANGE)\]\s*(.*?)\s*$",
    re.IGNORECASE,
)
_PATCH_MARKER = "=== REQUIREMENT PATCH ==="


@dataclass
class DocItem:
    """One addressable chunk. id: 'R3.2' / 'E4' / None (unaddressed preamble)."""
    id: Optional[str]
    raw: str  # exact text, including newlines - concatenation reproduces the doc


@dataclass
class DocSection:
    name: str        # header text as written
    header_raw: str  # header + underline lines, verbatim
    kind: str        # 'prospective' | 'bullets' | 'blob'
    items: List[DocItem] = field(default_factory=list)


@dataclass
class RequirementsDocument:
    preamble: str  # anything before the first section (e.g. a ``` fence)
    sections: List[DocSection]
    suffix: str    # trailing fence / blank lines

    def render(self) -> str:
        parts = [self.preamble]
        for section in self.sections:
            parts.append(section.header_raw)
            parts.extend(item.raw for item in section.items)
        parts.append(self.suffix)
        return "".join(parts)

    def find_item(self, item_id: str) -> Optional[DocItem]:
        for section in self.sections:
            for item in section.items:
                if item.id == item_id:
                    return item
        return None

    def find_section(self, name: str, fuzzy: bool = False) -> Optional[DocSection]:
        """Locate a section by name. Exact (case-insensitive) match first; when
        fuzzy, fall back to a section whose name STARTS WITH the target - so
        'CONSTRAINTS' still resolves to the standalone CONSTRAINTS section and
        never to 'EXISTING-SYSTEM ... AND CONSTRAINTS' (which it is a substring
        of, but not a prefix of)."""
        target = name.strip().upper()
        for section in self.sections:
            if section.name.strip().upper() == target:
                return section
        if fuzzy:
            for section in self.sections:
                if section.name.strip().upper().startswith(target):
                    return section
        return None

    def all_item_ids(self) -> Set[str]:
        return {i.id for s in self.sections for i in s.items if i.id}


def _section_kind(name: str) -> str:
    upper = name.upper()
    if "PROSPECTIVE" in upper and "REQUIREMENT" in upper:
        return "prospective"
    if "EXISTING-SYSTEM" in upper or "ASSUMPTION" in upper or upper.strip() == "CONSTRAINTS":
        return "bullets"
    return "blob"


def parse_requirements_document(text: str) -> RequirementsDocument:
    """Parse a requirements document into addressable items (identity-preserving)."""
    lines = text.splitlines(keepends=True)

    # Peel a trailing code fence (plus surrounding blank lines) into the suffix
    # so it can never be swallowed by an edit to the last item.
    suffix_start = len(lines)
    idx = len(lines) - 1
    while idx >= 0 and lines[idx].strip() == "":
        idx -= 1
    if idx >= 0 and lines[idx].strip().startswith("```"):
        suffix_start = idx
    suffix = "".join(lines[suffix_start:])
    lines = lines[:suffix_start]

    # Locate section headers: a non-empty line followed by an ===== underline.
    header_positions = [
        i for i in range(len(lines) - 1)
        if lines[i].strip() and not lines[i].lstrip().startswith("-")
        and _SECTION_UNDERLINE.match(lines[i + 1])
    ]

    preamble = "".join(lines[:header_positions[0]]) if header_positions else "".join(lines)
    sections: List[DocSection] = []
    e_counter = 0

    for pos_idx, start in enumerate(header_positions):
        body_start = start + 2
        body_end = header_positions[pos_idx + 1] if pos_idx + 1 < len(header_positions) else len(lines)
        name = lines[start].strip()
        kind = _section_kind(name)
        body = lines[body_start:body_end]
        section = DocSection(name=name, header_raw="".join(lines[start:body_start]), kind=kind)

        if kind == "prospective":
            section.items = _split_items(body, _R_ITEM_START, lambda m: m.group(1))
        elif kind == "bullets":
            def next_e_id(_m) -> str:
                nonlocal e_counter
                e_counter += 1
                return f"E{e_counter}"
            section.items = _split_items(body, _BULLET_START, next_e_id)
        else:
            section.items = [DocItem(id=None, raw="".join(body))] if body else []

        sections.append(section)

    return RequirementsDocument(preamble=preamble, sections=sections, suffix=suffix)


def _split_items(body_lines: List[str], start_pattern, id_fn) -> List[DocItem]:
    """Split section body at lines matching start_pattern; leading non-matching
    lines become an unaddressed preamble item. Continuation lines (including
    blank separators) attach to the current item."""
    items: List[DocItem] = []
    current_lines: List[str] = []
    current_id: Optional[str] = None
    started = False

    def flush():
        if current_lines:
            items.append(DocItem(id=current_id, raw="".join(current_lines)))

    for line in body_lines:
        m = start_pattern.match(line)
        if m:
            flush()
            current_lines = [line]
            current_id = id_fn(m)
            started = True
        else:
            if not started and current_id is None and not current_lines:
                current_lines = [line]
            else:
                current_lines.append(line)
    flush()
    return items


def annotate_for_prompt(
    doc: RequirementsDocument,
    statuses: Optional[Any] = None,
) -> str:
    """Render the document with [E#] markers prefixed to bullet items so the
    LLM can address them in patch operations. R items carry their own IDs.
    The markers exist only in the prompt copy, never in the stored document.

    `statuses` is an optional RequirementStatusStore. When given, each item that
    is not yet verified also carries its standing - `[PROVISIONAL since it.23,
    2/3]`, `[PENDING REMOVAL ...]`. Same rule as the [E#] markers and for the
    same reason: `render_document` reproduces `item.raw` byte-for-byte, so a
    status written into the document text would become part of the requirement.
    """
    parts = [doc.preamble]
    for section in doc.sections:
        parts.append(section.header_raw)
        for item in section.items:
            raw = item.raw
            if statuses is not None and item.id:
                raw = _with_status_marker(raw, statuses, item.id)
            if item.id and item.id.startswith("E"):
                parts.append(f"[{item.id}] {raw}")
            else:
                parts.append(raw)
    parts.append(doc.suffix)
    return "".join(parts)


def _with_status_marker(raw: str, statuses: Any, item_id: str) -> str:
    """Append the standing marker to an item's FIRST line.

    The first line carries the ID, so that is where a reader looks for the
    item's identity - and appending at the end of a multi-line item would
    detach the marker from what it describes.
    """
    try:
        from .requirement_status_store import format_marker

        marker = format_marker(statuses.get(item_id))
    except Exception:
        return raw
    if not marker:
        return raw
    head, sep, tail = raw.partition("\n")
    return f"{head.rstrip()}  {marker}{sep}{tail}"


def parse_original_requirement_ids(
    input_text: Optional[str],
    prefixes: Tuple[str, ...] = ("R", "E"),
) -> Set[str]:
    """Requirement IDs declared in the original source input (R1, E4.2, ...).
    These are the protected set: REMOVE operations on them are blocked.

    Both families are protected. An E-item states something that is true of the
    system as it already exists - the run cannot make it false by deleting the
    sentence, so a REMOVE of one is always a modelling convenience rather than a
    requirements decision. The default was R-only, which left every original
    existing-system constraint deletable by an agent.

    prefixes: which ID prefixes to recognize, for callers that genuinely want
    one family (the ownership audit passes its own).
    """
    if not input_text:
        return set()
    id_pattern = "(?:" + "|".join(re.escape(p) for p in prefixes) + r")\d+(?:\.\d+)*"
    ids = set()
    for line in input_text.splitlines():
        m = re.match(r"^\s*(" + id_pattern + r")\s*[:.)]", line)
        if m:
            ids.add(m.group(1))
    return ids


# --------------------------------------------------------------------------- #
# Patch parsing and application
# --------------------------------------------------------------------------- #

_BODY_LABEL = re.compile(r"^\s*(New text|Text|Justification|Reason|Provenance)\s*:\s*", re.IGNORECASE)


def parse_patch(response: str) -> Dict[str, Any]:
    """
    Parse the LLM's patch response.

    Returns:
        {
          "ops": [{"op": "MODIFY"|"ADD"|"REMOVE"|"MODIFY-SECTION",
                   "target": str, "body": str, "meta": str}],
          "no_change": bool,
          "errors": [str],
        }
    """
    result: Dict[str, Any] = {"ops": [], "no_change": False, "errors": []}
    if not response or not response.strip():
        result["errors"].append("empty response")
        return result

    text = response
    if _PATCH_MARKER in text:
        text = text.split(_PATCH_MARKER, 1)[1]

    lines = [l for l in text.splitlines() if not l.strip().startswith("```")]

    ops: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in lines:
        m = _PATCH_OP.match(line)
        if m:
            if current is not None:
                ops.append(current)
            op_name = m.group(1).upper()
            if op_name == "NO-CHANGE":
                result["no_change"] = True
                current = None
                continue
            current = {"op": op_name, "arg": m.group(2).strip(), "body_lines": []}
        elif current is not None:
            current["body_lines"].append(line)
    if current is not None:
        ops.append(current)

    for op in ops:
        body_lines = op.pop("body_lines")
        # Drop a leading "New text:"/"Text:" label; keep same-line content.
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        if body_lines:
            label = _BODY_LABEL.match(body_lines[0])
            if label:
                remainder = body_lines[0][label.end():]
                body_lines[0] = remainder
                if not remainder.strip():
                    body_lines.pop(0)
        body = "\n".join(body_lines).strip("\n")

        arg = op.pop("arg")
        # Target = leading R-id / E-id / section keyword; rest is metadata
        # (e.g. "R9 (provenance: Q-17)").
        target_match = re.match(r"^(" + _R_ID + r"|E\d+|[A-Za-z][A-Za-z0-9 &/-]*)", arg)
        target = target_match.group(1).strip() if target_match else arg
        op["target"] = target
        op["meta"] = arg[len(target):].strip() if target_match else ""
        op["body"] = body
        result["ops"].append(op)

    if not result["ops"] and not result["no_change"]:
        result["errors"].append(
            "no patch operations found - expected [MODIFY]/[ADD]/[REMOVE]/"
            "[MODIFY-SECTION] entries or [NO-CHANGE]"
        )
    return result


def _parent_id(item_id: str) -> Optional[str]:
    """'R4.4' -> 'R4', 'R4.4.1' -> 'R4.4', 'R4' -> None."""
    return item_id.rsplit(".", 1)[0] if "." in item_id else None


def _ensure_r_id_prefix(new_text: str, target: str, old_raw: str) -> str:
    """
    Keep a MODIFY'd requirement addressable by re-attaching its ID.

    An R item is only recognised on the next parse when its first line starts
    with `R#:` or `R#.` (_R_ITEM_START). A replacement body that omits the
    prefix - the response format shows it, but nothing enforced it - silently
    dissolves the item into the previous one: the ID vanishes from the document
    while the patch log, the traceability map and every construct annotation
    still refer to it. Mirrors the bullet-marker guard used for E items.

    A leading ID that names a DIFFERENT requirement is rewritten to `target`:
    the addressed item is the one being overwritten either way, and leaving the
    other ID in place would duplicate it and lose this one.
    """
    match = _R_ITEM_START.match(new_text)
    if match and match.group(1) == target:
        return new_text
    if match:
        new_text = new_text[match.end():].lstrip()
    # Reuse the item's own prefix so indentation and the ":"/"." separator
    # match the surrounding document.
    old_match = _R_ITEM_START.match(old_raw)
    prefix = old_raw[: old_match.end()] if old_match else f"{target}:"
    return f"{prefix} {new_text.lstrip()}"


def _graft_tail(new_text: str, old_raw: str) -> str:
    """Give replacement text the same trailing-newline pattern as the chunk it
    replaces, so inter-item spacing is preserved."""
    tail = old_raw[len(old_raw.rstrip("\n")):] or "\n"
    return new_text.rstrip("\n") + tail


def existing_system_texts(doc_text: Optional[str]) -> Set[str]:
    """The existing-system bullets of a document, keyed by their TEXT.

    Deliberately not by ID. `E1`, `E2`, ... are assigned by position at parse
    time (`next_e_id`), so they are addressing markers, not identities: insert
    one bullet at the top and every E-number below it now denotes a different
    sentence. A protected set captured as IDs would silently start protecting
    the wrong bullets, which is worse than protecting none.

    Used with the ORIGINAL (iteration-0) document to protect the existing-system
    constraints derived from the user's system description. An E-item states
    something already true of the system; deleting the sentence does not make it
    false, so removing one is a modelling convenience, never a requirements
    decision.
    """
    if not doc_text:
        return set()
    try:
        doc = parse_requirements_document(doc_text)
    except Exception:
        return set()
    return {
        _normalize_bullet(item.raw)
        for section in doc.sections if section.kind == "bullets"
        for item in section.items if item.id
    }


def _normalize_bullet(raw: str) -> str:
    """Bullet text with the marker and whitespace differences removed."""
    return " ".join(raw.split()).lstrip("-•").strip()


def apply_patch(
    doc_text: str,
    response: str,
    protected_ids: Optional[Set[str]] = None,
    defer_removals: bool = False,
    protected_texts: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Apply an LLM patch response to a requirements document.

    Items not named in the patch are copied byte-for-byte. REMOVE of a
    protected (original-source) requirement is blocked and reported, never
    applied - deleting an original requirement requires an explicit user
    decision outside this mechanism.

    `defer_removals=True` puts a REMOVE on probation instead of performing it:
    the item STAYS in the document and is reported under "deferred". Its Alloy
    encoding is still deleted (the op is reported in `applied`, which is what
    stages REMOVE_STALE_CONSTRUCTS), so the removal can be verified against a
    model that no longer contains it while the text remains available to review
    and to revert. The deletion itself happens once probation completes.

    Returns:
        {
          "text": str,        # updated document (== doc_text when nothing applied)
          "changed": bool,
          "applied": [str],   # human-readable descriptions
          "changes": [dict],  # {op, target, before, after} - the text itself
          "deferred": [str],  # REMOVEs recorded but not performed
          "blocked": [str],
          "errors": [str],
          "no_change": bool,
        }

    `applied` records THAT an item changed; `changes` records WHAT it said
    before and after. Only the latter answers "which constructs does this
    change invalidate" - "MODIFY R6" alone cannot tell a wording clarification
    from a reversal of meaning.
    """
    protected_ids = protected_ids or set()
    report: Dict[str, Any] = {
        "text": doc_text, "changed": False,
        "applied": [], "changes": [], "deferred": [], "blocked": [], "errors": [],
        "no_change": False,
    }

    def _record(kind: str, target: str, before: str, after: str) -> None:
        report["changes"].append({
            "op": kind,
            "target": target,
            "before": (before or "").strip(),
            "after": (after or "").strip(),
        })

    parsed = parse_patch(response)
    report["errors"].extend(parsed["errors"])
    report["no_change"] = parsed["no_change"]
    if not parsed["ops"]:
        return report

    doc = parse_requirements_document(doc_text)

    for op in parsed["ops"]:
        kind, target, body = op["op"], op["target"], op["body"]

        if kind == "MODIFY":
            item = doc.find_item(target)
            if item is None:
                report["errors"].append(f"MODIFY {target}: no such item")
                continue
            if not body:
                report["errors"].append(f"MODIFY {target}: empty replacement text")
                continue
            new_text = body
            if target.startswith("E") and item.raw.lstrip().startswith("-") \
                    and not new_text.lstrip().startswith(("-", "•")):
                new_text = "- " + new_text.lstrip()
            elif re.fullmatch(_R_ID, target):
                new_text = _ensure_r_id_prefix(new_text, target, item.raw)
            before = item.raw
            item.raw = _graft_tail(new_text, item.raw)
            report["applied"].append(f"MODIFY {target}")
            _record(kind, target, before, item.raw)

        elif kind == "REMOVE":
            # Two protections, because the two families are identified
            # differently: an R-item carries its ID in the source, an E-item's
            # ID is positional and only its text is stable.
            target_item = doc.find_item(target)
            protected_text = bool(
                protected_texts and target_item is not None
                and _normalize_bullet(target_item.raw) in protected_texts
            )
            if target in protected_ids or protected_text:
                report["blocked"].append(
                    f"REMOVE {target}: blocked - original source requirement; "
                    f"removal requires an explicit user decision"
                )
                continue
            if defer_removals:
                item = doc.find_item(target)
                if item is None:
                    report["errors"].append(f"REMOVE {target}: no such item")
                    continue
                # Recorded and encoded-against, but not performed: the text
                # stays so the removal can be reviewed and reverted.
                report["applied"].append(f"REMOVE {target}")
                report["deferred"].append(f"REMOVE {target}")
                _record(kind, target, item.raw, "")
                continue
            removed = False
            removed_text = ""
            for section in doc.sections:
                for item in list(section.items):
                    if item.id == target:
                        removed_text = removed_text or item.raw
                        section.items.remove(item)
                        removed = True
            if removed:
                report["applied"].append(f"REMOVE {target}")
                _record(kind, target, removed_text, "")
            else:
                report["errors"].append(f"REMOVE {target}: no such item")

        elif kind == "ADD":
            if not body:
                report["errors"].append(f"ADD {target}: empty text")
                continue
            if re.fullmatch(_R_ID, target):
                if target in doc.all_item_ids():
                    report["errors"].append(f"ADD {target}: id already exists")
                    continue
                section = next((s for s in doc.sections if s.kind == "prospective"), None)
                if section is None:
                    report["errors"].append(f"ADD {target}: no prospective requirements section")
                    continue
                # Place a sub-requirement (R_n.k) directly after its parent's
                # last existing sub-item, so it nests under R_n instead of
                # landing at the bottom of the section. Top-level R# still
                # appends at the end.
                parent = _parent_id(target)
                insert_idx = None
                if parent:
                    for i, it in enumerate(section.items):
                        if it.id == parent or (it.id and it.id.startswith(parent + ".")):
                            insert_idx = i + 1
                if insert_idx is not None:
                    prev_raw = section.items[insert_idx - 1].raw
                    added = DocItem(id=target, raw=_graft_tail(body, prev_raw))
                    section.items.insert(insert_idx, added)
                else:
                    added = DocItem(id=target, raw="\n" + body.rstrip("\n") + "\n")
                    section.items.append(added)
                report["applied"].append(f"ADD {target}")
                _record(kind, target, "", added.raw)
            else:
                # Bullet addition. Route by the target keyword so a constraint
                # lands in CONSTRAINTS rather than the first bullets section
                # (which is EXISTING-SYSTEM). Default to CONSTRAINTS when the
                # target names no existing section.
                section = doc.find_section(target, fuzzy=True) if target else None
                if section is None or section.kind != "bullets":
                    section = doc.find_section("CONSTRAINTS") \
                        or next((s for s in doc.sections if s.kind == "bullets"), None)
                if section is None:
                    report["errors"].append(f"ADD {target}: no assumptions/constraints section")
                    continue
                text_body = body if body.lstrip().startswith(("-", "•")) else "- " + body.lstrip()
                new_id = f"E{sum(1 for s in doc.sections for i in s.items if i.id and i.id.startswith('E')) + 1}"
                section.items.append(DocItem(id=new_id, raw=text_body.rstrip("\n") + "\n"))
                report["applied"].append(f"ADD {new_id} ({section.name.strip()})")
                _record(kind, new_id, "", text_body)

        elif kind == "MODIFY-SECTION":
            section = next(
                (s for s in doc.sections if s.name.strip().upper() == target.strip().upper()),
                None,
            )
            if section is None:
                report["errors"].append(f"MODIFY-SECTION {target}: no such section")
                continue
            if not body:
                report["errors"].append(f"MODIFY-SECTION {target}: empty replacement text")
                continue
            old_raw = "".join(i.raw for i in section.items)
            # Stored as one blob here; the next iteration's parse re-splits it
            # into addressable items from the rendered text.
            section.items = [DocItem(id=None, raw=_graft_tail(body, old_raw))]
            report["applied"].append(f"MODIFY-SECTION {section.name}")
            _record(kind, section.name.strip(), old_raw, section.items[0].raw)

    if report["applied"]:
        report["text"] = doc.render()
        # A deferred removal is recorded, not performed, so it alone leaves the
        # document byte-identical. Reporting `changed` for it would tell the
        # caller to store a "new" document that is the old one.
        report["changed"] = len(report["applied"]) > len(report["deferred"])
    return report


def remove_item(doc_text: str, req_id: str) -> Dict[str, Any]:
    """
    Delete one item outright - the deferred half of a probationary REMOVE.

    Called when a `pending_removal` completes probation, i.e. the model has been
    verified without the requirement's encoding for the full window. Returns
    {"text", "removed", "before"} with the ORIGINAL text when the id is absent,
    so a caller that lost track of an id cannot corrupt the document.
    """
    doc = parse_requirements_document(doc_text)
    before = ""
    removed = False
    for section in doc.sections:
        for item in list(section.items):
            if item.id == req_id:
                before = before or item.raw
                section.items.remove(item)
                removed = True
    if not removed:
        return {"text": doc_text, "removed": False, "before": ""}
    return {"text": doc.render(), "removed": True, "before": before}


def replace_item(doc_text: str, req_id: str, new_raw: str) -> Dict[str, Any]:
    """
    Overwrite one item's text - the revert half of a probationary MODIFY.

    Called when a contested MODIFY is rolled back to the wording the status
    store kept as `prior_text`. Returns {"text", "replaced", "before"} with the
    ORIGINAL document when the id is absent or the replacement is blank, so a
    caller working from a stale record cannot empty an item.
    """
    if not (new_raw or "").strip():
        return {"text": doc_text, "replaced": False, "before": ""}
    doc = parse_requirements_document(doc_text)
    before = ""
    replaced = False
    for section in doc.sections:
        for item in section.items:
            if item.id != req_id:
                continue
            before = before or item.raw
            # render() concatenates raw blocks with no separator, so the
            # trailing newline is structural, not cosmetic.
            text = new_raw
            if item.raw.endswith("\n") and not text.endswith("\n"):
                text += "\n"
            item.raw = text
            replaced = True
    if not replaced:
        return {"text": doc_text, "replaced": False, "before": ""}
    return {"text": doc.render(), "replaced": True, "before": before}
