import subprocess
from pathlib import Path

import pytest
from netCDF4 import Dataset

DATA = Path(__file__).parent / "data"


@pytest.fixture
def nc_from_cdl(tmp_path):
    def _build(cdl_name):
        cdl = DATA / cdl_name
        nc = tmp_path / cdl.with_suffix(".nc").name
        subprocess.run(["ncgen", "-o", str(nc), str(cdl)], check=True)
        return Dataset(nc)

    return _build
