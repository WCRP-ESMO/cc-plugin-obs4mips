import pytest

from cc_plugin_obs4mips.checks.ods_2_6 import Obs4Mips2_6Check
from cc_plugin_obs4mips.cv import CV
from cc_plugin_obs4mips.obs4mips import Obs4MipsCheck
from cc_plugin_obs4mips.specs.ods_2_6 import GLOBAL_ATTR_SPECS


class DatasetStub:
    def __init__(self, attributes):
        self._attributes = attributes

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
    assert any("activity_id" in message for result in results for message in result.msgs)


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
