"""
Check methods that can be used in all ODS versions.

Checks include:
- Check that all CV tables expected by the specification are available
- Check that required and recommended global attributes are present
- Validate global attribute formats
- Check controlled-vocabulary membership
"""

from compliance_checker.base import BaseCheck, BaseNCCheck, Result

from cc_plugin_obs4mips.cv import CV


class Obs4MipsBaseCheck(BaseNCCheck, BaseCheck):
    SPECS: list = []  # subclasses bind this
    CV_VERSION: str = ""  # subclasses bind this; CV.contains uses it
    _cc_display_headers = {
        BaseCheck.HIGH: "Required",
        BaseCheck.MEDIUM: "Recommended",
        BaseCheck.LOW: "Suggested",
    }

    def setup(self, ds):
        self._attrs = set(ds.ncattrs())

    def check_cv_tables_available(self, ds):
        """Check that all CV tables expected by the specification are available."""
        expected = {spec.cv for spec in self.SPECS if spec.cv}
        missing = sorted(
            table for table in expected if not CV.is_loaded(self.CV_VERSION, table)
        )
        return Result(
            BaseCheck.LOW,
            not missing,
            "CV tables shipped with plugin",
            [f"CV table not loaded (treated as always-valid): {t}" for t in missing],
        )

    def check_global_attributes_present(self, ds):
        """Check that required and recommended global attributes are present."""
        results = []
        for spec in self.SPECS:
            applies = spec.required_if is None or spec.required_if(ds)
            if not applies or spec.level not in (
                BaseCheck.HIGH,
                BaseCheck.MEDIUM,
            ):
                continue
            present = spec.name in self._attrs
            message = f"missing: {spec.name}"
            if present:
                value = getattr(ds, spec.name)
                if isinstance(value, str) and not value.strip():
                    present = False
                    message = f"empty or whitespace-only: {spec.name}"
            results.append(
                Result(
                    spec.level,
                    present,
                    "Required global attributes",
                    [] if present else [message],
                )
            )
        return results

    def check_global_attribute_formats(self, ds):
        """Validate attributes for which the specification defines a format."""
        results = []
        for spec in self.SPECS:
            if spec.format_check is None or spec.name not in self._attrs:
                continue
            value = getattr(ds, spec.name)
            valid = isinstance(value, str) and spec.format_check(value)
            results.append(
                Result(
                    spec.level,
                    valid,
                    "Global attribute formats",
                    [] if valid else [f"{spec.name}={value!r}: {spec.format_hint}"],
                )
            )
        return results

    def check_global_attribute_cv(self, ds):
        """Check controlled-vocabulary membership."""
        results = []
        for spec in self.SPECS:
            if spec.cv is None or spec.name not in self._attrs:
                continue
            value = getattr(ds, spec.name)
            weight = (
                BaseCheck.HIGH
                if spec.cv_strictness == "error"
                else BaseCheck.MEDIUM
            )
            if not CV.is_loaded(self.CV_VERSION, spec.cv):
                continue
            values = (
                value.split()
                if isinstance(value, str)
                and spec.name in {"activity_id", "realm", "region"}
                else [value]
            )
            messages = []
            for candidate in values:
                if not isinstance(candidate, str):
                    messages.append(
                        f"{spec.name}={candidate!r} must be a string to be checked "
                        f"against CV {spec.cv!r}"
                    )
                    continue
                if CV.contains(self.CV_VERSION, spec.cv, candidate):
                    continue
                message = (
                    f"{spec.name}={candidate!r} is not registered in CV "
                    f"{spec.cv!r}. Before requesting a new term, check whether an "
                    "existing CV term should be used."
                )
                suggestions = CV.suggestions(self.CV_VERSION, spec.cv, candidate)
                if suggestions:
                    message += " Similar registered terms: " + ", ".join(
                        repr(suggestion) for suggestion in suggestions
                    )
                messages.append(message)
            results.append(
                Result(
                    weight,
                    not messages,
                    "Unregistered controlled vocabulary terms",
                    messages,
                )
            )
        return results
