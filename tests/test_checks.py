from cc_plugin_obs4mips.obs4mips import Obs4MipsCheck

def test_required_global_attrs_pass(nc_from_cdl):
    check = Obs4MipsCheck()
    ds = nc_from_cdl("good_obs4mips.cdl")
    check.setup(ds)
    result = check.check_required_global_attrs(ds)
    score, out_of = result.value
    assert score == out_of, result.msgs

def test_required_global_attrs_missing(nc_from_cdl):
    check = Obs4MipsCheck()
    ds = nc_from_cdl("missing_attrs.cdl")
    check.setup(ds)
    result = check.check_required_global_attrs(ds)
    score, out_of = result.value
    assert score < out_of
    assert any("activity_id" in m for m in result.msgs)