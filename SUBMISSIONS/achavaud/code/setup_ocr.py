"""Download public Tesseract language data; no company documents are uploaded."""

import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parent / ".ocr")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    for language in ("fra", "eng"):
        path = args.directory / f"{language}.traineddata"
        if not path.exists():
            url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{language}.traineddata"
            with urlopen(url, timeout=60) as response:
                content = response.read()
            if len(content) < 100_000:
                raise ValueError(f"Unexpected OCR language data received from {url}")
            temporary = path.with_suffix(".download")
            temporary.write_bytes(content)
            temporary.replace(path)
        print(f"{path}: sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
