import inspect
import re

import numpy as np
import pytest
from compliance_checker.base import BaseCheck
from netCDF4 import Dataset

from cc_plugin_obs4mips.checks import (
    Obs4MipsCheck,
    _nominal_resolution_km,
    mean_resolution_km,
    nominal_resolutions_km,
)
from tests.conftest import GOOD_VALUES, failed, messages

BUNDLE = Obs4MipsCheck.bundle()
ODS_ATTRS = BUNDLE["attributes"]
ODS_DRS = BUNDLE["drs"]
DRS_VALUE_REGEX = Obs4MipsCheck.DRS_VALUE_REGEX
FREQUENCY_TIME_DIGITS = Obs4MipsCheck.FREQUENCY_TIME_DIGITS
split_value = Obs4MipsCheck.split_value
unregistered_terms = Obs4MipsCheck.unregistered_terms

CHECK_METHODS = [m for m in dir(Obs4MipsCheck) if m.startswith("check_")]
HIGH, MEDIUM, LOW = BaseCheck.HIGH, BaseCheck.MEDIUM, BaseCheck.LOW


# --------------------------------------------------------------------------------------
# The good file and the consistency of the hand-written data with the bundle
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", CHECK_METHODS)
def test_good_file_passes_every_check(run_check, method):
    assert messages(run_check(method)) == ""


@pytest.mark.parametrize("method", CHECK_METHODS)
def test_check_signature_is_what_compliance_checker_calls(method):
    # compliance-checker calls every check as check(ds); anything else is a TypeError
    parameters = list(inspect.signature(getattr(Obs4MipsCheck, method)).parameters)
    assert parameters == ["self", "ds"]


def test_good_values_cover_the_bundle():
    assert set(GOOD_VALUES) <= set(ODS_ATTRS)
    unconditional = {n for n, a in ODS_ATTRS.items() if a["requirement"] != "optional"}
    assert unconditional <= set(GOOD_VALUES)


def test_specs_only_name_bundle_attributes():
    assert set(FREQUENCY_TIME_DIGITS) <= set(ODS_ATTRS["frequency"]["allowed"])


def test_drs_parts_are_attributes_or_known_special_cases():
    for template in ODS_DRS.values():
        for part in template["parts"]:
            assert part["name"] in ODS_ATTRS or part["name"] in {
                "time_range",
                "version",
            }


def test_checker_identity():
    assert Obs4MipsCheck._cc_spec == "obs4mips"
    assert Obs4MipsCheck._cc_spec_version == BUNDLE["ods_version"]


def test_display_headers_cover_every_weight():
    # compliance-checker looks headers up by numeric weight
    assert Obs4MipsCheck._cc_display_headers == {
        HIGH: "Required",
        MEDIUM: "Recommended",
        LOW: "Optional",
    }


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def test_condition_grammar():
    assert Obs4MipsCheck().condition_holds(
        'product == "x" or realm != "y"', {"product": "x", "realm": "y"}
    )
    assert not Obs4MipsCheck().condition_holds('not product == "x"', {"product": "x"})
    assert Obs4MipsCheck().condition_holds('has_aux_unc == "TRUE"', {"has_aux_unc": "TRUE"})
    assert not Obs4MipsCheck().condition_holds('has_aux_unc == "TRUE"', {})
    with pytest.raises(ValueError):
        Obs4MipsCheck().condition_holds("__import__('os').system('true')", {})


def test_split_value_uses_the_separator_from_the_cvs():
    assert split_value("Conventions", "CF-1.12   ODS-2.6.1\n") == ["CF-1.12", "ODS-2.6.1"]
    assert split_value("realm", "atmos land") == ["atmos land"]  # no separator


def test_unregistered_terms_accepts_allowed_values_and_any_pattern():
    assert unregistered_terms("frequency", "mon") == []
    # grid_label has allowed values AND a pattern for sites
    assert unregistered_terms("grid_label", "gn") == []
    assert unregistered_terms("grid_label", "site-abc") == []
    # variant_label has several patterns; matching one is enough
    for label in ("BE", "r1i1p1f1", "r7"):
        assert unregistered_terms("variant_label", label) == []


