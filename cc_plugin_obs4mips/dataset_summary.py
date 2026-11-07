"""Generate a deterministic, machine-readable NetCDF header summary."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from netCDF4 import Dataset

from cc_plugin_obs4mips import __version__
from cc_plugin_obs4mips.checks import unregistered_terms
from cc_plugin_obs4mips.specs import BUNDLE


SUMMARY_SCHEMA = "obs4mips-dataset-summary"
SUMMARY_SCHEMA_VERSION = "1.0.0"
ODS_VERSION = BUNDLE["ods_version"]


def _json_value(value: Any) -> Any:
    """Convert NetCDF/NumPy attribute values to strict JSON values."""
    if isinstance(value, np.ma.MaskedArray):
        return _json_value(value.tolist())
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _attributes(owner: Any) -> dict[str, Any]:
    """Return all NetCDF attributes in deterministic name order."""
    return {
        name: _json_value(owner.getncattr(name)) for name in sorted(owner.ncattrs())
    }


def _coordinate_names(dataset: Dataset) -> tuple[set[str], set[str]]:
    """Identify dimension and auxiliary coordinate variables."""
    dimension_coordinates = {
        name
        for name, variable in dataset.variables.items()
        if name in dataset.dimensions and variable.dimensions == (name,)
    }
    auxiliary_coordinates: set[str] = set()
    for variable in dataset.variables.values():
        coordinates = getattr(variable, "coordinates", "")
        if isinstance(coordinates, str):
            auxiliary_coordinates.update(coordinates.split())
    auxiliary_coordinates.intersection_update(dataset.variables)
    auxiliary_coordinates.difference_update(dimension_coordinates)
    return dimension_coordinates, auxiliary_coordinates


def _variable_summary(variable: Any) -> dict[str, Any]:
    """Summarize a variable without reading its data values."""
    return {
        "dtype": str(variable.dtype),
        "dimensions": list(variable.dimensions),
        "shape": list(variable.shape),
        "attributes": _attributes(variable),
    }


def _cv_update_candidates(global_attributes: dict[str, Any]) -> dict[str, Any]:
    """Describe unregistered CV values for review and later automation."""
    terms = []
    for name, value in global_attributes.items():
        attr = BUNDLE["attributes"].get(name)
        if not attr or not isinstance(value, str) or not ("allowed" in attr or "patterns" in attr):
            continue
        for token, similar in unregistered_terms(name, value):
            candidate = {
                "attribute": name,
                "collection": attr["cv"]["table"],
                "registered_content": attr["rc"] == "yes",
                "submitted_value": token,
                "value_field": attr["cv"]["key"],
                "source_ref": BUNDLE["cvs_ref"],
                "similar_registered_values": similar,
            }
            if name == "variable_id":
                candidate["variable_metadata_path"] = f"/dataset/variables/{token}"
            terms.append(candidate)

    return {
        "guidance": (
            "Before proposing a new term, verify that an existing registered CV "
            "term is not appropriate."
        ),
        "dataset_global_attributes_path": "/dataset/global_attributes",
        "terms": terms,
    }


def summarize_dataset(dataset_path: str | Path) -> dict[str, Any]:
    """Build a versioned JSON-compatible summary of a NetCDF dataset header."""
    path = Path(dataset_path)
    with Dataset(path, mode="r") as dataset:
        global_attributes = _attributes(dataset)
        dimension_coordinates, auxiliary_coordinates = _coordinate_names(dataset)
        coordinate_names = dimension_coordinates | auxiliary_coordinates

        coordinates = {}
        for name in sorted(coordinate_names):
            summary = _variable_summary(dataset.variables[name])
            summary["coordinate_type"] = (
                "dimension" if name in dimension_coordinates else "auxiliary"
            )
            coordinates[name] = summary

        variables = {
            name: _variable_summary(variable)
            for name, variable in sorted(dataset.variables.items())
            if name not in coordinate_names
        }

        return {
            "schema": SUMMARY_SCHEMA,
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "ods_version": ODS_VERSION,
            "generated_by": {
                "name": "cc-plugin-obs4mips",
                "version": __version__,
            },
            "cv_update_candidates": _cv_update_candidates(global_attributes),
            "dataset": {
                "file_name": path.name,
                "file_format": dataset.file_format,
                "global_attributes": global_attributes,
                "dimensions": {
                    name: {
                        "size": len(dimension),
                        "unlimited": dimension.isunlimited(),
                    }
                    for name, dimension in sorted(dataset.dimensions.items())
                },
                "coordinates": coordinates,
                "variables": variables,
            },
        }


def write_dataset_summary(dataset_path: str | Path, output_path: str | Path) -> Path:
    """Write a dataset summary as deterministic, strict JSON."""
    output = Path(output_path)
    summary = summarize_dataset(dataset_path)
    output.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return output


def _default_output_path(dataset_path: str | Path) -> Path:
    path = Path(dataset_path)
    return Path.cwd() / f"{path.stem}.dataset-summary.json"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Write a machine-readable NetCDF header summary as JSON."
    )
    parser.add_argument("dataset", help="NetCDF dataset to summarize")
    parser.add_argument(
        "-o",
        "--output",
        help=(
            "output JSON path (default: <dataset-stem>.dataset-summary.json in "
            "the current directory)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the dataset-summary command."""
    args = build_parser().parse_args(argv)
    output = args.output or _default_output_path(args.dataset)
    written = write_dataset_summary(args.dataset, output)
    print(f"Wrote dataset summary: {written}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
