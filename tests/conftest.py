"""Shared test configuration."""

import sys
from pathlib import Path

# Make the extension lib importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "inkscape-extension"))
