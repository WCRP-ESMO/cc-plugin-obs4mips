import json

import numpy as np
from netCDF4 import Dataset

from cc_plugin_obs4mips.dataset_summary import (
    SUMMARY_SCHEMA,
    SUMMARY_SCHEMA_VERSION,
    main,
    summarize_dataset,
)


def make_dataset(path):
    with Dataset(path, "w") as dataset:
        dataset.createDimension("time", None)
        dataset.createDimension("station", 2)
        dataset.Conventions = "CF-1.12 ODS-2.6.1"
        dataset.institution_id = "Example-Institute"
        dataset.numeric_attribute = np.array([1, 2], dtype="i2")

        time = dataset.createVariable("time", "f8", ("time",))
        time.standard_name = "time"
        time.units = "days since 2000-01-01"

        station = dataset.createVariable("station", "i4", ("station",))
        station.long_name = "station index"

        latitude = dataset.createVariable("latitude", "f4", ("station",))
        latitude.standard_name = "latitude"
        latitude.units = "degrees_north"

        gpp = dataset.createVariable(
            "gpp", "f4", ("time", "station"), fill_value=np.float32(1e20)
        )
        gpp.coordinates = "latitude"
        gpp.units = "kg m-2 s-1"

        bounds = dataset.createVariable("time_bnds", "f8", ("time", "station"))
        bounds.long_name = "time bounds"


def test_summary_captures_header_without_data_values(tmp_path):
    dataset_path = tmp_path / "example.nc"
    make_dataset(dataset_path)

    summary = summarize_dataset(dataset_path)
    dataset = summary["dataset"]

    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["schema_version"] == SUMMARY_SCHEMA_VERSION
    assert summary["ods_version"] == "2.6.1"
    assert dataset["file_name"] == "example.nc"
    assert str(tmp_path) not in json.dumps(summary)
    assert dataset["global_attributes"] == {
        "Conventions": "CF-1.12 ODS-2.6.1",
        "institution_id": "Example-Institute",
        "numeric_attribute": [1, 2],
    }
    assert summary["cv_update_candidates"] == {
        "guidance": (
            "Before proposing a new term, verify that an existing registered CV "
            "term is not appropriate."
        ),
        "dataset_global_attributes_path": "/dataset/global_attributes",
        "terms": [
            {
                "attribute": "Conventions",
                "collection": "conventions",
                "registered_content": False,
                "submitted_value": "CF-1.12",
                "value_field": "id",
                "source": (
                    "https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/"
                    "f3a0079eca73d0a7e8a659fbf36c7a29e3ab9a72/conventions"
                ),
                "source_ref": "f3a0079eca73d0a7e8a659fbf36c7a29e3ab9a72",
                "similar_registered_values": ["cf-1.11"],
            },
            {
                "attribute": "Conventions",
                "collection": "conventions",
                "registered_content": False,
                "submitted_value": "ODS-2.6.1",
                "value_field": "id",
                "source": (
                    "https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/"
                    "f3a0079eca73d0a7e8a659fbf36c7a29e3ab9a72/conventions"
                ),
                "source_ref": "f3a0079eca73d0a7e8a659fbf36c7a29e3ab9a72",
                "similar_registered_values": ["ods-2.6", "ods-2.5"],
            },
            {
                "attribute": "institution_id",
                "collection": "institution_id",
                "registered_content": True,
                "submitted_value": "Example-Institute",
                "value_field": "drs_name",
                "source": (
                    "https://github.com/WCRP-ESMO/obs4MIPs_CVs/tree/"
                    "f3a0079eca73d0a7e8a659fbf36c7a29e3ab9a72/institution_id"
                ),
                "source_ref": "f3a0079eca73d0a7e8a659fbf36c7a29e3ab9a72",
                "similar_registered_values": [],
            }
        ],
    }
    assert dataset["dimensions"] == {
        "station": {"size": 2, "unlimited": False},
        "time": {"size": 0, "unlimited": True},
    }
    assert set(dataset["coordinates"]) == {"latitude", "station", "time"}
    assert dataset["coordinates"]["time"]["coordinate_type"] == "dimension"
    assert dataset["coordinates"]["latitude"]["coordinate_type"] == "auxiliary"
    assert set(dataset["variables"]) == {"gpp", "time_bnds"}
    assert dataset["variables"]["gpp"] == {
        "dtype": "float32",
        "dimensions": ["time", "station"],
        "shape": [0, 2],
        "attributes": {
            "_FillValue": np.float32(1e20).item(),
            "coordinates": "latitude",
            "units": "kg m-2 s-1",
        },
    }
    assert all("data" not in variable for variable in dataset["variables"].values())
    assert all(
        "data" not in coordinate for coordinate in dataset["coordinates"].values()
    )


def test_cli_writes_parseable_json(tmp_path, capsys):
    dataset_path = tmp_path / "example.nc"
    output_path = tmp_path / "summary.json"
    make_dataset(dataset_path)

    assert main([str(dataset_path), "--output", str(output_path)]) == 0

    written = json.loads(output_path.read_text())
    assert written == summarize_dataset(dataset_path)
    assert capsys.readouterr().out == f"Wrote dataset summary: {output_path}\n"
