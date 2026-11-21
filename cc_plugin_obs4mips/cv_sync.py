"""
Build, store and load the CVs bundle (the only place the checker gets ODS facts from).

The bundle holds:
  - every entry of global_attributes.json (requirement, conditional, separator, ...)
  - for attributes with a CV: `allowed` (registered CV terms) and/or `patterns`
    (regex-based terms)
  - the DRS part lists from drs_specs.yaml

Two copies can exist:
  - the packaged one, `cv_data/obs4mips.json`, written by `scripts/sync_cvs.py` from the
    ref pinned in `cv_sources.json` (developers; never edit by hand);
  - a user one, written by the `obs4mips-update-cvs` command into the user's data
    directory. It wins over the packaged one when it is valid and for the same ODS
    version, so users can update the CVs without reinstalling the tool.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import tempfile
import urllib.request
from importlib.resources import files
from pathlib import Path

from platformdirs import user_data_path

DEFAULT_REPOSITORY = "https://github.com/WCRP-ESMO/obs4MIPs_CVs"
DEFAULT_REF = "main"  # branch or tag or commit that `obs4mips-update-cvs` follows
USER_BUNDLE_ENV = (
    "OBS4MIPS_CV_BUNDLE"  # full path of the user bundle; overrides the default
)


# Building the bundle from an obs4MIPs_CVs checkout ------------------------------------


def _github_path(repository: str) -> str:
    return repository.removeprefix("https://github.com/").removesuffix(".git")


def resolve_ref(repository: str, ref: str) -> str:
    """Return the commit SHA a branch, tag or SHA points to (GitHub API)."""
    url = f"https://api.github.com/repos/{_github_path(repository)}/commits/{ref}"
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github.sha"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode().strip()


def download(repository: str, ref: str, destination: Path) -> Path:
    """Download a GitHub tarball of `ref` and return the extracted repo directory."""
    url = f"https://codeload.github.com/{_github_path(repository)}/tar.gz/{ref}"
    with urllib.request.urlopen(url, timeout=60) as response:
        archive = response.read()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if (
                Path(member.name).is_absolute()
                or ".." in parts
                or member.issym()
                or member.islnk()
            ):
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
            skipped += (
                1  # e.g. the empty variable_id stubs kept in the CVs; they never match
            )
    if skipped:
        print(
            f"note: {table}: skipped {skipped} term(s) with no {key!r}", file=sys.stderr
        )
    result = {}
    if allowed:
        result["allowed"] = sorted(allowed)
    if patterns:
        result["patterns"] = patterns
    return result


def build_bundle(cvs: Path, ref: str) -> dict:
    import yaml  # imported here so that running the checker does not need it

    spec = json.loads((cvs / "global_attributes.json").read_text(encoding="utf-8"))
    attributes = {}
    for name, attr in spec["global_attributes"].items():
        attributes[name] = dict(attr)
        if attr["cv"]:
            attributes[name].update(
                read_table(cvs, attr["cv"]["table"], attr["cv"]["key"])
            )

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


def bundle_text(bundle: dict) -> str:
    return json.dumps(bundle, indent=2) + "\n"


# Where the bundles live, and which one is used ----------------------------------------


def packaged_bundle_text() -> str:
    return (
        files("cc_plugin_obs4mips")
        .joinpath("cv_data/obs4mips.json")
        .read_text(encoding="utf-8")
    )


def user_bundle_path() -> Path:
    if env := os.environ.get(USER_BUNDLE_ENV):
        return Path(env)
    return (
        user_data_path("cc-plugin-obs4mips", appauthor=False, roaming=True)
        / "obs4mips.json"
    )


def load_bundle() -> dict:
    """Return the user bundle when it is valid and for the same ODS version, else the packaged one."""
    packaged = json.loads(packaged_bundle_text())
    path = user_bundle_path()
    if not path.is_file():
        return packaged
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
        missing = {"ods_version", "cvs_ref", "attributes", "drs"} - set(user)
        if missing:
            raise ValueError(f"missing keys {sorted(missing)}")
        if user["ods_version"] != packaged["ods_version"]:
            raise ValueError(
                f"it is for ODS {user['ods_version']} but this install checks ODS {packaged['ods_version']}"
            )
    except (OSError, ValueError) as error:  # json.JSONDecodeError is a ValueError
        print(
            f"cc-plugin-obs4mips: ignoring updated CVs in {path} ({error}); using the packaged CVs. "
            "Run 'obs4mips-update-cvs --reset' to remove the file.",
            file=sys.stderr,
        )
        return packaged
    return user


# ---------------------------------------------------------------------------
# The `obs4mips-update-cvs` command
# ---------------------------------------------------------------------------


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".obs4mips-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def update_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="obs4mips-update-cvs",
        description="Download the latest obs4MIPs CVs and use them instead of the ones packaged with this tool.",
    )
    parser.add_argument(
        "--repository", default=DEFAULT_REPOSITORY, help="GitHub repository of the CVs"
    )
    parser.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=f"branch, tag or commit to follow (default: {DEFAULT_REF})",
    )
    parser.add_argument(
        "--status", action="store_true", help="show which CVs are in use and exit"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the updated CVs and go back to the packaged ones",
    )
    args = parser.parse_args(argv)

    path = user_bundle_path()
    packaged = json.loads(packaged_bundle_text())

    if args.status:
        in_use = load_bundle()
        source = "packaged" if in_use == packaged else "updated"
        print(
            f"in use: {source} CVs, ODS {in_use['ods_version']}, commit {in_use['cvs_ref']}"
        )
        print(f"packaged: commit {packaged['cvs_ref']}")
        print(f"updated copy: {path if path.is_file() else 'none'}")
        return 0

    if args.reset:
        path.unlink(missing_ok=True)
        print(f"removed {path}; using the packaged CVs (commit {packaged['cvs_ref']})")
        return 0

    try:
        sha = resolve_ref(args.repository, args.ref)
        with tempfile.TemporaryDirectory(prefix="obs4mips-cvs-") as tmp:
            cvs = download(args.repository, sha, Path(tmp))
            bundle = build_bundle(cvs, sha)
    except OSError as error:  # urllib.error.URLError is an OSError
        print(
            f"could not download the CVs ({args.ref} of {args.repository}): {error}",
            file=sys.stderr,
        )
        return 1
    except (KeyError, ValueError, SystemExit) as error:
        print(
            f"the CVs at {args.ref} could not be read ({error!r}); nothing changed",
            file=sys.stderr,
        )
        return 1

    if bundle["ods_version"] != packaged["ods_version"]:
        print(
            f"the CVs at {args.ref} are for ODS {bundle['ods_version']} but this install checks "
            f"ODS {packaged['ods_version']}. Upgrade cc-plugin-obs4mips instead.",
            file=sys.stderr,
        )
        return 1

    previous = (
        json.loads(path.read_text(encoding="utf-8")) if path.is_file() else packaged
    )
    if bundle_text(previous) == bundle_text(bundle):
        print(f"already up to date (commit {sha})")
        return 0
    _write_atomic(path, bundle_text(bundle))
    print(
        f"updated CVs: {previous['cvs_ref'][:7]} -> {sha[:7]} ({args.ref}); wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(update_main())
