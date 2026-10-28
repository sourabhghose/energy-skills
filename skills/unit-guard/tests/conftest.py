"""Put this skill's scripts/ on sys.path so tests import the vetted modules directly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
