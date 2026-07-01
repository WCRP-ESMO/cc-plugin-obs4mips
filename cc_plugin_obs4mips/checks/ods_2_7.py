"""
EXAMPLE (NOT IMPLEMENTED): obs4MIPs 2.7 global attribute spec, derived from 2.6.

This is how we would implement new CHECKS on top of previous versions, using the
`derive_spec` helper below to make it clear what's changed.
"""

from cc_plugin_obs4mips.checks.ods_2_6 import Obs4Mips2_6Check
from cc_plugin_obs4mips.specs.ods_2_7 import GLOBAL_ATTR_SPECS


class Obs4Mips2_7Check(Obs4Mips2_6Check):
    register_checker = True
    _cc_spec_version = "2.7"
    SPECS = GLOBAL_ATTR_SPECS
    CV_VERSION = "2.7"

    # Override or add cross-field checks only where 2.7 differs
    def check_ensemble_id_format(self, ds):
        """New Check for 2.7"""
        pass
