import pytest
from compliance_checker.base import BaseCheck

from cc_plugin_obs4mips.checks import ATTRS, DRS, Obs4MipsCheck, condition_holds
from cc_plugin_obs4mips.specs import BUNDLE, CV_STRICTNESS, FORMAT_CHECKS, FREQUENCY_TIME_DIGITS
from tests.conftest import GOOD_VALUES, failed, messages

CHECK_METHODS = [m for m in dir(Obs4MipsCheck) if m.startswith("check_")]
HIGH, MEDIUM = BaseCheck.HIGH, BaseCheck.MEDIUM


# --------------------------------------------------------------------------------------
# The good file and the consistency of the hand-written data with the bundle
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", CHECK_METHODS)
def test_good_file_passes_every_check(run_check, method):
    assert messages(run_check(method)) == ""


def test_good_values_cover_the_bundle():
    assert set(GOOD_VALUES) <= set(ATTRS)
    unconditional = {n for n, a in ATTRS.items() if a["requirement"] != "optional"}
    assert unconditional <= set(GOOD_VALUES)


def test_specs_only_name_bundle_attributes():
    assert set(FORMAT_CHECKS) <= set(ATTRS)
    assert CV_STRICTNESS <= {n for n, a in ATTRS.items() if "allowed" in a or "patterns" in a}
    assert set(FREQUENCY_TIME_DIGITS) <= set(ATTRS["frequency"]["allowed"])


def test_drs_parts_are_attributes_or_known_special_cases():
    for template in DRS.values():
        for part in template["parts"]:
            assert part["name"] in ATTRS or part["name"] in {"time_range", "version"}


def test_checker_identity():
    assert Obs4MipsCheck._cc_spec == "obs4mips"
    assert Obs4MipsCheck._cc_spec_version == BUNDLE["ods_version"]


# --------------------------------------------------------------------------------------
# Presence and conditions
# --------------------------------------------------------------------------------------


def test_missing_required_attribute_is_high(run_check):
    results = failed(run_check("check_global_attributes_present", drop=("contact",)))
    assert [r.weight for r in results] == [HIGH]
    assert "contact" in messages(results)


def test_missing_recommended_attribute_is_medium(run_check):
    results = failed(run_check("check_global_attributes_present", drop=("doi",)))
    assert [r.weight for r in results] == [MEDIUM]


def test_empty_attribute_counts_as_missing(run_check):
    assert "contact" in messages(run_check("check_global_attributes_present", contact="  "))


def test_optional_attribute_may_be_absent(run_check):
    assert not failed(run_check("check_global_attributes_present", drop=("title", "history")))


def test_conditional_requirement_aux_uncertainty(run_check):
    results = run_check("check_global_attributes_present", has_aux_unc="TRUE")
    assert "aux_uncertainty_id" in messages(results)
    assert not failed(run_check("check_global_attributes_present", has_aux_unc="TRUE", aux_uncertainty_id="stderr"))


def test_conditional_requirement_site(run_check):
    results = run_check("check_global_attributes_present", product="site-observations")
    assert "site_id" in messages(results) and "site_location" in messages(results)


def test_variant_info_follows_condition(run_check):
    # variant_label != institution_id -> recommended
    assert "variant_info" in messages(run_check("check_global_attributes_present", drop=("variant_info",)))
    # variant_label == institution_id -> optional again
    same = {"variant_label": "ORNL", "drop": ("variant_info",)}
    assert "variant_info" not in messages(run_check("check_global_attributes_present", **same))


def test_condition_grammar():
    assert condition_holds('product == "x" or realm != "y"', {"product": "x", "realm": "y"})
    assert not condition_holds('not product == "x"', {"product": "x"})
    assert condition_holds('has_aux_unc == "TRUE"', {"has_aux_unc": "TRUE"})
    assert not condition_holds('has_aux_unc == "TRUE"', {})
    with pytest.raises(ValueError):
        condition_holds("__import__('os').system('true')", {})


# --------------------------------------------------------------------------------------
# Values: CVs and formats
# --------------------------------------------------------------------------------------


def test_unregistered_value_is_error_for_strict_attribute(run_check):
    results = failed(run_check("check_global_attribute_values", frequency="mons"))
    assert [r.weight for r in results] == [HIGH]
    assert "'mon'" in messages(results)  # suggestion


def test_unregistered_value_is_warning_otherwise(run_check):
    results = failed(run_check("check_global_attribute_values", Conventions="CF-1.12 CF-9.9"))
    assert [r.weight for r in results] == [MEDIUM]
    assert "CF-9.9" in messages(results)


def test_realm_is_single_valued(run_check):
    assert failed(run_check("check_global_attribute_values", realm="atmos land"))


def test_multi_valued_attribute_checks_each_value(run_check):
    assert not failed(run_check("check_global_attribute_values", Conventions="ODS-2.6.1 CF-1.12"))


def test_pattern_cvs(run_check):
    assert not failed(run_check("check_global_attribute_values", variant_label="r1i1p1f1"))
    assert failed(run_check("check_global_attribute_values", variant_label="bad label"))
    assert failed(run_check("check_global_attribute_values", creation_date="2025-01-01"))


