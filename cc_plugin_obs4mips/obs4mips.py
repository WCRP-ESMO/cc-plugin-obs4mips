"""obs4MIPs 2.6 compliance checks."""

from __future__ import annotations

from compliance_checker.base import BaseNCCheck, Result

from cc_plugin_obs4mips import __version__
from cc_plugin_obs4mips.cv import CV
from cc_plugin_obs4mips.specs import (
    FORBIDDEN_ID_CHARS,
    GLOBAL_ATTR_SPECS,
    RECOMMENDED,
    REQUIRED,
)


class Obs4MipsCheck(BaseNCCheck):
    register_checker = True
    _cc_spec = "obs4mips"
    _cc_spec_version = "2.6"
    _cc_description = "WCRP-ESMO obs4MIPs 2.6 compliance checks"
    _cc_url = "TBD"
    _cc_authors = "Morgan Steckler"
    _cc_checker_version = __version__

    def setup(self, ds):
        self._attrs = set(ds.ncattrs())

    def check_cv_tables_available(self, ds):
        expected = {s.cv for s in GLOBAL_ATTR_SPECS if s.cv}
        missing = sorted(t for t in expected if not CV.is_loaded(t))
        return Result(
            BaseCheck.LOW,
            not missing,
            "CV tables shipped with plugin",
            [f"CV table not loaded (treated as always-valid): {t}" for t in missing],
        )

    # ---- presence ----------------------------------------------------------

    def check_global_attributes_present(self, ds):
        """All required (incl. conditionally required) global attributes are present."""
        results = []
        for spec in GLOBAL_ATTR_SPECS:
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

    # ---- format ------------------------------------------------------------

    def check_global_attribute_formats(self, ds):
        """Format validation for attributes that specify one."""
        results = []
        for spec in GLOBAL_ATTR_SPECS:
            if spec.format_check is None or spec.name not in self._attrs:
                continue
            value = getattr(ds, spec.name)
            ok = isinstance(value, str) and spec.format_check(value)
            results.append(
                Result(
                    spec.level,
                    ok,
                    "Global attribute formats",
                    [] if ok else [f"{spec.name}={value!r}: {spec.format_hint}"],
                )
            )
        return results

    # ---- controlled vocabulary --------------------------------------------

    def check_global_attribute_cv(self, ds):
        """CV membership. 'error' strictness fails as HIGH; 'warn' as MEDIUM."""
        results = []
        for spec in GLOBAL_ATTR_SPECS:
            if spec.cv is None or spec.name not in self._attrs:
                continue
            value = getattr(ds, spec.name)
            weight = REQUIRED if spec.cv_strictness == "error" else RECOMMENDED
            in_cv = CV.contains(spec.cv, value)
            results.append(
                Result(
                    weight,
                    in_cv,
                    "Global attribute CV membership",
                    [] if in_cv else [f"{spec.name}={value!r} not in CV '{spec.cv}'"],
                )
            )
        return results

    # ---- cross-field consistency ------------------------------------------

    def check_source_id_matches_label_and_version(self, ds):
        """source_id should equal '<source_label>-<source_version_number>' (cleaned)."""
        needed = {"source_id", "source_label", "source_version_number"}
        if not needed.issubset(self._attrs):
            return None
        expected = f"{ds.source_label}-{ds.source_version_number}"
        expected_clean = FORBIDDEN_ID_CHARS.sub("-", expected)
        ok = ds.source_id == expected_clean
        return Result(
            REQUIRED,
            ok,
            "source_id derived from source_label + source_version_number",
            []
            if ok
            else [f"source_id={ds.source_id!r} != expected {expected_clean!r}"],
        )

    def check_institution_matches_institution_id(self, ds):
        """institution string should reference institution_id."""
        if not {"institution", "institution_id"}.issubset(self._attrs):
            return None
        inst = ds.institution
        inst_id = ds.institution_id
        ok = inst_id in inst or any(
            part and part in inst for part in inst_id.split("-")
        )
        return Result(
            RECOMMENDED,
            ok,
            "institution references institution_id",
            []
            if ok
            else [
                f"institution={inst!r} does not reference institution_id={inst_id!r}"
            ],
        )

    def check_anomaly_variable_naming(self, ds):
        """If units_metadata signals an anomaly, variable_id should end in 'anom'."""
        if not {"units_metadata", "variable_id"}.issubset(self._attrs):
            return None
        if "difference" not in ds.units_metadata.lower():
            return None
        ok = ds.variable_id.endswith("anom")
        return Result(
            REQUIRED,
            ok,
            "anomaly variables suffixed with 'anom'",
            []
            if ok
            else [
                f"units_metadata={ds.units_metadata!r} indicates an anomaly; "
                f"variable_id={ds.variable_id!r} should end in 'anom'"
            ],
        )

    def check_license_text(self, ds):
        """license should reference CC BY 4.0."""
        if "license" not in self._attrs:
            return None
        lic = ds.license
        ok = "CC BY 4.0" in lic or "creativecommons.org/licenses/by/4.0" in lic
        return Result(
            REQUIRED,
            ok,
            "license references CC-BY-4.0",
            []
            if ok
            else [
                "license should reference 'CC BY 4.0' and "
                "https://creativecommons.org/licenses/by/4.0/"
            ],
        )

    def check_file_name(self, ds):
        """
        Should be <variable_id>_<frequency>_<source_id>_<variant_label>_<grid_label>_[_<time_range>].nc
        E.g., siconc_mon_OSI-SAF-450-a-3-0_PCMDI-BE_gr1_185001-202301.nc
        Only allow characters a-z, A-Z, 0-9, and hyphen (except no hyphen in variable_id)
        """
        pass

    def check_file_directory(self, ds):
        """
        Should be in a directory structure like <activity_id>/<institution_id>/<source_id>/<frequency>/<variable_id>/<nominal_resolution>/<version>/
        where version is vYYYYMMDD when the NetCDF was produced
        E.g., obs4MIPs/NOAA-NCEI/OSI-SAF-450-a-3-0/mon/siconc/1x1 degree/4.1/
        """
        pass

    def check_coord_bounds(self, ds):
        """If not coordinate bounds, recommend adding them; sites shouldn't have lat/lon dims, they should have lot/lon vars linked to site dim"""
        pass
