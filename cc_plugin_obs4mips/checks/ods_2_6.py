"""
ODS 2.6: the attribute-specific and inter-attribute checks of this release.

The generic checks (presence, CV membership, DRS) are inherited from
`Obs4MipsCheckBase`. A later ODS version subclasses this class (see
docs/development/new_ods_version.md) and overrides only what changed.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from compliance_checker.base import Result

from cc_plugin_obs4mips.checks._helpers import (
    STANDARD_GRID_NOMINAL_RESOLUTIONS,
    _cell_edges,
    _is_standard_grid,
    _is_url,
    _nominal_resolution_km,
    _regular_latlon,
    mean_resolution_km,
    nominal_resolutions_km,
)
from cc_plugin_obs4mips.checks.base import ODS_WEIGHT, Obs4MipsCheckBase


class Obs4MipsCheck_2_6(Obs4MipsCheckBase):
    register_checker = True
    _cc_spec = "obs4mips"
    ods_version = "2.6"
    _cc_spec_version = ods_version
    _cc_description = f"WCRP-ESMO obs4MIPs {ods_version} compliance checks"

    PROCESSING_CODE_REGEX = r"https://github\.com/WCRP-ESMO/obs4MIPs/(blob|tree)/[0-9a-fA-F]{7,40}/examples(/.*)?"
    FORBIDDEN_ID_CHARS = re.compile(r"[._() :/]")
    DOI_REGEX = r"https://doi\.org/10\.\d{4,9}/\S+"
    UTC_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
    CELL_MEASURES = ("areacella", "areacello", "volcella", "volcello")
    LICENSE_GUIDANCE = (
        ("Data in this file produced by", "start with 'Data in this file produced by <Your Centre Name>'"),
        ("https://creativecommons.org/licenses/", "give the license URL (https://creativecommons.org/licenses/)"),
        ("acknowledged following guidelines found at", "say how to acknowledge the data ('Use of the data must be acknowledged following guidelines found at <URL>')"),
        ("Further information about this data", "point to further information ('Further information about this data, including some limitations, can be found via <URL>')"),
    )
    SITE_PRODUCT_VALUES = {
        "site-observations": {"grid": "site", "nominal_resolution": "site"},
        "site-collection": {
            "grid": "site-collection",
            "grid_label": "site-collection",
            "nominal_resolution": "site-collection",
            "site_id": "collection",
            "site_location": "collection",
        },
    }
    GRID_RESOLUTION_REGEX = re.compile(r"\d+(\.\d+)?\s*(x|by|×)\s*\d+(\.\d+)?", re.IGNORECASE)
    ODS_SITE_ATTRS = (
        "product",
        "nominal_resolution",
        "grid",
        "grid_label",
        "site_id",
        "site_location",
    )

    # Attribute-specific checks --------------------------------------------------------

    def check_contact(self, ds) -> list[Result]:
        """
        Recommend contact as 'Firstname Lastname (email)' or just 'email'.

        A missing contact is reported by check_global_attribute_presence at the severity
        of its ODS requirement. The ODS gives only guidance (not a rule) for the format
        of this free-text value, so that guidance is always shown as a low message.
        """
        contact = self.attrs.get("contact")
        if contact is None:
            return []
        email = r"[^\s()@]+@[^\s()@]+\.[^\s()@]+"
        if isinstance(contact, str) and re.fullmatch(
            rf"{email}|[^()]*\S\s*\({email}\)", contact.strip()
        ):
            return []
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Contact",
                msgs=[
                    "We recommend contact be 'Firstname Lastname (email)' or just an email, "
                    "e.g. 'Jane Doe (jane@example.org)' or 'jane@example.org'"
                ],
            )
        ]

    def check_creation_date(self, ds) -> list[Result]:
        """
        Check that creation_date is the same as the data file's actual creation date
        (its modification time, to within a day, since copies and time zones differ).
        """
        creation_date = self.attrs.get("creation_date")
        if not isinstance(creation_date, str):
            return []
        try:
            created = datetime.strptime(creation_date, self.UTC_TIMESTAMP_FORMAT)
        except ValueError:
            return []  # the CV pattern for creation_date reports a wrong format
        modified = datetime.fromtimestamp(
            Path(ds.filepath()).stat().st_mtime, timezone.utc
        )
        if abs(created.replace(tzinfo=timezone.utc) - modified) <= timedelta(days=1):
            return []
        return [
            Result(
                weight=ODS_WEIGHT["recommended"],
                value=False,
                name="Creation date",
                msgs=[
                    f"creation_date={creation_date!r} differs from the file's modification "
                    f"time {modified.strftime(self.UTC_TIMESTAMP_FORMAT)!r} by more than a day"
                ],
            )
        ]

    def check_data_specs_version(self, ds):
        """
        Right now, data_specs_version is freetext, but in the future I think it should
        be the CV version from the esgvoc_manifest.yaml file associated with the
        plugin's associated CV bundle. So, we'd:

        Check that the data_specs_version matches `cv_version` in the
        `esgvoc_manifest.yaml` in obs4MIPs_CVs. Would need to update cv_sync.py to
        include the esgvoc_manifest.yaml file.
        """
        return None

    def check_doi(self, ds) -> list[Result]:
        """
        DOI isn't in CVs, and ODS has mixed messaging about if it should be prepended
        with the https prefix, so I just make the https form the recommended format
        (versus a bare DOI without the https).
        """
        results = []
        for doi in self._tokens("doi", self.attrs.get("doi")):
            if not re.fullmatch(self.DOI_REGEX, doi):
                results.append(
                    Result(
                        weight=ODS_WEIGHT["optional"],
                        value=False,
                        name="DOI",
                        msgs=[
                            f"We recommend a DOI be written as a URL, 'https://doi.org/10.xxxx/xxxxxxxx'; found {doi!r}"
                        ],
                    )
                )
        return results

    def check_external_variables(self, ds) -> list[Result]:
        """
        If external_variables are cell measures, e.g., one or more of 'areacella',
        'areacello', 'volcella', 'volcello', recommend only using the 'bounds' attribute
        and dropping the cell measures from the external_variables list if the
        coordinate system is simple (regular latitude/longitude).
        """
        measures = [
            name
            for name in self._tokens(
                "external_variables", self.attrs.get("external_variables")
            )
            if name in self.CELL_MEASURES
        ]
        if not measures or _regular_latlon(ds) is None:
            return []
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="External variables",
                msgs=[
                    f"We recommend dropping {measures} from external_variables and using "
                    "the 'bounds' attribute of the latitude and longitude coordinates, "
                    "given that the grid is a simple regular latitude/longitude grid"
                ],
            )
        ]

    def check_grid(self, ds) -> list[Result]:
        """
        Recommend that the freetext grid attribute details the N by N resolution,
        horizontal and/or vertical datum, projection, re-gridding procedure if different
        from the original data, and any other relevant information regarding the grid.

        Only the resolution is checked (a number by a number, e.g. "2 x 2 degree"); the
        rest of the advice cannot be verified. Sites have no grid: check_site covers them.
        """
        grid = self.attrs.get("grid")
        if not isinstance(grid, str) or not grid.strip():
            return []  # a missing attribute is the presence check's business
        if self.attrs.get("product") in self.SITE_PRODUCT_VALUES:
            return []
        if self.GRID_RESOLUTION_REGEX.search(grid):
            return []
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Grid",
                msgs=[
                    "If not already done so, we recommend describing the grid as: "
                    "N by N resolution, horizontal and/or vertical datum, projection, and "
                    "the re-gridding procedure if different from the original data"
                ],
            )
        ]

    def check_grid_label(self, ds) -> list[Result]:
        """
        According to ODS, grid_label should be one of the CVs, or if one site, it should
        be `site-{site_id}`. So we should check that `site_id` matches the `site_id`
        nested in the `grid_label`.
        """
        grid_label = self.attrs.get("grid_label")
        if grid_label.startswith("site-"):
            actual_site_id = self.attrs.get("site_id")
            grid_label_site_id = grid_label.split("site-")[-1]
            if actual_site_id != grid_label_site_id:
                return [
                    Result(
                        weight=ODS_WEIGHT["optional"],
                        value=False,
                        name="Grid label",
                        msgs=[
                            f"site_id '{actual_site_id}' does not match the site_id in the grid_label '{grid_label}'"
                        ],
                    )
                ]

    def check_license(self, ds) -> list[Result]:
        """
        The recommended format is: “Data in this file produced by <Your Centre Name> is
        licensed under a Creative Commons Attribution-4.0 International (CC BY 4.0)
        License (https://creativecommons.org/licenses/). Use of the data must be
        acknowledged following guidelines found at <a URL maintained by you>. Further
        information about this data, including some limitations, can be found via
        <some URL maintained by you>.”

        Only the parts of that text are checked, not the exact wording: the CV for
        license requires a different spelling of the license name.
        """
        license_text = self.attrs.get("license")
        if not isinstance(license_text, str) or not license_text.strip():
            return []
        missing = [
            hint for marker, hint in self.LICENSE_GUIDANCE if marker not in license_text
        ]
        return (
            [
                Result(
                    weight=ODS_WEIGHT["optional"],
                    value=False,
                    name="License",
                    msgs=[f"We recommend the license text {hint}" for hint in missing],
                )
            ]
            if missing
            else []
        )

    def check_nominal_resolution(self, ds) -> list[Result]:
        """
        Nominal resolution is calculated in a specific way (see Appendix 2 of the CMIP6
        global attributes document), so check that nominal_resolution agrees with the
        mean resolution estimated from the latitude/longitude cell edges. Only regular
        latitude/longitude grids are supported; sites and other grids are skipped.

        The WIP standard 1x1 degree grid is labelled "1x1 degree" by the document, but
        that value is not in the CVs, so "100 km" is accepted for it too.
        """
        value = self.attrs.get("nominal_resolution")
        if not isinstance(value, str) or str(self.attrs.get("product", "")).startswith(
            "site"
        ):
            return []
        grid = _regular_latlon(ds)
        if grid is None:
            return []
        lat_edges, lon_edges = (_cell_edges(ds, name) for name in grid)
        if lat_edges is None or lon_edges is None:
            return []
        if _is_standard_grid(lat_edges, lon_edges):
            if value.strip() in STANDARD_GRID_NOMINAL_RESOLUTIONS:
                return []
            return [
                Result(
                    weight=ODS_WEIGHT["required"],
                    value=False,
                    name="Nominal resolution",
                    msgs=[
                        f"nominal_resolution={value!r} but the grid is the standard 1x1 degree "
                        "grid, whose nominal_resolution is '1x1 degree' (or '100 km')"
                    ],
                )
            ]
        stated = _nominal_resolution_km(value)
        if stated is None:
            return []  # a value that is not a distance is reported by the CV check
        mean = mean_resolution_km(lat_edges, lon_edges)
        accepted = nominal_resolutions_km(mean)
        if any(np.isclose(stated, label) for label in accepted):
            return []
        expected = " or ".join(f"{label:g} km" for label in sorted(accepted))
        return [
            Result(
                weight=ODS_WEIGHT["required"],
                value=False,
                name="Nominal resolution",
                msgs=[
                    f"nominal_resolution={value!r} does not match the grid: its mean "
                    f"resolution is {mean:.1f} km, which is {expected}"
                ],
            )
        ]

    def check_processing_code_location(self, ds) -> list[Result]:
        """
        Recommend that the processing_code_location attribute points to a valid URL
        where the processing code can be found or will be found.
        """
        location = self.attrs.get("processing_code_location")
        if (
            not isinstance(location, str)
            or not location.strip()
            or _is_url(location.strip())
        ):
            return []
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Processing code location",
                msgs=[
                    f"We recommend processing_code_location be an http(s) URL where the "
                    f"processing code can be found or will be found; found {location!r}"
                ],
            )
        ]

    def check_site(self, ds) -> list[Result]:
        """
        There are several attributes that are used with site data, and we want to check
        them all here. If data are sites or site collections:
        - "grid" should be "site" or "site-collection"
        - "grid_label" should be "site-<site_id>" or "site-collection"
        - nominal_resolution should be "site" or "site-collection"
        - product should be "site-observations" or "site-collection"
        - site_id should be present for individual sites or "collection" if multiple sites (collection not in CVs yet)
        - site_location should be a description, e.g., "location: San Luis,latitude: -33.4648,longitude: -66.4598", or "collection" for multiple sites (collection not in CVs yet)
        """
        product = self.attrs.get("product")
        if product not in self.SITE_PRODUCT_VALUES:
            return []
        expected = dict(self.SITE_PRODUCT_VALUES[product])
        if product == "site-observations":
            site_id = self.attrs.get("site_id")
            if isinstance(site_id, str) and site_id.strip():
                expected["grid_label"] = f"site-{site_id.strip()}"

        results = []
        for name, wanted in expected.items():
            value = self.attrs.get(name)
            if not isinstance(value, str) or not value.strip():
                continue  # absent or empty: check_global_attribute_presence reports it
            value = value.strip()
            if value == wanted:
                continue
            if (
                name == "grid_label"
                and product == "site-observations"
                and value.startswith("site-")
            ):
                continue  # a wrong site id in grid_label is reported by check_grid_label
            # describe the form, not the derived value (site_id may itself be a placeholder)
            shown = (
                "site-[site_id]"
                if name == "grid_label" and product == "site-observations"
                else wanted
            )
            results.append(
                Result(
                    weight=self._weight(name),
                    value=False,
                    name="Site",
                    msgs=[
                        f"{name} must be {shown!r} when product is {product!r}; found {value!r}"
                    ],
                )
            )
        return results

    def check_source_data_retrieval_date(self, ds) -> list[Result]:
        """
        Recommend that the source_data_retrieval_date attribute follows the ISO 8601 UTC
        format: YYYY-MM-DDTHH:MM:SSZ.
        """
        retrieved = self.attrs.get("source_data_retrieval_date")
        if not isinstance(retrieved, str) or not retrieved.strip():
            return []
        try:
            datetime.strptime(retrieved.strip(), self.UTC_TIMESTAMP_FORMAT)
            return []
        except ValueError:
            pass
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Source data retrieval date",
                msgs=[
                    f"We recommend source_data_retrieval_date be ISO 8601 UTC, YYYY-MM-DDTHH:MM:SSZ; found {retrieved!r}"
                ],
            )
        ]

    def check_source_data_url(self, ds) -> list[Result]:
        """
        Recommend that the source_data_url attribute points to a valid URL where the
        source data can be found (several URLs are separated by spaces).
        """
        return [
            Result(
                weight=ODS_WEIGHT["optional"],
                value=False,
                name="Source data URL",
                msgs=[
                    f"We recommend source_data_url be an http(s) URL where the source data can be found; found {url!r}"
                ],
            )
            for url in self._tokens("source_data_url", self.attrs.get("source_data_url"))
            if not _is_url(url)
        ]

    def check_source(self, ds) -> list[Result]:
        """
        There are several interelated source attributes in a NetCDF: source, source_id,
        source_label, and source_version_number. Source_id is used in the DRS, so it is
        already checked for illegal characters. Source_label is the same as source_id
        but with the appended source_version_number removed. Source_version_number is
        the same as the appended part of source_id but with illegal characters removed
        (non-numbers) and "." converted to "-".

        So source_id == source_label + "-" + <source_version_number with "." replaced by
        "-" and the remaining self.FORBIDDEN_ID_CHARS removed>, e.g. "CERES-EBAF" + "4.2"
        -> "CERES-EBAF-4-2". The check is case sensitive because these are registered
        content. source_id's own characters are checked by check_drs.

        source itself is not checked here: the ODS only calls it a description, and its
        more detailed template uses facts (release year, source description) that are
        not global attributes.
        """
        attrs = {
            name: self.attrs.get(name)
            for name in ("source_id", "source_label", "source_version_number")
        }
        if not all(isinstance(v, str) and v.strip() for v in attrs.values()):
            return []  # absent or empty: check_global_attribute_presence reports it
        source_id, label, version = (attrs[n].strip() for n in attrs)
        results = []

        suffix = self.FORBIDDEN_ID_CHARS.sub("", version.replace(".", "-"))
        expected = f"{label}-{suffix}" if suffix else label
        if source_id != expected:
            if not source_id.startswith(label):
                culprit, detail = (
                    "source_label",
                    f"source_id {source_id!r} does not start with source_label {label!r}",
                )
            else:
                culprit, detail = (
                    "source_version_number",
                    f"source_id {source_id!r} ends in {source_id[len(label) :]!r} after "
                    f"source_label {label!r}, but source_version_number {version!r} "
                    f"gives {('-' + suffix) if suffix else ''!r}",
                )
            results.append(
                Result(
                    weight=self._weight(culprit),
                    value=False,
                    name="Source",
                    msgs=[
                        f"source_id must be source_label + '-' + source_version_number "
                        f"(with '.' as '-' and {self.FORBIDDEN_ID_CHARS.pattern} removed), "
                        f"i.e. {expected!r}; {detail}"
                    ],
                )
            )
        return results
