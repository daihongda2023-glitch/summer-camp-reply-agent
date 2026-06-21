from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from summer_camp_agent.cli import main


if __name__ == "__main__":
    args = ["validate", *sys.argv[1:]]
    raise SystemExit(main(args))
