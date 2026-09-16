import pytest
from compliance_checker.base import BaseCheck

from cc_plugin_obs4mips.checks import Obs4Mips2_6_1Check as PublicChecker
from cc_plugin_obs4mips.checks.ods_2_6_1 import Obs4Mips2_6_1Check
from cc_plugin_obs4mips.cv import CV
from cc_plugin_obs4mips.specs._base import AttrSpec
from cc_plugin_obs4mips.specs.ods_2_6_1 import (
    GLOBAL_ATTR_SPECS,
    is_bare_doi,
    is_conventions_string,
    is_nominal_resolution,
    is_processing_code_location,
    is_url,
)


class VariableStub:
    def __init__(self, attributes=None):
        self._attributes = attributes or {}

    def ncattrs(self):
        return list(self._attributes)

    def __getattr__(self, name):
        try:
            return self._attributes[name]
        except KeyError as error:
            raise AttributeError(name) from error


class TimeVariableStub(VariableStub):
    def __init__(
        self,
        values,
        units="days since 2000-01-01",
        calendar="standard",
        climatology=None,
    ):
        attributes = {"units": units, "calendar": calendar}
        if climatology is not None:
            attributes["climatology"] = climatology
        super().__init__(attributes)
        self._values = values

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


class DatasetStub:
    def __init__(self, attributes, variables=None, filepath=None):
        self._attributes = attributes
        self.variables = variables or {}
        self._filepath = filepath

    def filepath(self):
        return self._filepath

    def ncattrs(self):
        return list(self._attributes)

    def __getattr__(self, name):
        try:
            return self._attributes[name]
        except KeyError as error:
            raise AttributeError(name) from error


def dataset_with_all_attributes():
    attributes = {spec.name: "test" for spec in GLOBAL_ATTR_SPECS}
    attributes["has_aux_unc"] = "FALSE"
    attributes["variant_label"] = "BE"
    return DatasetStub(attributes)


def spec_named(name):
    return next(spec for spec in GLOBAL_ATTR_SPECS if spec.name == name)


def ods_path_attributes(**updates):
    attributes = {
        "activity_id": "obs4MIPs",
        "institution_id": "RSS",
        "source_id": "CERES-EBAF-4-2",
        "frequency": "mon",
        "variable_id": "rlut",
        "nominal_resolution": "100 km",
        "variant_label": "RSS",
        "grid_label": "gn",
    }
    attributes.update(updates)
    return attributes


def test_checker_identifies_ods_2_6_1():
    assert PublicChecker is Obs4Mips2_6_1Check
    assert Obs4Mips2_6_1Check._cc_spec_version == "2.6.1"
    assert Obs4Mips2_6_1Check.CV_VERSION == "2.6.1"


def test_checker_uses_compliance_checker_base_api():
    check = Obs4Mips2_6_1Check(options={"example": True})

    assert isinstance(check, BaseCheck)
    assert check.options == {"example": True}
    assert check.get_test_ctx(BaseCheck.HIGH, "example") is not None


@pytest.mark.parametrize("level", [0, 4])
def test_attribute_spec_rejects_unknown_compliance_checker_level(level):
    with pytest.raises(ValueError, match="Compliance Checker severity"):
        AttrSpec(
            name="example",
            rc=False,
            requirement=level,
            required_if=None,
            cv=None,
            cv_strictness="warn",
            format_check=None,
            format_hint="example attribute",
        )


def test_attribute_spec_requires_boolean_registered_content_flag():
    with pytest.raises(TypeError, match="rc must be a boolean"):
        AttrSpec(
            name="example",
            rc="yes",
            requirement=BaseCheck.LOW,
            required_if=None,
            cv=None,
            cv_strictness="warn",
            format_check=None,
            format_hint="example attribute",
        )


def test_global_attribute_specs_expose_registered_content_metadata():
    assert spec_named("institution_id").rc is True
    assert spec_named("source_id").rc is True
    assert spec_named("variable_id").rc is True
    assert spec_named("activity_id").rc is False


def test_required_global_attributes_pass():
    check = Obs4Mips2_6_1Check()
    dataset = dataset_with_all_attributes()
    check.setup(dataset)

    results = check.check_global_attributes_present(dataset)

    assert results
    assert all(result.value for result in results)


def test_required_global_attribute_missing():
    check = Obs4Mips2_6_1Check()
    dataset = dataset_with_all_attributes()
    del dataset._attributes["activity_id"]
    check.setup(dataset)

    results = check.check_global_attributes_present(dataset)

    assert any(not result.value for result in results)
    assert any(
        "activity_id" in message for result in results for message in result.msgs
    )


