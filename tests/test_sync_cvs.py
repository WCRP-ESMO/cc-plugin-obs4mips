import json

import pytest

from cc_plugin_obs4mips.cv_sync import build_bundle, read_table

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


# --- shipped and updated snapshots, and the `cc-plugin-obs4mips` command ---

from cc_plugin_obs4mips import cli, cv_sync  # noqa: E402


def fake_cvs(root, ods_version="2.6"):
    write_term(root, "frequency", "mon", drs_name="mon")
    (root / "frequency" / "000_context.jsonld").write_text("{}")
    (root / "esgvoc_manifest.yaml").write_text("cv_version: 9.9.9\n")
    (root / "global_attributes.json").write_text(
        json.dumps({"ods_version": ods_version, "global_attributes": {"frequency": ATTRIBUTE}})
    )
    (root / "drs_specs.yaml").write_text(
        "directory: {separator: /, parts: [{source_collection: frequency, is_required: true}]}\n"
        "file_name: {separator: _, properties: {extension: nc}, parts: [{source_collection: frequency, is_required: true}]}\n"
        "dataset_id: {separator: ., parts: [{source_collection: frequency, is_required: true}]}\n"
    )
    return root


@pytest.fixture(autouse=True)
def user_root(tmp_path, monkeypatch):
    root = tmp_path / "user"
    monkeypatch.setenv(cv_sync.USER_DIR_ENV, str(root))
    cv_sync.load_bundle.cache_clear()
    yield root
    cv_sync.load_bundle.cache_clear()


@pytest.fixture
def cvs(tmp_path, monkeypatch):
    src = tmp_path / "cvs_src"
    src.mkdir()
    monkeypatch.setattr(cv_sync, "resolve_ref", lambda repository, ref: "a" * 40)
    monkeypatch.setattr(cv_sync, "download", lambda repository, ref, destination: src)
    return fake_cvs(src)


def test_every_shipped_snapshot_is_complete_and_named_by_its_ods_version():
    assert cv_sync.shipped_versions()
    for ods in cv_sync.shipped_versions():
        directory = cv_sync.shipped_root() / ods
        assert cv_sync.ods_version_of(directory) == ods
        source = cv_sync.read_source(directory)
        assert len(source["ref"]) == 40 and source["cv_version"]
        assert cv_sync.build_bundle(directory, source["ref"])["attributes"]


def test_shipped_cvs_are_used_without_an_update():
    bundle = cv_sync.load_bundle()
    assert bundle["source"] == "shipped"
    assert bundle["ods_version"] == cv_sync.latest_ods_version()


def test_update_installs_a_snapshot_that_load_bundle_prefers(cvs, user_root):
    cv_sync.update(cv_sync.DEFAULT_REPOSITORY, "main")
    bundle = cv_sync.load_bundle("2.6")
    assert (bundle["source"], bundle["cvs_ref"], bundle["cv_version"]) == ("updated", "a" * 40, "9.9.9")
    assert (user_root / "2.6" / "frequency" / "mon.json").is_file()
    assert (user_root / "2.6" / "SOURCE.json").is_file()


def test_update_from_a_local_checkout_needs_no_network(cvs, monkeypatch):
    def offline(*args):
        raise OSError("no network")

    monkeypatch.setattr(cv_sync, "resolve_ref", offline)
    monkeypatch.setattr(cv_sync, "download", offline)
    cv_sync.update(cv_sync.DEFAULT_REPOSITORY, "main", from_path=cvs)
    assert cv_sync.load_bundle("2.6")["cvs_ref"].startswith("local:")


def test_update_to_an_unknown_ods_version_is_allowed_with_a_warning(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    fake_cvs(other, "9.9")
    message = cv_sync.update(cv_sync.DEFAULT_REPOSITORY, "main", from_path=other)
    assert "no checker for ODS 9.9" in message
    assert cv_sync.load_bundle("2.6")["source"] == "shipped"  # untouched


def test_update_failure_changes_nothing(user_root, monkeypatch):
    def offline(repository, ref):
        raise OSError("no network")

    monkeypatch.setattr(cv_sync, "resolve_ref", offline)
    with pytest.raises(SystemExit):
        cv_sync.update(cv_sync.DEFAULT_REPOSITORY, "main")
    assert not user_root.exists()


def test_unreadable_snapshot_is_ignored_with_a_warning(user_root, capsys):
    (user_root / "2.6").mkdir(parents=True)
    (user_root / "2.6" / "SOURCE.json").write_text("{not json")
    assert cv_sync.load_bundle("2.6")["source"] == "shipped"
    assert "ignoring updated CVs" in capsys.readouterr().err


def test_revert_removes_updated_snapshots(cvs, user_root):
    cv_sync.update(cv_sync.DEFAULT_REPOSITORY, "main")
    assert "reverted" in cv_sync.revert()
    assert not (user_root / "2.6").exists()
    assert cv_sync.load_bundle("2.6")["source"] == "shipped"
    assert "nothing to revert" in cv_sync.revert()


def test_cli_status_update_revert(cvs, capsys):
    assert cli.main(["update"]) == 0
    assert cli.main(["status"]) == 0
    assert "using updated CVs" in capsys.readouterr().out
    assert cli.main(["revert"]) == 0
    assert cli.main(["status"]) == 0
    assert "using shipped CVs" in capsys.readouterr().out
