# obs4MIPs Compliance Checker
This is a Python tool that checks if a NetCDF dataset complies with the most recent Obs4MIPs Data Specifications (ODS). It is a plug-in for the [IOOS Compliance Checker](https://github.com/ioos/compliance-checker). The tool evaluates a NetCDF file against ODS specifications and generates a report detailing optional changes, recommended changes, and required changes. The report must not have any required changes before NetCDFs can be accepted and submitted to ESGF under the Obs4MIPs project.

## Installation
To install the obs4MIPs Compliance Checker, create a virtual environment (we recommend using `uv`) and install the package using pip:

```bash
uv venv
uv pip install cc-plugin-obs4mips
```

See the [IOOS Compliance Checker documentation](https://ioos.github.io/compliance-checker/) for additional installation notes.

## Usage
To check a NetCDF dataset for compliance with the obs4MIPs data standard, run the following command:

```bash
compliance-checker -t obs4mips [dataset.nc]
```

Replace `[dataset.nc]` with the path to your NetCDF dataset. The tool will output a report indicating whether the dataset is compliant with the obs4MIPs data standard and will list any issues found. See the [IOOS Compliance Checker documentation](https://ioos.github.io/compliance-checker/) for additional usage notes and options.

## Tool Artifacts

You can export the report as a text file to share with others:

```bash
compliance-checker \
  -t obs4mips \
  -f text \
  -o compliance-report.txt \
  [dataset.nc]
```

## Where the rules live

The ODS are maintained in the [`WCRP-ESMO/obs4MIPs_CVs`](https://github.com/WCRP-ESMO/obs4MIPs_CVs) repository, not within the QC tool. The plugin ships a copy of that repository (term directories, YAML specs, `global_attributes.json`) in `cc_plugin_obs4mips/data/<ods_version>/`, so it works offline, e.g. on web-protected machines. `data/<ods_version>/SOURCE.json` records the commit and the CVs release (`cv_version`) the copy comes from. From it the checker reads:

- every global attribute with its requirement level, condition, separator and allowed values or patterns
- the file name and directory templates (from `drs_specs.yaml`)

| To change... | Edit |
|---|---|
| an attribute, requirement level, allowed value or DRS part | the CVs repo; the sync (below) brings it here |
| a format a regex cannot express (UUID, DOI, URL, character sets): a capitalised class attribute | `checks/base.py` (shared) or `checks/ods_<version>.py` |
| how a check works | `checks/base.py` (generic: presence, CV membership, DRS) or `checks/ods_<version>.py` (attribute-specific) |
| support a new ODS release | [docs/development/new_ods_version.md](docs/development/new_ods_version.md) |

`data/` is generated; do not edit it by hand (CI checks it against `SOURCE.json`).

### Using other CVs than the shipped ones

```bash
cc-plugin-obs4mips status                       # which CVs are in use
cc-plugin-obs4mips update                       # latest main of obs4MIPs_CVs
cc-plugin-obs4mips update some-branch           # a branch, tag or commit
cc-plugin-obs4mips update --from /path/to/obs4MIPs_CVs   # a local checkout or .tar.gz (offline)
cc-plugin-obs4mips revert                       # back to the shipped CVs
```

The updated copy is stored per ODS version in your user data directory (set `OBS4MIPS_CV_DIR` to move it). CVs for an ODS version this install has no checker for are stored with a warning.

### Keeping the shipped CVs current

`.github/workflows/sync-cvs.yml` runs daily: it runs `scripts/sync_cvs.py` (follows `main` of the CVs repo), tests the result and opens a PR against `dev`. Merging `dev` into `main` releases a new version (`release.yml`, python-semantic-release from conventional commits; the sync PR uses `fix(data):`). By hand: `uv run python scripts/sync_cvs.py [--ref REF] [--source /path/to/obs4MIPs_CVs]`, then `uv run pytest -q`. `--check` fails if `data/` differs from the commit in `SOURCE.json`.

### Code layout

- `cv_sync.py`: reads a CVs snapshot into the bundle; `update`, `revert`, `status`. `cli.py` is the `cc-plugin-obs4mips` command.
- `checks/`: `base.py` (`Obs4MipsCheckBase`, shared logic), `ods_2_6.py` (`Obs4MipsCheck_2_6`), `_helpers.py` (pure functions). One subclass per ODS version.
- `scripts/sync_cvs.py`: writes the shipped `data/` from the CVs repo.
- `tests/conftest.py`: `GOOD_VALUES` describes a valid file; tests change one value and check the report.

Companion-file checks (`aux_uncertainty_id`, `external_variables`) are not implemented yet; the design notes are in `docs/planning/companion_files.md`. Plans for CVs versioning and update notifications are in `docs/planning/cvs_caching.md`.
