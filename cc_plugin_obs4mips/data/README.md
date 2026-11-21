# Shipped CVs

These directories are **generated** copies of the
[obs4MIPs_CVs](https://github.com/WCRP-ESMO/obs4MIPs_CVs) repository, one per ODS version
(`<ods_version>/`). Do not edit them by hand: CI fails if they differ from the commit
recorded in `<ods_version>/SOURCE.json`.

Update them with `uv run python scripts/sync_cvs.py` (a daily workflow does this and opens a PR).
