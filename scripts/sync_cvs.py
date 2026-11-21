#!/usr/bin/env python3
"""Write the shipped CVs, cc_plugin_obs4mips/data/<ods_version>/, from obs4MIPs_CVs.

  sync_cvs.py                  follow `main` of the CVs repository
  sync_cvs.py --ref REF        another branch, tag or commit (for example to patch an old ODS)
  sync_cvs.py --source PATH    a local checkout instead of downloading
  sync_cvs.py --check          fail if the shipped CVs differ from the commit in SOURCE.json

The data is generated: never edit it by hand (CI runs --check).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

from cc_plugin_obs4mips import cv_sync


def tree_hashes(directory: Path) -> dict[str, str]:
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=cv_sync.DEFAULT_REPOSITORY)
    parser.add_argument("--ref", default=cv_sync.DEFAULT_REF)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="obs4mips-sync-") as tmp:
        tmp = Path(tmp)
        if args.check:
            failures = 0
            for ods in cv_sync.shipped_versions():
                shipped = cv_sync.shipped_root() / ods
                source = cv_sync.read_source(shipped)
                cvs = cv_sync.download(source["repository"], source["ref"], tmp / ods)
                cv_sync.snapshot(cvs, tmp / f"expected-{ods}", source["repository"], source["ref"])
                if tree_hashes(shipped) != tree_hashes(tmp / f"expected-{ods}"):
                    print(f"stale or hand-edited: {shipped}", file=sys.stderr)
                    failures += 1
            return 1 if failures else 0

        if args.source:
            cvs, ref = args.source, f"local:{args.source.name}"
        else:
            ref = cv_sync.resolve_ref(args.repository, args.ref)
            cvs = cv_sync.download(args.repository, ref, tmp)
        destination = cv_sync.shipped_root() / cv_sync.ods_version_of(cvs)
        cv_sync.snapshot(cvs, destination, args.repository, ref)
        print(f"wrote {destination} (commit {ref[:7]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