def test_unregistered_terms_suggests_close_matches_ignoring_case():
    [(token, similar)] = unregistered_terms("frequency", "MON")
    assert token == "MON" and "mon" in similar


# --------------------------------------------------------------------------------------
# Presence and conditions
# --------------------------------------------------------------------------------------


def test_missing_required_attribute_is_high(run_check):
    results = failed(run_check("check_global_attribute_presence", drop=("contact",)))
    assert [r.weight for r in results] == [HIGH]
    assert "contact" in messages(results)


def test_missing_recommended_attribute_is_medium_and_encouraging(run_check):
    results = failed(run_check("check_global_attribute_presence", drop=("source_data_url",)))
    assert [r.weight for r in results] == [MEDIUM]
    assert "better to provide" in messages(results)


def test_conditionally_recommended_attribute_follows_condition(run_check):
    # variant_info is recommended only when variant_label != institution_id
    assert "variant_info" in messages(
        run_check("check_global_attribute_presence", drop=("variant_info",))
    )
    same = {"variant_label": "ORNL", "drop": ("variant_info",)}
    assert "variant_info" not in messages(
        run_check("check_global_attribute_presence", **same)
    )


def test_presence_reports_only_problems(run_check):
    assert run_check("check_global_attribute_presence") == []


def test_empty_attribute_counts_as_missing(run_check):
    assert "contact" in messages(
        run_check("check_global_attribute_presence", contact="  ")
    )


def test_optional_attribute_may_be_absent(run_check):
    assert not failed(
        run_check("check_global_attribute_presence", drop=("title", "history"))
    )


def test_conditional_requirement_aux_uncertainty(run_check):
    results = run_check("check_global_attribute_presence", has_aux_unc="TRUE")
    assert "aux_uncertainty_id" in messages(results)
    assert not failed(
        run_check(
            "check_global_attribute_presence",
            has_aux_unc="TRUE",
            aux_uncertainty_id="stderr",
        )
    )


def test_conditional_requirement_site(run_check):
    results = run_check("check_global_attribute_presence", product="site-observations")
    assert "site_id" in messages(results) and "site_location" in messages(results)


# --------------------------------------------------------------------------------------
# Values: CVs
# --------------------------------------------------------------------------------------


def test_cv_mismatch_is_high_with_suggestion(run_check):
    results = failed(run_check("check_global_attribute_cvs", frequency="mons"))
    assert [r.weight for r in results] == [HIGH]
    assert "'mon'" in messages(results)


def test_registered_content_mismatch_is_medium(run_check):
    # institution_id is registered content (rc: yes): providers copy it verbatim
    assert ODS_ATTRS["institution_id"]["rc"] == "yes"
    results = failed(run_check("check_global_attribute_cvs", institution_id="ORNLL"))
    assert [r.weight for r in results] == [MEDIUM]
    assert "'ORNL'" in messages(results)


def test_pure_format_cv_mismatch_is_high(run_check):
    for name, bad in (("creation_date", "2025-01-01"), ("tracking_id", "hdl:x/y")):
        assert ODS_ATTRS[name]["rc"] == "no"
        results = failed(run_check("check_global_attribute_cvs", **{name: bad}))
        assert [r.weight for r in results] == [HIGH]


def test_unregistered_value_in_multi_valued_attribute_names_the_term(run_check):
    results = failed(
        run_check("check_global_attribute_cvs", Conventions="CF-1.12 CF-9.9")
    )
    assert [r.weight for r in results] == [HIGH]
    assert "CF-9.9" in messages(results)


def test_cvs_report_only_problems(run_check):
    assert run_check("check_global_attribute_cvs") == []


def test_multi_valued_attribute_checks_each_value(run_check):
    assert not failed(
        run_check("check_global_attribute_cvs", Conventions="ODS-2.6.1 CF-1.12")
    )


def test_realm_is_single_valued(run_check):
    assert failed(run_check("check_global_attribute_cvs", realm="atmos land"))


