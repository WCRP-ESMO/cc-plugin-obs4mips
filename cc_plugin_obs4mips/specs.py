"""
The ODS facts that live in this tool instead of the CVs repo.

Almost everything about the Obs4MIPs Data Specifications (ODS) is read from the bundle
`cv_data/obs4mips.json`, which `scripts/sync_cvs.py` generates from the obs4MIPs_CVs
repository: attribute names, requirement levels, conditions, separators, allowed values,
regex patterns and the DRS (file name and directory) part lists.

What is left here are the things the CVs cannot express. If you are about to add another
ODS fact to this file, check first whether it belongs in the CVs repo instead.

Sections:
  BUNDLE              the generated CV data (read only)
  CV_STRICTNESS       tool policy: which CV mismatches are errors rather than warnings
  FORMAT_CHECKS       formats a regex or a CV list cannot express
  FREQUENCY_TIME_DIGITS, VERSION_REGEX, FORBIDDEN_ID_CHARS
                      small ODS facts that have no home in the CVs yet
"""

import json
import re
from importlib.resources import files
from urllib.parse import urlsplit
from uuid import UUID

BUNDLE = json.loads(
    files("cc_plugin_obs4mips").joinpath("cv_data/obs4mips.json").read_text(encoding="utf-8")
)

# A CV mismatch for these attributes is an error (high weight). Any other CV mismatch is
# a warning (medium weight). This is a policy of this tool, not an ODS rule.
CV_STRICTNESS = {
    "activity_id",
    "frequency",
    "grid_label",
    "has_aux_unc",
    "product",
    "realm",
    "region",
    "source_type",
}


def _is_url(value):
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _is_uuid(value):
    try:
        UUID(value.rsplit("/", 1)[-1])
    except ValueError:
        return False
    return True


# attribute name -> (function(token) -> bool, hint shown on failure).
# The function is called on each space-separated token if the attribute has a separator.
FORMAT_CHECKS = {
    "contact": (
        lambda v: bool(re.search(r"\([^\s()]+@[^\s()]+\.[^\s()]+\)", v)),
        "must contain an email address in parentheses, e.g. 'Jane Doe (jane@example.org)'",
    ),
    "doi": (
        lambda v: bool(re.fullmatch(r"10\.\d{4,9}/\S+", v)),
        "must be a bare DOI such as '10.5281/zenodo.1234567' (no https://doi.org/ prefix)",
    ),
    "processing_code_location": (_is_url, "must be an http(s) URL"),
    "source_data_retrieval_date": (
        lambda v: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", v)),
        "must be ISO 8601 UTC: YYYY-MM-DDTHH:MM:SSZ",
    ),
    "source_data_url": (_is_url, "must be an http(s) URL"),
    "tracking_id": (_is_uuid, "must end in a valid UUID"),
}

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
PROCESSING_CODE_REGEX = (
    r"https://github\.com/WCRP-ESMO/obs4MIPs/(blob|tree)/[0-9a-fA-F]{7,40}/examples(/.*)?"
)

# Characters that source_label + source_version_number may not keep in source_id
FORBIDDEN_ID_CHARS = re.compile(r"[._() :/]")
