# Update the cc-plugin-obs4mips tool

[6 November 2026]

The `cc-plugin-obs4mips` tool is a command-line plugin for `compliance-checker`, which is the validation tool used by the Earth System Grid Federation (ESGF) and other climate modeling groups to validate per-source controlled vocabulary before ingestion into ESGF data nodes. The purpose of the `cc-plugin-obs4mips` tool is for `Obs4MIPs` data preparers to validate their formatted observation NetCDF(s) before submitting to ESGF as part of the Obs4MIPs project. Data preparers should install and run this tool on their NetCDF(s) to ensure ODS compliance. The tool can output a summary of the NetCDF(s) and store/display validation results. Data preparers should fix errors reported by the tool before submitting a PR to register data in the `obs4MIPs_CVs` repository. It can also be used to validate the input JSON used by the `CMOR` tool, which formats NetCDFs to be Climate and Forecast (CF) compliant.

We designed `cc-plugin-obs4mips` so that maintaining and updating the tool is straightforward. When possible, we try to keep as much logic as possible inside the `obs4MIPs_CVs` repository, which stores the Controlled Vocabulary (CV) for the Obs4MIPs Data Specifications (ODS). The repository also stores a comprehensive accounting of ODS-defined global attributes in the `global_attributes.json`, as well as the Data Reference Syntax (DRS), which informs directory structures and file naming conventions for Obs4MIPs-compliant datasets. Any changes to the controlled vocabulary, global attributes, or DRS should be done in the `obs4MIPs_CVs` repository, and any special logic required for validation should be implemented in the plugin itself. Before updating the plugin, carefully assess if the update is necessary and whether it can be achieved by modifying the `obs4MIPs_CVs` repository alone.

The plugin working tree is simple:

```
├── cc_plugin_obs4mips
│   ├── checks
│   │   ├── base.py  # shared logic (Obs4MipsCheckBase)
│   │   ├── ods_2_6.py  # ODS 2.6 checks (Obs4MipsCheck_2_6)
│   │   └── _helpers.py
│   ├── data/<ods_version>/  # shipped CVs (generated)
│   ├── cli.py, cv_sync.py
│   ├── companion_file.py
│   └── dataset_summary.py
├── scripts
│   └── sync_cvs.py

```

The `checks/` package holds the checks. `Obs4MipsCheckBase.bundle()` returns the CVs, built from the copy of the Obs4MIPs CVs in `cc_plugin_obs4mips/data/<ods_version>/` (written by `scripts/sync_cvs.py`, or by `cc-plugin-obs4mips update` for a user).

For a new ODS release, see [new_ods_version.md](new_ods_version.md).

## Writing a check

The checks in `checks/ods_2_6.py` are the style reference; follow them when you add one. The same rules are in `AGENTS.md` for coding agents.

### Shape

- A check is a method of a check class (`Obs4MipsCheckBase` or an ODS version's subclass) named `check_*` with the signature `(self, ds)`. `compliance-checker` calls every check as `check(ds)`, so a method without `ds` raises a `TypeError` even if it never uses the dataset. The global attributes are available as `self.attrs`.
- Return a list of `Result` objects, or an empty list when there is nothing to report. Also return an empty list when the attribute is absent and a general check already reports that (see below), so a problem is reported once.
- Report problems only. Every `Result` has `value=False`; do not add passing results, because the report should show only what the data preparer has to look at.
- Build results with keyword arguments: `Result(weight=..., value=False, name=..., msgs=[...])`. The `name` is a short group title such as "Filename" or "Time variable". Each message says what is wrong, quotes the offending value with `!r`, and says what is expected.
- The first line of the docstring says what is checked. Comments above each branch say why the branch exists.
- Name helper methods `_check_*` so that `compliance-checker` does not run them as checks of their own. Return early when later comparisons would be meaningless (for example after a malformed `time_range`), rather than crashing or adding misleading follow-up messages.

### Severity

Never write a requirement level into a docstring or use a magic number. Read it from the CVs: `ODS_WEIGHT[...]` for a fixed level, or `self._weight(name)` / `self._level(name)` for the requirement of a particular attribute (conditions included).

| Situation | Severity |
|---|---|
| Attribute missing or empty | Reported by `check_global_attribute_presence` at its ODS requirement (required: high, recommended: medium). Attribute-specific checks return nothing. |
| Value not in the CV, or matching none of its patterns | High. Medium if the attribute is registered content (`rc: "yes"`). |
| Guidance only: the ODS suggests a form but sets no rule (for example the `contact` format) | Low, whatever the attribute's requirement. Word it as a recommendation ("We recommend ..."). |
| Heuristic about the data (for example a single time step implies frequency `fx`) | Medium |
| Attributes disagree with the data or the file name | High, unless it is a heuristic |

### Tests

Every check gets tests in `tests/test_checks.py` using the `run_check` fixture, which writes a real NetCDF file from `GOOD_VALUES`:

- one test that the good file reports nothing;
- one test per problem, asserting the weight and a fragment of the message;
- parametrized bad values, including the edge cases that used to crash (missing or malformed input).

A signature test already enforces the `(self, ds)` rule for every `check_*` method.
