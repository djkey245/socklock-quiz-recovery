"""Holdout test readout: did the recovery emails make money?

Input: one row per lead in the test,
    email, segment_id, group (treatment | holdout), ordered (0/1)
    optional for treatment leads: opened, clicked, unsubscribed, spam (0/1)
Output: incremental orders per lead with a 95% interval, per segment and in total,
a go / keep testing / stop verdict, and what the measured lift is worth at $400k and $800k spend.

The spend economics repeat model/egp_model.py (same constants).
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

from .quiz_schema import pain_label

REQUIRED = {"segment_id", "group", "ordered"}
HEALTH = {"opened": (0.40, ">="), "clicked": (0.03, ">="), "unsubscribed": (0.005, "<"), "spam": (0.0008, "<")}

# go / no-go thresholds (README: stop rule)
STOP_BELOW = 0.0015        # incremental orders per lead
Z95 = 1.959964

# spend economics, same as model/egp_model.py
BASE_SPEND, BASE_ROMI, CPC, LEAD_RATE = 400_000, 1.35, 1.00, 0.34
K = math.log(1.12) / math.log(2)
WITHOUT_RECOVERY_TARGET = 1.25

# planted truth for the synthetic readout: incremental orders per lead
TRUE_LIFT = {"lost_in_laundry": 0.016, "mismatched": 0.012, "kids_lose": 0.011,
             "sorting_time": 0.008, "wear_out": 0.0003}
DROP_MULT = {"offer": 1.3, "step_5": 0.8}
ORGANIC = {"offer": 0.006, "step_5": 0.003}   # holdout leads who come back and buy anyway


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def simulate_results(segments: pd.DataFrame, n_leads: int = 100_000, lift_scale: float = 1.0,
                     seed: int = 11) -> pd.DataFrame:
    """Synthetic 3-week test: leads drawn by segment share, split 50/50, orders from planted lifts.

    100k leads ~ 3 weeks of leads at $400k/month spend.
    """
    rng = np.random.default_rng(seed)
    seg = segments[["segment_id", "pain", "drop_stage", "leads"]].reset_index(drop=True)
    idx = rng.choice(len(seg), size=n_leads, p=(seg["leads"] / seg["leads"].sum()).to_numpy())
    df = seg.iloc[idx][["segment_id", "pain", "drop_stage"]].reset_index(drop=True)
    df["group"] = np.where(rng.random(n_leads) < 0.5, "treatment", "holdout")
    base = df["drop_stage"].map(ORGANIC).to_numpy()
    lift = (df["pain"].map(TRUE_LIFT) * df["drop_stage"].map(DROP_MULT)).to_numpy() * lift_scale
    p = base + np.where(df["group"] == "treatment", lift, 0.0)
    df["ordered"] = (rng.random(n_leads) < p).astype(int)
    t = (df["group"] == "treatment").to_numpy()
    for col, rate in {"opened": 0.46, "clicked": 0.045, "unsubscribed": 0.003, "spam": 0.0004}.items():
        df[col] = np.where(t, (rng.random(n_leads) < rate).astype(int), 0)
    df.insert(0, "email", [f"lead{i:06d}@example.com" for i in range(n_leads)])
    return df.drop(columns=["pain", "drop_stage"])


def validate(results: pd.DataFrame) -> None:
    missing = REQUIRED - set(results.columns)
    if missing:
        raise ValueError(f"Results CSV is missing columns: {', '.join(sorted(missing))}")
    bad = set(results["group"].unique()) - {"treatment", "holdout"}
    if bad:
        raise ValueError(f"Unknown group values: {', '.join(map(str, bad))} (use treatment / holdout)")


def _compare(nt: int, ot: int, nh: int, oh: int, z_ci: float = Z95) -> dict:
    rt, rh = (ot / nt if nt else 0.0), (oh / nh if nh else 0.0)
    lift = rt - rh
    se = math.sqrt(rt * (1 - rt) / nt + rh * (1 - rh) / nh) if nt and nh else math.inf
    p_pool = (ot + oh) / (nt + nh) if nt + nh else 0.0
    se0 = math.sqrt(p_pool * (1 - p_pool) * (1 / nt + 1 / nh)) if nt and nh and p_pool else math.inf
    z = lift / se0 if se0 not in (0, math.inf) else 0.0
    return {"treatment_leads": nt, "treatment_orders": ot, "holdout_leads": nh, "holdout_orders": oh,
            "treatment_rate": rt, "holdout_rate": rh, "lift": lift,
            "ci_low": lift - z_ci * se, "ci_high": lift + z_ci * se,
            "p_value": 2 * (1 - _phi(abs(z)))}


def verdict(row: dict) -> str:
    if row["ci_low"] > 0 and row["lift"] >= STOP_BELOW:
        return "Roll out"
    if row["ci_high"] < STOP_BELOW:
        return "Stop"
    return "Keep testing"


def leads_needed(base_rate: float, lift: float, power: float = 0.8) -> int:
    """Leads per group to detect `lift` over `base_rate` (two-sided, 5%)."""
    if lift <= 0:
        return 0
    zb = {0.8: 0.841621, 0.9: 1.281552}[power]
    p1, p2 = base_rate, base_rate + lift
    return math.ceil((Z95 + zb) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / lift ** 2)


def readout(results: pd.DataFrame) -> pd.DataFrame:
    """One row per segment plus a TOTAL row.

    Segment intervals are Bonferroni-corrected (95% across all segments at once), so with
    10 segments one lucky segment does not get rolled out by chance. TOTAL uses a plain 95%.
    """
    validate(results)
    r = results.assign(ordered=pd.to_numeric(results["ordered"]).astype(int))
    k = r["segment_id"].nunique()
    z_seg = NormalDist().inv_cdf(1 - 0.025 / max(k, 1))
    rows = []
    for sid, g in list(r.groupby("segment_id")) + [("TOTAL", r)]:
        t, h = g[g["group"] == "treatment"], g[g["group"] == "holdout"]
        z = Z95 if sid == "TOTAL" else z_seg
        row = {"segment_id": sid, **_compare(len(t), int(t["ordered"].sum()), len(h), int(h["ordered"].sum()), z)}
        row["verdict"] = verdict(row)
        row["leads_needed"] = leads_needed(row["holdout_rate"] or 0.004, max(row["lift"], 0.003))
        rows.append(row)
    out = pd.DataFrame(rows)
    seg = out["segment_id"].str.split("__", expand=True)
    out["label"] = np.where(out["segment_id"] == "TOTAL", "All tested leads",
                            seg[0].map(pain_label) + " / " + seg[1].map(
                                {"offer": "saw offer", "step_5": "left after email step"}).fillna(""))
    body = out[out["segment_id"] != "TOTAL"].sort_values("lift", ascending=False)
    return pd.concat([body, out[out["segment_id"] == "TOTAL"]]).reset_index(drop=True)


def flow_health(results: pd.DataFrame) -> pd.DataFrame:
    t = results[results["group"] == "treatment"]
    rows = []
    for col, (target, op) in HEALTH.items():
        if col not in t:
            continue
        rate = pd.to_numeric(t[col]).mean()
        ok = rate >= target if op == ">=" else rate < target
        rows.append({"metric": col, "rate": rate, "target": f"{op} {target:.2%}", "ok": bool(ok)})
    return pd.DataFrame(rows)


def overall_decision(ro: pd.DataFrame) -> str:
    body = ro[ro["segment_id"] != "TOTAL"]
    tot = ro[ro["segment_id"] == "TOTAL"].iloc[0]
    if (body["verdict"] == "Stop").all() or (tot["verdict"] == "Stop" and not (body["verdict"] == "Roll out").any()):
        return (f"Stop: incremental orders per lead are {tot['lift']:+.2%} overall (95% CI up to {tot['ci_high']:.2%}), "
                "below the 0.15% minimum. Reuse the analysis to fix the quiz email step instead.")
    win = body[body["verdict"] == "Roll out"]
    stop = body[body["verdict"] == "Stop"]
    parts = []
    if len(win):
        parts.append(f"Roll out to {len(win)} segment(s) and end their holdout (keep 10% as a permanent control)")
    if len(stop):
        parts.append(f"stop {len(stop)} segment(s) that do not pay back")
    rest = len(body) - len(win) - len(stop)
    if rest:
        parts.append(f"keep testing {rest} segment(s) until they reach the sample size shown")
    return "; ".join(parts) + "." if parts else "Keep testing."


# ---------- what the measured lift is worth ----------

def _degr(spend: float) -> float:
    return (spend / BASE_SPEND) ** K


def ads_romi(spend: float) -> float:
    return BASE_ROMI / _degr(spend)


def monthly_leads(spend: float) -> float:
    return spend / (CPC * _degr(spend)) * LEAD_RATE


def value_of_lift(lift: float, ltv: float = 60, esp: float = 3_000, spend_levels=(400_000, 800_000)) -> pd.DataFrame:
    rows = []
    for s in spend_levels:
        orders = monthly_leads(s) * max(lift, 0)
        romi = ads_romi(s)
        total = (s * romi + orders * ltv) / (s + esp)
        rows.append({"spend": s, "leads": monthly_leads(s), "orders": orders,
                     "egp": orders * ltv - esp, "romi_ads_only": romi, "romi_with_recovery": total,
                     "meets_125": total >= WITHOUT_RECOVERY_TARGET})
    return pd.DataFrame(rows)


def main() -> None:
    import argparse

    from . import analytics as a
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default="data/quiz_events.csv.gz")
    ap.add_argument("--leads", type=int, default=100_000)
    ap.add_argument("--lift-scale", type=float, default=0.7, help="0.7 ~ the 1%% base case")
    ap.add_argument("--out", default="data/experiment_results.csv.gz")
    args = ap.parse_args()
    segs = a.segments(a.leads(a.build_sessions(pd.read_csv(args.csv))))
    res = simulate_results(segs, args.leads, args.lift_scale)
    res.to_csv(args.out, index=False)
    print(f"{len(res):,} leads -> {args.out}")
    print(readout(res)[["segment_id", "lift", "ci_low", "ci_high", "verdict"]].to_string())


if __name__ == "__main__":
    main()