@pytest.mark.parametrize(
    "name, value",
    [
        ("variant_label", "BE"),
        ("variant_label", "r1i1p1f1"),
        ("grid_label", "gn"),
        ("grid_label", "site-abc"),
        ("tracking_id", f"hdl:21.14102/{GOOD_VALUES['tracking_id'][-36:]}"),
        ("tracking_id", GOOD_VALUES["tracking_id"][-36:]),  # bare UUID
        ("license", "Licensed under a Creative Commons Attribution 4.0 International License"),
        ("license", "Licensed under a Creative Commons Attribution-ShareAlike 4.0 International License"),
    ],
)  # fmt: skip
def test_a_value_matching_any_one_pattern_is_registered(run_check, name, value):
    # the CV's patterns are alternatives: a value must match one, not all
    assert not failed(run_check("check_global_attribute_cvs", **{name: value}))


@pytest.mark.parametrize(
    "name, bad",
    [
        ("variant_label", "bad label"),
        ("creation_date", "2025-01-01"),
        ("tracking_id", "hdl:21.14102/not-a-uuid"),
        ("license", "All rights reserved"),
    ],
)
def test_a_value_matching_no_pattern_is_unregistered(run_check, name, bad):
    results = failed(run_check("check_global_attribute_cvs", **{name: bad}))
    assert name in messages(results)


def test_data_specs_version_is_free_text(run_check):
    assert not failed(
        run_check("check_global_attribute_cvs", data_specs_version="anything")
    )


def test_non_string_value_is_an_error(run_check):
    # an attribute written as a number is not a string
    results = failed(run_check("check_global_attribute_cvs", region=5))
    assert [r.weight for r in results] == [HIGH]
    assert "must be a string" in messages(results)


def test_empty_value_is_left_to_the_presence_check(run_check):
    assert not failed(run_check("check_global_attribute_cvs", region="  "))


@pytest.mark.parametrize(
    "name, bad, expected",
    [
        ("activity_id", "obs4MIPs CMIP7", "single value without spaces"),
        ("grid_label", "site-a b", "single value without spaces"),
        ("source_id", "20CR_V3", "letters, digits and '-'"),
        ("institution_id", "OR.NL", "letters, digits and '-'"),
        ("variable_id", "ta-x", "letters and digits"),
    ],
)
def test_drs_values_use_only_allowed_characters(run_check, name, bad, expected):
    results = run_check("check_drs", **{name: bad})
    assert [r.weight for r in results] == [HIGH]
    assert expected in messages(results)


def test_registered_variable_id_with_a_hyphen_is_allowed(run_check):
    # four registered variable_ids contain "-" although the DRS rule forbids it
    assert "ta-plev37" in ODS_ATTRS["variable_id"]["allowed"]
    assert run_check("check_drs", variable_id="ta-plev37") == []


def test_drs_directory_must_match_the_attribute_exactly(run_check):
    # there is no "first value" rule for a space-separated DRS attribute
    assert failed(run_check("check_drs_directory", activity_id="obs4MIPs CMIP7"))


def test_every_registered_drs_term_is_valid():
    # the character rule must not reject registered content
    for name in {"activity_id", "frequency", "grid_label", "institution_id", "source_id"}:
        for term in ODS_ATTRS[name]["allowed"]:
            assert re.fullmatch(DRS_VALUE_REGEX, term), (name, term)


# --------------------------------------------------------------------------------------
# Attribute-specific checks
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contact",
    [
        "Jane Doe (jane@example.org)",
        "Jane Q. Doe  (jane@example.org)",
        "jane@example.org",
        "  jane@example.org  ",
    ],
)
def test_contact_accepts_name_with_email_or_email_alone(run_check, contact):
    assert not failed(run_check("check_contact", contact=contact))


@pytest.mark.parametrize(
    "contact",
    [
        "Jane Doe",  # no email
        "(jane@example.org)",  # parentheses but no name
        "Jane Doe jane@example.org",  # email not in parentheses
        "Jane Doe (jane@example)",  # email without a domain suffix
        "Jane Doe (jane@example.org",  # unbalanced
    ],
)
def test_contact_recommendation(run_check, contact):
    results = run_check("check_contact", contact=contact)
    assert [r.weight for r in results] == [LOW]  # only problems are reported
    assert "We recommend" in messages(results)


def test_contact_absent_is_left_to_the_presence_check(run_check):
    # the missing attribute is reported once, at its ODS requirement level (required: HIGH)
    assert run_check("check_contact", drop=("contact",)) == []
    results = failed(run_check("check_global_attribute_presence", drop=("contact",)))
    assert [r.weight for r in results] == [HIGH]


