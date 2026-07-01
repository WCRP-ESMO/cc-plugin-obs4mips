"""
Controlled-vocabulary registry.

CV tables live in cc_plugin_obs4mips/cv_data/ as JSON files.
Each table is either a JSON list of strings or {'values': [...], ...}.
Missing tables degrade gracefully (treat all values as valid) so we can develop checks
before the CV is published.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from importlib.resources import files
from pathlib import Path


class _CVRegistry:
    """Loads and queries controlled vocabularies from JSON files in the package."""

    def __init__(self, package: str = "cc_plugin_obs4mips.cv_data"):
        """Initialize the _CVRegistry instance."""
        self._package = package

    @lru_cache(maxsize=None)
    def _load(self, version: str, table: str):
        """Load the specified CV table for a given ODS version."""
        # User can supply path to CV table via environment variable for testing/override
        env_path = os.environ.get(f"OBS4MIPS_CV_{table.upper()}")
        if env_path:
            return set(json.loads(Path(env_path).read_text()))
        # Otherwise, load from cv_data/version
        try:
            text = (
                files(f"cc_plugin_obs4mips.cv_data.v{version}") / f"{table}.json"
            ).read_text()
            return set(json.loads(text))
        except (FileNotFoundError, ModuleNotFoundError):
            return None  # CV not shipped -> don't false-fail

    def contains(self, version: str, table: str, value: str) -> bool:
        """Check if value is in the specified CV table. Returns True if table is missing."""
        values = self._load(version, table)
        return True if values is None else value in values

    def is_loaded(self, version: str, table: str) -> bool:
        """Check if CV table is available (i.e. file exists and loaded successfully)."""
        return self._load(version, table) is not None


# Create a global CV registry instance for use in checks
CV = _CVRegistry()
