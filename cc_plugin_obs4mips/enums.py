"""
Enumerations (constants or sets of constants) that can be used by checks.py
"""

import json
import re
from importlib.resources import files

# Load the CV data bundle generated from the obs4MIPs_CVs repository
BUNDLE = json.loads(
    files("cc_plugin_obs4mips")
    .joinpath("cv_data/obs4mips.json")
    .read_text(encoding="utf-8")
)

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
