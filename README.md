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

The ODS are maintained in the [`WCRP-ESMO/obs4MIPs_CVs`](https://github.com/WCRP-ESMO/obs4MIPs_CVs) repository, not within the QC tool. This plugin reads them from one generated file, `cc_plugin_obs4mips/cv_data/obs4mips.json`, which contains:

- every global attribute with its requirement level, condition, separator and allowed values or patterns (from `global_attributes.json` and the CV directories)
- the file name and directory templates (from `drs_specs.yaml`)
- the CVs commit it was built from (`cvs_ref`)

| To change... | Edit |
|---|---|
| an attribute, requirement level, allowed value or DRS part | the CVs repo, then re-sync (below) |
| a format a regex cannot express (UUID, DOI, URL), or whether a CV mismatch is an error or a warning | `cc_plugin_obs4mips/specs.py` |
| how a check works (file name, directory, site attributes, ...) | `cc_plugin_obs4mips/checks.py` |

`obs4mips.json` is generated; do not edit it by hand.

### Updating for new CVs or a new ODS release

1. Merge the change in the CVs repo.
2. Set `ref` in `cv_sources.json` to the new commit.
3. Run `uv run python scripts/sync_cvs.py` (add `--source /path/to/obs4MIPs_CVs` to use a local checkout).
4. Run `uv run pytest -q` and commit the regenerated `obs4mips.json`.

CI runs `python scripts/sync_cvs.py --check`, which fails if `obs4mips.json` does not match the pinned commit.

### Code layout

- `checks.py`: one checker class. `check_global_attributes_present` and `check_global_attribute_values` loop over the bundle; `check_filename` and `check_directory_structure` build their templates from the DRS in the bundle. The remaining checks need the file itself or several attributes at once.
- `specs.py`: loads the bundle and holds the few ODS facts the CVs cannot express.
- `scripts/sync_cvs.py`: builds the bundle.
- `tests/conftest.py`: `GOOD_VALUES` describes a valid file; tests change one value and check the report.

Companion-file checks (`aux_uncertainty_id`, `external_variables`) are not implemented yet; the design notes are in `docs/planning/companion_files.md`. Plans for CVs versioning and update notifications are in `docs/planning/cvs_caching.md`.
