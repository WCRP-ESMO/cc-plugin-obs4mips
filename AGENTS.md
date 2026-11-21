# AGENTS.md — cc-plugin-obs4mips

This repo is the QA/QC half of a two-repo project. **Read
`~/Desktop/repos/obs4MIPs_CVs/AGENTS.md` first**; it describes the whole project and the
governing rule:

> ODS facts (attribute names, requirement levels, separators, regexes, DRS parts, CV
> tables) live in the CVs repo. This tool reads them and does not restate them.

## Quick reference

- `cc_plugin_obs4mips/cv_data/obs4mips.json` — **generated** by `scripts/sync_cvs.py` from
  the CVs commit pinned in `cv_sources.json`. Never edit by hand. It holds the global
  attributes (requirement, condition, separator, allowed values, patterns) and the DRS.
- `cc_plugin_obs4mips/enums.py` — loads the bundle (`BUNDLE`) and holds the few facts the
  CVs cannot express (`FREQUENCY_TIME_DIGITS`, `VERSION_REGEX`, ...).
- `cc_plugin_obs4mips/checks.py` — one checker class (`Obs4MipsCheck`). The general
  checks loop over the bundle (`check_global_attribute_presence`,
  `check_global_attribute_cvs`), `check_drs_filename` / `check_drs_directory` build their
  templates from the DRS, and the rest are attribute-specific or need the dataset.
- `tests/conftest.py` — `GOOD_VALUES` is a valid file; tests change one value and check the
  report. Tests write real NetCDF files, not stand-in classes.

```bash
uv sync --dev
uv run pytest -q
uv run ruff check .
uv run python scripts/sync_cvs.py --check
```

Python ≥ 3.10 is supported and CI runs 3.10: avoid newer syntax and stdlib.

## Rules specific to this repo

- Don't add a new ODS fact to `enums.py` or `checks.py` if it can live in the CVs repo.
  Put it there, bump the pin, re-sync. What remains in `enums.py` is the project's
  documented exception (formats a regex cannot express, one place only).
- Keep it small: prefer a loop over the bundle to a new function or class. A maintainer
  with basic Python should be able to follow `checks.py` top to bottom.
- Any change that depends on newer CVs content bumps `ref` in `cv_sources.json`, re-runs
  `sync_cvs.py`, and commits the regenerated `obs4mips.json`.
- Add a test for every new check or rule: a change to `GOOD_VALUES` that makes the check
  fail, and the expected message.
- Not implemented yet, with design notes in `docs/planning/`: companion-file checks (`companion_files.md`) and CVs update notifications (`cvs_caching.md`).
- Don't commit or push unless asked. Commit prefixes: `feat:`, `fix:`, `docs:`, `ci:`, `debug:`.
- **Registered content is verbatim.** Values like `institution_id`, `source_id` and `source`
  must match the CV exactly (case, punctuation, whitespace). Never normalize, trim or
  "correct" them when comparing or reporting, and never change `obs4mips.json` by hand. See
  "Registered content (RC) is dangerous to change" in the CVs repo's AGENTS.md.

## How to write a check (formatting guide)

Follow the existing checks in `checks.py`; they are the style reference.

**Shape**
- A check is a method named `check_*` with the signature `(self, ds)`. Compliance Checker
  calls every check as `check(ds)`, so a method without `ds` raises `TypeError` even if it
  never uses the dataset. Global attributes are in `self.attrs` (set in `setup`).
- Return a `list[Result]`, and `[]` when there is nothing to report. Return `[]` too when
  the attribute is absent and a general check already reports that (see "Severity").
- **Report only problems.** Every `Result` is `value=False`. Do not append passes.
- Build each result with keywords: `Result(weight=..., value=False, name=..., msgs=[...])`.
  `name` is a short group title ("Filename", "Time variable"); `msgs` says what is wrong,
  quotes the offending value with `!r`, and says what is expected.
- Leave the `check_*` method name and the first docstring line to say *what* is checked.
  Put comments above each branch, saying why it exists.
- If a check needs a helper, name it `_check_*` so Compliance Checker does not run it as
  a check of its own. Return early when later comparisons would be
  meaningless (for example after a malformed `time_range`), instead of crashing or adding
  misleading follow-up messages.

**Severity** (`weight`)
- Never write a requirement level into a docstring or a magic number. Take it from the
  CVs: `ODS_WEIGHT[...]` for a fixed level, `self._weight(name)` / `self._level(name)` for
  an attribute's own requirement (conditions included).
- A **missing or empty** attribute belongs to `check_global_attribute_presence`, at the
  severity of its ODS requirement (required: high, recommended: medium). Attribute-specific
  checks return `[]` when the attribute is absent, so a problem is reported once.
- A **value** that is not in the CV, or matches none of its patterns, is high; if the
  attribute is registered content (`rc: "yes"`) it is medium.
- **Guidance** (the ODS suggests a form but sets no rule, e.g. the `contact` format) is
  low, whatever the attribute's requirement. Word it as a recommendation
  ("We recommend ..."). Heuristics about the data (a single time step implies `fx`) are
  medium.
- A problem found by comparing attributes with the data or file name is high unless it is a
  heuristic.

**Tests**
- Every check gets tests in `tests/test_checks.py` through the `run_check` fixture, which
  writes a real NetCDF file from `GOOD_VALUES`: one test that the good file reports
  nothing, and one per problem asserting the weight and a fragment of the message.
- Parametrize over bad values; test the edge cases that used to crash (missing or
  malformed input). A signature test already guards the `(self, ds)` rule.
