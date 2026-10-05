"""Check that the local model answers, on text and on an image (server from start_server.sh must be running).

    .venv/bin/python our_work/local_llm/smoke_test.py
"""
import base64
import json
import time
import urllib.request
from pathlib import Path

import pymupdf

URL = "http://127.0.0.1:8080/v1/chat/completions"
PAGE = Path(__file__).parent.parent / "extraction" / "form_01" / "page_01.png"


def ask(content, think: bool) -> None:
    body = {"messages": [{"role": "user", "content": content}], "max_tokens": 2000,
            "chat_template_kwargs": {"enable_thinking": think}}
    start = time.time()
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        resp = json.load(r)
    t = resp.get("timings", {})
    print(f"  {time.time() - start:.1f}s | prompt {t.get('prompt_n')} tok @ {t.get('prompt_per_second', 0):.0f} tok/s"
          f" | output {t.get('predicted_n')} tok @ {t.get('predicted_per_second', 0):.1f} tok/s")
    print("  " + (resp["choices"][0]["message"]["content"] or "").strip()[:500].replace("\n", "\n  "))


print("1) text")
ask("Reply with one short sentence: what is a KYC form?", think=False)

print("2) image (form_01 page 1, top third, downscaled)")
pix = pymupdf.Pixmap(str(PAGE))
crop = pymupdf.Pixmap(pix, pix.width, pix.height // 3, pymupdf.IRect(0, 0, pix.width, pix.height // 3))
png = crop.tobytes("png")
ask([{"type": "text", "text": "Read the title of this form and list the field labels you see."},
     {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}], think=False)
