"""Generic check methods that consume any spec list via ``self.SPECS``."""

from compliance_checker.base import BaseCheck, BaseNCCheck, Result

from cc_plugin_obs4mips.cv import CV
from cc_plugin_obs4mips.specs.ods_2_6_1 import (
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
                    [] if valid else [f"{spec.name}={value!r} not in CV '{spec.cv}'"],
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

    def check_anomaly_variable_naming(self, ds):
        """Keep variable-level difference metadata and the ``anom`` suffix aligned."""
        if "variable_id" not in self._attrs:
            return None

        variable_id = ds.variable_id
        variables = getattr(ds, "variables", {})
        variable = variables.get(variable_id)
        if variable is None:
            return None

        units_metadata = getattr(variable, "units_metadata", None)
        is_difference = isinstance(units_metadata, str) and (
            "difference" in units_metadata.lower()
        )
        has_anomaly_suffix = variable_id.endswith("anom")
        if not is_difference and not has_anomaly_suffix:
            return None

        messages = []
        if is_difference and not has_anomaly_suffix:
            messages.append(
                f"{variable_id}:units_metadata={units_metadata!r} identifies a "
                "difference, so variable_id must end in 'anom'"
            )
        if has_anomaly_suffix and not is_difference:
            messages.append(
                f"{variable_id} is an anomaly variable and must define variable-level "
                "units_metadata identifying it as a difference"
            )
        return Result(
            REQUIRED,
            not messages,
            "Anomaly variable naming and units metadata",
            messages,
        )

    def check_site_metadata_consistency(self, ds):
        """Validate the non-CV relationships among ODS site attributes."""
        values = {
            name: str(getattr(ds, name, "")).strip()
            for name in (
                "product",
                "nominal_resolution",
                "grid",
                "grid_label",
                "site_id",
                "site_location",
            )
        }
        lowered = {name: value.lower() for name, value in values.items()}
        site_markers = {
            lowered["product"],
            lowered["nominal_resolution"],
            lowered["grid"],
            lowered["grid_label"],
        }
        is_collection = "site-collection" in site_markers
        is_individual = bool(site_markers & {"site", "site-observations"}) or lowered[
            "grid_label"
        ].startswith("site-")
        if not is_collection and not is_individual:
            return None

        problems = []
        if is_collection:
            expected = {
                "product": "site-collection",
                "nominal_resolution": "site-collection",
                "grid": "site-collection",
                "grid_label": "site-collection",
                "site_id": "collection",
                "site_location": "collection",
            }
            for name, expected_value in expected.items():
                if name in self._attrs and lowered[name] != expected_value:
                    problems.append(
                        f"{name}={values[name]!r}; expected {expected_value!r} for a "
                        "site collection"
                    )
        else:
            expected = {
                "product": "site-observations",
                "nominal_resolution": "site",
                "grid": "site",
            }
            for name, expected_value in expected.items():
                if name in self._attrs and lowered[name] != expected_value:
                    problems.append(
                        f"{name}={values[name]!r}; expected {expected_value!r} for an "
                        "individual site"
                    )

            if "grid_label" in self._attrs:
                # Appendix 3 says ``site`` while Table 1 says ``site-<site_id>``.
                # Accept both forms until that draft inconsistency is resolved.
                allowed_grid_labels = {"site"}
                if values["site_id"]:
                    allowed_grid_labels.add(f"site-{lowered['site_id']}")
                if lowered["grid_label"] not in allowed_grid_labels:
                    problems.append(
                        f"grid_label={values['grid_label']!r}; expected 'site' or "
                        f"'site-{values['site_id']}' for an individual site"
                    )

        return Result(
            REQUIRED,
            not problems,
            "Site metadata consistency",
            problems,
        )

    def check_license_text(self, ds):
        """Recommend the Creative Commons reference suggested by ODS note 13."""
        if "license" not in self._attrs:
            return None
        license_text = ds.license
        valid = isinstance(license_text, str) and (
            "creative commons" in license_text.lower()
            or "creativecommons.org/licenses/" in license_text.lower()
        )
        return Result(
            RECOMMENDED,
            valid,
            "License references a Creative Commons license",
            []
            if valid
            else [
                "ODS recommends referencing a Creative Commons license; other "
                "license terms remain permitted"
            ],
        )
