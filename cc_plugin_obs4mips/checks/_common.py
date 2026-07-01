"""Generic check methods that consume any spec list via self.SPECS."""

from compliance_checker.base import BaseNCCheck


class Obs4MipsBaseCheck(BaseNCCheck):
    SPECS: list = []  # subclasses bind this
    CV_VERSION: str = ""  # subclasses bind this; CV.contains uses it

    def setup(self, ds):
        self._attrs = set(ds.ncattrs())
