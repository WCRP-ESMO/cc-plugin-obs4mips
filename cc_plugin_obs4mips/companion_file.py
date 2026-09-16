"""Add user-supplied companion NetCDF files to the Compliance Checker CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def include_companion_files(args: Any) -> list[Path]:
    """Append explicitly supplied companion NetCDF files to parsed CLI inputs."""
    companions = list(getattr(args, "companion_file", []) or [])
    if not companions:
        return []

    locations = list(getattr(args, "dataset_location", []))
    if len(locations) != 1:
        raise ValueError(
            "--companion-file requires exactly one primary input dataset"
        )

    primary = Path(locations[0]).expanduser().resolve()
    if not primary.is_file():
        raise ValueError(
            "--companion-file requires one existing local primary NetCDF file"
        )

    companion_paths: list[Path] = []
    seen = {primary}
    for value in companions:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"companion NetCDF file does not exist: {value}")
        if path in seen:
            continue
        seen.add(path)
        companion_paths.append(path)

    args.dataset_location.extend(str(path) for path in companion_paths)
    return companion_paths


class Obs4MipsCompanionFileGenerator:
    """Compliance Checker CLI hook for user-supplied companion files."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        """Register the repeatable companion-file option."""
        parser.add_argument(
            "--companion-file",
            dest="companion_file",
            action="append",
            metavar="FILE",
            help=(
                "companion uncertainty or cell-measure NetCDF to check with one "
                "primary input; repeat the option for multiple files"
            ),
        )

    @staticmethod
    def get_checkers(args: argparse.Namespace) -> dict[str, type]:
        """Expand dataset arguments and return no generated checker classes."""
        try:
            include_companion_files(args)
        except ValueError as error:
            raise SystemExit(f"compliance-checker: error: {error}") from error
        return {}
