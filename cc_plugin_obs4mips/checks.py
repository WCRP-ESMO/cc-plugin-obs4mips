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
There are two usages of "requirement," and they should not be confused:
  1. In the CVs, it indicates how strongly an attribute is required by the ODS
    (e.g., "required", "recommended", "optional").
  2. In a check function, it determines what section of the report a finding about the
    attribute should appear in (e.g., high, medium, low severity).

Before making a change to cc-plugin-obs4mips, check if you can instead make the change
in the obs4MIPs_CVs repository first.

Where developers should make changes:
  - obs4MIPs_CVs repo: change an ODS fact (attribute, requirement, CV, regex, DRS, etc.)
  - cc-plugin-obs4mips/checks.py: logic or format that a simple regex cannot express
  - cc-plugin-obs4mips/checks.py: check validity of assigned attributes to data itself
"""

import ast
import re
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from difflib import get_close_matches
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import numpy as np
from compliance_checker.base import BaseCheck, BaseNCCheck, Result
from compliance_checker.cf import util as cfutil
from netCDF4 import num2date

from cc_plugin_obs4mips import __version__
from cc_plugin_obs4mips.enums import (
    BUNDLE,
    CELL_MEASURES,
    DOI_REGEX,
    DRS_VALUE_REGEX,
    DRS_VARIABLE_ID_REGEX,
    EARTH_RADIUS_KM,
    FORBIDDEN_ID_CHARS,
    FREQUENCY_TIME_DIGITS,
    LICENSE_GUIDANCE,
    NOMINAL_RESOLUTION_BOUNDARY_TOLERANCE,
    NOMINAL_RESOLUTION_LABELS_KM,
    NOMINAL_RESOLUTION_UPPER_BOUNDS_KM,
    SITE_PRODUCT_VALUES,
    STANDARD_GRID_NOMINAL_RESOLUTIONS,
    UTC_TIMESTAMP_FORMAT,
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
ODS_DRS_ATTRS = {p["name"] for spec in ODS_DRS.values() for p in spec["parts"]}
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


def _tokens(name, value):
    """Values of an attribute that are strings (else none); multi-valued split."""
    return split_value(name, value) if isinstance(value, str) and value.strip() else []


# Nominal resolution calculations for lat/lon grids ------------------------------------


def _regular_latlon(ds):
    """Names of the 1-D latitude and longitude coordinates of a regular grid, else None."""
    lats = [n for n in cfutil.get_latitude_variables(ds) if ds.variables[n].ndim == 1]
    lons = [n for n in cfutil.get_longitude_variables(ds) if ds.variables[n].ndim == 1]
    return (lats[0], lons[0]) if lats and lons else None


def _cell_edges(ds, name):
    """
    Cell edges (ascending) of a 1-D coordinate: from its contiguous bounds if it has
    them, else halfway between the cell centers. None when there is a single cell.
    """
    var = ds.variables[name]
    centers = np.sort(np.ma.filled(var[:], np.nan).astype(float))
    bounds = ds.variables.get(getattr(var, "bounds", ""))
    if bounds is not None and bounds.ndim == 2 and bounds.shape[0] == len(centers):
        edges = np.unique(np.ma.filled(bounds[:], np.nan).astype(float))
        if len(edges) == len(centers) + 1:
            return edges
    if len(centers) < 2:
        return None
    middle = (centers[:-1] + centers[1:]) / 2
    return np.concatenate(
        ([2 * centers[0] - middle[0]], middle, [2 * centers[-1] - middle[-1]])
    )


def mean_resolution_km(lat_edges, lon_edges):
    """
    Mean over all cells of the largest distance between two cell vertices, weighted by
    cell area (CMIP6 global attributes document, Appendix 2), for a lat/lon grid.
    """
    lat = np.radians(np.clip(lat_edges, -90, 90))
    lon = np.radians(lon_edges)

    def distance(lon1, lat1, lon2, lat2):  # great-circle (haversine), km
        a = np.sin((lat2 - lat1) / 2) ** 2
        a = a + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))

    west, east, width = lon[:-1], lon[1:], np.diff(lon)
    weighted = total = 0.0
    for south, north in zip(lat[:-1], lat[1:]):
        # the largest of the six vertex-to-vertex distances (a diagonal or a long side)
        dmax = np.max(
            [
                distance(west, south, east, south),
                distance(west, north, east, north),
                distance(west, south, west, north),
                distance(west, south, east, north),
                distance(west, north, east, south),
            ],
            axis=0,
        )
        area = EARTH_RADIUS_KM**2 * width * abs(np.sin(north) - np.sin(south))
        weighted += np.sum(area * dmax)
        total += np.sum(area)
    return weighted / total


def nominal_resolutions_km(mean_km):
    """Labels (in km) a mean resolution may take; both sides if it is near a bound."""
    bounds, labels = NOMINAL_RESOLUTION_UPPER_BOUNDS_KM, NOMINAL_RESOLUTION_LABELS_KM
    i = bisect_right(bounds, mean_km)
    tolerance = NOMINAL_RESOLUTION_BOUNDARY_TOLERANCE
    accepted = {labels[i]}
    if i > 0 and mean_km < bounds[i - 1] * (1 + tolerance):
        accepted.add(labels[i - 1])
    if i < len(bounds) and mean_km > bounds[i] * (1 - tolerance):
        accepted.add(labels[i + 1])
    return accepted


def _nominal_resolution_km(value):
    """'100 km' -> 100.0 and '500-m' -> 0.5; None for anything else."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(?: km|-m)", value.strip())
    if match is None:
        return None
    return float(match[1]) / (1000 if value.strip().endswith("-m") else 1)


