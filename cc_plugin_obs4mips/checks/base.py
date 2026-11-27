"""
Version-independent checks of the Obs4MIPs Data Specifications (ODS).

`Obs4MipsCheckBase` holds the logic that does not change between ODS versions because
the CVs drive it: reading the file's global attributes, requirement levels and
conditions, global attribute presence and CV membership, and the DRS (file name and
directory) checks. Each ODS version is a subclass in `ods_<version>.py` that sets
`ods_version` and adds or overrides only what differs. See docs/development/new_ods_version.md.

Every `check_*` method is run by compliance-checker and returns Result objects.
Which attributes exist, how required they are, what values they may take and what the
file name and directory look like come from the obs4MIPs_CVs snapshot of that ODS version
(`cv_sync.load_bundle`), not from this code.

There are two usages of "requirement", and they should not be confused:
  1. In the CVs, it says how strongly the ODS requires an attribute
     ("required", "recommended", "optional").
  2. In a check, it says which section of the report a finding goes in (high, medium,
     low severity).

Rules that the CVs cannot express (formats, character sets, ...) are class attributes
in capitals, so a newer ODS version overrides them in its subclass.
"""

import ast
import re
from difflib import get_close_matches
from pathlib import Path

import numpy as np
from compliance_checker.base import BaseCheck, BaseNCCheck, Result
from compliance_checker.cf import util as cfutil
from netCDF4 import num2date

from cc_plugin_obs4mips import __version__
from cc_plugin_obs4mips.cv_sync import load_bundle

ODS_WEIGHT = {
    "required": BaseCheck.HIGH,
    "recommended": BaseCheck.MEDIUM,
    "optional": BaseCheck.LOW,
}

_CONDITION_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.Compare, ast.Eq, ast.NotEq, ast.Name, ast.Load, ast.Constant,
)  # fmt: skip


