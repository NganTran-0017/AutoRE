"""
Patch-based requirements store: parse/render identity, patch application,
and protection of original-source requirements against removal.
"""

from pathlib import Path

from src.utils.requirements_store import (
    annotate_for_prompt,
    apply_patch,
    existing_system_texts,
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


def test_add_subrequirement_nests_under_parent():
    # A sub-requirement must land directly after its parent's subtree, not at
    # the bottom of the section.
    patch = """=== REQUIREMENT PATCH ===
[ADD] R1.1 (provenance: user answer Q-9)
Text:
R1.1: Triggering administrators must be distinct.
"""
    result = apply_patch(SAMPLE_DOC, patch)
    assert result["changed"] and result["applied"] == ["ADD R1.1"]
    text = result["text"]
    # R1.1 sits between R1 and R2, not after R3.
    assert text.index("R1.1: Triggering") < text.index("R2: Emergency Mode Duration")
    assert text.index("R1: Emergency Triggering") < text.index("R1.1: Triggering")
    reparsed = parse_requirements_document(text)
    assert "R1.1" in reparsed.all_item_ids()
    assert reparsed.render() == text  # round-trips for the next iteration


DOC_WITH_CONSTRAINTS = """```
SYSTEM OVERVIEW
===============
An RBAC platform.

EXISTING-SYSTEM REQUIREMENTS AND CONSTRAINTS
============================================
- Users have clearance levels High, Medium, or Low.

PROSPECTIVE FUNCTIONAL REQUIREMENTS
====================================
R1: Emergency Triggering
Exactly 2 administrators trigger an emergency.

CONSTRAINTS
===========
- Emergency mode must revert to Normal mode.
```
"""


def test_add_constraint_targets_constraints_section():
    # [ADD] CONSTRAINTS must resolve to the standalone CONSTRAINTS section, not
    # the earlier EXISTING-SYSTEM section it is a substring of.
    patch = """=== REQUIREMENT PATCH ===
[ADD] CONSTRAINTS (provenance: consequence of E1)
Text:
For each user and role, direct and delegated holding are distinguished at all times.
"""
    result = apply_patch(DOC_WITH_CONSTRAINTS, patch)
    assert result["changed"]
    doc = parse_requirements_document(result["text"])
    constraints = doc.find_section("CONSTRAINTS")
    existing = doc.find_section("EXISTING-SYSTEM", fuzzy=True)
    joined_constraints = "".join(i.raw for i in constraints.items)
    joined_existing = "".join(i.raw for i in existing.items)
    assert "direct and delegated holding are distinguished" in joined_constraints
    assert "direct and delegated holding are distinguished" not in joined_existing


def test_remove_protected_is_blocked():
    """Both families are protected. An E-item states something already true of
    the system; deleting the sentence does not make it false, so a REMOVE of
    one is a modelling convenience, never a requirements decision."""
    protected = parse_original_requirement_ids(ORIGINAL_INPUT)
    patch = """=== REQUIREMENT PATCH ===
[REMOVE] R1
Justification: model does not need it.

[REMOVE] E2
Justification: superseded.
"""
    result = apply_patch(SAMPLE_DOC, patch, protected_ids=protected,
                         protected_texts=existing_system_texts(SAMPLE_DOC))
    assert any("REMOVE R1" in b for b in result["blocked"])
    assert any("REMOVE E2" in b for b in result["blocked"])
    assert "R1: Emergency Triggering" in result["text"]
    assert "every request is eventually processed" in result["text"]


def test_a_bullet_the_run_added_is_still_removable():
    """Only ORIGINAL-source items are protected. A bullet the run introduced
    was never ground truth, so removal applies to it normally."""
    baseline = existing_system_texts(SAMPLE_DOC)
    doc = SAMPLE_DOC.replace(
        "- Users have clearance",
        "- Sessions are audited.\n- Users have clearance")
    result = apply_patch(
        doc, "=== REQUIREMENT PATCH ===\n[REMOVE] E1\nJustification: duplicate.\n",
        protected_ids=parse_original_requirement_ids(ORIGINAL_INPUT),
        protected_texts=baseline)
    assert result["applied"] == ["REMOVE E1"]
    assert "Sessions are audited" not in result["text"]


def test_protection_follows_the_text_when_bullets_are_renumbered():
    """E-numbers are positional. Inserting a bullet at the top shifts every one
    below it, so an ID captured at iteration 0 would protect the wrong
    sentence - the reason the protected set is keyed on text."""
    baseline = existing_system_texts(SAMPLE_DOC)
    doc = SAMPLE_DOC.replace(
        "- Users have clearance",
        "- Sessions are audited.\n- Users have clearance")
    # "Users have clearance levels" was E1 in the baseline and is E2 now.
    result = apply_patch(
        doc, "=== REQUIREMENT PATCH ===\n[REMOVE] E2\nJustification: no.\n",
        protected_ids=set(), protected_texts=baseline)
    assert any("REMOVE E2" in b for b in result["blocked"])
    assert "Users have clearance levels" in result["text"]


def test_existing_system_texts_ignores_whitespace_and_the_bullet_marker():
    baseline = existing_system_texts(SAMPLE_DOC)
    reflowed = SAMPLE_DOC.replace(
        "- Users have clearance levels High, Medium, or Low.",
        "-   Users have clearance levels High,\n  Medium, or Low.")
    result = apply_patch(
        reflowed, "=== REQUIREMENT PATCH ===\n[REMOVE] E1\nJustification: no.\n",
        protected_ids=set(), protected_texts=baseline)
    assert any("REMOVE E1" in b for b in result["blocked"])


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


# ------------------------------------------------------- R-ID prefix guard #

def test_modify_reattaches_a_dropped_r_id():
    """Without the ID the item stops being addressable on the next parse."""
    result = apply_patch(SAMPLE_DOC, """=== REQUIREMENT PATCH ===
[MODIFY] R1
New text:
Any single administrator may trigger an emergency.
""")
    assert result["applied"] == ["MODIFY R1"]
    assert "R1: Any single administrator may trigger an emergency." in result["text"]
    reparsed = parse_requirements_document(result["text"])
    assert "R1" in reparsed.all_item_ids()
    assert reparsed.render() == result["text"]


def test_modify_leaves_a_correct_prefix_alone():
    result = apply_patch(SAMPLE_DOC, """=== REQUIREMENT PATCH ===
[MODIFY] R1
New text:
R1: Emergency Triggering
Any single administrator may trigger an emergency.
""")
    assert "R1: Emergency Triggering" in result["text"]
    assert "R1: R1:" not in result["text"]


def test_modify_reuses_the_items_own_separator_and_indent():
    doc = """```
PROSPECTIVE FUNCTIONAL REQUIREMENTS
====================================
R3. Privileges During Emergency
    R3.1. Request processing may bypass FIFO order.
```
"""
    result = apply_patch(doc, """=== REQUIREMENT PATCH ===
[MODIFY] R3.1
New text:
Request processing follows FIFO order at all times.
""")
    assert "    R3.1. Request processing follows FIFO order" in result["text"]
    assert parse_requirements_document(result["text"]).render() == result["text"]


def test_modify_body_naming_a_different_id_is_normalised_to_the_target():
    """The addressed item is overwritten either way; a stray ID would duplicate
    that other requirement and lose this one."""
    result = apply_patch(SAMPLE_DOC, """=== REQUIREMENT PATCH ===
[MODIFY] R1
New text:
R2: Emergency mode is active for a limited time.
""")
    assert "R1: Emergency mode is active for a limited time." in result["text"]
    reparsed = parse_requirements_document(result["text"])
    assert {"R1", "R2"} <= reparsed.all_item_ids()
    # R2 still has its own text - it was not overwritten by the stray prefix.
    assert "R2: Emergency Mode Duration" in result["text"]


def test_guard_does_not_fire_on_a_body_merely_mentioning_a_requirement():
    result = apply_patch(SAMPLE_DOC, """=== REQUIREMENT PATCH ===
[MODIFY] R1
New text:
R1: Emergency Triggering
Exactly 2 administrators trigger an emergency, provided R2 has not yet elapsed.
""")
    assert "provided R2 has not yet elapsed" in result["text"]


def test_e_bullet_guard_is_unaffected_by_the_r_guard():
    result = apply_patch(SAMPLE_DOC, """=== REQUIREMENT PATCH ===
[MODIFY] E1
New text:
Users have clearance levels High or Low only.
""")
    assert "- Users have clearance levels High or Low only." in result["text"]


# ------------------------------------------------- before/after of a change #

def _changes(patch, doc=SAMPLE_DOC):
    return {c["target"]: c for c in apply_patch(doc, patch)["changes"]}


def test_modify_records_the_text_on_both_sides_not_just_the_id():
    """"MODIFY R1" cannot distinguish a clarification from a reversal."""
    changes = _changes("""=== REQUIREMENT PATCH ===
[MODIFY] R1
New text:
R1: Emergency Triggering
Any single administrator may trigger an emergency at any time.
""")
    assert changes["R1"]["op"] == "MODIFY"
    assert "Exactly 2 administrators" in changes["R1"]["before"]
    assert "Any single administrator" in changes["R1"]["after"]
    assert "Exactly 2 administrators" not in changes["R1"]["after"]


def test_remove_keeps_the_text_that_was_deleted():
    """The deleted text is the only place the void requirement still exists."""
    changes = _changes("""=== REQUIREMENT PATCH ===
[REMOVE] R3.2
Justification: superseded.
""")
    assert "mutually exclusive roles" in changes["R3.2"]["before"].lower()
    assert changes["R3.2"]["after"] == ""


def test_add_records_only_an_after():
    changes = _changes("""=== REQUIREMENT PATCH ===
[ADD] R4 (provenance: user answer)
Text:
R4: Emergency Logging
Every emergency is recorded in an audit log.
""")
    assert changes["R4"]["before"] == ""
    assert "audit log" in changes["R4"]["after"]


def test_a_blocked_or_errored_op_records_no_change():
    """`changes` carries applied ops only - a blocked REMOVE changed nothing."""
    protected = parse_original_requirement_ids(ORIGINAL_INPUT)
    result = apply_patch(SAMPLE_DOC, """=== REQUIREMENT PATCH ===
[REMOVE] R1
Justification: no longer needed.

[MODIFY] R99
New text:
R99: does not exist
""", protected)
    assert result["blocked"] and result["errors"]
    assert result["changes"] == []


def test_changes_and_applied_stay_in_step():
    result = apply_patch(SAMPLE_DOC, """=== REQUIREMENT PATCH ===
[MODIFY] R2
New text:
R2: Emergency Mode Duration
Emergency mode ends within one hour.

[ADD] CONSTRAINTS
Text:
- Audit logs are immutable.
""")
    assert len(result["changes"]) == len(result["applied"]) == 2


def test_changes_since_reports_how_not_only_which(tmp_path):
    """changed_requirement_ids_since answers WHICH; changes_since answers HOW."""
    from src.utils.requirement_patch_log import (
        RequirementPatchLog, RequirementPatchLogEntry,
    )

    log = RequirementPatchLog(log_path=tmp_path / "patch.json")
    log.add_entry(RequirementPatchLogEntry(
        iteration_id=20, raw_response="", applied=["MODIFY R1"],
        changes=[{"op": "MODIFY", "target": "R1",
                  "before": "enter Emergency mode only once",
                  "after": "enter Emergency mode repeatedly"}]))
    log.add_entry(RequirementPatchLogEntry(
        iteration_id=21, raw_response="", applied=["ADD R4"],
        changes=[{"op": "ADD", "target": "R4", "before": "", "after": "new"}]))

    assert log.changed_requirement_ids_since(20) == ["R1"]  # ADD is not a change
    since = log.changes_since(20)
    assert [c["target"] for c in since] == ["R1"]
    assert since[0]["iteration_id"] == 20
    assert "only once" in since[0]["before"]

    # Survives a save/load round-trip - the audit outlives the process.
    reloaded = RequirementPatchLog(log_path=tmp_path / "patch.json")
    assert reloaded.changes_since(20)[0]["after"] == "enter Emergency mode repeatedly"


def test_entries_written_before_the_field_existed_still_load(tmp_path):
    import json
    from src.utils.requirement_patch_log import RequirementPatchLog

    path = tmp_path / "patch.json"
    path.write_text(json.dumps([
        {"iteration_id": 20, "raw_response": "", "applied": ["MODIFY R6"]}
    ]))
    log = RequirementPatchLog(log_path=path)
    assert log.entries[0].changes == []
    assert log.changed_requirement_ids_since(0) == ["R6"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All requirements-patch tests passed.")