def test_contact_format_guidance_is_low_even_though_contact_is_required(run_check):
    assert ODS_ATTRS["contact"]["requirement"] == "required"
    results = run_check("check_contact", contact="Jane Doe")
    assert [r.weight for r in results] == [LOW]


# --------------------------------------------------------------------------------------
# Attribute guidance and data checks
# --------------------------------------------------------------------------------------


def test_creation_date_matches_the_file(run_check):
    assert run_check("check_creation_date") == []


def test_creation_date_far_from_the_file_modification_time_is_medium(run_check):
    results = run_check("check_creation_date", creation_date="2020-01-01T00:00:00Z")
    assert [r.weight for r in results] == [MEDIUM]
    assert "differs from the file's modification time" in messages(results)


@pytest.mark.parametrize("creation_date", ["2025-01-01", "yesterday", "2025-13-45T00:00:00Z"])
def test_creation_date_with_a_wrong_format_is_left_to_the_cv_check(run_check, creation_date):
    assert run_check("check_creation_date", creation_date=creation_date) == []


@pytest.mark.parametrize(
    "doi",
    [
        "10.5281/zenodo.1234567",  # bare DOI
        "http://doi.org/10.5281/zenodo.1234567",  # not https
        "https://doi.org/zenodo.1234567",  # no 10. prefix
    ],
)
def test_doi_is_recommended_as_an_https_url(run_check, doi):
    results = run_check("check_doi", doi=doi)
    assert [r.weight for r in results] == [LOW]
    assert "https://doi.org/10.xxxx/xxxxxxxx" in messages(results)


def test_doi_checks_each_of_several_values(run_check):
    results = run_check(
        "check_doi", doi="https://doi.org/10.5281/zenodo.1 10.5281/zenodo.2"
    )
    assert len(results) == 1 and "10.5281/zenodo.2" in messages(results)


def test_external_cell_measures_on_a_simple_grid_are_discouraged(run_check):
    results = run_check("check_external_variables", external_variables="areacella")
    assert [r.weight for r in results] == [LOW]
    assert "areacella" in messages(results) and "bounds" in messages(results)


@pytest.mark.parametrize(
    "changes",
    [
        {"external_variables": "gridspec"},  # not a cell measure
        {"external_variables": "areacella", "coords": None},  # no simple grid to rely on
    ],
)
def test_external_variables_without_a_recommendation(run_check, changes):
    assert run_check("check_external_variables", **changes) == []


def test_grid_without_a_resolution_is_discouraged(run_check):
    results = run_check("check_grid", grid="native grid")
    assert [r.weight for r in results] == [LOW]
    assert "N by N resolution" in messages(results)


def test_grid_is_not_checked_for_sites(run_check):
    assert run_check("check_grid", grid="site", product="site-observations") == []


def test_license_missing_all_recommended_parts(run_check):
    results = run_check("check_license", license="All rights reserved")
    assert [r.weight for r in results] == [LOW]
    for part in ("Data in this file produced by", "license URL", "acknowledge", "further information"):
        assert part in messages(results)


def test_license_missing_one_recommended_part(run_check):
    text = GOOD_VALUES["license"].replace(
        " Use of the data must be acknowledged following guidelines found at "
        "https://example.org/acknowledgement.",
        "",
    )
    results = run_check("check_license", license=text)
    assert len(messages(results).splitlines()) == 1
    assert "acknowledge" in messages(results)


def test_processing_code_location_must_be_a_url(run_check):
    results = run_check("check_processing_code_location", processing_code_location="my laptop")
    assert [r.weight for r in results] == [LOW]
    assert "http(s) URL" in messages(results)


@pytest.mark.parametrize("retrieved", ["yesterday", "2025-01-01", "2025-13-45T00:00:00Z", "2025-01-01T00:00:00"])
def test_source_data_retrieval_date_is_recommended_as_iso_utc(run_check, retrieved):
    results = run_check("check_source_data_retrieval_date", source_data_retrieval_date=retrieved)
    assert [r.weight for r in results] == [LOW]
    assert "YYYY-MM-DDTHH:MM:SSZ" in messages(results)


