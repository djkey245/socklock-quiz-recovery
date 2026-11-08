"""Synthetic quiz-event export, calibrated to the SockLock data room.

Share of ad clicks reaching each stage (data room): opened quiz 88%, step 3 61%,
step 4 58%, step 5 36%, offer 31%, paid 2%. Step 2 (72%) is our assumption.
Built-in patterns for the analysis to find: mobile drops more at the email step,
"sorting_time" drops more at the email step, "wear_out" rarely buys (the magnet
does not fix worn-out socks).

Usage: python -m socklock_recovery.generate_data --sessions 20000 --out data/quiz_events.csv.gz
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .quiz_schema import STEPS

# P(reach next stage | reached this stage), derived from the data-room funnel
REACH = {1: 0.88, 2: 0.72, 3: 0.61, 4: 0.58, 5: 0.36, 6: 0.31}
PAID = 0.02

DEVICES = {"mobile": 0.75, "desktop": 0.25}
COUNTRIES = {"US": 0.875, "UK": 0.05, "CA": 0.04, "AU": 0.035}
CREATIVES = {f"cr_{i:02d}": w for i, w in enumerate([0.22, 0.18, 0.15, 0.12, 0.1, 0.09, 0.08, 0.06], 1)}
ANSWER_WEIGHTS = {
    "who_for": {"me": 0.40, "partner": 0.15, "kids": 0.25, "family": 0.20},
    "pain": {"lost_in_laundry": 0.35, "mismatched": 0.25, "sorting_time": 0.15, "kids_lose": 0.15, "wear_out": 0.10},
    "style": {"casual": 0.45, "athletic": 0.30, "dress": 0.10, "mix": 0.15},
    "size": {"kids": 0.15, "S": 0.15, "M": 0.35, "L": 0.25, "XL": 0.10},
    "household": {"1": 0.25, "2": 0.30, "3-4": 0.35, "5+": 0.10},
}
# Relative pass-rate multipliers (normalised to a weighted mean of 1 below)
EMAIL_STEP_DEVICE = {"mobile": 1.0, "desktop": 1.25}
EMAIL_STEP_PAIN = {"lost_in_laundry": 1.05, "mismatched": 1.0, "sorting_time": 0.80, "kids_lose": 1.05, "wear_out": 0.95}
PAY_PAIN = {"lost_in_laundry": 1.30, "mismatched": 1.0, "sorting_time": 0.90, "kids_lose": 1.10, "wear_out": 0.25}


def _normalise(mult: dict, weights: dict) -> dict:
    mean = sum(mult[k] * weights[k] for k in mult)
    return {k: v / mean for k, v in mult.items()}


def _pick(rng, weights: dict, n: int) -> np.ndarray:
    keys = list(weights)
    p = np.array([weights[k] for k in keys], dtype=float)
    return rng.choice(keys, size=n, p=p / p.sum())


def generate_sessions(n: int = 20_000, seed: int = 42) -> pd.DataFrame:
    """One row per ad click: attributes, answers, max stage, purchase."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "session_id": [f"s{i:07d}" for i in range(n)],
        "device": _pick(rng, DEVICES, n),
        "country": _pick(rng, COUNTRIES, n),
        "creative_id": _pick(rng, CREATIVES, n),
    })
    for key, w in ANSWER_WEIGHTS.items():
        df[key] = _pick(rng, w, n)

    dev_m = _normalise(EMAIL_STEP_DEVICE, DEVICES)
    pain_m = _normalise(EMAIL_STEP_PAIN, ANSWER_WEIGHTS["pain"])
    pay_m = _normalise(PAY_PAIN, ANSWER_WEIGHTS["pain"])

    stage = np.zeros(n, dtype=int)
    prev = 1.0
    for s in range(1, 7):
        p = np.full(n, REACH[s] / prev)
        if s == 5:  # passing the email step
            p = p * df["device"].map(dev_m).to_numpy() * df["pain"].map(pain_m).to_numpy()
        advance = (stage == s - 1) & (rng.random(n) < np.clip(p, 0, 1))
        stage[advance] = s
        prev = REACH[s]
    p_pay = PAID / REACH[6] * df["pain"].map(pay_m).to_numpy()
    paid = (stage == 6) & (rng.random(n) < p_pay)

    df["max_stage"] = stage
    df["purchased"] = paid
    df["email"] = np.where(stage >= 5, [f"lead{i:07d}@example.com" for i in range(n)], None)
    start = datetime(2026, 10, 1)
    df["ts"] = [start + timedelta(seconds=int(x)) for x in rng.integers(0, 30 * 86400, n)]
    return df


def sessions_to_events(sessions: pd.DataFrame) -> pd.DataFrame:
    """Expand sessions into a raw event export, as a quiz tool would log it."""
    rows = []
    for r in sessions.itertuples(index=False):
        t = r.ts
        base = {"session_id": r.session_id, "device": r.device, "country": r.country, "creative_id": r.creative_id}

        def add(event, step=None, answer=None, email=None, secs=0):
            nonlocal t
            t = t + timedelta(seconds=secs)
            rows.append({**base, "ts": t.isoformat(), "event": event, "step": step, "answer": answer, "email": email})

        add("ad_click")
        for s in range(1, 6):
            if r.max_stage < s:
                break
            add("step_view", step=s, secs=5)
            if r.max_stage > s:  # answered and moved on
                key = STEPS[s]["key"]
                add("step_answer", step=s, answer=getattr(r, key), secs=8)
                if s == 4:
                    add("email_submitted", step=4, email=r.email, secs=4)
        if r.max_stage >= 6:
            add("offer_view", step=6, secs=5)
        if r.purchased:
            add("purchase", step=7, secs=90)
    return pd.DataFrame(rows, columns=["session_id", "ts", "event", "step", "answer", "email", "device", "country", "creative_id"])


def generate_events(n: int = 20_000, seed: int = 42) -> pd.DataFrame:
    return sessions_to_events(generate_sessions(n, seed))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=20_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/quiz_events.csv.gz")
    a = ap.parse_args()
    ev = generate_events(a.sessions, a.seed)
    ev.to_csv(a.out, index=False)
    print(f"{len(ev):,} events for {a.sessions:,} sessions -> {a.out}")


if __name__ == "__main__":
    main()
