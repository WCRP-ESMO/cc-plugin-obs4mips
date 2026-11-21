"""The `cc-plugin-obs4mips` command: update, revert or show the CVs the checker uses."""

from __future__ import annotations

import argparse
from pathlib import Path

from cc_plugin_obs4mips import cv_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cc-plugin-obs4mips",
        description="Manage the obs4MIPs CVs used by the checker (it ships with a copy).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    update = commands.add_parser(
        "update", help="use other CVs than the shipped ones (default: the latest main)"
    )
    update.add_argument(
        "ref",
        nargs="?",
        default=cv_sync.DEFAULT_REF,
        help=f"branch, tag or commit of the CVs repository (default: {cv_sync.DEFAULT_REF})",
    )
    update.add_argument("--repository", default=cv_sync.DEFAULT_REPOSITORY)
    update.add_argument(
        "--from",
        dest="from_path",
        type=Path,
        help="a local checkout or .tar.gz of the CVs repository (works offline)",
    )

    revert = commands.add_parser("revert", help="go back to the shipped CVs")
    revert.add_argument("--ods", help="only this ODS version (default: all)")

    commands.add_parser("status", help="show which CVs are in use")

    args = parser.parse_args(argv)
    if args.command == "update":
        print(cv_sync.update(args.repository, args.ref, args.from_path))
    elif args.command == "revert":
        print(cv_sync.revert(args.ods))
    else:
        print(cv_sync.status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