class Obs4MipsCheckBase(BaseNCCheck, BaseCheck):
    register_checker = False  # only the versioned subclasses are registered
    ods_version = None  # set by every ODS version; names the CVs snapshot in data/
    _cc_checker_version = __version__
    _cc_display_headers = {weight: level.capitalize() for level, weight in ODS_WEIGHT.items()}  # fmt: skip

    ODS_SEPARATORS = {"space": None}  # None = any whitespace
    ODS_DRS_TIME_RANGE_FORMATS = {
        4: "%Y",
        6: "%Y%m",
        8: "%Y%m%d",
        10: "%Y%m%d%H",
        12: "%Y%m%d%H%M",
        14: "%Y%m%d%H%M%S",
    }
    FREQUENCY_TIME_DIGITS = {
        "yr": 4,
        "dec": 4,
        "yrPt": 4,
        "mon": 6,
        "monC": 6,
        "monPt": 6,
        "day": 8,
        "6hr": 12,
        "3hr": 12,
        "1hr": 12,
        "1hrCM": 12,
        "6hrPt": 12,
        "3hrPt": 12,
        "1hrPt": 12,
        "subhrPt": 14,
    }
    VERSION_REGEX = r"v\d{8}"
    DRS_VALUE_REGEX = r"[A-Za-z0-9-]+"
    DRS_VARIABLE_ID_REGEX = r"[A-Za-z0-9]+"

    # The CVs of this ODS version ------------------------------------------------------

    @classmethod
    def bundle(cls) -> dict:
        return load_bundle(cls.ods_version)

    @property
    def ods_attrs(self) -> dict:
        return self.bundle()["attributes"]

    @property
    def ods_drs(self) -> dict:
        return self.bundle()["drs"]

    @property
    def ods_drs_attrs(self) -> set:
        return {p["name"] for spec in self.ods_drs.values() for p in spec["parts"]}

    # Helpers that read the CVs -----------------------------------------------------------

    def condition_holds(self, expression: str, attrs: dict) -> bool:
        """
        Evaluate a `when` expression from global_attributes.json.

        Only attribute names, quoted strings, `==`, `!=`, `and`, `or` and `not` are
        allowed (the CVs repo tests enforce the same grammar). Missing attributes count
        as "".
        """
        tree = ast.parse(expression, mode="eval")
        if not all(isinstance(node, _CONDITION_NODES) for node in ast.walk(tree)):
            raise ValueError(f"unsupported condition: {expression!r}")
        names = {name: str(attrs.get(name, "")).strip() for name in self.ods_attrs}
        return bool(
            eval(compile(tree, "<condition>", "eval"), {"__builtins__": {}}, names)
        )

    @classmethod
    def split_value(cls, name: str, value: str) -> list[str]:
        """Split a multi-valued attribute on the separator from the CVs (else one value)."""
        separator = cls.bundle()["attributes"][name]["separator"]
        if not separator:
            return [value]
        return [token.strip() for token in value.split(cls.ODS_SEPARATORS[separator])]

    @classmethod
    def unregistered_terms(cls, name: str, value: str) -> list[tuple[str, list[str]]]:
        """
        Screen for global attribute value typos by returning similar CV terms for terms
        that are not found in the CVs.
        """
        attr = cls.bundle()["attributes"][name]
        allowed, patterns = attr.get("allowed", []), attr.get("patterns", [])
        by_folded = {term.casefold(): term for term in allowed}
        unregistered = []
        for token in cls.split_value(name, value):
            if token in allowed or any(
                re.match(pattern, token) for pattern in patterns
            ):
                continue
            close = get_close_matches(
                token.casefold(), list(by_folded), n=3, cutoff=0.5
            )
            unregistered.append((token, [by_folded[c] for c in close]))
        return unregistered

    @classmethod
    def format_hint(cls, name: str) -> str:
        """State the regex(es) an attribute value must match."""
        patterns = cls.bundle()["attributes"][name].get("patterns", [])
        if len(patterns) == 1:
            return f"It must match the pattern {patterns[0]}"
        return "It must match any one of the patterns: " + " | ".join(patterns)

    @classmethod
    def _tokens(cls, name, value):
        """Values of an attribute that are strings (else none); multi-valued split."""
        return (
            cls.split_value(name, value)
            if isinstance(value, str) and value.strip()
            else []
        )

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
        condition = self.ods_attrs[name]["conditional"]
        # check if the condition holds, and if it does, return the requirement level
        if condition and self.condition_holds(condition["when"], self.attrs):
            return condition["requirement"]
        # otherwise, use the value associated with the attribute's requirement key
        return self.ods_attrs[name]["requirement"]

    def _weight(self, name):
        """Severity of a problem with an attribute, from its ODS requirement level."""
        return ODS_WEIGHT[self._level(name)]

    # Basic checks ---------------------------------------------------------------------

    def check_global_attribute_presence(self, ds) -> list[Result]:
        """
        Required global attributes must be present and not empty; recommended ones
        should be.
        """
        results = []
        for name in self.ods_attrs:
            level = self._level(name)
            if level == "optional" or str(self.attrs.get(name, "")).strip() != "":
                continue
            if level == "required":
                message = f"missing or empty {name}"
            else:
                message = f"{name} is missing or empty; it is better to provide it"
            results.append(
                Result(
                    weight=ODS_WEIGHT[level],
                    value=False,
                    name=f"{level.capitalize()} global attributes",
                    msgs=[message],
                )
            )
        return results

    def check_global_attribute_cvs(self, ds) -> list[Result]:
        """Check values against the CVs (allowed values/patterns)."""
        results = []

        # global attrs should be strings
        for name, value in self.attrs.items():
            attr = self.ods_attrs.get(name)
            if attr is None or (isinstance(value, str) and not value.strip()):
                continue  # skip attributes not in self.ods_attrs or empty strings
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

            # use "allowed" and "patterns" keys in cv_data/obs4mips.json to check...
            # (a term is registered if it is allowed OR matches ANY pattern)
            if "allowed" in attr or "patterns" in attr:
                messages = []
                # attributes with an enumerated list are CV problems; attributes with
                # only patterns are format problems
                is_format = "allowed" not in attr
                # ... if an attribute value is present in the CVs
                for token, similar in self.unregistered_terms(name, value):
                    if is_format:
                        message = (
                            f"{name}={token!r} does not have the expected format. "
                            + self.format_hint(name)
                        )
                    else:
                        message = f"{name}={token!r} is not registered in the {name} CV"
                        if similar:
                            message += ". Similar registered terms: " + ", ".join(
                                map(repr, similar)
                            )
                    messages.append(message)
                if messages:
                    # registered content is copied verbatim by data providers, so a
                    # mismatch is a warning; any other CV (formats, etc.) is an error
                    registered = attr["rc"] == "yes"
                    results.append(
                        Result(
                            weight=ODS_WEIGHT[
                                "recommended" if registered else "required"
                            ],
                            value=False,
                            name="Format mismatch" if is_format else "CVs mismatch",
                            msgs=messages,
                        )
                    )

        return results

    def check_drs(self, ds) -> list[Result]:
        """
        Each DRS item must contain only A-Z, a-z, 0-9 or "-" (variable_id: no "-"),
        which also rules out several space-separated values.
        """
        results = []
        for name in sorted(self.ods_drs_attrs & set(self.attrs)):
            value = self.attrs[name]
            if not isinstance(value, str) or not value.strip():
                continue
            # a registered term is always valid, even if it breaks the character rule
            if value in self.ods_attrs.get(name, {}).get("allowed", []):
                continue
            regex = (
                self.DRS_VARIABLE_ID_REGEX
                if name == "variable_id"
                else self.DRS_VALUE_REGEX
            )
            if re.fullmatch(regex, value):
                continue
            allowed = (
                "letters and digits"
                if name == "variable_id"
                else "letters, digits and '-'"
            )
            message = (
                f"{name}={value!r} is part of the DRS and may only contain {allowed}"
            )
            if re.search(r"\s", value.strip()):
                message += "; it must be a single value without spaces"
            results.append(
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Data Reference Syntax",
                    msgs=[message],
                )
            )
        return results

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
        has_time_values = time_arr is not None and time_arr.size > 0  # boolean

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
            time_var != "time" or getattr(time_arr, "axis", None) != "T"
        ):
            results.append(
                Result(
                    weight=ODS_WEIGHT["optional"],
                    value=False,
                    name="Time variable",
                    msgs=[
                        f"time variable {time_names[0]!r} should be named 'time' and have axis 'T'"
                    ],
                )
            )

        # a single time step is assumed to be time-invariant data
        if has_time_values and time_arr.size == 1 and frequency not in (None, "fx"):
            results.append(
                Result(
                    weight=ODS_WEIGHT["recommended"],
                    value=False,
                    name="Frequency attribute",
                    msgs=[
                        f"data with a single time step is assumed to be time-invariant, "
                        f"so frequency should be 'fx' (found {frequency!r})"
                    ],
                )
            )

        # if time_range is not specified ...
        if time_range is None:
            # ... and there are more than one time data points ...
            if has_time_values and time_arr.size > 1:  # type: ignore
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

        # nothing more to validate if the file name has no time_range
        if time_range is None:
            return results

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
            or len(match[1]) not in self.ODS_DRS_TIME_RANGE_FORMATS
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
            return results  # the dates cannot be compared to anything below

        # ensure time range matches the expected number of digits given the frequency
        start, end = match[1], match[2]
        digits = (
            self.FREQUENCY_TIME_DIGITS.get(frequency) if frequency is not None else None
        )
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
                values = np.ma.ravel(time_arr[:])
                dates = num2date(
                    [values[0], values[-1]],
                    units=time_arr.units,
                    calendar=getattr(time_arr, "calendar", "standard"),
                )
                actual = tuple(
                    d.strftime(self.ODS_DRS_TIME_RANGE_FORMATS[len(start)])
                    for d in dates
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
        spec = self.ods_drs["file_name"]
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
        spec = self.ods_drs["directory"]
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
            return results  # levels cannot be lined up with the DRS parts

        # check each DRS part against the corresponding directory level
        for part, actual in zip(parts, directories[-len(parts) :]):
            if part == "version":
                if not re.fullmatch(self.VERSION_REGEX, actual):
                    results.append(
                        Result(
                            weight=ODS_WEIGHT["required"],
                            value=False,
                            name="Directory structure",
                            msgs=[
                                f"DRS version {actual!r} does not match the required form {self.VERSION_REGEX!r}"
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
