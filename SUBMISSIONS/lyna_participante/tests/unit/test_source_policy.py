from datacraft.models import SourceRole


def roles(kb):
    return {d.doc_type: d.role for d in kb.pack.documents if d.subject_id == kb.client_id}


def test_primary_markdown_and_derived_copies(kb_a):
    r = roles(kb_a)
    assert r["corporate"] is SourceRole.PRIMARY
    assert r["corporate_facts"] is SourceRole.DERIVED
    assert r["exposure"] is SourceRole.DERIVED


def test_traps_are_never_admissible(kb_a):
    r = roles(kb_a)
    assert r["registered_office_archive"] is SourceRole.HISTORICAL
    assert r["office_supplies_invoice"] is SourceRole.CONTEXTUAL
    assert r["staff_training_plan"] is SourceRole.CONTEXTUAL


def test_lookup_skips_historical_address(kb_a):
    # The 2024 Bordeaux address exists in the pack but must never be retrieved by default.
    facts = kb_a.lookup("registered_office_archive", "/address")
    assert facts == []
    assert kb_a.fact("corporate", "/address").value.endswith("Lyon, France")


def test_reporting_scope_excludes_parent(kb_factory):
    kb = kb_factory("belorive_patrimoine")
    names = {c.name for c in kb.reporting_scope()}
    assert "Belorive Participations SAS" not in names
    assert {"Belorive Patrimoine SAS", "Belorive Immobilier Belarus LLC", "Belorive Clôture Russia LLC"} <= names


def test_dataset_checksums_match_loaded_documents(root, kb_a):
    import json
    sums = json.loads((root / "SHA256SUMS.json").read_text())
    for doc in kb_a.pack.documents:
        assert sums[doc.path] == doc.sha256
