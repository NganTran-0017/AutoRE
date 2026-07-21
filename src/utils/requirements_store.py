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
from typing import Any, Dict, List, Optional, Set


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


def annotate_for_prompt(doc: RequirementsDocument) -> str:
    """Render the document with [E#] markers prefixed to bullet items so the
    LLM can address them in patch operations. R items carry their own IDs.
    The markers exist only in the prompt copy, never in the stored document."""
    parts = [doc.preamble]
    for section in doc.sections:
        parts.append(section.header_raw)
        for item in section.items:
            if item.id and item.id.startswith("E"):
                parts.append(f"[{item.id}] {item.raw}")
            else:
                parts.append(item.raw)
    parts.append(doc.suffix)
    return "".join(parts)


def parse_original_requirement_ids(input_text: Optional[str]) -> Set[str]:
    """Requirement IDs declared in the original source input (R1, R3.2, ...).
    These are the protected set: REMOVE operations on them are blocked."""
    if not input_text:
        return set()
    ids = set()
    for line in input_text.splitlines():
        m = re.match(r"^\s*(" + _R_ID + r")\s*[:.)]", line)
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


def _graft_tail(new_text: str, old_raw: str) -> str:
    """Give replacement text the same trailing-newline pattern as the chunk it
    replaces, so inter-item spacing is preserved."""
    tail = old_raw[len(old_raw.rstrip("\n")):] or "\n"
    return new_text.rstrip("\n") + tail


def apply_patch(
    doc_text: str,
    response: str,
    protected_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Apply an LLM patch response to a requirements document.

    Items not named in the patch are copied byte-for-byte. REMOVE of a
    protected (original-source) requirement is blocked and reported, never
    applied - deleting an original requirement requires an explicit user
    decision outside this mechanism.

    Returns:
        {
          "text": str,        # updated document (== doc_text when nothing applied)
          "changed": bool,
          "applied": [str],   # human-readable descriptions
          "blocked": [str],
          "errors": [str],
          "no_change": bool,
        }
    """
    protected_ids = protected_ids or set()
    report: Dict[str, Any] = {
        "text": doc_text, "changed": False,
        "applied": [], "blocked": [], "errors": [], "no_change": False,
    }

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
            item.raw = _graft_tail(new_text, item.raw)
            report["applied"].append(f"MODIFY {target}")

        elif kind == "REMOVE":
            if target in protected_ids:
                report["blocked"].append(
                    f"REMOVE {target}: blocked - original source requirement; "
                    f"removal requires an explicit user decision"
                )
                continue
            removed = False
            for section in doc.sections:
                for item in list(section.items):
                    if item.id == target:
                        section.items.remove(item)
                        removed = True
            if removed:
                report["applied"].append(f"REMOVE {target}")
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
                section.items.append(DocItem(id=target, raw="\n" + body.rstrip("\n") + "\n"))
                report["applied"].append(f"ADD {target}")
            else:
                # Bullet addition to the existing-system/assumptions section.
                section = next((s for s in doc.sections if s.kind == "bullets"), None)
                if section is None:
                    report["errors"].append(f"ADD {target}: no assumptions/constraints section")
                    continue
                text_body = body if body.lstrip().startswith(("-", "•")) else "- " + body.lstrip()
                new_id = f"E{sum(1 for s in doc.sections for i in s.items if i.id and i.id.startswith('E')) + 1}"
                section.items.append(DocItem(id=new_id, raw=text_body.rstrip("\n") + "\n"))
                report["applied"].append(f"ADD {new_id} (assumption/constraint)")

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

    if report["applied"]:
        report["text"] = doc.render()
        report["changed"] = True
    return report