def test_required_global_attribute_rejects_whitespace_only_value():
    check = Obs4Mips2_6_1Check()
    dataset = dataset_with_all_attributes()
    dataset._attributes["contact"] = "   "
    check.setup(dataset)

    results = check.check_global_attributes_present(dataset)

    assert any(
        "empty or whitespace-only: contact" in message
        for result in results
        for message in result.msgs
    )


@pytest.mark.parametrize("frequency", ["mon", "monC", "1hrPt", "fx"])
def test_frequency_cv_accepts_obs4mips_drs_names(frequency):
    assert CV.contains("2.6.1", "frequency", frequency)


@pytest.mark.parametrize("frequency", ["monthly", "monc", "1HR", ""])
def test_frequency_cv_rejects_unknown_or_mis_cased_values(frequency):
    assert not CV.contains("2.6.1", "frequency", frequency)


def test_checker_reports_invalid_frequency_as_required_with_cv_guidance():
    check = Obs4Mips2_6_1Check()
    dataset = DatasetStub({"frequency": "monthly"})
    check.setup(dataset)

    results = check.check_global_attribute_cv(dataset)

    assert len(results) == 1
    assert not results[0].value
    assert results[0].weight == 3
    assert results[0].name == "Unregistered controlled vocabulary terms"
    assert results[0].msgs == [
        "frequency='monthly' is not registered in CV 'frequency'. Before "
        "requesting a new term, check whether an existing CV term should be used. "
        "Similar registered terms: 'monPt', 'mon', 'monC'"
    ]


def test_checker_rejects_non_string_cv_value():
    check = Obs4Mips2_6_1Check()
    dataset = DatasetStub({"frequency": 1})
    check.setup(dataset)

    results = check.check_global_attribute_cv(dataset)

    assert len(results) == 1
    assert not results[0].value
    assert results[0].msgs == [
        "frequency=1 must be a string to be checked against CV 'frequency'"
    ]


def test_title_is_optional_but_encouraged_attributes_are_recommended():
    assert spec_named("title").requirement == BaseCheck.LOW
    assert spec_named("doi").requirement == BaseCheck.MEDIUM
    assert spec_named("source_data_retrieval_date").requirement == BaseCheck.MEDIUM
    assert spec_named("source_data_url").requirement == BaseCheck.MEDIUM

    dataset = dataset_with_all_attributes()
    for name in ("title", "doi", "source_data_retrieval_date", "source_data_url"):
        del dataset._attributes[name]
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    results = check.check_global_attributes_present(dataset)

    messages = [message for result in results for message in result.msgs]
    assert "missing: title" not in messages
    assert {message for message in messages if message.startswith("missing:")} == {
        "missing: doi",
        "missing: source_data_retrieval_date",
        "missing: source_data_url",
    }
    assert all(result.weight == BaseCheck.MEDIUM for result in results if result.msgs)


def test_site_attributes_are_conditional_and_best_estimate_needs_no_variant_info():
    dataset = dataset_with_all_attributes()
    del dataset._attributes["site_id"]
    del dataset._attributes["site_location"]
    del dataset._attributes["variant_info"]
    dataset._attributes["variant_label"] = "RSS-BE"
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    results = check.check_global_attributes_present(dataset)

    assert all(result.value for result in results)

    dataset._attributes["grid"] = "site"
    check.setup(dataset)
    results = check.check_global_attributes_present(dataset)
    messages = [message for result in results for message in result.msgs]
    assert "missing: site_id" in messages
    assert "missing: site_location" in messages


def test_non_ods_institution_name_heuristic_is_not_registered():
    check = Obs4Mips2_6_1Check()

    assert not hasattr(check, "check_institution_matches_institution_id")


@pytest.mark.parametrize(
    "value",
    ["0.5 km", "100 km", "1x1degree", "1x1 degree", "site", "site-collection"],
)
def test_nominal_resolution_accepts_ods_forms(value):
    assert is_nominal_resolution(value)


@pytest.mark.parametrize("value", ["10.1234/example", "10.123456789/data.v2"])
def test_bare_doi_validation_accepts_structured_dois(value):
    assert is_bare_doi(value)


@pytest.mark.parametrize(
    "value", ["not-a-doi", "doi:10.1234/example", "https://doi.org/10.1234/example"]
)
def test_bare_doi_validation_rejects_non_bare_forms(value):
    assert not is_bare_doi(value)


