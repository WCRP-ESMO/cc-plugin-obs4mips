#!/usr/bin/env python3
"""Build cc_plugin_obs4mips/cv_data/obs4mips.json from a pinned obs4MIPs_CVs revision.

The bundle is the only place where the checker gets ODS facts from. It holds:
  - every entry of global_attributes.json (requirement, conditional, separator, ...)
  - for attributes backed by a CV: `allowed` (values of the CV key) and/or `patterns`
    (regex terms)
  - the DRS part lists from drs_specs.yaml

To update: change `ref` in cv_sources.json, run this script, run the tests.
Never edit the bundle by hand.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import yaml  # only needed here, not by the checker at runtime

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "cv_sources.json"
BUNDLE = ROOT / "cc_plugin_obs4mips" / "cv_data" / "obs4mips.json"


def download(repository: str, ref: str, destination: Path) -> Path:
    """Download a GitHub tarball of `ref` and return the extracted repo directory."""
    path = repository.removeprefix("https://github.com/").removesuffix(".git")
    url = f"https://codeload.github.com/{path}/tar.gz/{ref}"
    with urllib.request.urlopen(url, timeout=60) as response:
        archive = response.read()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if Path(member.name).is_absolute() or ".." in parts or member.issym() or member.islnk():
                raise SystemExit(f"unsafe path in archive: {member.name}")
        if sys.version_info >= (3, 12):
            tar.extractall(destination, filter="data")
        else:
            tar.extractall(destination)
    (root,) = [p for p in destination.iterdir() if p.is_dir()]
    return root


def read_table(cvs: Path, table: str, key: str | None) -> dict:
    """Read one CV directory: regex terms give `patterns`, other terms give `allowed`.

    `key` is the term field holding the value (drs_name, description, ...). It is null
    for free-text tables, which then have no `allowed` list.
    """
    if not (cvs / table).is_dir():
        raise SystemExit(f"CV directory not found: {cvs / table}")
    allowed, patterns, skipped = [], [], 0
    for file in sorted((cvs / table).glob("*.json")):
        term = json.loads(file.read_text(encoding="utf-8"))
        if "regex" in term:
            patterns.append(term["regex"])
        elif key and term.get(key):
            allowed.append(term[key])
        elif key:
            skipped += 1  # e.g. the empty variable_id stubs kept in the CVs; they never match
    if skipped:
        print(f"note: {table}: skipped {skipped} term(s) with no {key!r}", file=sys.stderr)
    result = {}
    if allowed:
        result["allowed"] = sorted(allowed)
    if patterns:
        result["patterns"] = patterns
    return result


def build_bundle(cvs: Path, ref: str) -> dict:
    spec = json.loads((cvs / "global_attributes.json").read_text(encoding="utf-8"))
    attributes = {}
    for name, attr in spec["global_attributes"].items():
        attributes[name] = dict(attr)
        if attr["cv"]:
            attributes[name].update(read_table(cvs, attr["cv"]["table"], attr["cv"]["key"]))

    drs_specs = yaml.safe_load((cvs / "drs_specs.yaml").read_text(encoding="utf-8"))
    drs = {}
    for name in ("directory", "file_name", "dataset_id"):
        drs[name] = {
            "separator": drs_specs[name]["separator"],
            "parts": [
                {"name": p["source_collection"], "required": p["is_required"]}
                for p in drs_specs[name]["parts"]
            ],
        }
    drs["file_name"]["extension"] = drs_specs["file_name"]["properties"]["extension"]

    return {
        "ods_version": spec["ods_version"],
        "cvs_ref": ref,
        "attributes": attributes,
        "drs": drs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="use a local obs4MIPs_CVs checkout instead of downloading")
    parser.add_argument("--ref", help="override the pinned ref (recorded in the bundle)")
    parser.add_argument("--check", action="store_true", help="fail if the bundle is stale; write nothing")
    args = parser.parse_args(argv)

    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    ref = args.ref or sources["ref"]
    with tempfile.TemporaryDirectory(prefix="obs4mips-cvs-") as tmp:
        cvs = args.source or download(sources["repository"], ref, Path(tmp))
        text = json.dumps(build_bundle(cvs, ref), indent=2) + "\n"

    current = BUNDLE.read_text(encoding="utf-8") if BUNDLE.exists() else None
    if args.check:
        if current != text:
            print(f"stale: {BUNDLE}", file=sys.stderr)
            return 1
        return 0
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE.write_text(text, encoding="utf-8")
    print(f"wrote {BUNDLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