def _is_standard_grid(lat_edges, lon_edges):
    """The WIP standard grid: 1x1 degree, 360 x 180 cells, a longitude centered at 0.5E."""
    return (
        len(lat_edges) == 181
        and len(lon_edges) == 361
        and np.allclose(np.diff(lat_edges), 1)
        and np.allclose(np.diff(lon_edges), 1)
        and np.isclose(lat_edges[0], -90)
        and np.isclose(lon_edges[0], round(lon_edges[0]))  # centers at x.5, e.g. 0.5E
    )


# Validation checks stored in a compliance-checker class -------------------------------


class Obs4MipsCheck(BaseNCCheck, BaseCheck):
    register_checker = True
    _cc_spec = "obs4mips"
    _cc_spec_version = BUNDLE["ods_version"]  # Gathered from the obs4MIPs_CVs repo
    _cc_description = f"WCRP-ESMO obs4MIPs {BUNDLE['ods_version']} compliance checks"
    _cc_checker_version = __version__
    _cc_display_headers = {weight: level.capitalize() for level, weight in ODS_WEIGHT.items()}  # fmt: skip

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
        for name in ODS_ATTRS:
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

            # use "allowed" and "patterns" keys in cv_data/obs4mips.json to check...
            # (a term is registered if it is allowed OR matches ANY pattern)
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
                            name="CVs mismatch",
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
        for name in sorted(ODS_DRS_ATTRS & set(self.attrs)):
            value = self.attrs[name]
            if not isinstance(value, str) or not value.strip():
                continue
            # a registered term is always valid, even if it breaks the character rule
            if value in ODS_ATTRS.get(name, {}).get("allowed", []):
                continue
            regex = DRS_VARIABLE_ID_REGEX if name == "variable_id" else DRS_VALUE_REGEX
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
            return results  # the dates cannot be compared to anything below

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
                values = np.ma.ravel(time_arr[:])
                dates = num2date(
                    [values[0], values[-1]],
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
            return results  # levels cannot be lined up with the DRS parts

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

    def check_contact(self, ds) -> list[Result]:
        """
        Recommend contact as 'Firstname Lastname (email)' or just 'email'.

        A missing contact is reported by check_global_attribute_presence at the severity
        of its ODS requirement. The ODS gives only guidance (not a rule) for the format
        of this free-text value, so that guidance is always shown as a low message.
        """
        contact = self.attrs.get("contact")
        if contact is None:
            return []
        email = r"[^\s()@]+@[^\s()@]+\.[^\s()@]+"
        if isinstance(contact, str) and re.fullmatch(
            rf"{email}|[^()]*\S\s*\({email}\)", contact.strip()
        ):
            return []
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Contact",
                msgs=[
                    "We recommend contact be 'Firstname Lastname (email)' or just an email, "
                    "e.g. 'Jane Doe (jane@example.org)' or 'jane@example.org'"
                ],
            )
        ]

    def check_creation_date(self, ds) -> list[Result]:
        """
        Check that creation_date is the same as the data file's actual creation date
        (its modification time, to within a day, since copies and time zones differ).
        """
        creation_date = self.attrs.get("creation_date")
        if not isinstance(creation_date, str):
            return []
        try:
            created = datetime.strptime(creation_date, UTC_TIMESTAMP_FORMAT)
        except ValueError:
            return []  # the CV pattern for creation_date reports a wrong format
        modified = datetime.fromtimestamp(
            Path(ds.filepath()).stat().st_mtime, timezone.utc
        )
        if abs(created.replace(tzinfo=timezone.utc) - modified) <= timedelta(days=1):
            return []
        return [
            Result(
                weight=ODS_WEIGHT["recommended"],
                value=False,
                name="Creation date",
                msgs=[
                    f"creation_date={creation_date!r} differs from the file's modification "
                    f"time {modified.strftime(UTC_TIMESTAMP_FORMAT)!r} by more than a day"
                ],
            )
        ]

    def check_data_specs_version(self, ds):
        """
        Right now, data_specs_version is freetext, but in the future I think it should
        be the CV version from the esgvoc_manifest.yaml file associated with the
        plugin's associated CV bundle. So, we'd:

        Check that the data_specs_version matches `cv_version` in the
        `esgvoc_manifest.yaml` in obs4MIPs_CVs. Would need to update cv_sync.py to
        include the esgvoc_manifest.yaml file.
        """
        return None

    def check_doi(self, ds) -> list[Result]:
        """
        DOI isn't in CVs, and ODS has mixed messaging about if it should be prepended
        with the https prefix, so I just make the https form the recommended format
        (versus a bare DOI without the https).
        """
        results = []
        for doi in _tokens("doi", self.attrs.get("doi")):
            if not re.fullmatch(DOI_REGEX, doi):
                results.append(
                    Result(
                        weight=ODS_WEIGHT["optional"],
                        value=False,
                        name="DOI",
                        msgs=[
                            f"We recommend a DOI be written as a URL, 'https://doi.org/10.xxxx/xxxxxxxx'; found {doi!r}"
                        ],
                    )
                )
        return results

    def check_external_variables(self, ds) -> list[Result]:
        """
        If external_variables are cell measures, e.g., one or more of 'areacella',
        'areacello', 'volcella', 'volcello', recommend only using the 'bounds' attribute
        and dropping the cell measures from the external_variables list if the
        coordinate system is simple (regular latitude/longitude).
        """
        measures = [
            name
            for name in _tokens(
                "external_variables", self.attrs.get("external_variables")
            )
            if name in CELL_MEASURES
        ]
        if not measures or _regular_latlon(ds) is None:
            return []
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="External variables",
                msgs=[
                    f"We recommend dropping {measures} from external_variables and using "
                    "the 'bounds' attribute of the latitude and longitude coordinates, "
                    "given that the grid is a simple regular latitude/longitude grid"
                ],
            )
        ]

    def check_grid(self, ds) -> list[Result]:
        """
        Always recommend that the freetext grid attribute details the N by N resolution,
        horizontal and/or vertical datum, projection, re-gridding procedure if different
        from the original data, and any other relevant information regarding the grid.
        """
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Grid",
                msgs=[
                    "If not already done so, we recommend describing the grid as: "
                    "N by N resolution, horizontal and/or vertical datum, projection, and "
                    "the re-gridding procedure if different from the original data"
                ],
            )
        ]

    def check_grid_label(self, ds) -> list[Result]:
        """
        According to ODS, grid_label should be one of the CVs, or if one site, it should
        be `site-{site_id}`. So we should check that `site_id` matches the `site_id`
        nested in the `grid_label`.
        """
        grid_label = self.attrs.get("grid_label")
        if grid_label.startswith("site-"):
            actual_site_id = self.attrs.get("site_id")
            grid_label_site_id = grid_label.split("site-")[-1]
            if actual_site_id != grid_label_site_id:
                return [
                    Result(
                        weight=ODS_WEIGHT["optional"],
                        value=False,
                        name="Grid label",
                        msgs=[
                            f"site_id '{actual_site_id}' does not match the site_id in the grid_label '{grid_label}'"
                        ],
                    )
                ]

    def check_license(self, ds) -> list[Result]:
        """
        The recommended format is: “Data in this file produced by <Your Centre Name> is
        licensed under a Creative Commons Attribution-4.0 International (CC BY 4.0)
        License (https://creativecommons.org/licenses/). Use of the data must be
        acknowledged following guidelines found at <a URL maintained by you>. Further
        information about this data, including some limitations, can be found via
        <some URL maintained by you>.”

        Only the parts of that text are checked, not the exact wording: the CV for
        license requires a different spelling of the license name.
        """
        license_text = self.attrs.get("license")
        if not isinstance(license_text, str) or not license_text.strip():
            return []
        missing = [
            hint for marker, hint in LICENSE_GUIDANCE if marker not in license_text
        ]
        return (
            [
                Result(
                    weight=ODS_WEIGHT["optional"],
                    value=False,
                    name="License",
                    msgs=[f"We recommend the license text {hint}" for hint in missing],
                )
            ]
            if missing
            else []
        )

    def check_nominal_resolution(self, ds) -> list[Result]:
        """
        Nominal resolution is calculated in a specific way (see Appendix 2 of the CMIP6
        global attributes document), so check that nominal_resolution agrees with the
        mean resolution estimated from the latitude/longitude cell edges. Only regular
        latitude/longitude grids are supported; sites and other grids are skipped.

        The WIP standard 1x1 degree grid is labelled "1x1 degree" by the document, but
        that value is not in the CVs, so "100 km" is accepted for it too.
        """
        value = self.attrs.get("nominal_resolution")
        if not isinstance(value, str) or str(self.attrs.get("product", "")).startswith(
            "site"
        ):
            return []
        grid = _regular_latlon(ds)
        if grid is None:
            return []
        lat_edges, lon_edges = (_cell_edges(ds, name) for name in grid)
        if lat_edges is None or lon_edges is None:
            return []
        if _is_standard_grid(lat_edges, lon_edges):
            if value.strip() in STANDARD_GRID_NOMINAL_RESOLUTIONS:
                return []
            return [
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Nominal resolution",
                    msgs=[
                        f"nominal_resolution={value!r} but the grid is the standard 1x1 degree "
                        "grid, whose nominal_resolution is '1x1 degree' (or '100 km')"
                    ],
                )
            ]
        stated = _nominal_resolution_km(value)
        if stated is None:
            return []  # a value that is not a distance is reported by the CV check
        mean = mean_resolution_km(lat_edges, lon_edges)
        accepted = nominal_resolutions_km(mean)
        if any(np.isclose(stated, label) for label in accepted):
            return []
        expected = " or ".join(f"{label:g} km" for label in sorted(accepted))
        return [
            Result(
                weight=ODS_WEIGHT["required"],
                value=False,
                name="Nominal resolution",
                msgs=[
                    f"nominal_resolution={value!r} does not match the grid: its mean "
                    f"resolution is {mean:.1f} km, which is {expected}"
                ],
            )
        ]

    def check_processing_code_location(self, ds) -> list[Result]:
        """
        Recommend that the processing_code_location attribute points to a valid URL
        where the processing code can be found or will be found.
        """
        location = self.attrs.get("processing_code_location")
        if (
            not isinstance(location, str)
            or not location.strip()
            or _is_url(location.strip())
        ):
            return []
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Processing code location",
                msgs=[
                    f"We recommend processing_code_location be an http(s) URL where the "
                    f"processing code can be found or will be found; found {location!r}"
                ],
            )
        ]

    def check_site(self, ds) -> list[Result]:
        """
        There are several attributes that are used with site data, and we want to check
        them all here. If data are sites or site collections:
        - "grid" should be "site" or "site-collection"
        - "grid_label" should be "site-<site_id>" or "site-collection"
        - nominal_resolution should be "site" or "site-collection"
        - product should be "site-observations" or "site-collection"
        - site_id should be present for individual sites or "collection" if multiple sites (collection not in CVs yet)
        - site_location should be a description, e.g., "location: San Luis,latitude: -33.4648,longitude: -66.4598", or "collection" for multiple sites (collection not in CVs yet)
        """
        product = self.attrs.get("product")
        if product not in SITE_PRODUCT_VALUES:
            return []
        expected = dict(SITE_PRODUCT_VALUES[product])
        if product == "site-observations":
            site_id = self.attrs.get("site_id")
            if isinstance(site_id, str) and site_id.strip():
                expected["grid_label"] = f"site-{site_id.strip()}"

        results = []
        for name, wanted in expected.items():
            value = self.attrs.get(name)
            if not isinstance(value, str) or not value.strip():
                continue  # absent or empty: check_global_attribute_presence reports it
            value = value.strip()
            if value == wanted:
                continue
            if (
                name == "grid_label"
                and product == "site-observations"
                and value.startswith("site-")
            ):
                continue  # a wrong site id in grid_label is reported by check_grid_label
            results.append(
                Result(
                    weight=self._weight(name),
                    value=False,
                    name="Site",
                    msgs=[
                        f"{name} must be {wanted!r} when product is {product!r}; found {value!r}"
                    ],
                )
            )
        return results

    def check_source_data_retrieval_date(self, ds) -> list[Result]:
        """
        Recommend that the source_data_retrieval_date attribute follows the ISO 8601 UTC
        format: YYYY-MM-DDTHH:MM:SSZ.
        """
        retrieved = self.attrs.get("source_data_retrieval_date")
        if not isinstance(retrieved, str) or not retrieved.strip():
            return []
        try:
            datetime.strptime(retrieved.strip(), UTC_TIMESTAMP_FORMAT)
            return []
        except ValueError:
            pass
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Source data retrieval date",
                msgs=[
                    f"We recommend source_data_retrieval_date be ISO 8601 UTC, YYYY-MM-DDTHH:MM:SSZ; found {retrieved!r}"
                ],
            )
        ]

    def check_source_data_url(self, ds) -> list[Result]:
        """
        Recommend that the source_data_url attribute points to a valid URL where the
        source data can be found (several URLs are separated by spaces).
        """
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Source data URL",
                msgs=[
                    f"We recommend source_data_url be an http(s) URL where the source data can be found; found {url!r}"
                ],
            )
            for url in _tokens("source_data_url", self.attrs.get("source_data_url"))
            if not _is_url(url)
        ]

    def check_source(self, ds) -> list[Result]:
        """
        There are several interelated source attributes in a NetCDF: source, source_id,
        source_label, and source_version_number. Source_id is used in the DRS, so it is
        already checked for illegal characters. Source_label is the same as source_id
        but with the appended source_version_number removed. Source_version_number is
        the same as the appended part of source_id but with illegal characters removed
        (non-numbers) and "." converted to "-".

        So source_id == source_label + "-" + <source_version_number with "." replaced by
        "-" and the remaining FORBIDDEN_ID_CHARS removed>, e.g. "CERES-EBAF" + "4.2"
        -> "CERES-EBAF-4-2". The check is case sensitive because these are registered
        content. source_id's own characters are checked by check_drs.

        source itself is not checked here: the ODS only calls it a description, and its
        more detailed template uses facts (release year, source description) that are
        not global attributes.
        """
        attrs = {
            name: self.attrs.get(name)
            for name in ("source_id", "source_label", "source_version_number")
        }
        if not all(isinstance(v, str) and v.strip() for v in attrs.values()):
            return []  # absent or empty: check_global_attribute_presence reports it
        source_id, label, version = (attrs[n].strip() for n in attrs)
        results = []

        suffix = FORBIDDEN_ID_CHARS.sub("", version.replace(".", "-"))
        expected = f"{label}-{suffix}" if suffix else label
        if source_id != expected:
            if not source_id.startswith(label):
                culprit, detail = (
                    "source_label",
                    f"source_id {source_id!r} does not start with source_label {label!r}",
                )
            else:
                culprit, detail = (
                    "source_version_number",
                    f"source_id {source_id!r} ends in {source_id[len(label) :]!r} after "
                    f"source_label {label!r}, but source_version_number {version!r} "
                    f"gives {('-' + suffix) if suffix else ''!r}",
                )
            results.append(
                Result(
                    weight=self._weight(culprit),
                    value=False,
                    name="Source",
                    msgs=[
                        f"source_id must be source_label + '-' + source_version_number "
                        f"(with '.' as '-' and {FORBIDDEN_ID_CHARS.pattern} removed), "
                        f"i.e. {expected!r}; {detail}"
                    ],
                )
            )
        return results
