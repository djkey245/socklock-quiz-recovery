import pandas as pd
import pytest

from socklock_recovery import analytics as a
from socklock_recovery import experiment as x
from socklock_recovery.generate_data import generate_events


@pytest.fixture(scope="module")
def segs():
    return a.segments(a.leads(a.build_sessions(generate_events(20_000, seed=5))))


def test_readout_recovers_planted_lift(segs):
    # family-wise 95%: about 1 seed in 20 rolls out a no-effect segment by chance, so the seed is fixed
    ro = x.readout(x.simulate_results(segs, 100_000, 0.7, seed=3))
    tot = ro[ro["segment_id"] == "TOTAL"].iloc[0]
    assert tot["ci_low"] < 0.0105 < tot["ci_high"] or tot["lift"] == pytest.approx(0.0105, abs=0.002)
    assert tot["verdict"] == "Roll out"
    wear = ro[ro["segment_id"].str.startswith("wear_out")]
    assert (wear["verdict"] != "Roll out").all()


def test_no_effect_means_stop(segs):
    ro = x.readout(x.simulate_results(segs, 100_000, 0.0, seed=2))
    assert (ro["verdict"] != "Roll out").all()
    assert x.overall_decision(ro).startswith("Stop")


def test_compare_math():
    r = x._compare(1000, 30, 1000, 10)
    assert r["lift"] == pytest.approx(0.02)
    assert r["ci_low"] > 0 and r["p_value"] < 0.01


def test_value_of_lift_meets_goal_only_with_recovery():
    assert not x.value_of_lift(0.0).set_index("spend").loc[800_000, "meets_125"]
    v = x.value_of_lift(0.01).set_index("spend").loc[800_000]
    assert v["romi_ads_only"] == pytest.approx(1.205, abs=0.001)
    assert v["meets_125"]


def test_bad_results_rejected():
    with pytest.raises(ValueError, match="missing columns"):
        x.readout(pd.DataFrame({"segment_id": ["a"]}))
    with pytest.raises(ValueError, match="Unknown group"):
        x.readout(pd.DataFrame({"segment_id": ["a"], "group": ["control"], "ordered": [0]}))


def test_flow_health(segs):
    fh = x.flow_health(x.simulate_results(segs, 20_000, seed=3)).set_index("metric")
    assert fh["ok"].all()
