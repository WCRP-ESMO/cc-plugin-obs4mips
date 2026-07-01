"""
EXAMPLE (NOT IMPLEMENTED): obs4MIPs 2.7 global attribute spec, derived from 2.6.

This is how we would implement new specs on top of previous versions, using the
`derive_spec` helper below to make it clear what's changed.
"""

from cc_plugin_obs4mips.specs._base import (
    RECOMMENDED,  # type: ignore
    REQUIRED,  # type: ignore
    AttrSpec,
    derive_spec,
)
from cc_plugin_obs4mips.specs.ods_2_6 import GLOBAL_ATTR_SPECS as V2_6

# Changes from 2.6 -> 2.7:
#   + new required attribute: ensemble_id
#   - removed: aux_uncertainty_id (folded into the variable-level metadata)
#   ~ doi: optional -> recommended
#   ~ data_specs_version: format check now requires "2.7"

GLOBAL_ATTR_SPECS = derive_spec(
    V2_6,  # type: ignore
    add=[
        AttrSpec("ensemble_id", REQUIRED),
    ],
    remove=["aux_uncertainty_id"],
    update={
        "doi": {"level": RECOMMENDED},
        "data_specs_version": {
            "format_check": lambda v: v == "2.7",
            "format_hint": "must be '2.7'",
        },
    },
)
