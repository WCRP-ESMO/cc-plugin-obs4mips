# Supporting a new ODS release

Each ODS release is one `Obs4MipsCheckBase()` class. A new release **subclasses the previous one**, so you write only what changed and nothing is copied. Old releases are archived by leaving their file alone. The tool must not offer a release before it is ready: only released versions are registered as `compliance-checker` suites.

Names below use ODS `2.7` as the example; replace it with the real `ods_version` exactly as written in the CVs' `global_attributes.json` (for example `2.6` is not `2.6.1`).

## What lives where

| What | Where |
|---|---|
| Shared logic (setup, requirement levels, presence, CV membership, DRS) | `checks/base.py`, `Obs4MipsCheckBase` |
| Rules the CVs cannot express (formats, character sets), as capitalised class attributes | the class that uses them: `DOI_REGEX`, `FREQUENCY_TIME_DIGITS`, ... |
| Attribute-specific checks of a release | `checks/ods_<version>.py` |
| The CVs of a release | `data/<ods_version>/` (generated, never by hand) |
| Which suites exist | `pyproject.toml` entry points and `checks/__init__.py` |

## Steps

1. **Change the CVs repo first.** New attributes, requirement levels, terms and DRS changes belong in `obs4MIPs_CVs`; the checker reads them. Merge that and get `global_attributes.json` to the new `ods_version`.
2. **Ship the new CVs.** Sync into a new folder named by the `ods_version` (the sync names it from `global_attributes.json`, so `data/2.6/` is left untouched as the archive):
```bash
uv run python scripts/sync_cvs.py --ref <branch-or-commit-of-the-new-ODS>
```

Check that `data/2.7/` exists next to `data/2.6/`. From now on the daily sync (which follows `main`) updates the newest ODS only; to patch the old one, run the sync with `--ref` of the fix and commit the result.

3. **Write the class** `checks/ods_2_7.py`:
```python
from compliance_checker.base import Result

from cc_plugin_obs4mips.checks.base import ODS_WEIGHT
from cc_plugin_obs4mips.checks.ods_2_6 import Obs4MipsCheck_2_6


class Obs4MipsCheck_2_7(Obs4MipsCheck_2_6):
      ods_version = "2.7"
      _cc_spec_version = ods_version
      _cc_description = f"WCRP-ESMO obs4MIPs {ods_version} compliance checks"

      # a rule that changed: override the class attribute, every check using it follows
      DOI_REGEX = r"https://doi\.org/10\.\d{4,9}/\S+"

      # a check whose logic changed: override the method (same name, signature (self, ds))
      def check_license(self, ds) -> list[Result]:
         ...

      # an attribute that is new in 2.7: add a method
      def check_new_attribute(self, ds) -> list[Result]:
         ...
```

Everything not written here is inherited. A check that no longer applies in 2.7 is overridden to `return []`. Do not copy methods from the parent.

4. **Add tests**: a new `GOOD_VALUES` entry (or a variant of the fixture) for the new attributes, and tests for each override. `tests/test_checks.py::test_a_new_ods_version_overrides_only_what_changed` shows the pattern.
5. **Register it** (this is what makes the version usable):
   - `pyproject.toml`: add `"obs4mips:2.7" = "cc_plugin_obs4mips.checks:Obs4MipsCheck_2_7"` and point
     `"obs4mips"` at the new class.
   - `checks/__init__.py`: import the class and set `Obs4MipsCheck = Obs4MipsCheck_2_7` (the newest).
   - `tests/test_checks.py::test_only_released_ods_versions_are_registered_as_suites`: add `"obs4mips:2.7"`.
     `test_there_are_no_cvs_for_an_unreleased_ods_version` uses `2.7` as its example; change it to
     the next version.
6. **Run everything**: `uv run pytest -q`, `uv run ruff check .`, `uv run python scripts/sync_cvs.py --check`.
7. **Release**: merge to `dev`, then `dev` into `main`. `python-semantic-release` reads the commit
   messages: use `feat: support ODS 2.7` (a new minor plugin version). The plugin version is the
   git tag; it is not the ODS version and not the CVs `cv_version`.

## Until the release is ready

Do all the work on `dev` without step 5. Without a registered entry point, users cannot select `obs4mips:2.7`, and `load_bundle("2.7")` raises "no CVs" unless `data/2.7/` exists. (The sync creates `data/2.7/` as soon as the CVs `main` says `2.7`; that is harmless, since nothing registers a checker for it until step 5.)

## What stays the same for users

- `compliance-checker -t obs4mips:2.6 ...` keeps working and keeps using `data/2.6/`.
- `compliance-checker -t obs4mips ...` uses the newest registered version.
- `cc-plugin-obs4mips update` stores CVs per ODS version, so updating the 2.7 CVs never touches 2.6.
