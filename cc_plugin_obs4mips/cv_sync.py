"""
Where the checker gets ODS facts from: a snapshot of the obs4MIPs_CVs repository.

Two kinds of snapshot exist, one directory per ODS version (named like the
`ods_version` of `global_attributes.json`, e.g. `2.6`):
  - the shipped one, `cc_plugin_obs4mips/data/<ods_version>/`, written by
    `scripts/sync_cvs.py` (developers and CI; never edit it by hand);
  - an updated one, written by `cc-plugin-obs4mips update` into the user's data directory.
    It wins over the shipped one until `cc-plugin-obs4mips revert` removes it.

A snapshot holds the term directories, the `*.yaml` specs, `global_attributes.json` and a
`SOURCE.json` saying which commit it is. `load_bundle()` reads a snapshot into the dict
that `checks.py` uses (every global attribute plus its allowed terms, and the DRS).
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from importlib.resources import files
from pathlib import Path

from platformdirs import user_data_path

DEFAULT_REPOSITORY = "https://github.com/WCRP-ESMO/obs4MIPs_CVs"
DEFAULT_REF = "main"  # branch, tag or commit that `update` and the sync follow
USER_DIR_ENV = "OBS4MIPS_CV_DIR"  # root of the updated snapshots; overrides the default
GENERATED_BY = "scripts/sync_cvs.py or `cc-plugin-obs4mips update`; do not edit by hand"


# Getting a snapshot ---------------------------------------------------------------------


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
    """Download the GitHub tarball of `ref` (pooch) and return the extracted repo directory."""
    import pooch  # imported here so that running the checker does not need it

    pooch.get_logger().setLevel("WARNING")  # no download chatter
    url = f"https://codeload.github.com/{_github_path(repository)}/tar.gz/{ref}"
    pooch.retrieve(
        url,
        known_hash=None,
        path=destination,
        fname="cvs.tar.gz",
        processor=pooch.Untar(),
        progressbar=False,
    )
    (root,) = [p for p in (destination / "cvs.tar.gz.untar").iterdir() if p.is_dir()]
    return root


def read_source(directory: Path) -> dict:
    return json.loads((directory / "SOURCE.json").read_text(encoding="utf-8"))


def cv_version_of(cvs: Path) -> str | None:
    """`cv_version` of esgvoc_manifest.yaml: the CVs release (not the ODS version)."""
    import yaml

    manifest = cvs / "esgvoc_manifest.yaml"
    if not manifest.is_file():
        return None
    version = yaml.safe_load(manifest.read_text(encoding="utf-8")).get("cv_version")
    return None if version is None else str(version)


def ods_version_of(cvs: Path) -> str:
    return json.loads((cvs / "global_attributes.json").read_text(encoding="utf-8"))[
        "ods_version"
    ]


def snapshot(cvs: Path, destination: Path, repository: str, ref: str) -> None:
    """Copy what the checker needs from a CVs checkout into `destination` (replaced)."""
    staging = destination.with_name(destination.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for file in sorted([*cvs.glob("*.yaml"), *cvs.glob("global_attributes*.json")]):
            shutil.copy2(file, staging / file.name)
        for directory in sorted(p for p in cvs.iterdir() if p.is_dir()):
            if (directory / "000_context.jsonld").is_file():  # a CV directory
                shutil.copytree(directory, staging / directory.name)
        source = {
            "_generated_by": GENERATED_BY,
            "repository": repository,
            "ref": ref,
            "cv_version": cv_version_of(cvs),
        }
        (staging / "SOURCE.json").write_text(
            json.dumps(source, indent=2) + "\n", encoding="utf-8"
        )
        shutil.rmtree(destination, ignore_errors=True)
        os.replace(staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


# Reading a snapshot ---------------------------------------------------------------------


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
    import yaml

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
        "cv_version": cv_version_of(cvs),
        "attributes": attributes,
        "drs": drs,
    }


# Which snapshot is used -----------------------------------------------------------------


def _version_key(version: str) -> tuple:
    return tuple(int(part) if part.isdigit() else 0 for part in version.split("."))


def shipped_root() -> Path:
    return Path(str(files("cc_plugin_obs4mips").joinpath("data")))


def user_root() -> Path:
    if env := os.environ.get(USER_DIR_ENV):
        return Path(env)
    return user_data_path("cc-plugin-obs4mips", appauthor=False, roaming=True) / "cvs"


def shipped_versions() -> list[str]:
    """ODS versions this install carries CVs for, oldest first."""
    root = shipped_root()
    versions = [p.name for p in root.iterdir() if (p / "SOURCE.json").is_file()]
    return sorted(versions, key=_version_key)


def latest_ods_version() -> str:
    return shipped_versions()[-1]


def _read_snapshot(directory: Path) -> dict:
    return build_bundle(directory, read_source(directory)["ref"])


@functools.cache
def load_bundle(ods_version: str | None = None) -> dict:
    """The bundle of an ODS version (default: the newest): updated snapshot if valid, else shipped."""
    ods_version = ods_version or latest_ods_version()
    shipped = shipped_root() / ods_version
    if not (shipped / "SOURCE.json").is_file():
        raise SystemExit(
            f"cc-plugin-obs4mips has no CVs for ODS {ods_version} "
            f"(available: {', '.join(shipped_versions())})"
        )
    updated = user_root() / ods_version
    if (updated / "SOURCE.json").is_file():
        try:
            bundle = _read_snapshot(updated)
        except (OSError, KeyError, ValueError, SystemExit) as error:
            print(
                f"cc-plugin-obs4mips: ignoring updated CVs in {updated} ({error!r}); "
                "using the shipped CVs. Run 'cc-plugin-obs4mips revert' to remove them.",
                file=sys.stderr,
            )
        else:
            return {**bundle, "source": "updated"}
    return {**_read_snapshot(shipped), "source": "shipped"}


# Commands (used by cli.py) --------------------------------------------------------------


def update(repository: str, ref: str, from_path: Path | None = None) -> str:
    """Install a snapshot into the user's data directory; return a message."""
    try:
        with tempfile.TemporaryDirectory(prefix="obs4mips-cvs-") as tmp:
            tmp = Path(tmp)
            if from_path is None:
                sha = resolve_ref(repository, ref)
                cvs, source_ref, origin = download(repository, sha, tmp), sha, ref
            elif from_path.is_dir():
                cvs, source_ref, origin = from_path, f"local:{from_path}", str(from_path)
            else:
                shutil.unpack_archive(from_path, tmp)
                (cvs,) = [p for p in tmp.iterdir() if p.is_dir()]
                source_ref, origin = f"local:{from_path.name}", str(from_path)
            build_bundle(cvs, source_ref)  # fail now if the CVs cannot be read
            ods = ods_version_of(cvs)
            destination = user_root() / ods
            snapshot(cvs, destination, repository, source_ref)
    except OSError as error:  # urllib.error.URLError is an OSError
        raise SystemExit(f"could not get the CVs ({from_path or ref}): {error}")
    except (KeyError, ValueError, TypeError) as error:
        raise SystemExit(
            f"the CVs ({from_path or ref}) could not be read ({error!r}); nothing changed"
        )
    load_bundle.cache_clear()
    message = f"using CVs for ODS {ods} from {origin} ({source_ref[:7]}); wrote {destination}"
    if ods not in shipped_versions():
        message += (
            f"\nwarning: this install has no checker for ODS {ods} (it supports "
            f"{', '.join(shipped_versions())}); upgrade cc-plugin-obs4mips"
        )
    return message


def revert(ods_version: str | None = None) -> str:
    """Remove updated snapshots (one ODS version or all); the shipped ones are used again."""
    root = user_root()
    targets = [root / ods_version] if ods_version else sorted(root.glob("*"))
    removed = [t for t in targets if t.is_dir()]
    for target in removed:
        shutil.rmtree(target)
    load_bundle.cache_clear()
    if not removed:
        return "nothing to revert: already using the shipped CVs"
    return "reverted to the shipped CVs for ODS " + ", ".join(t.name for t in removed)


def status() -> str:
    lines = []
    for ods in shipped_versions():
        shipped = read_source(shipped_root() / ods)
        in_use = load_bundle(ods)
        lines.append(
            f"ODS {ods}: using {in_use['source']} CVs "
            f"(cv_version {in_use['cv_version']}, commit {in_use['cvs_ref'][:7]})"
        )
        lines.append(
            f"  shipped: cv_version {shipped['cv_version']}, commit {shipped['ref'][:7]}"
        )
    updated = sorted(user_root().glob("*/SOURCE.json"))
    lines.append(
        f"updated copies: {', '.join(str(p.parent) for p in updated) if updated else 'none'}"
    )
    return "\n".join(lines)
