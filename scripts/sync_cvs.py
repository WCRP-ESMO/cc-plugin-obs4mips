#!/usr/bin/env python3
"""Generate packaged CV snapshots from a pinned obs4MIPs_CVs revision."""

from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY_ROOT / "cv_sources.json"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "cc_plugin_obs4mips" / "cv_data"


class SyncError(RuntimeError):
    """Raised when a CV source cannot safely produce a snapshot."""


def load_config(path: Path, ods_version: str) -> dict[str, Any]:
    """Load and minimally validate one ODS version's source configuration."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        config = payload["versions"][ods_version]
    except FileNotFoundError as error:
        raise SyncError(f"CV source configuration not found: {path}") from error
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SyncError(
            f"Invalid CV source configuration for ODS {ods_version}: {path}"
        ) from error

    repository = config.get("repository")
    source_ref = config.get("ref")
    tables = config.get("tables")
    if not isinstance(repository, str) or not repository.startswith(
        "https://github.com/"
    ):
        raise SyncError("'repository' must be an https://github.com URL")
    if not isinstance(source_ref, str) or not source_ref:
        raise SyncError("'ref' must be a non-empty tag or commit")
    if not isinstance(tables, dict) or not tables:
        raise SyncError("'tables' must be a non-empty object")
    return config


def _github_archive_url(repository: str, source_ref: str) -> str:
    """Return GitHub's tar archive URL for a repository and ref."""
    repository_path = repository.removeprefix("https://github.com/").removesuffix(
        ".git"
    )
    if repository_path.count("/") != 1:
        raise SyncError(f"Unsupported GitHub repository URL: {repository}")
    return f"https://codeload.github.com/{repository_path}/tar.gz/{source_ref}"


def download_source(repository: str, source_ref: str, destination: Path) -> Path:
    """Download and safely unpack a pinned GitHub source archive."""
    url = _github_archive_url(repository, source_ref)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            archive = response.read()
    except (urllib.error.URLError, TimeoutError) as error:
        raise SyncError(f"Could not download CV source {url}: {error}") from error

    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            members = tar.getmembers()
            roots = {Path(member.name).parts[0] for member in members if member.name}
            if len(roots) != 1:
                raise SyncError(
                    "CV source archive must contain exactly one root directory"
                )
            for member in members:
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise SyncError(f"Unsafe path in CV source archive: {member.name}")
                if member.issym() or member.islnk():
                    raise SyncError(
                        f"Links are not allowed in CV source archive: {member.name}"
                    )
            if sys.version_info >= (3, 12):
                tar.extractall(destination, filter="data")
            else:  # pragma: no cover - Python 3.10/3.11 compatibility
                tar.extractall(destination)
    except (tarfile.TarError, OSError) as error:
        raise SyncError(f"Could not unpack CV source {url}: {error}") from error

    return destination / roots.pop()


