"""Make the harness modules importable and share helpers across the EnergyBench tests."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
