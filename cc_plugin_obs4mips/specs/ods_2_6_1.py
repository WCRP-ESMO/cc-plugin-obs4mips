"""obs4MIPs ODS 2.6.1 global attribute specification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlsplit
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
_NOMINAL_RES = re.compile(
    r"^(?:\d+(?:\.\d+)?\s*km|\d+(?:\.\d+)?x\d+(?:\.\d+)?\s*degree|"
    r"site(?:-collection)?)$",
    re.IGNORECASE,
)
_DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_GIT_REF = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)

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
    """Require the two ODS conventions as complete, separated tokens."""
    tokens = set(re.split(r"[\s,;]+", v.strip()))
    return {"CF-1.11", "ODS-2.6"}.issubset(tokens)


def is_clean_source_id(v: str) -> bool:
    """Check if string does not contain forbidden characters for source_id"""
    return not bool(FORBIDDEN_ID_CHARS.search(v))


def is_bare_doi(v: str) -> bool:
    """Check for the bare DOI form shown in ODS Table 1."""
    return bool(_DOI.fullmatch(v))


def is_url(v: str) -> bool:
    """Check for an absolute HTTP(S) URL."""
    parsed = urlsplit(v)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def is_processing_code_location(v: str) -> bool:
    """Require a permalink to code in the obs4MIPs CMOR-tables repository."""
    if not is_url(v):
        return False
    parsed = urlsplit(v)
    if parsed.scheme.lower() != "https" or parsed.netloc.lower() != "github.com":
        return False
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 5:
        return False
    organization, repository, view, revision = parts[:4]
    return (
        organization in {"PCMDI", "WCRP-ESMO"}
        and repository == "obs4MIPs-cmor-tables"
        and view in {"blob", "tree"}
        and bool(_GIT_REF.fullmatch(revision))
    )


def is_boolean_string(v: str) -> bool:
    """Check for the uppercase TRUE/FALSE form required by ODS Table 1."""
    return v in ("TRUE", "FALSE")


def is_nominal_resolution(v: str) -> bool:
    """Check numeric and site-specific ODS nominal-resolution forms."""
    return bool(_NOMINAL_RES.match(v))


# --------------------------------------------------------------------------------------
# Conditional-requirement predicates
# --------------------------------------------------------------------------------------


def has_aux_unc_true(ds) -> bool:
    """Check if dataset has has_aux_unc attribute set to 'TRUE' (case-insensitive)"""
    return str(getattr(ds, "has_aux_unc", "")).strip().upper() == "TRUE"


def grid_is_site(ds) -> bool:
    """Identify site data even when one of its related attributes is incorrect."""
    values = {
        str(getattr(ds, name, "")).strip().lower()
        for name in ("grid", "grid_label", "nominal_resolution", "product")
    }
    return bool(values & {"site", "site-observations", "site-collection"})


def variant_is_not_be(ds) -> bool:
    """Check whether the variant is not an institutional best-estimate label."""
    label = str(getattr(ds, "variant_label", "")).strip().upper()
    return label != "BE" and not label.endswith("-BE")


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
        RECOMMENDED,
        format_check=is_bare_doi,
        format_hint="must be a bare DOI such as '10.1234/example'",
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
        format_hint="expected '# km', '#x# degree', 'site', or 'site-collection'",
    ),
    AttrSpec(
        "processing_code_location",
        REQUIRED,
        format_check=is_processing_code_location,
        format_hint=(
            "must be a revision-pinned GitHub URL in the PCMDI or WCRP-ESMO "
            "obs4MIPs-cmor-tables repository"
        ),
    ),
    AttrSpec("product", REQUIRED, cv="product", cv_strictness="error"),
    AttrSpec("realm", REQUIRED, cv="realm", cv_strictness="error"),
    AttrSpec("references", REQUIRED),
    AttrSpec("region", REQUIRED, cv="region", cv_strictness="error"),
    AttrSpec("site_id", REQUIRED, required_if=grid_is_site),
    AttrSpec(
        "site_location",
        REQUIRED,
        required_if=grid_is_site,
        cv="site_location",
        cv_strictness="warn",
    ),
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
        RECOMMENDED,
        format_check=is_iso_utc,
        format_hint="must be ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ",
    ),
    AttrSpec(
        "source_data_url",
        RECOMMENDED,
        format_check=is_url,
        format_hint="must be an http(s) URL",
    ),
    AttrSpec("source_type", REQUIRED, cv="source_type", cv_strictness="error"),
    AttrSpec("title", OPTIONAL),
    AttrSpec(
        "tracking_id",
        REQUIRED,
        format_check=is_valid_tracking_id,
        format_hint="must be 'hdl:21.14102/<uuid>' with a valid UUID",
    ),
    AttrSpec("variable_id", REQUIRED, cv="variable_id", cv_strictness="warn"),
    AttrSpec("variant_info", RECOMMENDED, required_if=variant_is_not_be),
    AttrSpec("variant_label", REQUIRED),
]
