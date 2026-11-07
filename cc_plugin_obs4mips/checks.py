"""
Compliance Checker checks for the Obs4MIPs Data Specifications (ODS).

Every method named `check_*` is run by compliance-checker and returns Result objects.
Which attributes exist, how required they are, what values they may take and what the
file name and directory look like all come from the generated bundle (see specs.py).
Only the checks that need the dataset itself or several attributes at once are written
out by hand here.

Where to change things:
  - an ODS fact (attribute, requirement, allowed value, DRS part): the obs4MIPs_CVs repo,
    then run scripts/sync_cvs.py
  - a format a regex cannot express, or a strictness policy: specs.py
  - how a check works: this file
"""

import ast
import re
from difflib import get_close_matches
from pathlib import Path

from compliance_checker.base import BaseCheck, BaseNCCheck, Result
from netCDF4 import num2date

from cc_plugin_obs4mips import __version__
from cc_plugin_obs4mips.specs import (
    BUNDLE,
    CV_STRICTNESS,
    FORBIDDEN_ID_CHARS,
    FORMAT_CHECKS,
    FREQUENCY_TIME_DIGITS,
    PROCESSING_CODE_REGEX,
    VERSION_REGEX,
)

ATTRS = BUNDLE["attributes"]
DRS = BUNDLE["drs"]
HIGH, MEDIUM, LOW = BaseCheck.HIGH, BaseCheck.MEDIUM, BaseCheck.LOW
WEIGHT = {"required": HIGH, "recommended": MEDIUM, "optional": LOW}
SEPARATORS = {"space": None, "comma": ",", "semicolon": ";"}  # None = any whitespace
TIME_FORMATS = {4: "%Y", 6: "%Y%m", 8: "%Y%m%d", 10: "%Y%m%d%H", 12: "%Y%m%d%H%M", 14: "%Y%m%d%H%M%S"}
SITE_ATTRS = ("product", "nominal_resolution", "grid", "grid_label", "site_id", "site_location")

_CONDITION_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.Compare, ast.Eq, ast.NotEq, ast.Name, ast.Load, ast.Constant,
)  # fmt: skip


def condition_holds(expression, attrs):
    """Evaluate a `when` expression from global_attributes.json.

    Only attribute names, quoted strings, ==, !=, and, or and not are allowed (the CVs
    repo tests enforce the same grammar). Missing attributes count as "".
    """
    tree = ast.parse(expression, mode="eval")
    if not all(isinstance(node, _CONDITION_NODES) for node in ast.walk(tree)):
        raise ValueError(f"unsupported condition: {expression!r}")
    names = {name: str(attrs.get(name, "")).strip() for name in ATTRS}
    return bool(eval(compile(tree, "<condition>", "eval"), {"__builtins__": {}}, names))


def split_value(name, value):
    """Split a multi-valued attribute on the separator from the CVs (else one value)."""
    separator = ATTRS[name]["separator"]
    if not separator:
        return [value]
    return [token.strip() for token in value.split(SEPARATORS[separator])]


def unregistered_terms(name, value):
    """Return [(token, similar registered values)] for tokens that are not in the CV."""
    allowed, patterns = ATTRS[name].get("allowed", []), ATTRS[name].get("patterns", [])
    by_folded = {term.casefold(): term for term in allowed}
    unregistered = []
    for token in split_value(name, value):
        if token in allowed or any(re.match(pattern, token) for pattern in patterns):
            continue
        close = get_close_matches(token.casefold(), list(by_folded), n=3, cutoff=0.5)
        unregistered.append((token, [by_folded[c] for c in close]))
    return unregistered


