"""Pukara source package."""
from pathlib import Path

# Single source of truth for the package version (used by pyproject.toml).
__version__ = "1.2.0"

# Project root (the directory that contains this `src/` package).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