def read_table(
    source_root: Path,
    table: str,
    value_field: str,
    *,
    fallback_field: str | None = None,
    term_types: list[str] | None = None,
) -> list[str]:
    """Validate an upstream collection and extract its checkable values."""
    table_root = source_root / table
    if not table_root.is_dir():
        raise SyncError(f"CV collection does not exist: {table_root}")

    values: list[str] = []
    term_files = sorted(
        path for path in table_root.glob("*.json") if not path.name.startswith("000_")
    )
    if not term_files:
        raise SyncError(f"CV collection contains no term JSON files: {table_root}")

    for term_file in term_files:
        try:
            term = json.loads(term_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise SyncError(f"Invalid JSON in {term_file}: {error}") from error
        if not isinstance(term, dict):
            raise SyncError(f"CV term must be a JSON object: {term_file}")

        term_id = term.get("id")
        term_type = term.get("type")
        value = term.get(value_field)
        if (not isinstance(value, str) or not value) and fallback_field:
            value = term.get(fallback_field)
        if not isinstance(term_id, str) or not term_id:
            raise SyncError(f"CV term has no non-empty string 'id': {term_file}")
        expected_types = term_types or [table]
        if term_type not in expected_types:
            raise SyncError(
                f"CV term {term_id!r} has type {term_type!r}; expected one of "
                f"{expected_types!r}"
            )
        if not isinstance(value, str) or not value:
            expected_fields = repr(value_field)
            if fallback_field:
                expected_fields += f" or fallback {fallback_field!r}"
            raise SyncError(
                f"CV term {term_id!r} has no non-empty string {expected_fields}"
            )
        values.append(value)

    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise SyncError(
            f"CV collection {table!r} has duplicate extracted values: "
            + ", ".join(duplicates)
        )
    return sorted(values)


def render_snapshot(
    *,
    ods_version: str,
    table: str,
    repository: str,
    source_ref: str,
    value_field: str,
    fallback_field: str | None,
    values: list[str],
) -> str:
    """Render a stable, reviewable snapshot document."""
    payload = {
        "schema_version": 1,
        "cv": table,
        "cv_version": ods_version,
        "source": f"{repository}/tree/{source_ref}/{table}",
        "source_ref": source_ref,
        "value_field": value_field,
        "values": values,
    }
    if fallback_field:
        payload["fallback_field"] = fallback_field
        payload["values"] = payload.pop("values")
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def sync(
    *,
    ods_version: str,
    config_path: Path,
    output_root: Path,
    source_root: Path | None,
    source_ref_override: str | None,
    selected_tables: list[str] | None,
    check: bool,
) -> list[Path]:
    """Generate or check configured CV snapshots and return their paths."""
    config = load_config(config_path, ods_version)
    repository = config["repository"]
    source_ref = source_ref_override or config["ref"]
    tables = config["tables"]

    if selected_tables:
        unknown = sorted(set(selected_tables) - set(tables))
        if unknown:
            raise SyncError("Unconfigured CV table(s): " + ", ".join(unknown))
        table_names = selected_tables
    else:
        table_names = sorted(tables)

    with tempfile.TemporaryDirectory(prefix="obs4mips-cvs-") as temp_dir:
        actual_source_root = source_root
        if actual_source_root is None:
            actual_source_root = download_source(repository, source_ref, Path(temp_dir))

        changed: list[Path] = []
        for table in table_names:
            table_config = tables[table]
            value_field = table_config.get("value_field")
            if not isinstance(value_field, str) or not value_field:
                raise SyncError(f"Table {table!r} has no valid 'value_field'")
            fallback_field = table_config.get("fallback_field")
            if fallback_field is not None and (
                not isinstance(fallback_field, str) or not fallback_field
            ):
                raise SyncError(f"Table {table!r} has no valid 'fallback_field'")
            term_types = table_config.get("term_types")
            if term_types is not None and (
                not isinstance(term_types, list)
                or not term_types
                or not all(isinstance(item, str) and item for item in term_types)
            ):
                raise SyncError(f"Table {table!r} has no valid 'term_types'")
            values = read_table(
                actual_source_root,
                table,
                value_field,
                fallback_field=fallback_field,
                term_types=term_types,
            )
            rendered = render_snapshot(
                ods_version=ods_version,
                table=table,
                repository=repository,
                source_ref=source_ref,
                value_field=value_field,
                fallback_field=fallback_field,
                values=values,
            )
            output_path = output_root / ods_version / f"{table}.json"
            current = (
                output_path.read_text(encoding="utf-8")
                if output_path.exists()
                else None
            )
            if current != rendered:
                changed.append(output_path)
                if not check:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(rendered, encoding="utf-8")
        return changed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ods-version", default="2.6.1")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--source",
        type=Path,
        help="use an existing obs4MIPs_CVs checkout instead of downloading",
    )
    parser.add_argument(
        "--ref",
        dest="source_ref",
        help="override the pinned source ref (the output records the override)",
    )
    parser.add_argument(
        "--table",
        action="append",
        dest="tables",
        help="sync one configured table; may be supplied more than once",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale snapshots without modifying them",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        changed = sync(
            ods_version=args.ods_version,
            config_path=args.config,
            output_root=args.output_root,
            source_root=args.source,
            source_ref_override=args.source_ref,
            selected_tables=args.tables,
            check=args.check,
        )
    except SyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.check and changed:
        for path in changed:
            print(f"stale: {path}", file=sys.stderr)
        return 1
    action = "checked" if args.check else "updated"
    print(f"{action} {len(changed) if not args.check else 0} CV snapshot(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
