#!/usr/bin/env python3
"""Build cc_plugin_obs4mips/cv_data/obs4mips.json from a pinned obs4MIPs_CVs revision.

The bundle is the only place where the checker gets ODS facts from. It holds:
  - every entry of global_attributes.json (requirement, conditional, separator, ...)
  - for attributes backed by a CV: `allowed` (values of the CV key) and/or `patterns`
    (regex terms)
  - the DRS part lists from drs_specs.yaml

To update: change `ref` in cv_sources.json, run this script, run the tests.
Never edit the bundle by hand. The logic lives in cc_plugin_obs4mips/cv_sync.py, which
also powers the user-facing `obs4mips-update-cvs` command.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from cc_plugin_obs4mips.cv_sync import build_bundle, bundle_text, download, read_table  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "cv_sources.json"
BUNDLE = ROOT / "cc_plugin_obs4mips" / "cv_data" / "obs4mips.json"


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
        text = bundle_text(build_bundle(cvs, ref))

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
