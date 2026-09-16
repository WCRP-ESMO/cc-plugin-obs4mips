from argparse import ArgumentParser, Namespace
from pathlib import Path

import pytest

from cc_plugin_obs4mips.companion_file import (
    Obs4MipsCompanionFileGenerator,
    include_companion_files,
)


def touch(path: Path) -> Path:
    path.touch()
    return path


def test_cli_hook_appends_user_supplied_companions_in_order(tmp_path):
    primary = touch(tmp_path / "tas.nc")
    uncertainty = touch(tmp_path / "tasStdDev.nc")
    cell_measure = touch(tmp_path / "areacella.nc")
    args = Namespace(
        companion_file=[str(uncertainty), str(cell_measure)],
        dataset_location=[str(primary)],
    )

    assert include_companion_files(args) == [
        uncertainty.resolve(),
        cell_measure.resolve(),
    ]
    assert args.dataset_location == [
        str(primary),
        str(uncertainty.resolve()),
        str(cell_measure.resolve()),
    ]


def test_cli_hook_deduplicates_primary_and_companion_paths(tmp_path):
    primary = touch(tmp_path / "tas.nc")
    companion = touch(tmp_path / "tasStdDev.nc")
    args = Namespace(
        companion_file=[str(primary), str(companion), str(companion)],
        dataset_location=[str(primary)],
    )

    assert include_companion_files(args) == [companion.resolve()]
    assert args.dataset_location == [str(primary), str(companion.resolve())]


def test_cli_hook_requires_exactly_one_primary_input(tmp_path):
    companion = touch(tmp_path / "companion.nc")
    args = Namespace(
        companion_file=[str(companion)],
        dataset_location=[str(tmp_path / "one.nc"), str(tmp_path / "two.nc")],
    )

    with pytest.raises(ValueError, match="exactly one primary input"):
        include_companion_files(args)

    with pytest.raises(SystemExit, match="exactly one primary input"):
        Obs4MipsCompanionFileGenerator.get_checkers(args)


@pytest.mark.parametrize("missing", ["primary", "companion"])
def test_cli_hook_rejects_missing_files(tmp_path, missing):
    primary = tmp_path / "primary.nc"
    companion = tmp_path / "companion.nc"
    if missing != "primary":
        touch(primary)
    if missing != "companion":
        touch(companion)
    args = Namespace(
        companion_file=[str(companion)],
        dataset_location=[str(primary)],
    )

    with pytest.raises(ValueError, match="does not exist|existing local primary"):
        include_companion_files(args)


def test_cli_hook_is_noop_without_companions():
    args = Namespace(companion_file=None, dataset_location=["remote-url"])

    assert include_companion_files(args) == []
    assert args.dataset_location == ["remote-url"]


def test_companion_file_option_is_repeatable():
    parser = ArgumentParser()
    Obs4MipsCompanionFileGenerator.add_arguments(parser)

    args = parser.parse_args(
        [
            "--companion-file",
            "uncertainty.nc",
            "--companion-file",
            "areacella.nc",
        ]
    )

    assert args.companion_file == ["uncertainty.nc", "areacella.nc"]
