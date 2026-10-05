"""CLI: verify answer JSON against sources and KYC traps.

    python scripts/factcheck.py
    python scripts/factcheck.py --form form_01
    python scripts/factcheck.py --fix
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.factcheck import main

if __name__ == "__main__":
    main()
