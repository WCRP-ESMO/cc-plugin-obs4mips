"""
cc_plugin_obs4mips.obs4mips:Obs4MipsChecker

obs4MIPs CheckSuite that IOOS Compliance Checker will discover at run-time.
"""

import typing

from cc_plugin_obs4mips import __version__
from compliance_checker.base import BaseNCCheck, Result


class Obs4MipsCheck(BaseNCCheck):
    """BaseObs4MipsCheck"""

    register_checker = True
    _cc_spec = "obs4mips"
    _cc_spec_version = "2.6.1"
    _cc_checker_version = __version__
    _cc_display_headers: typing.ClassVar[dict] = {
        3: "Required",
        2: "Recommended",
        1: "Suggested",
    }

    @classmethod
    def __init__(cls):