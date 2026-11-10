"""
Compliance Checker checks for the Obs4MIPs Data Specifications (ODS).

Every method named `check_*` is run by compliance-checker and returns Result objects.
Which attributes exist, how required they are, what values they may take, and what the
file name and directory look like all come from the generated obs4MIPs_CVs bundle.

Currently, a user has to create the obs4MIPs_CVs manually using `scripts/sync_cvs.py`
and `cv_sources.json`. When synced, a file is stored at `cv_data/obs4mips.json` which
contains `global_attributes.json`, `drs_specs.yaml`, and the CVs themselves from
obs4MIPs_CVs, where "allowed" are a list of allowed CVs, and "patterns" are regex
patterns that values must match.

Below, you will find checks organized as:
  - General checks (global attributes presence/format, CVs, DRS compliance)
  - Global attribute-specific checks
  - Inter-attribute checks

Developer notes:
----------------
Before making a change to cc-plugin-obs4mips, check if you can instead make the change
in the obs4MIPs_CVs repository first.

Where developers should make changes:
  - obs4MIPs_CVs repo: change an ODS fact (attribute, requirement, CV, regex, DRS, etc.)
  - cc-plugin-obs4mips/checks.py: logic or format that a simple regex cannot express
  - cc-plugin-obs4mips/checks.py: check validity of assigned attributes to data itself
"""

import ast
import re
from difflib import get_close_matches
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from compliance_checker.base import BaseCheck, BaseNCCheck, Result
from compliance_checker.cf import util as cfutil
from netCDF4 import num2date

from cc_plugin_obs4mips import __version__
from cc_plugin_obs4mips.enums import (
    BUNDLE,
    FREQUENCY_TIME_DIGITS,
    VERSION_REGEX,
)

# Parse facets of the CV bundle for easier access --------------------------------------

ODS_ATTRS = BUNDLE["attributes"]
ODS_DRS = BUNDLE["drs"]
ODS_WEIGHT = {
    "required": BaseCheck.HIGH,
    "recommended": BaseCheck.MEDIUM,
    "optional": BaseCheck.LOW,
}
ODS_SEPARATORS = {"space": None}  # None = any whitespace
ODS_DRS_TIME_RANGE_FORMATS = {
    4: "%Y",
    6: "%Y%m",
    8: "%Y%m%d",
    10: "%Y%m%d%H",
    12: "%Y%m%d%H%M",
    14: "%Y%m%d%H%M%S",
}
ODS_SITE_ATTRS = (
    "product",
    "nominal_resolution",
    "grid",
    "grid_label",
    "site_id",
    "site_location",
)

# Helpers ------------------------------------------------------------------------------

_CONDITION_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.Compare, ast.Eq, ast.NotEq, ast.Name, ast.Load, ast.Constant,
)  # fmt: skip


def condition_holds(expression: str, attrs: dict) -> bool:
    """
    Evaluate a `when` expression from global_attributes.json.

    Only attribute names, quoted strings, `==`, `!=`, `and`, `or` and `not` are allowed
    (the CVs repo tests enforce the same grammar). Missing attributes count as "".
    """
    # Parse the expression into an AST and ensure it only contains allowed nodes
    tree = ast.parse(expression, mode="eval")
    if not all(isinstance(node, _CONDITION_NODES) for node in ast.walk(tree)):
        raise ValueError(f"unsupported condition: {expression!r}")
    names = {name: str(attrs.get(name, "")).strip() for name in ODS_ATTRS}
    return bool(eval(compile(tree, "<condition>", "eval"), {"__builtins__": {}}, names))


def split_value(name: str, value: str) -> list[str]:
    """Split a multi-valued attribute on the separator from the CVs (else one value)."""
    separator = ODS_ATTRS[name]["separator"]
    if not separator:
        return [value]
    return [token.strip() for token in value.split(ODS_SEPARATORS[separator])]


