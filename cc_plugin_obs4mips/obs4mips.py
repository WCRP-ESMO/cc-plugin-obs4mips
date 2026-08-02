"""Backward-compatible import for the obs4MIPs 2.6 checker."""

from cc_plugin_obs4mips.checks.ods_2_6 import Obs4Mips2_6Check

# Keep installations made with the original entry point working.  New installs use
# ``cc_plugin_obs4mips.checks.ods_2_6:Obs4Mips2_6Check`` directly.
Obs4MipsCheck = Obs4Mips2_6Check

__all__ = ["Obs4MipsCheck"]
