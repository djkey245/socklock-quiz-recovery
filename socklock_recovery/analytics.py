"""Quiz funnel, drop-off segments, pain analysis and the recovery opportunity.

Input: a raw quiz event export (see generate_data.py for the format).
"""
from __future__ import annotations

import math

import pandas as pd

from .quiz_schema import ANSWER_KEYS, PAID_STAGE, STAGES, STEPS, pain_label, stage_label

REQUIRED_COLUMNS = {"session_id", "ts", "event", "step", "answer", "email", "device", "country", "creative_id"}
DIMENSIONS = ["device", "country", "creative_id", "who_for", "pain", "style", "size", "household"]


def validate_events(events: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(events.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")


def build_sessions(events: pd.DataFrame) -> pd.DataFrame:
    """Collapse events into one row per session (= one ad click)."""
    validate_events(events)
    ev = events.copy()
    ev["step"] = pd.to_numeric(ev["step"], errors="coerce")

    base = ev.groupby("session_id").agg(
        ts=("ts", "min"), device=("device", "first"), country=("country", "first"),
        creative_id=("creative_id", "first"),
    )
    reached = ev[ev["event"].isin(["step_view", "offer_view"])].groupby("session_id")["step"].max()
    base["max_stage"] = reached.reindex(base.index).fillna(0).astype(int)
    base["purchased"] = base.index.isin(ev.loc[ev["event"] == "purchase", "session_id"])
    emails = ev.loc[ev["event"] == "email_submitted"].groupby("session_id")["email"].last()
    base["email"] = emails.reindex(base.index)

    answers = ev[ev["event"] == "step_answer"].copy()
    answers["key"] = answers["step"].map({s: d["key"] for s, d in STEPS.items()})
    wide = answers.pivot_table(index="session_id", columns="key", values="answer", aggfunc="last")
    for key in ANSWER_KEYS:
        base[key] = wide[key].reindex(base.index) if key in wide else None
    return base.reset_index()


def funnel(sessions: pd.DataFrame) -> pd.DataFrame:
    """Sessions reaching each stage, as a share of clicks and of the previous stage."""
    n = len(sessions)
    rows = []
    for stage, label in STAGES:
        rows.append({"stage": stage, "label": label, "sessions": int((sessions["max_stage"] >= stage).sum())})
    rows.append({"stage": PAID_STAGE, "label": "Paid", "sessions": int(sessions["purchased"].sum())})
    df = pd.DataFrame(rows)
    df["pct_of_clicks"] = df["sessions"] / n if n else 0.0
    df["step_conversion"] = df["sessions"] / df["sessions"].shift(1)
    df["lost"] = df["sessions"].shift(1) - df["sessions"]
    df.loc[0, ["step_conversion", "lost"]] = [1.0, 0]
    df["lost"] = df["lost"].astype(int)
    return df


def biggest_leaks(funnel_df: pd.DataFrame, top: int = 3) -> pd.DataFrame:
    return funnel_df.iloc[1:].sort_values("lost", ascending=False).head(top)


def _reached(sessions: pd.DataFrame, stage: int) -> pd.Series:
    return sessions["purchased"] if stage == PAID_STAGE else sessions["max_stage"] >= stage


def transition_breakdown(sessions: pd.DataFrame, dim: str, from_stage: int, to_stage: int,
                         min_n: int = 50) -> pd.DataFrame:
    """Pass rate from one stage to another, per value of a dimension.

    `z` compares each group with the rest; |z| >= 2 on a big enough group is flagged.
    """
    base = sessions[_reached(sessions, from_stage)]
    if dim in ("pain", "who_for", "style", "size", "household"):
        base = base[base[dim].notna()]
    passed = _reached(base, to_stage)
    total_n, total_pass = len(base), int(passed.sum())
    avg = total_pass / total_n if total_n else 0.0

    g = pd.DataFrame({"value": base[dim], "passed": passed}).groupby("value")["passed"].agg(["count", "sum"])
    g.columns = ["sessions", "passed"]
    g["rate"] = g["passed"] / g["sessions"]
    g["vs_avg_pp"] = (g["rate"] - avg) * 100
    rest_n = total_n - g["sessions"]
    rest_rate = (total_pass - g["passed"]) / rest_n.where(rest_n > 0)
    pooled = avg * (1 - avg)
    se = (pooled * (1 / g["sessions"] + 1 / rest_n.where(rest_n > 0))) ** 0.5
    g["z"] = ((g["rate"] - rest_rate) / se).fillna(0.0)
    g["flag"] = (g["z"].abs() >= 2) & (g["sessions"] >= min_n)
    g["lost"] = g["sessions"] - g["passed"]
    out = g.reset_index().sort_values("rate")
    if dim == "pain":
        out["label"] = out["value"].map(pain_label)
    else:
        out["label"] = out["value"].astype(str)
    out.attrs["avg_rate"] = avg
    out.attrs["from"] = stage_label(from_stage)
    out.attrs["to"] = stage_label(to_stage)
    return out


def anomalies(sessions: pd.DataFrame, from_stage: int, to_stage: int, dims=None) -> pd.DataFrame:
    """All flagged groups across dimensions for one transition, worst first."""
    frames = []
    for dim in dims or DIMENSIONS:
        t = transition_breakdown(sessions, dim, from_stage, to_stage)
        if t.empty or (dim in ("pain", "style", "size", "household", "who_for") and from_stage < STEP_OF[dim] + 1):
            continue
        t = t[t["flag"]].assign(dimension=dim)
        frames.append(t)
    if not frames:
        return pd.DataFrame(columns=["dimension", "label", "sessions", "rate", "vs_avg_pp", "z", "lost"])
    return pd.concat(frames).sort_values("z")[["dimension", "label", "sessions", "rate", "vs_avg_pp", "z", "lost"]]


STEP_OF = {d["key"]: s for s, d in STEPS.items()}


def pain_analysis(sessions: pd.DataFrame) -> pd.DataFrame:
    """Which pains bring people in, which pass the email step, which actually pay."""
    s = sessions[sessions["pain"].notna()]
    offer = s[s["max_stage"] >= 6]
    buyers = s[s["purchased"]]
    at_email = s[s["max_stage"] >= 4]
    rows = []
    for key, label in STEPS[2]["options"].items():
        n = int((s["pain"] == key).sum())
        if n == 0:
            continue
        e = at_email[at_email["pain"] == key]
        o = offer[offer["pain"] == key]
        b = buyers[buyers["pain"] == key]
        rows.append({
            "pain": key, "label": label, "answered": n,
            "share_of_answers": n / len(s),
            "email_pass_rate": (e["max_stage"] >= 5).mean() if len(e) else math.nan,
            "offer_to_paid": len(b) / len(o) if len(o) else math.nan,
            "buyers": len(b),
            "share_of_buyers": len(b) / len(buyers) if len(buyers) else math.nan,
        })
    df = pd.DataFrame(rows)
    df["conversion_index"] = df["share_of_buyers"] / df["share_of_answers"]
    return df.sort_values("conversion_index", ascending=False).reset_index(drop=True)


def pain_insights(pains: pd.DataFrame) -> list[str]:
    """Plain-language findings for the creative team."""
    if pains.empty:
        return []
    out = []
    best, worst = pains.iloc[0], pains.iloc[-1]
    out.append(
        f"'{best.label}' is {best.share_of_answers:.0%} of quiz answers but {best.share_of_buyers:.0%} of buyers "
        f"(index {best.conversion_index:.2f}). Lead with this pain in new hooks and originals."
    )
    if worst.conversion_index < 0.8:
        out.append(
            f"'{worst.label}' is {worst.share_of_answers:.0%} of answers but only {worst.share_of_buyers:.0%} of buyers "
            f"(index {worst.conversion_index:.2f}). Ads that attract this pain buy clicks that do not convert; "
            f"the product promise does not answer it."
        )
    leak = pains.sort_values("email_pass_rate").iloc[0]
    avg_pass = (pains["email_pass_rate"] * pains["answered"]).sum() / pains["answered"].sum()
    if leak.email_pass_rate < avg_pass - 0.03:
        out.append(
            f"'{leak.label}' drops hardest at the email step: {leak.email_pass_rate:.0%} pass vs {avg_pass:.0%} on average. "
            f"Test a value promise before asking for the email for this group."
        )
    return out


def leads(sessions: pd.DataFrame) -> pd.DataFrame:
    """Contactable non-buyers: gave an email, did not pay."""
    l = sessions[sessions["email"].notna() & ~sessions["purchased"]].copy()
    l["drop_stage"] = l["max_stage"].map(lambda s: "offer" if s >= 6 else "step_5")
    return l


def segments(lead_df: pd.DataFrame) -> pd.DataFrame:
    """Recovery segments = pain x where the lead stopped."""
    if lead_df.empty:
        return pd.DataFrame(columns=["segment_id", "pain", "drop_stage", "leads", "share", "top_who_for", "top_size"])
    g = lead_df.groupby(["pain", "drop_stage"])
    seg = g.size().rename("leads").reset_index()
    seg["top_who_for"] = g["who_for"].agg(lambda x: x.mode().iat[0] if not x.mode().empty else None).values
    seg["top_size"] = g["size"].agg(lambda x: x.mode().iat[0] if not x.mode().empty else None).values
    seg["share"] = seg["leads"] / seg["leads"].sum()
    seg["segment_id"] = seg["pain"] + "__" + seg["drop_stage"]
    seg["label"] = seg["pain"].map(pain_label) + " / " + seg["drop_stage"].map(
        {"offer": "saw offer, did not pay", "step_5": "left after email step"})
    return seg.sort_values("leads", ascending=False).reset_index(drop=True)


def opportunity(lead_share_of_clicks: float, monthly_spend: float, cpc: float, conversion: float,
                ltv: float, platform_cost: float = 0.0) -> dict:
    """Monthly EGP from recovering leads. EGP = orders x LTV - platform cost (no extra ad spend)."""
    clicks = monthly_spend / cpc
    monthly_leads = clicks * lead_share_of_clicks
    orders = monthly_leads * conversion
    egp = orders * ltv - platform_cost
    return {
        "clicks": clicks, "leads": monthly_leads, "orders": orders, "egp": egp,
        "romi_lift_pp": (orders * ltv) / monthly_spend * 100 if monthly_spend else 0.0,
    }
