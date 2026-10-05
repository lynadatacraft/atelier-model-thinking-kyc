from datacraft.ingestion.markdown_loader import parse_markdown

SAMPLE = """# Tax status memorandum

Document ID: X-TAX-20260901

**FICTIONAL EXERCISE DOCUMENT — NOT VALID FOR REAL USE.**

Entity: X SAS. Information as of 2026-09-01; accounting period is calendar 2025.

```json
{"tax_residences": [{"country": "France"}], "supervisor": null}
```
"""


def test_parses_title_id_date_prose_and_json():
    parsed = parse_markdown(SAMPLE)
    assert parsed.title == "Tax status memorandum"
    assert parsed.document_id == "X-TAX-20260901"
    assert parsed.as_of.isoformat() == "2026-09-01"
    assert parsed.data == {"tax_residences": [{"country": "France"}], "supervisor": None}
    assert "Information as of 2026-09-01" in parsed.prose
    assert "```" not in parsed.prose and "Document ID" not in parsed.prose


def test_markdown_without_json_block():
    assert parse_markdown("# Title\n\nJust text.").data is None
