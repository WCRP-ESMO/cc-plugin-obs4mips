"""
Fixtures that write small but real NetCDF files, so tests never need stand-in classes.

GOOD_VALUES is the one place that says what a valid file looks like. A test changes a
value (or drops an attribute) and checks that exactly the expected problem is reported.
"""

import uuid
from pathlib import Path

import numpy as np
import pytest
from netCDF4 import Dataset

from cc_plugin_obs4mips.checks import Obs4MipsCheck

GOOD_VALUES = {
    "activity_id": "obs4MIPs",
    "Conventions": "CF-1.12 ODS-2.6.1",
    "contact": "Jane Doe (jane@example.org)",
    "creation_date": "2025-01-01T00:00:00Z",
    "data_specs_version": "2.6.1",
    "dataset_contributor": "Jane Doe",
    "doi": "10.5281/zenodo.1234567",
    "frequency": "mon",
    "grid": "native grid",
    "grid_label": "gn",
    "has_aux_unc": "FALSE",
    "institution": "Oakridge National Laboratory, TN, USA",
    "institution_id": "ORNL",
    "license": "Data are licensed under a Creative Commons Attribution 4.0 International License",
    "nominal_resolution": "100 km",
    "processing_code_location": "https://github.com/WCRP-ESMO/obs4MIPs/blob/0123456789abcdef/examples/run.py",
    "product": "reanalysis",
    "realm": "atmos",
    "references": "Doe et al. (2025)",
    "region": "global",
    "source": "Monthly NOAA/CIRES/DOE 20th Century Reanalysis V3",
    "source_data_retrieval_date": "2025-01-01T00:00:00Z",
    "source_data_url": "https://example.org/data",
    "source_id": "20CR-V3",
    "source_label": "20CR",
    "source_type": "reanalysis",
    "source_version_number": "V3",
    "tracking_id": f"hdl:21.14102/{uuid.UUID(int=1)}",
    "variable_id": "tas",
    "variant_info": "Best estimate",
    "variant_label": "BE",
}

# File location and name that agree with GOOD_VALUES
GOOD_DIRECTORY = "obs4MIPs/ORNL/20CR-V3/mon/tas/gn/v20250101"
GOOD_FILENAME = "tas_mon_20CR-V3_BE_gn_200001-200002.nc"


@pytest.fixture
def good_values():
    return dict(GOOD_VALUES)


@pytest.fixture
def run_check(tmp_path, monkeypatch):
    """run_check("check_filename", frequency="day") -> list of Results.

    Writes a good file (two monthly time steps), applies the changes, and runs one check.
      drop=(...)        attribute names to leave out
      directory=...     replace GOOD_DIRECTORY
      filename=...      replace GOOD_FILENAME
      time_values=...   replace the time axis (days since 2000-01-01)
      anything else     is a global attribute value
    """
    monkeypatch.chdir(tmp_path)  # relative paths: the directory checks see only what we write

    def run(method, *, drop=(), directory=GOOD_DIRECTORY, filename=GOOD_FILENAME,
            time_values=(15.0, 45.0), **changes):  # fmt: skip
        values = {**GOOD_VALUES, **changes}
        path = Path(directory) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with Dataset(path, "w") as ds:
            ds.createDimension("time", len(time_values))
            time = ds.createVariable("time", "f8", ("time",))
            time.units, time.calendar = "days since 2000-01-01", "standard"
            time[:] = np.array(time_values)
            variable = ds.createVariable(values["variable_id"], "f4", ("time",))
            variable.units = "K"
            if "units_metadata" in values:
                variable.units_metadata = values.pop("units_metadata")
            ds.setncatts({k: v for k, v in values.items() if k not in drop})
        with Dataset(path) as ds:
            checker = Obs4MipsCheck()
            checker.setup(ds)
            results = getattr(checker, method)(ds)
        if results is None:
            return []
        return results if isinstance(results, list) else [results]

    return run


def failed(results):
    """The Results that did not pass."""
    return [r for r in results if not (r.value[0] == r.value[1] if isinstance(r.value, tuple) else r.value)]


def messages(results):
    """All messages of the failed Results, as one string."""
    return "\n".join(msg for r in failed(results) for msg in r.msgs)
