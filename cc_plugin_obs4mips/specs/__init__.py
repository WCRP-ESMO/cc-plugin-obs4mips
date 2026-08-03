"""Public specification API, defaulting to the current ODS 2.6.1 spec."""

from cc_plugin_obs4mips.specs.ods_2_6_1 import (
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
