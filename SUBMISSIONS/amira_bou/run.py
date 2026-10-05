#!/usr/bin/env python3
"""One command: fill a KYC questionnaire from the tagged fact store.

    python run.py --form form_01
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.ask import answer_form


def main() -> None:
    parser = argparse.ArgumentParser(description="DATACRAFT KYC — structured fact-store pipeline")
    parser.add_argument("--form", default="form_01", help="form_01 … form_05")
    parser.add_argument("--pdf", action="store_true", help="Also overlay answers onto a filled PDF.")
    args = parser.parse_args()
    answer_form(args.form, write_pdf=args.pdf)


if __name__ == "__main__":
    main()