def test_conventions_are_complete_tokens_and_urls_are_absolute():
    assert is_conventions_string("ODS-2.6.1")
    assert is_conventions_string("CF-1.12 ODS-2.6.1")
    assert is_conventions_string("ACDD-1.3 CF-1.11 ODS-2.6.1")
    assert not is_conventions_string("CF-1.11 ODS-2.6")
    assert not is_conventions_string("CF-1.12 ODS-2.6.1-draft")
    assert not is_conventions_string("CF-1.12 ODS-2.6.1;")
    assert is_url("https://example.org/data")
    assert not is_url("https:///data")


def test_processing_code_location_recognizes_recommended_obs4mips_permalink():
    revision = "9876ae84146244a20fb498f2a2be7e8272a3142f"
    assert is_processing_code_location(
        f"https://github.com/WCRP-ESMO/obs4MIPs/blob/{revision}/examples/process.py"
    )
    assert not is_processing_code_location(
        "https://github.com/WCRP-ESMO/obs4MIPs/blob/main/examples/process.py"
    )
    assert not is_processing_code_location(
        f"https://github.com/WCRP-ESMO/obs4MIPs/blob/{revision}/src/process.py"
    )
    assert not is_processing_code_location("https://example.org/process.py")


def test_processing_code_location_repository_is_recommended_not_required():
    location = (
        "https://github.com/rubisco-sfa/ilamb3-data/"
        "blob/main/data/WECANN-1-0/convert.py"
    )
    dataset = DatasetStub({"processing_code_location": location})
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    format_results = check.check_global_attribute_formats(dataset)
    repository_result = check.check_processing_code_location_repository(dataset)

    assert len(format_results) == 1
    assert format_results[0].value
    assert repository_result.weight == BaseCheck.MEDIUM
    assert not repository_result.value
    assert repository_result.name == "processing_code_location"
    assert repository_result.msgs == [
        "We recommend forking https://github.com/WCRP-ESMO/obs4MIPs, adding your "
        "processing scripts to the `examples` directory, and submitting a PR."
    ]


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        (
            {
                "product": "site-observations",
                "nominal_resolution": "site",
                "grid": "site",
                "grid_label": "site-SGP",
                "site_id": "SGP",
                "site_location": "Southern Great Plains",
            },
            True,
        ),
        (
            {
                "product": "site-collection",
                "nominal_resolution": "site-collection",
                "grid": "site-collection",
                "grid_label": "site-collection",
                "site_id": "collection",
                "site_location": "collection",
            },
            True,
        ),
        (
            {
                "product": "site-observations",
                "nominal_resolution": "100 km",
                "grid": "site",
                "grid_label": "gn",
                "site_id": "SGP",
                "site_location": "Southern Great Plains",
            },
            False,
        ),
    ],
)
def test_site_metadata_consistency(attributes, expected):
    dataset = DatasetStub(attributes)
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_site_metadata_consistency(dataset)

    assert result is not None
    assert result.value is expected


