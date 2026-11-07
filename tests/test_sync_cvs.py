import json

import pytest

from scripts.sync_cvs import build_bundle, read_table

ATTRIBUTE = {
    "description": "x", "dtype": "string", "separator": None, "requirement": "required",
    "conditional": None, "cv": {"table": "frequency", "key": "drs_name"}, "rc": "no",
    "introduced": "2.6", "notes": None,
}  # fmt: skip


def write_term(root, table, name, **fields):
    (root / table).mkdir(exist_ok=True)
    (root / table / f"{name}.json").write_text(json.dumps({"id": name, "type": table, **fields}))


def test_read_table_splits_values_and_patterns(tmp_path):
    write_term(tmp_path, "frequency", "mon", drs_name="mon")
    write_term(tmp_path, "frequency", "day", drs_name="day")
    write_term(tmp_path, "frequency", "stub", drs_name="")  # empty stubs are skipped
    write_term(tmp_path, "frequency", "site", regex="site-.*")
    assert read_table(tmp_path, "frequency", "drs_name") == {"allowed": ["day", "mon"], "patterns": ["site-.*"]}


def test_read_table_without_key_has_no_allowed_values(tmp_path):
    write_term(tmp_path, "contact", "freetext")
    assert read_table(tmp_path, "contact", None) == {}


def test_build_bundle(tmp_path):
    write_term(tmp_path, "frequency", "mon", drs_name="mon")
    (tmp_path / "global_attributes.json").write_text(
        json.dumps({"ods_version": "2.6", "global_attributes": {"frequency": ATTRIBUTE, "grid": {**ATTRIBUTE, "cv": None}}})
    )
    (tmp_path / "drs_specs.yaml").write_text(
        "directory: {separator: /, parts: [{source_collection: frequency, is_required: true}]}\n"
        "file_name: {separator: _, properties: {extension: nc}, parts: [{source_collection: frequency, is_required: true}]}\n"
        "dataset_id: {separator: ., parts: [{source_collection: frequency, is_required: true}]}\n"
    )
    bundle = build_bundle(tmp_path, "abc123")
    assert bundle["cvs_ref"] == "abc123" and bundle["ods_version"] == "2.6"
    assert bundle["attributes"]["frequency"]["allowed"] == ["mon"]
    assert "allowed" not in bundle["attributes"]["grid"]
    assert bundle["drs"]["file_name"] == {
        "separator": "_", "parts": [{"name": "frequency", "required": True}], "extension": "nc",
    }  # fmt: skip


def test_missing_collection_is_an_error(tmp_path):
    with pytest.raises(SystemExit):
        read_table(tmp_path, "nope", "drs_name")
