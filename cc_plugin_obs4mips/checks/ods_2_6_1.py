from cc_plugin_obs4mips import __version__
from cc_plugin_obs4mips.checks._common import Obs4MipsBaseCheck
from cc_plugin_obs4mips.specs.ods_2_6_1 import GLOBAL_ATTR_SPECS


class Obs4Mips2_6_1Check(Obs4MipsBaseCheck):
    register_checker = True
    _cc_spec = "obs4mips"
    _cc_spec_version = "2.6.1"
    _cc_description = "WCRP-ESMO obs4MIPs 2.6.1 compliance checks"
    _cc_checker_version = __version__
    SPECS = GLOBAL_ATTR_SPECS
    CV_VERSION = "2.6.1"
