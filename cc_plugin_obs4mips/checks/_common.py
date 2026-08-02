"""Generic check methods that consume any spec list via ``self.SPECS``."""

from compliance_checker.base import BaseCheck, BaseNCCheck, Result

from cc_plugin_obs4mips.cv import CV
from cc_plugin_obs4mips.specs.ods_2_6 import (
    FORBIDDEN_ID_CHARS,
    RECOMMENDED,
    REQUIRED,
)


class Obs4MipsBaseCheck(BaseNCCheck):
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
            if not applies or spec.level not in (REQUIRED, RECOMMENDED):
                continue
            present = spec.name in self._attrs
            results.append(
                Result(
                    spec.level,
                    present,
                    "Required global attributes",
                    [] if present else [f"missing: {spec.name}"],
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
            weight = REQUIRED if spec.cv_strictness == "error" else RECOMMENDED
            valid = CV.contains(self.CV_VERSION, spec.cv, value)
            results.append(
                Result(
                    weight,
                    valid,
                    "Global attribute CV membership",
                    []
                    if valid
                    else [f"{spec.name}={value!r} not in CV '{spec.cv}'"],
                )
            )
        return results

    def check_source_id_matches_label_and_version(self, ds):
        """Check source_id against source_label and source_version_number."""
        needed = {"source_id", "source_label", "source_version_number"}
        if not needed.issubset(self._attrs):
            return None
        expected = f"{ds.source_label}-{ds.source_version_number}"
        expected = FORBIDDEN_ID_CHARS.sub("-", expected)
        valid = ds.source_id == expected
        return Result(
            REQUIRED,
            valid,
            "source_id derived from source_label + source_version_number",
            [] if valid else [f"source_id={ds.source_id!r} != expected {expected!r}"],
        )

    def check_institution_matches_institution_id(self, ds):
        """Check that institution references institution_id."""
        if not {"institution", "institution_id"}.issubset(self._attrs):
            return None
        institution = ds.institution
        institution_id = ds.institution_id
        valid = institution_id in institution or any(
            part and part in institution for part in institution_id.split("-")
        )
        return Result(
            RECOMMENDED,
            valid,
            "institution references institution_id",
            []
            if valid
            else [
                f"institution={institution!r} does not reference "
                f"institution_id={institution_id!r}"
            ],
        )

    def check_anomaly_variable_naming(self, ds):
        """Require anomaly variable IDs to end in ``anom``."""
        if not {"units_metadata", "variable_id"}.issubset(self._attrs):
            return None
        if "difference" not in ds.units_metadata.lower():
            return None
        valid = ds.variable_id.endswith("anom")
        return Result(
            REQUIRED,
            valid,
            "anomaly variables suffixed with 'anom'",
            []
            if valid
            else [
                f"units_metadata={ds.units_metadata!r} indicates an anomaly; "
                f"variable_id={ds.variable_id!r} should end in 'anom'"
            ],
        )

    def check_license_text(self, ds):
        """Check that the license references CC BY 4.0."""
        if "license" not in self._attrs:
            return None
        license_text = ds.license
        valid = (
            "CC BY 4.0" in license_text
            or "creativecommons.org/licenses/by/4.0" in license_text
        )
        return Result(
            REQUIRED,
            valid,
            "license references CC-BY-4.0",
            []
            if valid
            else [
                "license should reference 'CC BY 4.0' and "
                "https://creativecommons.org/licenses/by/4.0/"
            ],
        )