def test_source_data_url_must_be_a_url(run_check):
    results = run_check("check_source_data_url", source_data_url="example.org/data")
    assert [r.weight for r in results] == [LOW]


def test_source_data_url_checks_each_of_several_values(run_check):
    results = run_check(
        "check_source_data_url", source_data_url="https://example.org/a example.org/b"
    )
    assert len(results) == 1 and "example.org/b" in messages(results)


@pytest.mark.parametrize("name", ["contact", "doi", "grid", "license", "processing_code_location"])
def test_attribute_guidance_ignores_an_absent_attribute(run_check, name):
    # a missing attribute is the presence check's business
    assert run_check(f"check_{name}", drop=(name,)) == []


# --------------------------------------------------------------------------------------
# nominal_resolution
# --------------------------------------------------------------------------------------


def test_mean_resolution_matches_the_documented_example():
    # the CMIP6 document: a 0.5x0.5 degree global grid has a mean resolution of 71.5 km
    lat, lon = np.arange(-90, 90.1, 0.5), np.arange(0, 360.1, 0.5)
    assert mean_resolution_km(lat, lon) == pytest.approx(71.5, abs=0.1)


@pytest.mark.parametrize(
    "mean_km, expected",
    [
        (0.5, {0.5}),
        (100, {100}),
        (143, {100}),  # a 1 degree grid is labelled 100 km, as the document says
        (357, {250, 500}),  # 2.5 degrees: within 3% of the 360 km bound
        (340, {250}),
        (71.5, {50, 100}),  # within 3% of the 72 km bound: either label
        (73, {50, 100}),
        (20000, {10000}),
    ],
)
def test_nominal_resolution_labels_follow_the_document(mean_km, expected):
    assert nominal_resolutions_km(mean_km) == expected


def test_nominal_resolution_value_in_km():
    assert _nominal_resolution_km("100 km") == 100
    assert _nominal_resolution_km("2.5 km") == 2.5
    assert _nominal_resolution_km("500-m") == 0.5
    assert _nominal_resolution_km("site") is None


def test_nominal_resolution_must_match_the_grid(run_check):
    results = run_check("check_nominal_resolution", nominal_resolution="100 km")
    assert [r.weight for r in results] == [HIGH]
    assert "250 km" in messages(results)  # the 2 degree grid


def test_nominal_resolution_follows_the_grid_not_the_attribute(run_check):
    one_degree = (np.arange(-89.75, 90, 1.5), np.arange(0.75, 360, 1.5))  # ~214 km
    assert not failed(
        run_check("check_nominal_resolution", nominal_resolution="250 km", coords=one_degree)
    )
    assert "does not match" in messages(
        run_check("check_nominal_resolution", nominal_resolution="500 km", coords=one_degree)
    )


def test_standard_one_degree_grid(run_check):
    standard = (np.arange(-89.5, 90, 1.0), np.arange(0.5, 360, 1.0))
    for accepted in ("1x1 degree", "100 km"):
        assert not failed(
            run_check("check_nominal_resolution", nominal_resolution=accepted, coords=standard)
        )
    assert "standard 1x1 degree grid" in messages(
        run_check("check_nominal_resolution", nominal_resolution="250 km", coords=standard)
    )


def test_nominal_resolution_with_a_regional_grid(run_check):
    # a 0.5 degree grid over 30-40N is finer than its global 71.5 km mean
    regional = (np.arange(30.25, 40, 0.5), np.arange(0.25, 20, 0.5))
    assert not failed(
        run_check("check_nominal_resolution", nominal_resolution="50 km", coords=regional)
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"coords": None},  # no latitude/longitude coordinates
        {"product": "site-observations", "nominal_resolution": "site"},
        {"nominal_resolution": "1x1 degree"},  # not a distance: the CV check reports it
        {"coords": (np.array([0.0]), np.array([0.0]))},  # a single cell has no size
    ],
)
def test_nominal_resolution_is_skipped_where_it_cannot_be_computed(run_check, changes):
    assert run_check("check_nominal_resolution", **changes) == []


