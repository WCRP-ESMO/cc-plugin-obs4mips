import json
from pathlib import Path

import pytest

from scripts.sync_cvs import SyncError, read_table, sync


def write_term(root: Path, name: str, **overrides):
    term = {
        "id": name,
        "type": "frequency",
        "drs_name": name,
        **overrides,
    }
    table_root = root / "frequency"
    table_root.mkdir(parents=True, exist_ok=True)
    (table_root / f"{name}.json").write_text(json.dumps(term), encoding="utf-8")


def write_config(path: Path):
    config = {
        "schema_version": 1,
        "versions": {
            "2.6.1": {
                "repository": "https://github.com/WCRP-ESMO/obs4MIPs_CVs",
                "ref": "abc123",
                "tables": {"frequency": {"value_field": "drs_name"}},
            }
        },
    }
    path.write_text(json.dumps(config), encoding="utf-8")


def test_read_table_extracts_sorted_drs_names(tmp_path):
    write_term(tmp_path, "mon")
    write_term(tmp_path, "1hrPt", id="1hrpt")

    assert read_table(tmp_path, "frequency", "drs_name") == ["1hrPt", "mon"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"type": "grid_label"}, "expected 'frequency'"),
        ({"drs_name": ""}, "no non-empty string 'drs_name'"),
    ],
)
def test_read_table_rejects_malformed_terms(tmp_path, overrides, message):
    write_term(tmp_path, "mon", **overrides)

    with pytest.raises(SyncError, match=message):
        read_table(tmp_path, "frequency", "drs_name")


def test_sync_writes_snapshot_and_check_detects_drift(tmp_path):
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    config_path = tmp_path / "sources.json"
    write_term(source_root, "mon")
    write_config(config_path)

    changed = sync(
        ods_version="2.6.1",
        config_path=config_path,
        output_root=output_root,
        source_root=source_root,
        source_ref_override=None,
        selected_tables=None,
        check=False,
    )
    snapshot = output_root / "2.6.1" / "frequency.json"
    assert changed == [snapshot]
    assert json.loads(snapshot.read_text())["values"] == ["mon"]

    assert (
        sync(
            ods_version="2.6.1",
            config_path=config_path,
            output_root=output_root,
            source_root=source_root,
            source_ref_override=None,
            selected_tables=None,
            check=True,
        )
        == []
    )

    write_term(source_root, "day")
    assert sync(
        ods_version="2.6.1",
        config_path=config_path,
        output_root=output_root,
        source_root=source_root,
        source_ref_override=None,
        selected_tables=None,
        check=True,
    ) == [snapshot]
