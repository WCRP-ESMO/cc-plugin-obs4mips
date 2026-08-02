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

## Controlled vocabularies

Controlled-vocabulary snapshots used at runtime are stored under
`cc_plugin_obs4mips/cv_data/<version>/`. The ODS 2.6.1 frequency vocabulary is
derived from the `drs_name` fields in the official
[`WCRP-ESMO/obs4MIPs_CVs`](https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/frequency)
frequency terms. Each snapshot records its upstream commit so validation remains
reproducible even while the upstream vocabulary evolves.
