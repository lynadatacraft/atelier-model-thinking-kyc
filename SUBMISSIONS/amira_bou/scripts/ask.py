"""CLI entry: python scripts/ask.py --form form_01"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.ask import main

if __name__ == "__main__":
    main()