# --------------------------------------------------------------------------------------
# File name
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("tas_mon_20CR-V3_BE_gn_200001-200002.txt", "must end with"),
        ("tas_mon_20CR-V3_BE.nc", "must follow"),  # 4 parts
        ("tas_mon_20CR-V3_BE_gn_200001-200002_extra.nc", "must follow"),  # 7 parts
        ("pr_mon_20CR-V3_BE_gn_200001-200002.nc", "variable_id='pr'"),
        (
            "tas_mon_20CR-V3_BE_gn_200001-200003.nc",
            "does not match the time coordinate span",
        ),
        ("tas_mon_20CR-V3_BE_gn_2000-2000.nc", "6-digit"),
        ("tas_mon_20CR-V3_BE_gn_200002-200001.nc", "ordered"),
        ("tas_mon_20CR-V3_BE_gn.nc", "must include time_range"),
    ],
)
def test_filename_problems(run_check, filename, expected):
    assert expected in messages(run_check("check_drs_filename", filename=filename))


@pytest.mark.parametrize(
    "time_range",
    ["2000", "200001", "200001-", "20000101-200002", "a-b", "200001--200002"],
)
def test_malformed_time_range_is_reported_not_a_crash(run_check, time_range):
    results = run_check(
        "check_drs_filename", filename=f"tas_mon_20CR-V3_BE_gn_{time_range}.nc"
    )
    assert "must contain ordered, equally precise" in messages(results)


def test_time_range_with_an_unknown_number_of_digits_is_reported_not_a_crash(run_check):
    # 5 digits is not a CMIP6 date precision
    results = run_check(
        "check_drs_filename", filename="tas_mon_20CR-V3_BE_gn_20000-20001.nc"
    )
    assert "must contain ordered, equally precise" in messages(results)


def test_a_single_time_step_is_assumed_to_be_fx(run_check):
    results = failed(
        run_check(
            "check_drs_filename",
            filename="tas_mon_20CR-V3_BE_gn.nc",
            time_values=(15.0,),
        )
    )
    assert [(r.weight, r.name) for r in results] == [(MEDIUM, "Frequency attribute")]
    assert "should be 'fx'" in messages(results)


@pytest.mark.parametrize("time_name", ["TIME", "t"])
def test_time_variable_may_have_any_name(run_check, time_name):
    # found by its units, so the span mismatch is still caught
    bad = "tas_mon_20CR-V3_BE_gn_200001-200003.nc"
    assert "time coordinate span" in messages(
        run_check("check_drs_filename", filename=bad, time_name=time_name)
    )
    problems = failed(run_check("check_drs_filename", time_name=time_name))
    assert {r.name for r in problems} <= {"Time variable"}  # only a naming hint


def test_time_variable_not_named_time_gets_a_recommendation(run_check):
    results = failed(run_check("check_drs_filename", time_name="t"))
    assert [r.weight for r in results] == [LOW]
    assert "should be named 'time'" in messages(results)


def test_time_variable_without_axis_t_gets_a_recommendation(run_check):
    results = failed(run_check("check_drs_filename", time_axis=None))
    assert [r.weight for r in results] == [LOW]
    assert "axis 'T'" in messages(results)


def test_time_variable_without_data_is_an_error(run_check):
    results = failed(
        run_check(
            "check_drs_filename",
            time_values=(),
            filename="tas_mon_20CR-V3_BE_gn_200001-200002.nc",
        )
    )
    assert HIGH in [r.weight for r in results]
    assert "has no data" in messages(results)


def test_time_axis_prefers_cf_declared_variable(tmp_path):
    # an extra variable with "days since" units named so it sorts first must not be picked
    path = tmp_path / "x.nc"
    with Dataset(path, "w") as ds:
        ds.createDimension("time", 2)
        for name, std in (("a_other", None), ("time", "time")):
            v = ds.createVariable(name, "f8", ("time",))
            v.units = "days since 2000-01-01"
            if std:
                v.standard_name = std
                v.axis = "T"
        ds["a_other"][:] = [1000.0, 2000.0]
        ds["time"][:] = [15.0, 45.0]
    with Dataset(path) as ds:
        checker = Obs4MipsCheck()
        checker.setup(ds)
        results = checker._check_drs_filename_time_range(ds, "200001-200002")
    assert "time coordinate span" not in messages(results)
    # ... but having two time variables is worth a hint
    assert [(r.weight, r.name) for r in failed(results)] == [(LOW, "Time variable")]
    assert "multiple time variables" in messages(results)


