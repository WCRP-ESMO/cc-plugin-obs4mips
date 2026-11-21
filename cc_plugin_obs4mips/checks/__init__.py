"""
Checks for the Obs4MIPs Data Specifications, one class per ODS version.

  base.py     Obs4MipsCheckBase: the logic every ODS version shares
  ods_2_6.py  Obs4MipsCheck_2_6: what ODS 2.6 adds on top of it

`Obs4MipsCheck` is the newest version (the `obs4mips` suite). Add a version by following
docs/development/new_ods_version.md.
"""

from cc_plugin_obs4mips.checks._helpers import (
    mean_resolution_km,
    nominal_resolutions_km,
    _nominal_resolution_km,
)
from cc_plugin_obs4mips.checks.base import ODS_WEIGHT, Obs4MipsCheckBase
from cc_plugin_obs4mips.checks.ods_2_6 import Obs4MipsCheck_2_6

Obs4MipsCheck = Obs4MipsCheck_2_6  # newest ODS version

__all__ = [
    "ODS_WEIGHT",
    "Obs4MipsCheck",
    "Obs4MipsCheckBase",
    "Obs4MipsCheck_2_6",
    "mean_resolution_km",
    "nominal_resolutions_km",
    "_nominal_resolution_km",
]