@pytest.mark.parametrize(
    ("variable_id", "units_metadata", "expected"),
    [
        ("tasanom", "temperature: difference", True),
        ("tas", "temperature: difference", False),
        ("tasanom", "temperature: on_scale", False),
    ],
)
def test_anomaly_naming_uses_variable_level_units_metadata(
    variable_id, units_metadata, expected
):
    assert all(spec.name != "units_metadata" for spec in GLOBAL_ATTR_SPECS)
    dataset = DatasetStub(
        {"variable_id": variable_id},
        {variable_id: VariableStub({"units_metadata": units_metadata})},
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_anomaly_variable_naming(dataset)

    assert result is not None
    assert result.value is expected


def test_license_recommendation_is_not_a_required_failure():
    dataset = DatasetStub({"license": "UK Open Government Licence v3.0"})
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_license_text(dataset)

    assert not result.value
    assert result.weight == BaseCheck.MEDIUM
    assert result.name == "license"
    assert result.msgs == [
        "license='UK Open Government Licence v3.0' does not reference a Creative "
        "Commons license. ODS recommends referencing one; other license terms "
        "remain permitted"
    ]


def test_filename_matches_template_attributes_and_time_coordinate():
    filename = "rlut_mon_CERES-EBAF-4-2_RSS_gn_200003-200004.nc"
    dataset = DatasetStub(
        ods_path_attributes(),
        {"time": TimeVariableStub([74, 105])},
        f"/archive/{filename}",
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert result.value, result.msgs


def test_filename_reports_attribute_and_time_coordinate_mismatches():
    filename = "rlut_day_CERES-EBAF-4-2_RSS_gn_200003-200005.nc"
    dataset = DatasetStub(
        ods_path_attributes(),
        {"time": TimeVariableStub([74, 105])},
        f"/archive/{filename}",
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert not result.value
    assert any("frequency='day'" in message for message in result.msgs)
    assert any(
        "time coordinate span '200003-200004'" in message for message in result.msgs
    )


@pytest.mark.parametrize(
    ("filename", "message_fragment"),
    [
        (
            "rlut-extra_mon_CERES-EBAF-4-2_RSS_gn_200003-200004.nc",
            "variable_id='rlut-extra'",
        ),
        (
            "rlut_mon_CERES_EBAF_RSS_gn_200003-200004.nc",
            "must follow",
        ),
        (
            "rlut_mon_CERES-EBAF-4-2_RSS_gn_200003-200004.nc4",
            "must end with '.nc'",
        ),
        (
            "rlut_mon_CERES-EBAF-4-2_RSS_gn_200005-200003.nc",
            "ordered, equally precise",
        ),
        (
            "rlut_mon_CERES-EBAF-4-2_RSS_gn_20003-20004.nc",
            "ordered, equally precise",
        ),
    ],
)
def test_filename_rejects_invalid_structure(filename, message_fragment):
    dataset = DatasetStub(ods_path_attributes(), filepath=f"/archive/{filename}")
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert not result.value
    assert any(message_fragment in message for message in result.msgs)


def test_filename_rejects_hyphen_in_variable_id():
    filename = "rlut-anom_mon_CERES-EBAF-4-2_RSS_gn_200003-200004.nc"
    dataset = DatasetStub(
        ods_path_attributes(variable_id="rlut-anom"), filepath=f"/archive/{filename}"
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert not result.value
    assert any("variable_id='rlut-anom'" in message for message in result.msgs)


def test_filename_requires_time_range_when_time_coordinate_has_values():
    filename = "rlut_mon_CERES-EBAF-4-2_RSS_gn.nc"
    dataset = DatasetStub(
        ods_path_attributes(),
        {"time": TimeVariableStub([74, 105])},
        f"/archive/{filename}",
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert not result.value
    assert result.msgs == ["time-varying data must include time_range in the file name"]


def test_filename_omits_time_range_for_fixed_fields():
    filename = "orog_fx_CERES-EBAF-4-2_RSS_gn.nc"
    dataset = DatasetStub(
        ods_path_attributes(variable_id="orog", frequency="fx"),
        filepath=f"/archive/{filename}",
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert result.value, result.msgs


def test_filename_rejects_time_range_for_fixed_fields():
    filename = "orog_fx_CERES-EBAF-4-2_RSS_gn_2000-2001.nc"
    dataset = DatasetStub(
        ods_path_attributes(variable_id="orog", frequency="fx"),
        filepath=f"/archive/{filename}",
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert not result.value
    assert "time-invariant frequency 'fx' must omit time_range" in result.msgs


@pytest.mark.parametrize(
    ("frequency", "time_range", "expected_digits"),
    [
        ("yr", "200001-200101", 4),
        ("mon", "20000101-20000201", 6),
        ("day", "200001-200002", 8),
        ("1hr", "2000010100-2000010200", 12),
        ("subhrPt", "200001010000-200001010100", 14),
    ],
)
def test_filename_enforces_cmip_time_precision(frequency, time_range, expected_digits):
    filename = f"rlut_{frequency}_CERES-EBAF-4-2_RSS_gn_{time_range}.nc"
    dataset = DatasetStub(
        ods_path_attributes(frequency=frequency), filepath=f"/archive/{filename}"
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert not result.value
    assert any(
        f"requires {expected_digits}-digit labels" in message for message in result.msgs
    )


def test_filename_uses_frequency_not_suffix_for_climatology():
    filename = "rlut_monC_CERES-EBAF-4-2_RSS_gn_200003-200004.nc"
    dataset = DatasetStub(
        ods_path_attributes(frequency="monC"),
        {"time": TimeVariableStub([74, 105], climatology="climatology_bnds")},
        f"/archive/{filename}",
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert result.value, result.msgs


def test_filename_rejects_non_ods_clim_suffix_for_climatology():
    filename = "rlut_monC_CERES-EBAF-4-2_RSS_gn_200003-200004-clim.nc"
    dataset = DatasetStub(
        ods_path_attributes(frequency="monC"),
        {"time": TimeVariableStub([74, 105], climatology="climatology_bnds")},
        f"/archive/{filename}",
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert not result.value
    assert any("ordered, equally precise" in message for message in result.msgs)


def test_filename_rejects_non_ods_clim_suffix_without_climatology():
    filename = "rlut_mon_CERES-EBAF-4-2_RSS_gn_200003-200004-clim.nc"
    dataset = DatasetStub(
        ods_path_attributes(),
        {"time": TimeVariableStub([74, 105])},
        f"/archive/{filename}",
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_filename(dataset)

    assert not result.value
    assert any("ordered, equally precise" in message for message in result.msgs)


def test_directory_structure_matches_attributes_and_version():
    filename = "rlut_mon_CERES-EBAF-4-2_RSS_gn_200003-200004.nc"
    path = f"/archive/obs4MIPs/RSS/CERES-EBAF-4-2/mon/rlut/100km/v20240803/{filename}"
    dataset = DatasetStub(ods_path_attributes(), filepath=path)
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_directory_structure(dataset)

    assert result.value, result.msgs


def test_directory_uses_first_activity_when_global_attribute_lists_multiple():
    filename = "rlut_mon_CERES-EBAF-4-2_RSS_gn_200003-200004.nc"
    path = f"/archive/obs4MIPs/RSS/CERES-EBAF-4-2/mon/rlut/100km/v20240803/{filename}"
    dataset = DatasetStub(
        ods_path_attributes(activity_id="obs4MIPs another-activity"), filepath=path
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_directory_structure(dataset)

    assert result.value, result.msgs


def test_directory_structure_reports_component_and_version_errors():
    filename = "rlut_mon_CERES-EBAF-4-2_RSS_gn_200003-200004.nc"
    path = f"/archive/obs4MIPs/RSS/CERES-EBAF-4-2/day/rlut/100-km/20240803/{filename}"
    dataset = DatasetStub(ods_path_attributes(), filepath=path)
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_directory_structure(dataset)

    assert not result.value
    assert result.msgs == [
        "Directory structure must follow "
        "<activity_id>/<institution_id>/<source_id>/<frequency>/<variable_id>/"
        "<nominal_resolution>/<version>/<filename>.nc",
        "Provided directory structure: "
        "/archive/obs4MIPs/RSS/CERES-EBAF-4-2/day/rlut/100-km/20240803\n"
        "  - "
        "DRS frequency 'day' does not match the frequency global attribute: 'mon'"
        "\n  - "
        "DRS nominal_resolution '100-km' does not match the nominal_resolution "
        "global attribute: '100km'"
        "\n  - "
        "DRS version '20240803' does not match the required form: 'vYYYYMMDD'",
    ]


def test_directory_structure_requires_all_seven_drs_levels():
    dataset = DatasetStub(
        ods_path_attributes(),
        filepath="/archive/v20240803/rlut_mon_CERES-EBAF-4-2_RSS_gn.nc",
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_directory_structure(dataset)

    assert not result.value
    assert result.msgs == [
        "Directory structure must follow "
        "<activity_id>/<institution_id>/<source_id>/<frequency>/<variable_id>/"
        "<nominal_resolution>/<version>/<filename>.nc",
        "Provided directory structure: /archive/v20240803\n"
        "  - "
        "DRS has 2 directory levels; "
        "ODS requires seven trailing DRS levels",
    ]


def test_absolute_path_root_is_not_treated_as_a_drs_directory():
    filename = "obs4MIPs_ColumbiaU_WECANN-1-0_mon_gpp_gn_v20260302.nc"
    path = f"/Users/6ru/Desktop/ilamb3-data/data/WECANN-1-0/{filename}"
    dataset = DatasetStub(
        ods_path_attributes(
            institution_id="ColumbiaU",
            source_id="WECANN-1-0",
            variable_id="gpp",
            nominal_resolution="1 degree",
        ),
        filepath=path,
    )
    check = Obs4Mips2_6_1Check()
    check.setup(dataset)

    result = check.check_directory_structure(dataset)

    assert not result.value
    assert result.msgs == [
        "Directory structure must follow "
        "<activity_id>/<institution_id>/<source_id>/<frequency>/<variable_id>/"
        "<nominal_resolution>/<version>/<filename>.nc",
        "Provided directory structure: "
        "/Users/6ru/Desktop/ilamb3-data/data/WECANN-1-0\n"
        "  - "
        "DRS has 6 directory levels; "
        "ODS requires seven trailing DRS levels",
    ]
    assert all("activity_id directory" not in message for message in result.msgs)