def unregistered_terms(name: str, value: str) -> list[tuple[str, list[str]]]:
    """
    Screen for global attribute value typos by returning similar CV terms for terms that
    are not found in the CVs.
    """
    allowed, patterns = (
        ODS_ATTRS[name].get("allowed", []),
        ODS_ATTRS[name].get("patterns", []),
    )
    by_folded = {term.casefold(): term for term in allowed}
    unregistered = []
    for token in split_value(name, value):
        if token in allowed or any(re.match(pattern, token) for pattern in patterns):
            continue
        close = get_close_matches(token.casefold(), list(by_folded), n=3, cutoff=0.5)
        unregistered.append((token, [by_folded[c] for c in close]))
    return unregistered


def _is_url(value):
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _is_uuid(value):
    try:
        UUID(value.rsplit("/", 1)[-1])
    except ValueError:
        return False
    return True


# Validation checks stored in a compliance-checker class -------------------------------


class Obs4MipsCheck(BaseNCCheck, BaseCheck):
    register_checker = True
    _cc_spec = "obs4mips"
    _cc_spec_version = BUNDLE["ods_version"]  # Gathered from the obs4MIPs_CVs repo
    _cc_description = f"WCRP-ESMO obs4MIPs {BUNDLE['ods_version']} compliance checks"
    _cc_checker_version = __version__
    _cc_display_headers = ODS_WEIGHT

    def setup(self, ds):
        """Collect all global attributes from the supplied NetCDF."""
        self.attrs = {name: ds.getncattr(name) for name in ds.ncattrs()}

    def _level(self, name):
        """
        Using global_attributes.json from the CVs, read the requirement level for a
        given attribute (self.attrs[name]) using the "requirement" key or the
        "conditional"["requirement"] key if the condition holds.
        """
        # if global_attributes.json has a non-null conditional key ...
        condition = ODS_ATTRS[name]["conditional"]
        # check if the condition holds, and if it does, return the requirement level
        if condition and condition_holds(condition["when"], self.attrs):
            return condition["requirement"]
        # otherwise, use the value associated with the attribute's requirement key
        return ODS_ATTRS[name]["requirement"]

    # Basic checks ---------------------------------------------------------------------

    def check_global_attribute_presence(self) -> list[Result]:
        """Required global attributes must be present and not empty."""
        results = []
        for name in ODS_ATTRS:
            level = self._level(name)
            if level != "required":
                continue
            present = str(self.attrs.get(name, "")).strip() != ""
            results.append(
                Result(
                    ODS_WEIGHT[level],
                    present,
                    "Required global attributes",
                    [] if present else [f"missing or empty {name}"],
                )
            )
        return results

    def check_global_attribute_cvs(self) -> list[Result]:
        """Check values against the CVs (allowed values/patterns)."""
        results = []

        # if an attribute is part of the DRS, it must not contain whitespace
        drs_parts = {p["name"] for spec in ODS_DRS.values() for p in spec["parts"]}
        for name in sorted(drs_parts & set(self.attrs)):
            value = self.attrs[name]
            if isinstance(value, str) and re.search(r"\s", value.strip()):
                results.append(
                    Result(
                        weight=ODS_WEIGHT["required"],
                        value=False,
                        name="Data Reference Structure",
                        msgs=[
                            f"{name}={value!r} is part of the DRS and must be a single value without spaces"
                        ],
                    )
                )

        # global attrs should be strings
        for name, value in self.attrs.items():
            attr = ODS_ATTRS.get(name)
            if attr is None or (isinstance(value, str) and not value.strip()):
                continue  # skip attributes not in ODS_ATTRS or empty strings
            if not isinstance(value, str):
                results.append(
                    Result(
                        weight=ODS_WEIGHT["required"],
                        value=False,
                        name="CVs mismatch",
                        msgs=[f"{name}={value!r} must be a string"],
                    )
                )
                continue

            # use "allowed" key and "patterns" keys in cv_data/obs4mips.json to check...
            if "allowed" in attr or "patterns" in attr:
                messages = []
                # ... if an attribute value is present in the CVs
                for token, similar in unregistered_terms(name, value):
                    message = f"{name}={token!r} is not registered in the CV for {name}"
                    if similar:
                        message += ". Similar registered terms: " + ", ".join(
                            map(repr, similar)
                        )
                    messages.append(message)
                results.append(
                    Result(
                        weight=ODS_WEIGHT["recommended"],
                        value=not messages,
                        name="CVs mismatch",
                        msgs=messages,
                    )
                )
                # ... if an attribute value does not match the allowed patterns
                if "patterns" in attr:
                    pattern_messages = []
                    for pattern in attr["patterns"]:
                        if not re.fullmatch(pattern, value):
                            pattern_messages.append(
                                f"{name}={value!r} does not match the allowed pattern {pattern!r}"
                            )
                    if pattern_messages:
                        results.append(
                            Result(
                                weight=ODS_WEIGHT["required"],
                                value=False,
                                name="CVs mismatch",
                                msgs=pattern_messages,
                            )
                        )

        return results

    def check_drs(self):
        """
        Required -
        Ensure each drs item is A-Z, a-z, 0-9, or "-" except for variable_id, which
        shouldn't have "-"
        """
        return None

    def _check_drs_filename_time_range(self, ds, time_range):
        """
        Helper check used below to validate time_range rules: structure, digits per
        frequency, match to the time axis, fx.
        """
        results = []

        # get the frequency attribute from the data's global attrs
        frequency = self.attrs.get("frequency")

        # ranking function to prefer CF time standard_name and axis name
        def rank(name):
            var = ds.variables[name]
            declared = (
                getattr(var, "standard_name", None) == "time"
                or getattr(var, "axis", None) == "T"
            )
            return (not declared, name not in ds.dimensions, name)

        # get the actual time data using compliance-checker tooling (cfutil)
        time_names = sorted(cfutil.get_time_variables(ds), key=rank)  # possible names
        time_var = time_names[0] if time_names else None  # likely time variable name
        time_arr = ds.variables[time_var] if time_var else None  # time data
        has_time_values = time_arr is not None and len(time_arr) > 0  # boolean

        # if time variable is found but has no data, that's an issue
        if time_var and not has_time_values:
            results.append(
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Time variable",
                    msgs=[f"time variable {time_var!r} has no data associated with it"],
                )
            )

        # if more than one time variable found, recommend using "time" & "T"
        if len(time_names) > 1:
            results.append(
                Result(
                    weight=ODS_WEIGHT["optional"],
                    value=False,
                    name="Time variable",
                    msgs=[
                        f"multiple time variables detected {time_names=}; recommend using only 'time' with axis 'T'"
                    ],
                )
            )

        # if 1 time var is found but it's not "time" with axis "T", recommend changing
        if len(time_names) == 1 and (
            getattr(time_var, "standard_name", None) != "time"
            or getattr(time_var, "axis", None) != "T"
        ):
            results.append(
                Result(
                    weight=ODS_WEIGHT["optional"],
                    value=False,
                    name="Time variable",
                    msgs=[
                        f"consider renaming time variable {time_names[0]!r} to 'time' with axis 'T'"
                    ],
                )
            )

        # if time_range is not specified ...
        if time_range is None:
            # ... and there are more than one time data points ...
            if has_time_values and len(time_arr) > 1:  # type: ignore
                # ... and frequnecy was set to fixed, that's incorrect
                if frequency == "fx":
                    results.append(
                        Result(
                            weight=ODS_WEIGHT["required"],
                            value=False,
                            name="Frequency attribute",
                            msgs=[
                                "fixed frequency 'fx' data must not have more than 1 time value"
                            ],
                        )
                    )
                # ... otherwise, time_range must be included in the file name
                else:
                    results.append(
                        Result(
                            weight=ODS_WEIGHT["required"],
                            value=False,
                            name="Filename",
                            msgs=[
                                "data with time steps must include time_range in the file name"
                            ],
                        )
                    )

        # if "fx" is frequency, time_range should be omitted
        if frequency == "fx":
            results.append(
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Frequency attribute",
                    msgs=["time-invariant frequency 'fx' must omit time_range"],
                )
            )

        # time_range is not a global attr, but it should be validated as part of the DRS
        match = re.fullmatch(r"(\d+)-(\d+)", time_range)
        if (
            not match
            or len(match[1]) != len(match[2])
            or len(match[1]) not in ODS_DRS_TIME_RANGE_FORMATS
            or match[1] > match[2]
        ):
            results.append(
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Filename",
                    msgs=[
                        f"time_range={time_range!r} must contain ordered, equally precise "
                        "CMIP6 (http://goo.gl/v1drZl) dates separated by one hyphen"
                    ],
                )
            )

        # ensure time range matches the expected number of digits given the frequency
        start, end = match[1], match[2]
        digits = FREQUENCY_TIME_DIGITS.get(frequency) if frequency is not None else None
        if digits is not None and len(start) != digits:
            results.append(
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Filename",
                    msgs=[
                        f"time_range={time_range!r} has {len(start)}-digit labels; "
                        f"frequency={frequency!r} requires {digits}-digit labels"
                    ],
                )
            )

        # if time values exist, check that they match the start and end of the time_range
        if has_time_values:
            try:
                dates = num2date(
                    [time_arr[0], time_arr[-1]],
                    units=time_arr.units,
                    calendar=getattr(time_arr, "calendar", "standard"),
                )
                actual = tuple(
                    d.strftime(ODS_DRS_TIME_RANGE_FORMATS[len(start)]) for d in dates
                )
            except (AttributeError, TypeError, ValueError):
                actual = None  # an undecodable time axis is reported by the CF checks
            if actual is not None and (start, end) != actual:
                results.append(
                    Result(
                        weight=ODS_WEIGHT["required"],
                        value=False,
                        name="Filename",
                        msgs=[
                            f"file-name time_range={time_range!r} does not match the time coordinate span {'-'.join(actual)!r}"
                        ],
                    )
                )
        return results

    def check_drs_filename(self, ds):
        """File name must follow the DRS file_name template and agree with the attributes."""

        # get the file name specification from the DRS template
        spec = ODS_DRS["file_name"]
        separator, extension = spec["separator"], "." + spec["extension"]
        parts = [p["name"] for p in spec["parts"]]
        required = [p["name"] for p in spec["parts"] if p["required"]]
        template = separator.join(f"<{p}>" for p in required)
        template += (
            "".join(f"[{separator}<{p}>]" for p in parts if p not in required)
            + extension
        )

        # extract the actual file name from the NetCDF path
        filename = Path(ds.filepath()).name

        # ensure filename ends with the correct extension
        results = []
        if not filename.endswith(extension):
            results.append(
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Filename",
                    msgs=[f"file name {filename!r} must end with {extension!r}"],
                )
            )

        # ensure the file name has the correct number of parts according to the DRS
        tokens = filename.removesuffix(extension).split(separator)
        if not len(required) <= len(tokens) <= len(parts):
            results.append(
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Filename",
                    msgs=[f"file name must follow {template}"],
                )
            )
            return results

        # check that file name parts match the global attributes they map to
        # (except time_range, which isn't an ODS global attribute)
        time_range = None
        for part, token in zip(parts, tokens):
            if part == "time_range":
                time_range = token
            elif part in self.attrs and token != self.attrs[part]:
                results.append(
                    Result(
                        weight=ODS_WEIGHT["required"],
                        value=False,
                        name="Filename",
                        msgs=[
                            f"file-name {part}={token!r} does not match global attribute {part}={self.attrs[part]!r}"
                        ],
                    )
                )

        # use function above to do data-specific checks for time range
        if "time_range" in parts:
            results += self._check_drs_filename_time_range(ds, time_range)
        return results

    def check_drs_directory(self, ds):
        """The trailing directories must follow the DRS directory template."""
        results = []

        # extract the DRS directory specification and template
        spec = ODS_DRS["directory"]
        parts = [p["name"] for p in spec["parts"]]
        template = spec["separator"].join(f"<{p}>" for p in parts)

        # get the actual directory structure from the file path
        path = Path(ds.filepath())

        # ensure we have enough directory levels to match the DRS parts
        directories = path.parent.parts[1:] if path.is_absolute() else path.parent.parts
        if len(directories) < len(parts):
            results.append(
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Directory structure",
                    msgs=[
                        f"directory structure must follow {template}",
                        f"provided directory structure: {path.parent}\n  - DRS has {len(directories)} directory "
                        f"levels; ODS requires {len(parts)} trailing DRS levels",
                    ],
                )
            )

        # check each DRS part against the corresponding directory level
        for part, actual in zip(parts, directories[-len(parts) :]):
            if part == "version":
                if not re.fullmatch(VERSION_REGEX, actual):
                    results.append(
                        Result(
                            weight=ODS_WEIGHT["required"],
                            value=False,
                            name="Directory structure",
                            msgs=[
                                f"DRS version {actual!r} does not match the required form {VERSION_REGEX!r}"
                            ],
                        )
                    )
            elif part in self.attrs:
                expected = str(self.attrs[part])
                if actual != expected:
                    results.append(
                        Result(
                            weight=ODS_WEIGHT["required"],
                            value=False,
                            name="Directory structure",
                            msgs=[
                                f"DRS {part} {actual!r} does not match the {part} global attribute: {expected!r}"
                            ],
                        )
                    )
        return results

    # Attribute-specific checks --------------------------------------------------------

    def check_contact(self):
        """Recommend contact as 'Firstname Lastname (email)' or just 'email'."""
        contact = self.attrs.get("contact")
        if contact is None:
            return None
        email = r"[^\s()@]+@[^\s()@]+\.[^\s()@]+"
        valid = isinstance(contact, str) and bool(
            re.fullmatch(rf"{email}|[^()]*\S\s*\({email}\)", contact.strip())
        )
        return Result(
            ODS_WEIGHT["optional"],
            valid,
            "contact",
            []
            if valid
            else [
                "We recommend contact be 'Firstname Lastname (email)' or just an email, "
                "e.g. 'Jane Doe (jane@example.org)' or 'jane@example.org'"
            ],
        )

    def check_creation_date(self):
        """
        Recommended -
        Check that the creation_date attribute is the same as the data file's actual
        creation date.
        """
        return None

    def check_data_specs_version(self):
        """
        Required -
        Check that the data_specs_version matches `cv_version` in the
        `esgvoc_manifest.yaml` in obs4MIPs_CVs. Maybe need to update sync_cvs to
        include the esgvoc_manifest.yaml file.
        """
        return None

    def check_doi(self):
        """
        Optional -
        DOI isn't in CVs, but ODS has a recommended format for it that includes the
        https prefix: https://doi.org/xx.xxxx/xxxxxxxx
        """
        return None

    def check_external_variables(self):
        """
        Optional -
        If external_variables are cell measures, e.g., one or more of 'areacella',
        'areacello', 'volcella', 'volcello', recommend only using the 'bounds' attribute
        and dropping the cell measures from the external_variables list if the
        coordinate system is simple.
        """
        return None

    def check_grid(self):
        """
        Optional -
        Recommend that the grid attribute details the N by N resolution, horizontal
        and/or vertical datum, projection, re-gridding procedure if different from the
        original data, and any other relevant information regarding the grid.
        """
        return None

    def check_license(self):
        """
        Optional -
        The recommended format is: “Data in this file produced by <Your Centre Name> is
        licensed under a Creative Commons Attribution-4.0 International (CC BY 4.0)
        License (https://creativecommons.org/licenses/). Use of the data must be
        acknowledged following guidelines found at <a URL maintained by you>. Further
        information about this data, including some limitations, can be found via
        <some URL maintained by you>.”
        """
        return None

    def check_nominal_resolution(self):
        """
        Required -
        Nominal resolution is calculated in a specific way, so we should check using the
        lat/lon data (unless site coordinates are used) if nominal_resolution was
        estimated correctly. See /Users/6ru/Downloads/CMIP6_global_attributes_filenames_CVs.docx
        Appendix 2 for how to estimate it.

        If grid is regular 1 x 1 degree, the nominal resolution should be "1x1 degree"
        (conflictingly, "1x1 degree" is not in the CVs)
        """
        return None

    def check_processing_code_location(self):
        """
        Recommend -
        Recommend that the processing_code_location attribute points to a valid URL
        where the processing code can be found or will be found.
        """
        return None

    def check_source_data_retrieval_date(self):
        """
        Required -
        Recommend that the source_data_retrieval_date attribute is provided and follows
        the ISO 8601 UTC format: YYYY-MM-DDTHH:MM:SSZ.
        """
        return None

    def check_source_data_url(self):
        """
        Optional -
        Recommend that the source_data_url attribute is provided and points to a valid URL
        where the source data can be found.
        """
        return None

    # Multi-attribute checks -----------------------------------------------------------