class Obs4MipsCheck(BaseNCCheck, BaseCheck):
    register_checker = True
    _cc_spec = "obs4mips"
    _cc_spec_version = BUNDLE["ods_version"]
    _cc_description = f"WCRP-ESMO obs4MIPs {BUNDLE['ods_version']} compliance checks"
    _cc_checker_version = __version__
    _cc_display_headers = {HIGH: "Required", MEDIUM: "Recommended", LOW: "Suggested"}

    def setup(self, ds):
        self.attrs = {name: ds.getncattr(name) for name in ds.ncattrs()}

    def _level(self, name):
        """requirement from the CVs, raised by `conditional` when its condition holds."""
        condition = ATTRS[name]["conditional"]
        if condition and condition_holds(condition["when"], self.attrs):
            return condition["requirement"]
        return ATTRS[name]["requirement"]

    # ------------------------------------------------------------------------------
    # Checks driven entirely by the bundle
    # ------------------------------------------------------------------------------

    def check_global_attributes_present(self, ds):
        """Required and recommended global attributes must be present and not empty."""
        results = []
        for name in ATTRS:
            level = self._level(name)
            if level == "optional":
                continue
            present = str(self.attrs.get(name, "")).strip() != ""
            results.append(
                Result(
                    WEIGHT[level],
                    present,
                    "Global attributes present",
                    [] if present else [f"missing or empty: {name}"],
                )
            )
        return results

    def check_global_attribute_values(self, ds):
        """Check values against the CVs (allowed values or patterns) and FORMAT_CHECKS."""
        results = []
        for name, value in self.attrs.items():
            attr = ATTRS.get(name)
            if attr is None or (isinstance(value, str) and not value.strip()):
                continue  # not an ODS attribute, or empty (reported as missing above)
            if not isinstance(value, str):
                results.append(Result(HIGH, False, "Global attribute values", [f"{name}={value!r} must be a string"]))
                continue

            if "allowed" in attr or "patterns" in attr:
                messages = []
                for token, similar in unregistered_terms(name, value):
                    message = f"{name}={token!r} is not registered in the CV for {name}"
                    if similar:
                        message += ". Similar registered terms: " + ", ".join(map(repr, similar))
                    messages.append(message)
                results.append(
                    Result(
                        HIGH if name in CV_STRICTNESS else MEDIUM,
                        not messages,
                        "Unregistered controlled vocabulary terms",
                        messages,
                    )
                )

            if name in FORMAT_CHECKS:
                is_valid, hint = FORMAT_CHECKS[name]
                messages = [f"{name}={t!r}: {hint}" for t in split_value(name, value) if not is_valid(t)]
                results.append(
                    Result(
                        WEIGHT[self._level(name)],
                        not messages,
                        "Global attribute formats",
                        messages,
                    )
                )
        return results

    def check_filename(self, ds):
        """File name must follow the DRS file_name template and agree with the attributes."""
        spec = DRS["file_name"]
        separator, extension = spec["separator"], "." + spec["extension"]
        parts = [p["name"] for p in spec["parts"]]
        required = [p["name"] for p in spec["parts"] if p["required"]]
        template = separator.join(f"<{p}>" for p in required)
        template += "".join(f"[{separator}<{p}>]" for p in parts if p not in required) + extension

        filename = Path(ds.filepath()).name
        problems = []
        if not filename.endswith(extension):
            problems.append(f"file name {filename!r} must end with {extension!r}")
        tokens = filename.removesuffix(extension).split(separator)
        if not len(required) <= len(tokens) <= len(parts):
            problems.append(f"file name must follow {template}")
            return Result(HIGH, False, "ODS file name", problems)

        time_range = None
        for part, token in zip(parts, tokens):
            if part == "time_range":
                time_range = token
            elif part in self.attrs and token != self.attrs[part]:
                problems.append(
                    f"file-name {part}={token!r} does not match global attribute {part}={self.attrs[part]!r}"
                )
        if "time_range" in parts:
            problems += self._time_range_problems(ds, time_range)
        return Result(HIGH, not problems, "ODS file name", problems)

    def _time_range_problems(self, ds, time_range):
        """time_range rules: structure, digits per frequency, match to the time axis, fx."""
        frequency = self.attrs.get("frequency")
        time = ds.variables.get("time")
        has_time_values = time is not None and len(time) > 0
        if time_range is None:
            if frequency != "fx" and has_time_values:
                return ["data with multiple time steps must include time_range in the file name"]
            return []

        problems = []
        if frequency == "fx":
            problems.append("time-invariant frequency 'fx' must omit time_range")
        match = re.fullmatch(r"(\d+)-(\d+)", time_range)
        if not match or len(match[1]) != len(match[2]) or len(match[1]) not in TIME_FORMATS or match[1] > match[2]:
            problems.append(
                f"time_range={time_range!r} must contain ordered, equally precise "
                "CMIP6 (http://goo.gl/v1drZl) dates separated by one hyphen"
            )
            return problems

        start, end = match[1], match[2]
        digits = FREQUENCY_TIME_DIGITS.get(frequency)
        if digits is not None and len(start) != digits:
            problems.append(
                f"time_range={time_range!r} has {len(start)}-digit labels; "
                f"frequency={frequency!r} requires {digits}-digit labels"
            )
        if has_time_values:
            try:
                dates = num2date(
                    [time[0], time[-1]], units=time.units, calendar=getattr(time, "calendar", "standard")
                )
                actual = tuple(d.strftime(TIME_FORMATS[len(start)]) for d in dates)
            except (AttributeError, TypeError, ValueError):
                actual = None  # an undecodable time axis is reported by the CF checks
            if actual is not None and (start, end) != actual:
                problems.append(
                    f"file-name time_range={time_range!r} does not match the time coordinate span {'-'.join(actual)!r}"
                )
        return problems

    def check_directory_structure(self, ds):
        """The trailing directories must follow the DRS directory template."""
        spec = DRS["directory"]
        parts = [p["name"] for p in spec["parts"]]
        template = spec["separator"].join(f"<{p}>" for p in parts)
        name = "ODS directory structure (DRS)"

        path = Path(ds.filepath())
        directories = path.parent.parts[1:] if path.is_absolute() else path.parent.parts
        if len(directories) < len(parts):
            return Result(
                HIGH,
                False,
                name,
                [
                    f"Directory structure must follow {template}",
                    f"Provided directory structure: {path.parent}\n  - DRS has {len(directories)} directory "
                    f"levels; ODS requires {len(parts)} trailing DRS levels",
                ],
            )

        problems = []
        for part, actual in zip(parts, directories[-len(parts):]):
            if part == "version":
                if not re.fullmatch(VERSION_REGEX, actual):
                    problems.append(f"DRS version {actual!r} does not match the required form {VERSION_REGEX!r}")
            elif part in self.attrs:
                expected = str(self.attrs[part])
                if ATTRS[part]["separator"] == "space":
                    expected = (expected.split() or [expected])[0]  # first of several values
                if actual != expected:
                    problems.append(f"DRS {part} {actual!r} does not match the {part} global attribute: {expected!r}")
        return Result(
            HIGH,
            not problems,
            name,
            []
            if not problems
            else [
                f"Directory structure must follow {template}",
                f"Provided directory structure: {path.parent}" + "".join(f"\n  - {p}" for p in problems),
            ],
        )

    # ------------------------------------------------------------------------------
    # Checks that need several attributes or the data itself
    # ------------------------------------------------------------------------------

    def check_processing_code_location_repository(self, ds):
        """Recommend contributing processing scripts to the obs4MIPs repository."""
        location = self.attrs.get("processing_code_location")
        if location is None:
            return None
        valid = isinstance(location, str) and re.fullmatch(PROCESSING_CODE_REGEX, location) is not None
        return Result(
            MEDIUM,
            valid,
            "processing_code_location",
            []
            if valid
            else [
                "We recommend forking https://github.com/WCRP-ESMO/obs4MIPs, adding your "
                "processing scripts to the `examples` directory, and submitting a PR."
            ],
        )

    def check_source_id_matches_label_and_version(self, ds):
        """source_id is source_label-source_version_number with forbidden characters as '-'."""
        if not {"source_id", "source_label", "source_version_number"} <= self.attrs.keys():
            return None
        expected = FORBIDDEN_ID_CHARS.sub("-", f"{self.attrs['source_label']}-{self.attrs['source_version_number']}")
        valid = self.attrs["source_id"] == expected
        return Result(
            HIGH,
            valid,
            "source_id derived from source_label + source_version_number",
            [] if valid else [f"source_id={self.attrs['source_id']!r} != expected {expected!r}"],
        )

    def check_anomaly_variable_naming(self, ds):
        """A variable with difference units_metadata must have a variable_id ending in 'anom'."""
        variable_id = self.attrs.get("variable_id")
        variable = ds.variables.get(variable_id)
        if variable is None:
            return None

        units_metadata = getattr(variable, "units_metadata", None)
        is_difference = isinstance(units_metadata, str) and "difference" in units_metadata.lower()
        has_suffix = variable_id.endswith("anom")
        if not is_difference and not has_suffix:
            return None

        messages = []
        if is_difference and not has_suffix:
            messages.append(
                f"{variable_id}:units_metadata={units_metadata!r} identifies a difference, "
                "so variable_id must end in 'anom'"
            )
        if has_suffix and not is_difference:
            messages.append(
                f"{variable_id} is an anomaly variable and must define variable-level "
                "units_metadata identifying it as a difference"
            )
        return Result(HIGH, not messages, "Anomaly variable naming and units metadata", messages)

    def check_site_metadata_consistency(self, ds):
        """Site attributes must agree with each other (individual site or site collection)."""
        values = {name: str(self.attrs.get(name, "")).strip() for name in SITE_ATTRS}
        lowered = {name: value.lower() for name, value in values.items()}
        markers = {lowered[name] for name in ("product", "nominal_resolution", "grid", "grid_label")}
        is_collection = "site-collection" in markers
        is_individual = bool(markers & {"site", "site-observations"}) or lowered["grid_label"].startswith("site-")
        if not is_collection and not is_individual:
            return None

        if is_collection:
            kind = "a site collection"
            expected = {
                "product": "site-collection",
                "nominal_resolution": "site-collection",
                "grid": "site-collection",
                "grid_label": "site-collection",
                "site_id": "collection",
                "site_location": "collection",
            }
        else:
            kind = "an individual site"
            expected = {"product": "site-observations", "nominal_resolution": "site", "grid": "site"}

        problems = [
            f"{name}={values[name]!r}; expected {wanted!r} for {kind}"
            for name, wanted in expected.items()
            if name in self.attrs and lowered[name] != wanted
        ]
        if is_individual and not is_collection and "grid_label" in self.attrs:
            # Appendix 3 says `site` while Table 1 says `site-<site_id>`: accept both
            # until that draft inconsistency is resolved.
            allowed = {"site"} | ({f"site-{lowered['site_id']}"} if values["site_id"] else set())
            if lowered["grid_label"] not in allowed:
                problems.append(
                    f"grid_label={values['grid_label']!r}; expected 'site' or "
                    f"'site-{values['site_id']}' for an individual site"
                )
        return Result(HIGH, not problems, "Site metadata consistency", problems)
