import pytest
from compliance_checker.base import BaseCheck

from cc_plugin_obs4mips.checks.ods_2_6 import Obs4Mips2_6Check
from cc_plugin_obs4mips.cv import CV
from cc_plugin_obs4mips.obs4mips import Obs4MipsCheck
from cc_plugin_obs4mips.specs.ods_2_6 import (
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


class DatasetStub:
    def __init__(self, attributes, variables=None):
        self._attributes = attributes
        self.variables = variables or {}

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


def test_legacy_checker_import_is_compatible():
    assert Obs4MipsCheck is Obs4Mips2_6Check


def test_required_global_attributes_pass():
    check = Obs4Mips2_6Check()
    dataset = dataset_with_all_attributes()
    check.setup(dataset)

    results = check.check_global_attributes_present(dataset)

    assert results
    assert all(result.value for result in results)


def test_required_global_attribute_missing():
    check = Obs4Mips2_6Check()
    dataset = dataset_with_all_attributes()
    del dataset._attributes["activity_id"]
    check.setup(dataset)

    results = check.check_global_attributes_present(dataset)

    assert any(not result.value for result in results)
    assert any(
        "activity_id" in message for result in results for message in result.msgs
    )


@pytest.mark.parametrize("frequency", ["mon", "monC", "1hrPt", "fx"])
def test_frequency_cv_accepts_obs4mips_drs_names(frequency):
    assert CV.contains("2.6.1", "frequency", frequency)


@pytest.mark.parametrize("frequency", ["monthly", "monc", "1HR", ""])
def test_frequency_cv_rejects_unknown_or_mis_cased_values(frequency):
    assert not CV.contains("2.6.1", "frequency", frequency)


def test_checker_reports_invalid_frequency_as_required():
    check = Obs4Mips2_6Check()
    dataset = DatasetStub({"frequency": "monthly"})
    check.setup(dataset)

    results = check.check_global_attribute_cv(dataset)

    assert len(results) == 1
    assert not results[0].value
    assert results[0].weight == 3
    assert results[0].msgs == ["frequency='monthly' not in CV 'frequency'"]


def test_title_is_optional_but_encouraged_attributes_are_recommended():
    assert spec_named("title").level == BaseCheck.LOW
    assert spec_named("doi").level == BaseCheck.MEDIUM
    assert spec_named("source_data_retrieval_date").level == BaseCheck.MEDIUM
    assert spec_named("source_data_url").level == BaseCheck.MEDIUM

    dataset = dataset_with_all_attributes()
    for name in ("title", "doi", "source_data_retrieval_date", "source_data_url"):
        del dataset._attributes[name]
    check = Obs4Mips2_6Check()
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
    check = Obs4Mips2_6Check()
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
    check = Obs4Mips2_6Check()

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
    assert is_conventions_string("CF-1.11 ODS-2.6")
    assert is_conventions_string("CF-1.11; ODS-2.6")
    assert not is_conventions_string("NOT-CF-1.11 ODS-2.6-draft")
    assert is_url("https://example.org/data")
    assert not is_url("https:///data")


def test_processing_code_location_requires_obs4mips_revision_permalink():
    revision = "9876ae84146244a20fb498f2a2be7e8272a3142f"
    assert is_processing_code_location(
        "https://github.com/PCMDI/obs4MIPs-cmor-tables/"
        f"tree/{revision}/inputs/RSS/NASA-LaRC"
    )
    assert is_processing_code_location(
        "https://github.com/WCRP-ESMO/obs4MIPs-cmor-tables/"
        f"blob/{revision}/inputs/RSS/process.py"
    )
    assert not is_processing_code_location(
        "https://github.com/PCMDI/obs4MIPs-cmor-tables/tree/main/inputs/RSS"
    )
    assert not is_processing_code_location("https://example.org/process.py")


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
    check = Obs4Mips2_6Check()
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
    check = Obs4Mips2_6Check()
    check.setup(dataset)

    result = check.check_anomaly_variable_naming(dataset)

    assert result is not None
    assert result.value is expected


def test_license_recommendation_is_not_a_required_failure():
    dataset = DatasetStub({"license": "UK Open Government Licence v3.0"})
    check = Obs4Mips2_6Check()
    check.setup(dataset)

    result = check.check_license_text(dataset)

    assert not result.value
    assert result.weight == BaseCheck.MEDIUM
