# obs4MIPs Compliance Checker
This is a Python tool that checks if a NetCDF dataset complies with the obs4MIPs data standard (ODS) version 2.6.1. It is a plug-in for the [IOOS Compliance Checker](https://github.com/ioos/compliance-checker). The tool evaluates the dataset against the ODS specifications and generates a report indicating whether the dataset is compliant and lists any issues found. This step is necessary before adding the dataset information to the [obs4MIPs_CVs repository](https://github.com/WCRP-ESMO/obs4MIPs-cmor-tables) and before submitting the dataset to ESGF.

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

To select the ODS release explicitly, use:

```bash
compliance-checker -t obs4mips:2.6.1 [dataset.nc]
```

## Issue submission artifacts

Create a human-readable Compliance Checker report and a separate machine-readable
JSON summary of the NetCDF header for attachment to an issue:

```bash
compliance-checker \
  -t obs4mips:2.6.1 \
  -f text \
  -o compliance-report.txt \
  [dataset.nc]

obs4mips-dataset-summary \
  -o dataset-summary.json \
  [dataset.nc]
```

The dataset summary is a parseable equivalent of `ncdump -h`. It includes the
filename and file format, every global attribute, dimensions and unlimited status,
coordinate metadata, and data-variable metadata. It deliberately excludes array
values and the submitter's absolute local path. The top-level `schema_version`
field provides a stable contract for scripts that process issue attachments.

When a submitted value is not registered in a packaged controlled vocabulary,
the text report asks the submitter to check for an appropriate existing term and
shows similar registered values. The JSON summary records the same values under
`cv_update_candidates`, along with the target collection, membership field,
pinned CV source, and pointers to the dataset metadata needed by an automated CV
repository updater.

## Controlled vocabularies

Controlled-vocabulary snapshots used at runtime are stored under
`cc_plugin_obs4mips/cv_data/<version>/`. The ODS 2.6.1 snapshots contain every
collection in the official
[`WCRP-ESMO/obs4MIPs_CVs`](https://github.com/WCRP-ESMO/obs4MIPs_CVs) repository.
Each snapshot records its upstream commit and the field used for membership checks,
so validation remains reproducible even while the upstream vocabulary evolves.

The snapshots are generated files; do not edit them manually. Source repositories,
pinned revisions, and table mappings are declared in `cv_sources.json`. To update
all configured tables after deliberately changing a pinned revision, run:

```bash
python scripts/sync_cvs.py --ods-version 2.6.1
```

The command downloads that exact revision, validates each upstream term, extracts
the configured value field, and writes a deterministic package snapshot. To use an
existing checkout without network access, pass `--source /path/to/obs4MIPs_CVs`.

CI and local verification can detect an out-of-date generated snapshot without
changing files:

```bash
python scripts/sync_cvs.py --ods-version 2.6.1 --check
```
