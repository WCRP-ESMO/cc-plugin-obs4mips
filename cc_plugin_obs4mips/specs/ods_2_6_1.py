"""
obs4MIPs ODS 2.6.1 global attribute specifications.

Creates GLOBAL_ATTR_SPECS, which is a list of AttrSpec objects that store a name,
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import UUID

from cc_plugin_obs4mips.specs._base import (
    OPTIONAL,
    RECOMMENDED,
    REQUIRED,
    AttrSpec,
)

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
    """Require ODS-2.6.1 as a complete token in a space-separated list."""
    return "ODS-2.6.1" in v.split()


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
    """Check for a revision-pinned script in the recommended obs4MIPs repo."""
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
        organization == "WCRP-ESMO"
        and repository == "obs4MIPs"
        and view in {"blob", "tree"}
        and bool(_GIT_REF.fullmatch(revision))
        and parts[4] == "examples"
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


# Build the global attribute specs list using the AttrSpec dataclass
GLOBAL_ATTR_SPECS: list[AttrSpec] = [
    AttrSpec(
        name="activity_id",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="activity_id",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/activity_id
        cv_strictness="error",
        format_check=None,
        format_hint="must be 'obs4MIPs'",
    ),
    AttrSpec(
        name="aux_uncertainty_id",
        rc=False,
        requirement=REQUIRED,
        required_if=has_aux_unc_true,
        cv="aux_uncertainty_id",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/aux_uncertainty_id
        cv_strictness="warn",
        format_check=None,
        format_hint="must be one of the the controlled vocabulary",
    ),
    AttrSpec(
        name="comment",
        rc=False,
        requirement=OPTIONAL,
        required_if=None,
        cv=None,
        cv_strictness="warn",
        format_check=None,
        format_hint="a character string containing additional information about the data or methods used to produce it",
    ),
    AttrSpec(
        name="contact",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv=None,  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/contact
        cv_strictness="warn",
        format_check=None,
        format_hint="name and contact information, e.g., 'First Last (email@address.com)', of person who should be contacted for more information about the data",
    ),
    AttrSpec(
        name="Conventions",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="conventions",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/conventions
        cv_strictness="warn",
        format_check=is_conventions_string,
        format_hint="must contain at least 'ODS-2.6.1' as a space-separated convention",
    ),
    AttrSpec(
        name="creation_date",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv=None,  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/creation_date
        cv_strictness="warn",
        format_check=is_iso_utc,
        format_hint="must be ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ",
    ),
    AttrSpec(
        name="dataset_contributor",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv=None,  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/dataset_contributor
        cv_strictness="warn",
        format_check=None,
        format_hint="name of the individual that prepared the ODS-compliant data, e.g., 'First Last'",
    ),
    AttrSpec(
        name="data_specs_version",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="data_specs_version",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/data_specs_version
        cv_strictness="error",
        format_check=lambda v: v == "2.6.1",
        format_hint="must be '2.6.1'",  # according to ODS description, this is wrong, but it matches the ODS example
    ),
    AttrSpec(
        name="doi",
        rc=False,
        requirement=RECOMMENDED,
        required_if=None,
        cv=None,
        cv_strictness="warn",
        format_check=is_bare_doi,
        format_hint="must be a bare DOI such as '10.1234/example'",
    ),
    AttrSpec(
        name="external_variables",
        rc=False,
        requirement=OPTIONAL,
        required_if=None,
        cv=None,
        cv_strictness="warn",
        format_check=None,
        format_hint="must be one of the controlled vocabulary",
    ),
    AttrSpec(
        name="frequency",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="frequency",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/frequency
        cv_strictness="error",
        format_check=None,
        format_hint="must be one of the controlled vocabulary",
    ),
    AttrSpec(
        name="grid",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv=None,
        cv_strictness="warn",
        format_check=None,
        format_hint="describe the horizontal grid and re-gridding procedure, e.g., 'data re-gridded to a CMIP6 standard 1x1 degree latxlon grid from the native T63 grid using an area-average preserving method'",
    ),
    AttrSpec(
        name="grid_label",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="grid_label",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/grid_label
        cv_strictness="error",
        format_check=None,
        format_hint="must be one of the controlled vocabulary",
    ),
    AttrSpec(
        name="has_aux_unc",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="has_aux_unc",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/has_aux_unc
        cv_strictness="error",
        format_check=is_boolean_string,
        format_hint="must be 'TRUE' or 'FALSE'",
    ),
    AttrSpec(
        name="history",
        rc=False,
        requirement=OPTIONAL,
        required_if=None,
        cv=None,
        cv_strictness="warn",
        format_check=None,
        format_hint="a character string containing an audit trail for modifications to the original data where each modification is typically preceded by a 'timestamp'",
    ),
    AttrSpec(
        name="institution",
        rc=True,
        requirement=REQUIRED,
        required_if=None,
        cv="institution",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/institution_id; the "description" keys in the JSONs
        cv_strictness="warn",
        format_check=None,
        format_hint="name of the institution, city, state abbreviation, country abbreviation, e.g., 'National Oceanic and Atmospheric Administration, Silver Spring, Maryland, USA'",
    ),
    AttrSpec(
        name="institution_id",
        rc=True,
        requirement=REQUIRED,
        required_if=None,
        cv="institution_id",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/institution_id
        cv_strictness="warn",
        format_check=None,  # Can only contain a-z, A-Z, 0-9, and -
        format_hint="abbreviated identifier for the institution, e.g., 'NOAA'",
    ),
    AttrSpec(
        name="license",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="license",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/license
        cv_strictness="error",
        format_check=None,
        format_hint="a description of the data license, preferrably a CC license, e.g., 'Data in this file produced by <Your Centre Name> is licensed under a Creative Commons Attribution-4.0 International (CC BY 4.0) License (https://creativecommons.org/licenses/). Use of the data must be acknowledged following guidelines found at <a URL maintained by you>. Further information about this data, including some limitations, can be found via <some URL maintained by you>",
    ),
    AttrSpec(
        name="nominal_resolution",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="nominal_resolution",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/nominal_resolution
        cv_strictness="warn",
        format_check=is_nominal_resolution,
        format_hint="must be one of the controlled vocabulary",
    ),
    AttrSpec(
        name="processing_code_location",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv=None,  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/processing_code_location
        cv_strictness="warn",
        format_check=is_url,
        format_hint="must be an absolute HTTP(S) URL",
    ),
    AttrSpec(
        name="product",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="product",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/product
        cv_strictness="error",
        format_check=None,
        format_hint="must be one of the controlled vocabulary",
    ),
    AttrSpec(
        name="realm",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="realm",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/realm
        cv_strictness="error",
        format_check=None,
        format_hint="must be one of the controlled vocabulary",
    ),
    AttrSpec(
        name="references",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv=None,  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/references
        cv_strictness="warn",
        format_check=None,
        format_hint="a character string containing a list of published or web-based references that describe the data or the methods used to produce it",
    ),
    AttrSpec(
        name="region",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="region",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/region
        cv_strictness="error",
        format_check=None,
        format_hint="must be one of the controlled vocabulary",
    ),
    AttrSpec(
        name="site_id",
        rc=False,  # I believe this should be registered content, but in ODS, it is not
        requirement=REQUIRED,
        required_if=grid_is_site,
        cv="site_id",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/site_id
        cv_strictness="warn",
        format_check=None,
        format_hint="name for the in-situ measurement location if individual site, or 'collection' if multiple sites",
    ),
    AttrSpec(
        name="site_location",
        rc=False,  # Should also be RC and a description associated with site_id?
        requirement=REQUIRED,
        required_if=grid_is_site,  # no CV unless more than one point, then it should be 'collection'
        cv="site_location",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/site_location
        cv_strictness="warn",
        format_check=None,
        format_hint="must be one of the controlled vocabulary",
    ),
    AttrSpec(
        name="source",
        rc=True,
        requirement=REQUIRED,
        required_if=None,
        cv="source",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/source_id; the "description" keys in the jsons
        cv_strictness="warn",
        format_check=None,
        format_hint="the unabbreviated name of the dataset and the version",
    ),
    AttrSpec(
        name="source_id",
        rc=True,
        requirement=REQUIRED,
        required_if=None,
        cv="source_id",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/source_id
        cv_strictness="warn",
        format_check=is_clean_source_id,
        format_hint="the abbreviated dataset name and version; must not contain '.', '_', '(', ')', ' ', ':', or '/'",
    ),
    AttrSpec(
        name="source_label",
        rc=True,
        requirement=REQUIRED,
        required_if=None,
        cv=None,  # Currently missing this in https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/source_id
        cv_strictness="warn",
        format_check=None,
        format_hint="the abbreviated dataset name",
    ),
    AttrSpec(
        name="source_version_number",
        rc=True,
        requirement=REQUIRED,
        required_if=None,
        cv="source_version_number",  # Currently missing this in https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/source_id
        cv_strictness="warn",
        format_check=None,
        format_hint="the version number of the dataset",
    ),
    AttrSpec(
        name="source_data_notes",
        rc=False,
        requirement=OPTIONAL,
        required_if=None,
        cv=None,
        cv_strictness="warn",
        format_check=None,
        format_hint="any additional notes on the accessibility of the source data",
    ),
    AttrSpec(
        name="source_data_retrieval_date",
        rc=False,
        requirement=RECOMMENDED,
        required_if=None,
        cv=None,
        cv_strictness="warn",
        format_check=is_iso_utc,
        format_hint="must be ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ",
    ),
    AttrSpec(
        name="source_data_url",
        rc=False,
        requirement=RECOMMENDED,
        required_if=None,
        cv=None,
        cv_strictness="warn",
        format_check=is_url,
        format_hint="must be an http(s) URL",
    ),
    AttrSpec(
        name="source_type",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="source_type",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/source_type
        cv_strictness="error",
        format_check=None,
        format_hint="must be one of the controlled vocabularies",
    ),
    AttrSpec(
        name="title",
        rc=False,
        requirement=OPTIONAL,
        required_if=None,
        cv=None,
        cv_strictness="warn",
        format_check=None,
        format_hint="a general description of the dataset/variable that might include the institution_id and/or the variant; often used as a human-readable title above a map of the data",
    ),
    AttrSpec(
        name="tracking_id",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv=None,  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/tracking_id
        cv_strictness="warn",
        format_check=is_valid_tracking_id,
        format_hint="must be 'hdl:21.14102/<uuid>' with a valid UUID",
    ),
    AttrSpec(
        name="variable_id",
        rc=True,
        requirement=REQUIRED,
        required_if=None,
        cv="variable_id",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/variable_id
        cv_strictness="warn",
        format_check=None,
        format_hint="a unique identifier associated with the dataset's variable",
    ),
    AttrSpec(
        name="variant_info",
        rc=False,
        requirement=RECOMMENDED,
        required_if=variant_is_not_be,
        cv=None,
        cv_strictness="warn",
        format_check=None,
        format_hint="a description of who prepared the variant and a description of the variant itself",
    ),
    AttrSpec(
        name="variant_label",
        rc=False,
        requirement=REQUIRED,
        required_if=None,
        cv="variant_label",  # https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/main/variant_label
        cv_strictness="warn",
        format_check=None,  # the second half of variant_label, e.g., for RSS-BE, only BE is in the CV; for RSS-r1, only "r" is in the CV
        format_hint="the institution_id + variant_label CV + number if variant_label is 'r'; used when, e.g., an institution has multiple methods for estimating one variable_id",
    ),
]
