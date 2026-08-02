"""Public specification API, defaulting to the current ODS 2.6 spec."""

from cc_plugin_obs4mips.specs.ods_2_6 import (
    FORBIDDEN_ID_CHARS,
    GLOBAL_ATTR_SPECS,
    OPTIONAL,
    RECOMMENDED,
    REQUIRED,
    AttrSpec,
)

__all__ = [
    "AttrSpec",
    "FORBIDDEN_ID_CHARS",
    "GLOBAL_ATTR_SPECS",
    "OPTIONAL",
    "RECOMMENDED",
    "REQUIRED",
]