def test_scalar_time_variable_is_supported(tmp_path):
    path = tmp_path / "x.nc"
    with Dataset(path, "w") as ds:
        time = ds.createVariable("time", "f8", ())
        time.units, time.standard_name, time.axis = "days since 2000-01-01", "time", "T"
        time[...] = 15.0
    with Dataset(path) as ds:
        checker = Obs4MipsCheck()
        checker.setup(ds)
        checker.attrs["frequency"] = "fx"
        assert not failed(checker._check_drs_filename_time_range(ds, None))


def test_fx_must_omit_time_range(run_check):
    results = run_check(
        "check_drs_filename",
        frequency="fx",
        filename="tas_fx_20CR-V3_BE_gn_200001-200002.nc",
    )
    assert "must omit time_range" in messages(results)


def test_fx_without_time_range_passes(run_check):
    assert not failed(
        run_check(
            "check_drs_filename",
            frequency="fx",
            filename="tas_fx_20CR-V3_BE_gn.nc",
            time_values=(0.0,),
        )
    )


def test_fx_with_several_time_values_is_an_error(run_check):
    results = run_check(
        "check_drs_filename", frequency="fx", filename="tas_fx_20CR-V3_BE_gn.nc"
    )
    assert "more than 1 time value" in messages(results)


def test_time_range_precision_follows_frequency(run_check):
    # 'day' needs 8-digit dates; the file gets two time steps on those days
    good = "tas_day_20CR-V3_BE_gn_20000116-20000215.nc"
    assert not failed(run_check("check_drs_filename", frequency="day", filename=good))
    assert "8-digit" in messages(run_check("check_drs_filename", frequency="day"))


# --------------------------------------------------------------------------------------
# Directory
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directory, expected",
    [
        ("obs4MIPs/ORNL/20CR-V3/mon/tas/gr/v20250101", "grid_label"),
        ("obs4MIPs/ORNL/20CR-V3/mon/tas/gn/20250101", "version"),
        ("obs4MIPs/NASA/20CR-V3/mon/tas/gn/v20250101", "institution_id"),
    ],
)
def test_directory_problems(run_check, directory, expected):
    assert expected in messages(run_check("check_drs_directory", directory=directory))


def test_directory_with_too_few_levels_is_one_clear_error(run_check):
    results = failed(run_check("check_drs_directory", directory="tas/gn/v20250101"))
    assert len(results) == 1  # no misaligned "does not match" noise
    assert "directory levels" in messages(results)


def test_directory_may_have_leading_levels(run_check):
    assert not failed(
        run_check(
            "check_drs_directory",
            directory="some/where/obs4MIPs/ORNL/20CR-V3/mon/tas/gn/v20250101",
        )
    )


@pytest.mark.parametrize(
    "source_id, label, version",
    [
        ("CERES-EBAF-4-2", "CERES-EBAF", "4.2"),
        ("CMAP-V1902", "CMAP", "V1902"),
        ("ESA-CCI-SST-V3-0-1", "ESA-CCI-SST", "V3.0.1"),
        ("AIRS-10", "AIRS", "1_0"),
    ],
)
def test_source_id_agrees_with_label_and_version(run_check, source_id, label, version):
    results = run_check(
        "check_source",
        source_id=source_id,
        source_label=label,
        source_version_number=version,
    )
    assert messages(results) == ""


@pytest.mark.parametrize(
    "changes",
    [
        {"source_label": "20CRX"},  # label is not the start of source_id
        {"source_version_number": "V4"},  # version disagrees
        {"source_version_number": "V3.0"},  # "." becomes "-", so 20CR-V3-0
        {"source_id": "20CR_V3"},  # separator must be "-"
        {"source_id": "20cr-V3"},  # case sensitive
    ],
)
def test_source_id_disagreeing_with_label_and_version_is_high(run_check, changes):
    results = run_check("check_source", **changes)
    assert [r.weight for r in results] == [HIGH]
    assert "source_id must be source_label" in messages(results)


def test_source_check_leaves_missing_attributes_to_the_presence_check(run_check):
    assert run_check("check_source", drop=("source_label",)) == []



