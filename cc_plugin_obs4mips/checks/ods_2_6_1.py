"""
ODS 2.6.1 checks include:
- Any checks already in the base class (see Obs4MipsBaseCheck in _base.py)
"""

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from compliance_checker.base import Result
from netCDF4 import num2date

from cc_plugin_obs4mips import __version__
from cc_plugin_obs4mips.checks._base import Obs4MipsBaseCheck
from cc_plugin_obs4mips.specs.ods_2_6_1 import (
    FORBIDDEN_ID_CHARS,
    GLOBAL_ATTR_SPECS,
    RECOMMENDED,
    REQUIRED,
    is_processing_code_location,
)

_FILENAME_COMPONENTS = (
    "variable_id",
    "frequency",
    "source_id",
    "variant_label",
    "grid_label",
)
_DIRECTORY_COMPONENTS = (
    "activity_id",
    "institution_id",
    "source_id",
    "frequency",
    "variable_id",
    "nominal_resolution",
)
_DIRECTORY_TEMPLATE = (
    "<activity_id>/<institution_id>/<source_id>/<frequency>/<variable_id>/"
    "<nominal_resolution>/<version>/<filename>.nc"
)
_VARIABLE_ID = re.compile(r"^[A-Za-z0-9]+$")
_FILENAME_TOKEN = re.compile(r"^[A-Za-z0-9-]+$")
_VERSION = re.compile(r"^v\d{8}$")
_TIME_RANGE = re.compile(r"^(?P<start>\d+)-(?P<end>\d+)$")
_TIME_FORMATS = {
    4: "%Y",
    6: "%Y%m",
    8: "%Y%m%d",
    10: "%Y%m%d%H",
    12: "%Y%m%d%H%M",
    14: "%Y%m%d%H%M%S",
}
_FREQUENCY_PRECISION = {
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


def _dataset_path(ds):
    """Return the dataset path without requiring it to exist on this filesystem."""
    filepath = getattr(ds, "filepath", None)
    try:
        raw_path = filepath() if callable(filepath) else filepath
    except (OSError, RuntimeError):
        return None
    if not isinstance(raw_path, (str, os.PathLike)) or not str(raw_path):
        return None

    raw_path = str(raw_path)
    parsed = urlsplit(raw_path)
    if parsed.scheme and parsed.path:
        raw_path = unquote(parsed.path)
    return Path(raw_path)


def _parse_time_range(value):
    """Parse the structural CMIP time-range form without consulting a CV."""
    match = _TIME_RANGE.fullmatch(value)
    if not match:
        return None
    start, end = match.group("start"), match.group("end")
    if len(start) != len(end) or len(start) not in _TIME_FORMATS or start > end:
        return None
    return start, end


def _dataset_time_range(ds, precision):
    """Return first/last time-coordinate values formatted to filename precision."""
    try:
        time = ds.variables["time"]
        if len(time) == 0:
            return None
        units = time.units
        calendar = getattr(time, "calendar", "standard")
        dates = num2date([time[0], time[-1]], units=units, calendar=calendar)
        date_format = _TIME_FORMATS[precision]
        return tuple(date.strftime(date_format) for date in dates)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        # CF checks report malformed or undecodable time coordinates separately.
        return None


def _has_time_values(ds):
    try:
        return "time" in ds.variables and len(ds.variables["time"]) > 0
    except (AttributeError, TypeError):
        return False


class Obs4Mips2_6_1Check(Obs4MipsBaseCheck):
    register_checker = True
    _cc_spec = "obs4mips"
    _cc_spec_version = "2.6.1"
    _cc_description = "WCRP-ESMO obs4MIPs 2.6.1 compliance checks"
    _cc_checker_version = __version__
    SPECS = GLOBAL_ATTR_SPECS
    CV_VERSION = "2.6.1"

    def check_processing_code_location_repository(self, ds):
        """Recommend contributing processing scripts to the obs4MIPs repository."""
        if "processing_code_location" not in self._attrs:
            return None

        location = ds.processing_code_location
        valid = isinstance(location, str) and is_processing_code_location(location)
        return Result(
            RECOMMENDED,
            valid,
            "processing_code_location",
            []
            if valid
            else [
                "We recommend forking https://github.com/WCRP-ESMO/obs4MIPs, "
                "adding your processing scripts to the `examples` directory, and "
                "submitting a PR."
            ],
        )

    def check_filename(self, ds):
        """
        Validate the ODS filename template and its non-CV relationships.

        Checks the following aspects of the ODS filename:
        - Correct file extension (.nc)
        - Valid character usage
        - Proper structure and components given global attributes
        - Valid time range format that aligns with actual data
        - If time invariant (fx), time range not allowed
        """
        path = _dataset_path(ds)
        if path is None:
            return Result(
                REQUIRED,
                False,
                "ODS file name",
                ["dataset path is unavailable; cannot validate the ODS file name"],
            )

        filename = path.name
        problems = []
        if not filename.endswith(".nc"):
            problems.append(f"file name {filename!r} must end with '.nc'")
            stem = filename.rsplit(".", 1)[0]
        else:
            stem = filename[:-3]

        parts = stem.split("_")
        if len(parts) not in (5, 6):
            problems.append(
                "file name must follow "
                "<variable_id>_<frequency>_<source_id>_<variant_label>_"
                "<grid_label>[_<time_range>].nc"
            )
            return Result(REQUIRED, False, "ODS file name", problems)

        # Constructed using only: a-z, A-Z, 0-9, and the hyphen ("-"), except the
        # hyphen must not appear in variable_id.
        # Underscores are prohibited throughout except as shown in the template
        components = dict(zip(_FILENAME_COMPONENTS, parts[:5]))
        for name, value in components.items():
            pattern = _VARIABLE_ID if name == "variable_id" else _FILENAME_TOKEN
            if not pattern.fullmatch(value):
                rule = (
                    "letters and digits"
                    if name == "variable_id"
                    else ("letters, digits, and hyphens")
                )
                problems.append(f"file-name {name}={value!r} may contain only {rule}")
            # Check that the component matches its associated global attribute
            if name in self._attrs:
                expected = getattr(ds, name)
                if not isinstance(expected, str) or value != expected:
                    problems.append(
                        f"file-name {name}={value!r} does not match global "
                        f"attribute {name}={expected!r}"
                    )

        time_range = parts[5] if len(parts) == 6 else None
        frequency = getattr(ds, "frequency", None)
        # For time-invariant fields, the last segment (time_range) is omitted
        if time_range is not None:
            parsed_time_range = _parse_time_range(time_range)
            if parsed_time_range is None:
                problems.append(
                    f"time_range={time_range!r} must contain ordered, equally precise "
                    "CMIP6 (http://goo.gl/v1drZl) dates separated by one hyphen"
                )
            else:
                start, end = parsed_time_range
                expected_precision = _FREQUENCY_PRECISION.get(frequency)
                if expected_precision is not None and len(start) != expected_precision:
                    problems.append(
                        f"time_range={time_range!r} has {len(start)}-digit labels; "
                        f"frequency={frequency!r} requires {expected_precision}-digit "
                        "labels"
                    )

                actual_range = _dataset_time_range(ds, len(start))
                if actual_range is not None and (start, end) != actual_range:
                    problems.append(
                        f"file-name time_range={time_range!r} does not match the time "
                        f"coordinate span {'-'.join(actual_range)!r}"
                    )
            if frequency == "fx":
                problems.append("time-invariant frequency 'fx' must omit time_range")
        elif frequency != "fx" and _has_time_values(ds):
            problems.append(
                "time-varying data must include time_range in the file name"
            )

        return Result(REQUIRED, not problems, "ODS file name", problems)

    def check_directory_structure(self, ds):
        """Validate the trailing ODS DRS directory hierarchy."""
        path = _dataset_path(ds)
        if path is None:
            return Result(
                REQUIRED,
                False,
                "ODS directory structure (DRS)",
                [
                    "dataset path is unavailable; cannot validate its directory structure"
                ],
            )

        provided_structure = str(path.parent)
        template_message = f"Directory structure must follow {_DIRECTORY_TEMPLATE}"
        provided_message = f"Provided directory structure: {provided_structure}"

        # Check if directory depth is sufficient for the expected DRS structure
        directories = path.parent.parts
        if path.is_absolute():
            directories = directories[1:]
        if len(directories) < 7:
            return Result(
                REQUIRED,
                False,
                "ODS directory structure (DRS)",
                [
                    template_message,
                    provided_message
                    + f"\n  - DRS has {len(directories)} directory levels; "
                    "ODS requires seven trailing DRS levels",
                ],
            )

        # Ensure that the actual directory components match the expected global attrs
        actual_components = directories[-7:-1]
        version = directories[-1]
        problems = []
        for name, actual in zip(_DIRECTORY_COMPONENTS, actual_components):
            if name not in self._attrs:
                continue
            expected = getattr(ds, name)
            if isinstance(expected, str):
                if name == "activity_id":
                    expected = expected.split()[0] if expected.split() else expected
                elif name == "nominal_resolution":
                    expected = expected.replace(" ", "")
            if not isinstance(expected, str) or actual != expected:
                problems.append(
                    f"DRS {name} {actual!r} does not match the {name} global "
                    f"attribute: {expected!r}"
                )

        if not _VERSION.fullmatch(version):
            problems.append(
                f"DRS version {version!r} does not match the required form: 'vYYYYMMDD'"
            )

        return Result(
            REQUIRED,
            not problems,
            "ODS directory structure (DRS)",
            []
            if not problems
            else [
                template_message,
                provided_message + "".join(f"\n  - {problem}" for problem in problems),
            ],
        )

    def check_source_id_matches_label_and_version(self, ds):
        """Check source_id against source_label and source_version_number."""
        needed = {"source_id", "source_label", "source_version_number"}
        if not needed.issubset(self._attrs):
            return None
        expected = f"{ds.source_label}-{ds.source_version_number}"
        expected = FORBIDDEN_ID_CHARS.sub("-", expected)
        valid = ds.source_id == expected
        return Result(
            REQUIRED,
            valid,
            "source_id derived from source_label + source_version_number",
            [] if valid else [f"source_id={ds.source_id!r} != expected {expected!r}"],
        )

    def check_anomaly_variable_naming(self, ds):
        """Keep variable-level difference metadata and the ``anom`` suffix aligned."""
        if "variable_id" not in self._attrs:
            return None

        variable_id = ds.variable_id
        variables = getattr(ds, "variables", {})
        variable = variables.get(variable_id)
        if variable is None:
            return None

        units_metadata = getattr(variable, "units_metadata", None)
        is_difference = isinstance(units_metadata, str) and (
            "difference" in units_metadata.lower()
        )
        has_anomaly_suffix = variable_id.endswith("anom")
        if not is_difference and not has_anomaly_suffix:
            return None

        messages = []
        if is_difference and not has_anomaly_suffix:
            messages.append(
                f"{variable_id}:units_metadata={units_metadata!r} identifies a "
                "difference, so variable_id must end in 'anom'"
            )
        if has_anomaly_suffix and not is_difference:
            messages.append(
                f"{variable_id} is an anomaly variable and must define variable-level "
                "units_metadata identifying it as a difference"
            )
        return Result(
            REQUIRED,
            not messages,
            "Anomaly variable naming and units metadata",
            messages,
        )

    def check_site_metadata_consistency(self, ds):
        """Validate the non-CV relationships among ODS site attributes."""
        values = {
            name: str(getattr(ds, name, "")).strip()
            for name in (
                "product",
                "nominal_resolution",
                "grid",
                "grid_label",
                "site_id",
                "site_location",
            )
        }
        lowered = {name: value.lower() for name, value in values.items()}
        site_markers = {
            lowered["product"],
            lowered["nominal_resolution"],
            lowered["grid"],
            lowered["grid_label"],
        }
        is_collection = "site-collection" in site_markers
        is_individual = bool(site_markers & {"site", "site-observations"}) or lowered[
            "grid_label"
        ].startswith("site-")
        if not is_collection and not is_individual:
            return None

        problems = []
        if is_collection:
            expected = {
                "product": "site-collection",
                "nominal_resolution": "site-collection",
                "grid": "site-collection",
                "grid_label": "site-collection",
                "site_id": "collection",
                "site_location": "collection",
            }
            for name, expected_value in expected.items():
                if name in self._attrs and lowered[name] != expected_value:
                    problems.append(
                        f"{name}={values[name]!r}; expected {expected_value!r} for a "
                        "site collection"
                    )
        else:
            expected = {
                "product": "site-observations",
                "nominal_resolution": "site",
                "grid": "site",
            }
            for name, expected_value in expected.items():
                if name in self._attrs and lowered[name] != expected_value:
                    problems.append(
                        f"{name}={values[name]!r}; expected {expected_value!r} for an "
                        "individual site"
                    )

            if "grid_label" in self._attrs:
                # Appendix 3 says ``site`` while Table 1 says ``site-<site_id>``.
                # Accept both forms until that draft inconsistency is resolved.
                allowed_grid_labels = {"site"}
                if values["site_id"]:
                    allowed_grid_labels.add(f"site-{lowered['site_id']}")
                if lowered["grid_label"] not in allowed_grid_labels:
                    problems.append(
                        f"grid_label={values['grid_label']!r}; expected 'site' or "
                        f"'site-{values['site_id']}' for an individual site"
                    )

        return Result(
            REQUIRED,
            not problems,
            "Site metadata consistency",
            problems,
        )

    def check_license_text(self, ds):
        """Recommend the Creative Commons reference suggested by ODS note 13."""
        if "license" not in self._attrs:
            return None
        license_text = ds.license
        valid = isinstance(license_text, str) and (
            "creative commons" in license_text.lower()
            or "creativecommons.org/licenses/" in license_text.lower()
            or "cc" in license_text.lower()  # this isn't great, re-do with regex?
        )
        return Result(
            RECOMMENDED,
            valid,
            "license",
            []
            if valid
            else [
                f"license={license_text!r} does not reference a Creative Commons "
                "license. ODS recommends referencing one; other license terms "
                "remain permitted"
            ],
        )
