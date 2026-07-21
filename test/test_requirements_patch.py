"""
Patch-based requirements store: parse/render identity, patch application,
and protection of original-source requirements against removal.
"""

from pathlib import Path

from src.utils.requirements_store import (
    annotate_for_prompt,
    apply_patch,
    parse_original_requirement_ids,
    parse_patch,
    parse_requirements_document,
)


SAMPLE_DOC = """```
SYSTEM OVERVIEW
===============
An RBAC platform with an Emergency Module to be integrated.

EXISTING-SYSTEM ASSUMPTIONS AND CONSTRAINTS
============================================
- Users have clearance levels High, Medium, or Low.
- Requests are processed concurrently in FIFO order, and every request is eventually processed.
- Delegated roles expire after a fixed amount of time or are revoked by administrators.

PROSPECTIVE FUNCTIONAL REQUIREMENTS
====================================
R1: Emergency Triggering
Exactly 2 administrators trigger an emergency while in Normal mode.

R2: Emergency Mode Duration
Emergency mode is active for a limited time; the system must eventually return to Normal mode.

R3: Privileges During Emergency
R3.1: Request processing may bypass FIFO order.
R3.2: Users may temporarily hold mutually exclusive roles.
```
"""

ORIGINAL_INPUT = """SYSTEM DESCRIPTION:
The RBAC system supports delegation.

FUNCTIONAL REQUIREMENTS:
R1. Exactly 2 administrators trigger an emergency.
R2. Emergency mode is time-limited.
R3. During the Emergency mode:
    R3.1. FIFO bypass allowed.
    R3.2. Mutually exclusive roles allowed.
"""


# ------------------------------------------------------------ parse/render #

def test_parse_render_identity_sample():
    doc = parse_requirements_document(SAMPLE_DOC)
    assert doc.render() == SAMPLE_DOC
    assert {"R1", "R2", "R3", "R3.1", "R3.2", "E1", "E2", "E3"} <= doc.all_item_ids()


def test_parse_render_identity_real_docs():
    for name in ("Reqs_0.txt", "Reqs_68.txt"):
        path = Path("Output/ReqsDoc") / name
        if not path.exists():
            continue
        text = path.read_text()
        assert parse_requirements_document(text).render() == text, f"identity failed: {name}"


def test_annotate_marks_bullets_only():
    doc = parse_requirements_document(SAMPLE_DOC)
    annotated = annotate_for_prompt(doc)
    assert "[E1] - Users have clearance levels" in annotated
    assert "[E2] - Requests are processed" in annotated
    assert "[R1]" not in annotated  # R items carry their own IDs
    # Markers never leak into the stored document.
    assert "[E1]" not in doc.render()


def test_original_ids():
    ids = parse_original_requirement_ids(ORIGINAL_INPUT)
    assert ids == {"R1", "R2", "R3", "R3.1", "R3.2"}
    assert parse_original_requirement_ids(None) == set()


# ------------------------------------------------------------ patch parse #

def test_parse_patch_ops_and_labels():
    patch = """Some preamble the model wrote.
=== REQUIREMENT PATCH ===
[MODIFY] R2
New text:
R2: Emergency Mode Duration
Emergency mode ends by timeout or early termination.

[ADD] R4 (provenance: user answer Q-3)
Text:
R4: Post-Emergency Restoration
Privileges are revoked after Emergency mode ends.

[REMOVE] E3
Justification: superseded by user clarification.
"""
    parsed = parse_patch(patch)
    assert not parsed["errors"]
    ops = {(o["op"], o["target"]) for o in parsed["ops"]}
    assert ops == {("MODIFY", "R2"), ("ADD", "R4"), ("REMOVE", "E3")}
    modify = next(o for o in parsed["ops"] if o["op"] == "MODIFY")
    assert modify["body"].startswith("R2: Emergency Mode Duration")
    add = next(o for o in parsed["ops"] if o["op"] == "ADD")
    assert "provenance" in add["meta"]


def test_parse_patch_no_change_and_garbage():
    parsed = parse_patch("=== REQUIREMENT PATCH ===\n[NO-CHANGE]\n")
    assert parsed["no_change"] and not parsed["ops"] and not parsed["errors"]

    parsed = parse_patch("here is the full updated document instead...")
    assert parsed["errors"]  # no ops found