SITE = {
    "product": "site-observations",
    "grid": "site",
    "grid_label": "site-AR-SLu",
    "nominal_resolution": "site",
    "site_id": "AR-SLu",
    "site_location": "location: San Luis,latitude: -33.4648,longitude: -66.4598",
}
SITE_COLLECTION = {
    "product": "site-collection",
    "grid": "site-collection",
    "grid_label": "site-collection",
    "nominal_resolution": "site-collection",
    "site_id": "collection",
    "site_location": "collection",
}


@pytest.mark.parametrize("values", [SITE, SITE_COLLECTION])
def test_good_site_data_passes_check_site(run_check, values):
    assert run_check("check_site", **values) == []


@pytest.mark.parametrize(
    "values, changes, name",
    [
        (SITE, {"grid": "site-collection"}, "grid"),
        (SITE, {"grid": "1 degree"}, "grid"),
        (SITE, {"grid_label": "gn"}, "grid_label"),
        (SITE, {"nominal_resolution": "100 km"}, "nominal_resolution"),
        (SITE_COLLECTION, {"grid": "site"}, "grid"),
        (SITE_COLLECTION, {"grid_label": "site-AR-SLu"}, "grid_label"),
        (SITE_COLLECTION, {"nominal_resolution": "site"}, "nominal_resolution"),
        (SITE_COLLECTION, {"site_id": "AR-SLu"}, "site_id"),
        (SITE_COLLECTION, {"site_location": "San Luis"}, "site_location"),
    ],
)
def test_site_attributes_must_agree_with_product(run_check, values, changes, name):
    results = run_check("check_site", **{**values, **changes})
    assert [r.weight for r in results] == [HIGH]
    assert messages(results).startswith(name)


def test_site_grid_label_with_wrong_site_id_is_left_to_check_grid_label(run_check):
    assert run_check("check_site", **{**SITE, "grid_label": "site-XX"}) == []


def test_site_check_ignores_non_site_data_and_missing_attributes(run_check):
    assert run_check("check_site") == []
    assert run_check("check_site", **{**SITE, "grid": ""}) == []
    assert run_check("check_site", **SITE, drop=("nominal_resolution",)) == []


def test_variable_id_names_a_variable_in_the_file(run_check):
    assert run_check("check_variable_id") == []


def test_variable_id_that_is_not_a_variable_in_the_file(run_check):
    results = run_check("check_variable_id", variable_name="pr")
    assert [r.weight for r in results] == [HIGH]
    assert "variable_id='tas'" in messages(results) and "'pr'" in messages(results)


def test_variable_id_absent_is_left_to_the_presence_check(run_check):
    assert run_check("check_variable_id", drop=("variable_id",)) == []


# --------------------------------------------------------------------------------------
# ODS versions
# --------------------------------------------------------------------------------------


def test_only_released_ods_versions_are_registered_as_suites():
    from importlib.metadata import entry_points

    suites = {e.name: e.value for e in entry_points(group="compliance_checker.suites")}
    obs4mips = {n: v for n, v in suites.items() if n.split(":")[0] == "obs4mips"}
    assert set(obs4mips) == {"obs4mips", "obs4mips:2.6"}  # add a name when an ODS is released


def test_there_are_no_cvs_for_an_unreleased_ods_version():
    from cc_plugin_obs4mips.cv_sync import load_bundle

    with pytest.raises(SystemExit, match="no CVs for ODS 2.7"):
        load_bundle("2.7")


def test_the_base_class_is_not_a_suite():
    from cc_plugin_obs4mips.checks import Obs4MipsCheckBase

    assert Obs4MipsCheckBase.register_checker is False and Obs4MipsCheckBase.ods_version is None


def test_a_new_ods_version_overrides_only_what_changed():
    """The pattern of docs/development/new_ods_version.md: subclass, change one attribute."""
    from cc_plugin_obs4mips.checks import Obs4MipsCheck_2_6

    class Newer(Obs4MipsCheck_2_6):
        DOI_REGEX = r"doi:10\.\d{4,9}/\S+"

    old, new = Obs4MipsCheck_2_6.DOI_REGEX, Newer.DOI_REGEX
    assert new != old and Newer.check_license is Obs4MipsCheck_2_6.check_license  # inherited
