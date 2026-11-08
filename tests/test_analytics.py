import pandas as pd
import pytest

from socklock_recovery import analytics as a
from socklock_recovery.generate_data import generate_events


@pytest.fixture(scope="module")
def sessions():
    return a.build_sessions(generate_events(30_000, seed=7))


def test_funnel_matches_data_room(sessions):
    f = a.funnel(sessions).set_index("stage")["pct_of_clicks"]
    targets = {1: 0.88, 3: 0.61, 4: 0.58, 5: 0.36, 6: 0.31, 7: 0.02}
    for stage, target in targets.items():
        assert f[stage] == pytest.approx(target, abs=0.012), stage


def test_funnel_lost_adds_up(sessions):
    f = a.funnel(sessions)
    assert f["lost"].iloc[1:].sum() == len(sessions) - f["sessions"].iloc[-1]


def test_email_step_finds_mobile(sessions):
    t = a.transition_breakdown(sessions, "device", 4, 5).set_index("value")
    assert t.loc["mobile", "rate"] < t.loc["desktop", "rate"]
    assert t["flag"].all()


def test_pain_analysis_finds_planted_patterns(sessions):
    p = a.pain_analysis(sessions).set_index("pain")
    assert p["conversion_index"].idxmax() == "lost_in_laundry"
    assert p["conversion_index"].idxmin() == "wear_out"
    assert p["email_pass_rate"].idxmin() == "sorting_time"
    assert p["share_of_answers"].sum() == pytest.approx(1.0)
    assert len(a.pain_insights(a.pain_analysis(sessions))) == 3


def test_leads_are_emails_without_purchase(sessions):
    l = a.leads(sessions)
    assert l["email"].notna().all() and not l["purchased"].any()
    share = len(l) / len(sessions)
    assert share == pytest.approx(0.34, abs=0.015)


def test_segments_cover_all_leads(sessions):
    l = a.leads(sessions)
    s = a.segments(l)
    assert s["leads"].sum() == len(l)
    assert len(s) == 10


def test_opportunity_matches_doc_base_case():
    o = a.opportunity(0.34, 400_000, 1.0, 0.01, 60, 3_000)
    assert o["leads"] == pytest.approx(136_000)
    assert o["egp"] == pytest.approx(78_600)


def test_missing_columns_rejected():
    with pytest.raises(ValueError, match="missing columns"):
        a.build_sessions(pd.DataFrame({"session_id": [1]}))
