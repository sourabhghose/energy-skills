"""Put this skill's scripts/ and tests/ on sys.path."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
