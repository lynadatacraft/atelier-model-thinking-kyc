"""Parse source Markdown documents: title, document id, prose header and the JSON block."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

_JSON_BLOCK = re.compile(r"```json\s*\n(.*?)```", re.S)
_DOC_ID = re.compile(r"^Document ID:\s*(\S+)\s*$", re.M)
_AS_OF = re.compile(r"as of (\d{4}-\d{2}-\d{2})")


@dataclass
class ParsedMarkdown:
    title: str | None
    document_id: str | None
    prose: str
    data: Any
    as_of: date | None


def parse_markdown(text: str) -> ParsedMarkdown:
    match = _JSON_BLOCK.search(text)
    data = json.loads(match.group(1)) if match else None
    body = _JSON_BLOCK.sub("", text)

    title = None
    prose_lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and title is None:
            title = stripped[2:].strip()
        elif not _DOC_ID.match(stripped):
            prose_lines.append(stripped)

    doc_id = _DOC_ID.search(body)
    as_of = _AS_OF.search(body)
    return ParsedMarkdown(
        title=title,
        document_id=doc_id.group(1) if doc_id else None,
        prose="\n".join(prose_lines),
        data=data,
        as_of=date.fromisoformat(as_of.group(1)) if as_of else None,
    )