def test_data_specs_version_is_free_text(run_check):
    assert not failed(run_check("check_global_attribute_values", data_specs_version="anything"))


def test_license_must_match_a_registered_license(run_check):
    assert failed(run_check("check_global_attribute_values", license="All rights reserved"))


@pytest.mark.parametrize(
    "name, bad",
    [
        ("tracking_id", "hdl:21.14102/not-a-uuid"),
        ("doi", "https://doi.org/10.5281/zenodo.1234567"),
        ("contact", "Jane Doe"),
        ("source_data_url", "example.org/data"),
        ("source_data_retrieval_date", "yesterday"),
    ],
)
def test_format_checks(run_check, name, bad):
    assert name in messages(run_check("check_global_attribute_values", **{name: bad}))


def test_non_string_value_is_an_error(run_check):
    # an attribute written as a number is not a string
    assert failed(run_check("check_global_attribute_values", region=5))


def test_processing_code_location_recommendation(run_check):
    results = run_check("check_processing_code_location_repository", processing_code_location="https://example.org/x")
    assert [r.weight for r in failed(results)] == [MEDIUM]


# --------------------------------------------------------------------------------------
# File name
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("tas_mon_20CR-V3_BE_gn_200001-200002.txt", "must end with"),
        ("tas_mon_20CR-V3_BE.nc", "must follow"),  # 4 parts
        ("pr_mon_20CR-V3_BE_gn_200001-200002.nc", "variable_id='pr'"),
        ("tas_mon_20CR-V3_BE_gn_200001-200003.nc", "does not match the time coordinate span"),
        ("tas_mon_20CR-V3_BE_gn_2000-2000.nc", "6-digit"),
        ("tas_mon_20CR-V3_BE_gn_200002-200001.nc", "ordered"),
        ("tas_mon_20CR-V3_BE_gn.nc", "must include time_range"),
    ],
)
def test_filename_problems(run_check, filename, expected):
    assert expected in messages(run_check("check_filename", filename=filename))


def test_fx_must_omit_time_range(run_check):
    results = run_check("check_filename", frequency="fx", filename="tas_fx_20CR-V3_BE_gn_200001-200002.nc")
    assert "fx" in messages(results)
    assert not failed(run_check("check_filename", frequency="fx", filename="tas_fx_20CR-V3_BE_gn.nc", time_values=(0.0,)))


def test_time_range_precision_follows_frequency(run_check):
    # 'day' needs 8-digit dates; the file gets two time steps on those days
    good = "tas_day_20CR-V3_BE_gn_20000116-20000215.nc"
    assert not failed(run_check("check_filename", frequency="day", filename=good))
    assert "8-digit" in messages(run_check("check_filename", frequency="day"))


# --------------------------------------------------------------------------------------
# Directory
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directory, expected",
    [
        ("tas/gn/v20250101", "directory levels"),
        ("obs4MIPs/ORNL/20CR-V3/mon/tas/gr/v20250101", "grid_label"),
        ("obs4MIPs/ORNL/20CR-V3/mon/tas/gn/20250101", "version"),
        ("obs4MIPs/NASA/20CR-V3/mon/tas/gn/v20250101", "institution_id"),
    ],
)
def test_directory_problems(run_check, directory, expected):
    assert expected in messages(run_check("check_directory_structure", directory=directory))


def test_directory_uses_first_activity_id(run_check):
    results = run_check("check_directory_structure", activity_id="obs4MIPs CMIP7")
    assert not failed(results)


# --------------------------------------------------------------------------------------
# Checks across attributes or data
# --------------------------------------------------------------------------------------


def test_source_id_is_derived(run_check):
    assert not failed(run_check("check_source_id_matches_label_and_version", source_label="A.B", source_version_number="V 1", source_id="A-B-V-1"))
    assert failed(run_check("check_source_id_matches_label_and_version", source_label="20CR", source_version_number="V2"))


def test_anomaly_naming(run_check):
    assert failed(run_check("check_anomaly_variable_naming", units_metadata="temperature: difference"))
    assert failed(run_check("check_anomaly_variable_naming", variable_id="tasanom"))
    assert not failed(run_check("check_anomaly_variable_naming", variable_id="tasanom", units_metadata="temperature: difference"))


def test_site_collection(run_check):
    good = dict(product="site-collection", nominal_resolution="site-collection", grid="site-collection",
                grid_label="site-collection", site_id="collection", site_location="collection")  # fmt: skip
    assert not failed(run_check("check_site_metadata_consistency", **good))
    assert "site_id" in messages(run_check("check_site_metadata_consistency", **{**good, "site_id": "abc"}))


def test_individual_site(run_check):
    good = dict(product="site-observations", nominal_resolution="site", grid="site", grid_label="site-abc", site_id="abc")  # fmt: skip
    assert not failed(run_check("check_site_metadata_consistency", **good))
    assert "grid_label" in messages(run_check("check_site_metadata_consistency", **{**good, "grid_label": "gn"}))
    assert "product" in messages(run_check("check_site_metadata_consistency", **{**good, "product": "reanalysis"}))


def test_non_site_file_is_not_checked(run_check):
    assert run_check("check_site_metadata_consistency") == []
