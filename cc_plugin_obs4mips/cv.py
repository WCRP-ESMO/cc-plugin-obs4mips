"""Load packaged obs4MIPs controlled-vocabulary snapshots."""

from __future__ import annotations

import json
import os
from difflib import get_close_matches
from functools import lru_cache
from importlib.resources import files
from pathlib import Path


class _CVRegistry:
    """Loads and queries controlled vocabularies from JSON files in the package."""

    def __init__(self, package: str = "cc_plugin_obs4mips"):
        """Initialize the _CVRegistry instance."""
        self._package = package

    @lru_cache(maxsize=None)
    def _load(self, version: str, table: str):
        """Load the specified CV table for a given ODS version."""
        env_path = os.environ.get(f"OBS4MIPS_CV_{table.upper()}")
        if env_path:
            return self._parse_values(json.loads(Path(env_path).read_text()), table)

        try:
            resource = files(self._package).joinpath(
                "cv_data", version, f"{table}.json"
            )
            return self._parse_values(json.loads(resource.read_text()), table)
        except (FileNotFoundError, ModuleNotFoundError):
            return None

    @staticmethod
    def _parse_values(payload, table: str) -> frozenset[str]:
        """Normalize either a bare list or a metadata-wrapped CV snapshot."""
        values = payload.get("values") if isinstance(payload, dict) else payload
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise ValueError(
                f"CV table {table!r} must be a list or contain a string 'values' list"
            )
        return frozenset(values)

    def contains(self, version: str, table: str, value: str) -> bool:
        """Check if value is in the specified CV table. Returns True if table is missing."""
        values = self._load(version, table)
        return True if values is None else value in values

    def is_loaded(self, version: str, table: str) -> bool:
        """Check if CV table is available (i.e. file exists and loaded successfully)."""
        return self._load(version, table) is not None

    def values(self, version: str, table: str) -> frozenset[str]:
        """Return registered values, or an empty set when the table is unavailable."""
        return self._load(version, table) or frozenset()

    def metadata(self, version: str, table: str) -> dict:
        """Return the generation metadata stored with a packaged CV snapshot."""
        env_path = os.environ.get(f"OBS4MIPS_CV_{table.upper()}")
        try:
            payload = (
                json.loads(Path(env_path).read_text())
                if env_path
                else json.loads(
                    files(self._package)
                    .joinpath("cv_data", version, f"{table}.json")
                    .read_text()
                )
            )
        except (FileNotFoundError, ModuleNotFoundError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            key: payload[key]
            for key in ("cv", "cv_version", "source", "source_ref", "value_field")
            if key in payload
        }

    def suggestions(
        self, version: str, table: str, value: str, *, limit: int = 3
    ) -> list[str]:
        """Return similar registered values, comparing without regard to case."""
        values = sorted(self.values(version, table))
        by_folded = {candidate.casefold(): candidate for candidate in values}
        matches = get_close_matches(
            value.casefold(), list(by_folded), n=limit, cutoff=0.5
        )
        return [by_folded[match] for match in matches]


# Create a global CV registry instance for use in checks
CV = _CVRegistry()
