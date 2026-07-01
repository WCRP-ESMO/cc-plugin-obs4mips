"""obs4MIPs 2.6 global attribute specification, as data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional
from uuid import UUID

from compliance_checker.base import BaseCheck

# Priority mapping per IOOS compliance-checker conventions
REQUIRED = BaseCheck.HIGH  # 3 — shows as Errors in the report
RECOMMENDED = BaseCheck.MEDIUM  # 2 — shows as Warnings
OPTIONAL = BaseCheck.LOW  # 1 — shows as Info


########################################################################################
# Format Validators
########################################################################################

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_TRACKING_ID = re.compile(r"^hdl:21\.14102/(?P<uuid>[0-9a-f-]{36})$", re.IGNORECASE)
_NOMINAL_RES = re.compile(r"^\d+(\.\d+)?\s*km$|^\d+x\d+\s*degree$", re.IGNORECASE)
_URL = re.compile(r"^https?://", re.IGNORECASE)

# Forbidden in source_id per the spec
FORBIDDEN_ID_CHARS = re.compile(r"[._() :/]")


def is_iso_utc(v: str) -> bool:
    """Check if string is in ISO-8601 UTC format: YYYY-MM-DDTHH:MM:SSZ"""
    return bool(_ISO_UTC.match(v))


def is_valid_tracking_id(v: str) -> bool:
    """Check if string is in format 'hdl:21.14102/<uuid>' with a valid UUID"""
    m = _TRACKING_ID.match(v)
    if not m:
        return False
    try:
        UUID(m.group("uuid"))
    except ValueError:
        return False
    return True


def is_conventions_string(v: str) -> bool:
    """Check if string contains both 'CF-1.11' and 'ODS-2.6' (order doesn't matter)"""
    return "CF-1.11" in v and "ODS-2.6" in v


def is_clean_source_id(v: str) -> bool:
    """Check if string does not contain forbidden characters for source_id"""
    return not bool(FORBIDDEN_ID_CHARS.search(v))


def is_bare_doi(v: str) -> bool:
    """Check if string looks like a bare DOI without http(s) or 'doi:' prefix"""
    return not v.lower().startswith(("http://", "https://", "doi:"))


def is_url(v: str) -> bool:
    """Check if string is a valid URL starting with http:// or https://"""
    return bool(_URL.match(v))


def is_boolean_string(v: str) -> bool:
    """Check if string is 'TRUE' or 'FALSE' (case-insensitive)"""
    return v in ("TRUE", "FALSE")


def is_nominal_resolution(v: str) -> bool:
    """
    Check if string is in expected format for nominal_resolution: '# km' or '#x# degree'
    """
    return bool(_NOMINAL_RES.match(v))


# --------------------------------------------------------------------------------------
# Conditional-requirement predicates
# --------------------------------------------------------------------------------------


def has_aux_unc_true(ds) -> bool:
    """Check if dataset has has_aux_unc attribute set to 'TRUE' (case-insensitive)"""
    return str(getattr(ds, "has_aux_unc", "")).strip().upper() == "TRUE"


def grid_is_site(ds) -> bool:
    """Check if dataset grid attribute is 'site' or 'site-collection' (case-insensitive)"""
    return str(getattr(ds, "grid", "")).strip().lower() in ("site", "site-collection")


def variant_is_not_be(ds) -> bool:
    """Check if dataset variant_label attribute is not 'BE' (case-insensitive)"""
    return str(getattr(ds, "variant_label", "")).strip().upper() != "BE"


########################################################################################
# Format Validators
########################################################################################


@dataclass(frozen=True)
class AttrSpec:
    """Specification for a single attribute, including its name, requirement level,
    conditional requirements, CV validation, and format checks.
    """

    name: str
    level: int  # REQUIRED / RECOMMENDED / OPTIONAL
    required_if: Optional[Callable] = None  # ds -> bool; only checked when True
    cv: Optional[str] = None  # CV table name to validate against
    cv_strictness: str = "warn"  # "error" or "warn"
    format_check: Optional[Callable[[str], bool]] = None
    format_hint: str = ""  # message when format fails


# Build the global attribute specs list using the AttrSpec dataclass
GLOBAL_ATTR_SPECS: list[AttrSpec] = [
    AttrSpec("activity_id", REQUIRED, cv="activity_id", cv_strictness="error"),
    AttrSpec("aux_uncertainty_id", REQUIRED, required_if=has_aux_unc_true),
    AttrSpec("comment", OPTIONAL),
    AttrSpec("contact", REQUIRED),
    AttrSpec(
        "Conventions",
        REQUIRED,
        format_check=is_conventions_string,
        format_hint="must contain 'CF-1.11' and 'ODS-2.6'",
    ),
    AttrSpec(
        "creation_date",
        REQUIRED,
        format_check=is_iso_utc,
        format_hint="must be ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ",
    ),
    AttrSpec("dataset_contributor", REQUIRED),
    AttrSpec(
        "data_specs_version",
        REQUIRED,
        format_check=lambda v: v == "2.6",
        format_hint="must be '2.6'",
    ),
    AttrSpec(
        "doi",
        OPTIONAL,
        format_check=is_bare_doi,
        format_hint="should be a bare DOI without http(s) or 'doi:' prefix",
    ),
    AttrSpec(
        "external_variables", OPTIONAL, cv="external_variables", cv_strictness="error"
    ),
    AttrSpec("frequency", REQUIRED, cv="frequency", cv_strictness="error"),
    AttrSpec("grid", REQUIRED),
    AttrSpec("grid_label", REQUIRED, cv="grid_label", cv_strictness="error"),
    AttrSpec(
        "has_aux_unc",
        REQUIRED,
        format_check=is_boolean_string,
        format_hint="must be 'TRUE' or 'FALSE'",
    ),
    AttrSpec("history", OPTIONAL),
    AttrSpec("institution", REQUIRED, cv="institution", cv_strictness="warn"),
    AttrSpec("institution_id", REQUIRED, cv="institution_id", cv_strictness="warn"),
    AttrSpec("license", REQUIRED),
    AttrSpec(
        "nominal_resolution",
        REQUIRED,
        cv="nominal_resolution",
        cv_strictness="warn",
        format_check=is_nominal_resolution,
        format_hint="expected '# km' or '#x# degree'",
    ),
    AttrSpec(
        "processing_code_location",
        REQUIRED,
        format_check=is_url,
        format_hint="must be an http(s) URL",
    ),
    AttrSpec("product", REQUIRED, cv="product", cv_strictness="error"),
    AttrSpec("realm", REQUIRED, cv="realm", cv_strictness="error"),
    AttrSpec("references", REQUIRED),
    AttrSpec("region", REQUIRED, cv="region", cv_strictness="error"),
    AttrSpec("site_id", REQUIRED, required_if=grid_is_site),
    AttrSpec("site_location", REQUIRED, cv="site_location", cv_strictness="warn"),
    AttrSpec("source", REQUIRED, cv="source", cv_strictness="warn"),
    AttrSpec(
        "source_id",
        REQUIRED,
        cv="source_id",
        cv_strictness="warn",
        format_check=is_clean_source_id,
        format_hint="must not contain '.', '_', '(', ')', ' ', ':', or '/'",
    ),
    AttrSpec("source_label", REQUIRED, cv="source_label", cv_strictness="warn"),
    AttrSpec(
        "source_version_number",
        REQUIRED,
        cv="source_version_number",
        cv_strictness="warn",
    ),
    AttrSpec("source_data_notes", OPTIONAL),
    AttrSpec(
        "source_data_retrieval_date",
        OPTIONAL,
        format_check=is_iso_utc,
        format_hint="must be ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ",
    ),
    AttrSpec(
        "source_data_url",
        OPTIONAL,
        format_check=is_url,
        format_hint="must be an http(s) URL",
    ),
    AttrSpec("source_type", REQUIRED, cv="source_type", cv_strictness="error"),
    AttrSpec("title", REQUIRED),
    AttrSpec(
        "tracking_id",
        REQUIRED,
        format_check=is_valid_tracking_id,
        format_hint="must be 'hdl:21.14102/<uuid>' with a valid UUID",
    ),
    AttrSpec("units_metadata", OPTIONAL),
    AttrSpec("variable_id", REQUIRED, cv="variable_id", cv_strictness="warn"),
    AttrSpec("variant_info", RECOMMENDED, required_if=variant_is_not_be),
    AttrSpec("variant_label", REQUIRED),
]