# ------------------------------------------------------------ apply_patch #

def test_modify_preserves_everything_else():
    patch = """=== REQUIREMENT PATCH ===
[MODIFY] R2
New text:
R2: Emergency Mode Duration
Emergency mode ends by timeout or by early termination by the triggering administrators.
"""
    result = apply_patch(SAMPLE_DOC, patch)
    assert result["changed"] and result["applied"] == ["MODIFY R2"]
    assert "early termination by the triggering administrators" in result["text"]
    # Byte-identical outside the modified chunk.
    for untouched in (
        "An RBAC platform with an Emergency Module to be integrated.",
        "- Users have clearance levels High, Medium, or Low.",
        "R3.1: Request processing may bypass FIFO order.",
    ):
        assert untouched in result["text"]
    # Round-trips through the parser for the next iteration.
    assert parse_requirements_document(result["text"]).render() == result["text"]


def test_modify_bullet_keeps_bullet_marker():
    patch = """=== REQUIREMENT PATCH ===
[MODIFY] E1
New text:
Users have clearance levels High, Medium, or Low; administrators always have High clearance.
"""
    result = apply_patch(SAMPLE_DOC, patch)
    assert result["changed"]
    assert "- Users have clearance levels High, Medium, or Low; administrators always have High" in result["text"]


def test_add_requirement_and_bullet():
    patch = """=== REQUIREMENT PATCH ===
[ADD] R4 (provenance: user answer Q-3)
Text:
R4: Post-Emergency Restoration
Privileges are revoked after Emergency mode ends.

[ADD] EXISTING-SYSTEM (provenance: verified finding iter 12)
Text:
Self-delegation is prohibited.
"""
    result = apply_patch(SAMPLE_DOC, patch)
    assert result["changed"]
    assert "R4: Post-Emergency Restoration" in result["text"]
    assert "- Self-delegation is prohibited." in result["text"]
    reparsed = parse_requirements_document(result["text"])
    assert "R4" in reparsed.all_item_ids()
    assert "E4" in reparsed.all_item_ids()


def test_remove_protected_is_blocked():
    protected = parse_original_requirement_ids(ORIGINAL_INPUT)
    patch = """=== REQUIREMENT PATCH ===
[REMOVE] R1
Justification: model does not need it.

[REMOVE] E2
Justification: superseded.
"""
    result = apply_patch(SAMPLE_DOC, patch, protected_ids=protected)
    assert any("REMOVE R1" in b for b in result["blocked"])
    assert "R1: Emergency Triggering" in result["text"]  # still there
    assert result["applied"] == ["REMOVE E2"]  # non-original bullet removable
    assert "every request is eventually processed" not in result["text"]


def test_modify_section():
    patch = """=== REQUIREMENT PATCH ===
[MODIFY-SECTION] SYSTEM OVERVIEW
New text:
An RBAC platform. A new Emergency Module is being integrated and verified.
"""
    result = apply_patch(SAMPLE_DOC, patch)
    assert result["applied"] == ["MODIFY-SECTION SYSTEM OVERVIEW"]
    assert "being integrated and verified" in result["text"]
    assert "R1: Emergency Triggering" in result["text"]


def test_bad_targets_and_duplicates_error_without_change():
    patch = """=== REQUIREMENT PATCH ===
[MODIFY] R99
New text:
R99: nope

[ADD] R1
Text:
R1: duplicate
"""
    result = apply_patch(SAMPLE_DOC, patch)
    assert not result["changed"]
    assert result["text"] == SAMPLE_DOC
    assert len(result["errors"]) == 2


def test_unusable_patch_leaves_document_untouched():
    result = apply_patch(SAMPLE_DOC, "SYSTEM OVERVIEW\n===\nfull rewrite attempt")
    assert not result["changed"]
    assert result["text"] == SAMPLE_DOC
    assert result["errors"]


def test_no_change_patch():
    result = apply_patch(SAMPLE_DOC, "=== REQUIREMENT PATCH ===\n[NO-CHANGE]")
    assert result["no_change"] and not result["changed"]
    assert result["text"] == SAMPLE_DOC


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All requirements-patch tests passed.")
