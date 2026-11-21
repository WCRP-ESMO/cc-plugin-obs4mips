"""
Enumerations (constants or sets of constants) that can be used by checks.py
"""

import re

from cc_plugin_obs4mips.cv_sync import load_bundle

# The CV data bundle generated from the obs4MIPs_CVs repository: the copy a user updated
# with `obs4mips-update-cvs`, else the one packaged with the tool
BUNDLE = load_bundle()

# Number of digits in each date of the file-name time_range, per frequency.
FREQUENCY_TIME_DIGITS = {
    "yr": 4, "dec": 4, "yrPt": 4,
    "mon": 6, "monC": 6, "monPt": 6,
    "day": 8,
    "6hr": 12, "3hr": 12, "1hr": 12, "1hrCM": 12, "6hrPt": 12, "3hrPt": 12, "1hrPt": 12,
    "subhrPt": 14,
}  # fmt: skip

# The last directory of the DRS: vYYYYMMDD
VERSION_REGEX = r"v\d{8}"

# ODS recommends processing scripts live in the obs4MIPs repo, pinned to a revision
PROCESSING_CODE_REGEX = r"https://github\.com/WCRP-ESMO/obs4MIPs/(blob|tree)/[0-9a-fA-F]{7,40}/examples(/.*)?"

# Characters that source_label + source_version_number may not keep in source_id
FORBIDDEN_ID_CHARS = re.compile(r"[._() :/]")

# DRS values may only contain these characters (variable_id may not contain "-")
DRS_VALUE_REGEX = r"[A-Za-z0-9-]+"
DRS_VARIABLE_ID_REGEX = r"[A-Za-z0-9]+"

# ODS recommends the DOI as a URL: https://doi.org/10.xxxx/xxxxxxxx
DOI_REGEX = r"https://doi\.org/10\.\d{4,9}/\S+"

# Format of creation_date and source_data_retrieval_date: ISO 8601 in UTC
UTC_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Cell measures that may be listed in external_variables
CELL_MEASURES = ("areacella", "areacello", "volcella", "volcello")

# ODS recommends the license text contain these parts (marker text, what it is for)
LICENSE_GUIDANCE = (
    ("Data in this file produced by", "start with 'Data in this file produced by <Your Centre Name>'"),
    ("https://creativecommons.org/licenses/", "give the license URL (https://creativecommons.org/licenses/)"),
    ("acknowledged following guidelines found at", "say how to acknowledge the data ('Use of the data must be acknowledged following guidelines found at <URL>')"),
    ("Further information about this data", "point to further information ('Further information about this data, including some limitations, can be found via <URL>')"),
)  # fmt: skip

# nominal_resolution (CMIP6 global attributes document, Appendix 2): mean resolution of
# the grid in km is labelled with the first label whose upper bound it is below
EARTH_RADIUS_KM = 6371.0
NOMINAL_RESOLUTION_UPPER_BOUNDS_KM = (0.72, 1.6, 3.6, 7.2, 16, 36, 72, 160, 360, 720, 1600, 3600, 7200)  # fmt: skip
NOMINAL_RESOLUTION_LABELS_KM = (0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)  # fmt: skip
NOMINAL_RESOLUTION_BOUNDARY_TOLERANCE = 0.03  # the document adjusted bounds by < 3%
# the one grid for which the label is "1x1 degree" instead of "100 km"
STANDARD_GRID_NOMINAL_RESOLUTIONS = ("1x1 degree", "100 km")

# Values that site data must use, by product (ODS notes on grid, grid_label,
# nominal_resolution, site_id and site_location). grid_label of a single site is
# "site-" + site_id, so it is built in check_site. "collection" is not in the site_id CV yet
SITE_PRODUCT_VALUES = {
    "site-observations": {"grid": "site", "nominal_resolution": "site"},
    "site-collection": {
        "grid": "site-collection",
        "grid_label": "site-collection",
        "nominal_resolution": "site-collection",
        "site_id": "collection",
        "site_location": "collection",
    },
}
