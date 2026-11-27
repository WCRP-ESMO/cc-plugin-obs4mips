# Obs4MIPs Compliance Checker
This is a Python tool that checks if a NetCDF dataset complies with the most recent Obs4MIPs Data Specifications (ODS). It is a plug-in for the [IOOS Compliance Checker](https://github.com/ioos/compliance-checker). The tool evaluates a NetCDF file against ODS specifications and generates a report detailing optional changes, recommended changes, and required changes. The report must not have any required changes before NetCDFs can be accepted and submitted to ESGF under the Obs4MIPs project.

## Installation
To install the Obs4MIPs Compliance Checker, create a virtual environment (we recommend [installing](https://docs.astral.sh/uv/getting-started/installation/) and using the `uv` Python package manager) and install the package using pip:

```bash
uv venv
uv pip install cc-plugin-obs4mips
```

Or if you use a different virtual environment manager, activate your environment and install the package using pip:

```bash
pip install cc-plugin-obs4mips
```

See the [IOOS Compliance Checker documentation](https://ioos.github.io/compliance-checker/) for additional installation notes.

## Usage
To check a NetCDF dataset for compliance with the Obs4MIPs data standard, activate your environment (`source .venv/bin/activate` if using `uv`), and run the following command:

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

## Update the CVs

If the CVs repository main branch has changed, the `cc-plugin-obs4mips` tool will synchronize with the latest version of the CVs, ensuring that the compliance checker uses the most up-to-date controlled vocabularies. To update the CVs, just update the tool:

```bash
uv pip install --upgrade cc-plugin-obs4mips
```

Or simply use `pip install --upgrade cc-plugin-obs4mips` if you are not using the `uv` package manager.
