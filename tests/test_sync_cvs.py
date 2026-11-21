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


# --- user-updatable bundle and the obs4mips-update-cvs command ---

from cc_plugin_obs4mips import cv_sync  # noqa: E402


def fake_cvs(root, ods_version="2.6"):
    write_term(root, "frequency", "mon", drs_name="mon")
    (root / "global_attributes.json").write_text(
        json.dumps({"ods_version": ods_version, "global_attributes": {"frequency": ATTRIBUTE}})
    )
    (root / "drs_specs.yaml").write_text(
        "directory: {separator: /, parts: [{source_collection: frequency, is_required: true}]}\n"
        "file_name: {separator: _, properties: {extension: nc}, parts: [{source_collection: frequency, is_required: true}]}\n"
        "dataset_id: {separator: ., parts: [{source_collection: frequency, is_required: true}]}\n"
    )
    return root


@pytest.fixture
def user_bundle(tmp_path, monkeypatch):
    path = tmp_path / "user" / "obs4mips.json"
    monkeypatch.setenv(cv_sync.USER_BUNDLE_ENV, str(path))
    return path


def patch_download(monkeypatch, cvs, sha="a" * 40):
    monkeypatch.setattr(cv_sync, "resolve_ref", lambda repository, ref: sha)
    monkeypatch.setattr(cv_sync, "download", lambda repository, ref, destination: cvs)


def packaged_ods_version():
    return json.loads(cv_sync.packaged_bundle_text())["ods_version"]


def test_load_bundle_is_the_packaged_one_without_an_update(user_bundle):
    assert cv_sync.load_bundle() == json.loads(cv_sync.packaged_bundle_text())


def test_update_writes_a_bundle_that_load_bundle_prefers(tmp_path, user_bundle, monkeypatch, capsys):
    (tmp_path / "cvs_src").mkdir()
    patch_download(monkeypatch, fake_cvs(tmp_path / "cvs_src", packaged_ods_version()))
    assert cv_sync.update_main([]) == 0
    assert cv_sync.load_bundle()["cvs_ref"] == "a" * 40
    assert "updated CVs" in capsys.readouterr().out
    assert cv_sync.update_main([]) == 0  # second run changes nothing
    assert "already up to date" in capsys.readouterr().out


def test_update_refuses_another_ods_version(tmp_path, user_bundle, monkeypatch, capsys):
    (tmp_path / "cvs_src").mkdir()
    patch_download(monkeypatch, fake_cvs(tmp_path / "cvs_src", ods_version="99.0"))
    assert cv_sync.update_main([]) == 1
    assert not user_bundle.exists() and "ODS 99.0" in capsys.readouterr().err


def test_update_failure_leaves_the_existing_bundle_alone(user_bundle, monkeypatch):
    def offline(repository, ref):
        raise OSError("no network")

    monkeypatch.setattr(cv_sync, "resolve_ref", offline)
    assert cv_sync.update_main([]) == 1
    assert not user_bundle.exists()


def test_broken_user_bundle_is_ignored_with_a_warning(user_bundle, capsys):
    user_bundle.parent.mkdir(parents=True)
    user_bundle.write_text("{not json")
    assert cv_sync.load_bundle() == json.loads(cv_sync.packaged_bundle_text())
    assert "ignoring updated CVs" in capsys.readouterr().err


def test_reset_removes_the_user_bundle(user_bundle, capsys):
    user_bundle.parent.mkdir(parents=True)
    user_bundle.write_text("{}")
    assert cv_sync.update_main(["--reset"]) == 0 and not user_bundle.exists()
