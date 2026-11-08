"""SockLock Quiz Lead Recovery: Streamlit app.

Run: streamlit run app.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from socklock_recovery import analytics as a
from socklock_recovery import creative as cr
from socklock_recovery import email_qa as qa
from socklock_recovery import emails as em
from socklock_recovery import experiment as ex
from socklock_recovery.generate_data import generate_events
from socklock_recovery.quiz_schema import STAGES, stage_label

load_dotenv()
SAMPLE = Path(__file__).parent / "data" / "quiz_events.csv.gz"
SAMPLE_TEST = Path(__file__).parent / "data" / "experiment_results.csv.gz"
ACCENT, GREY = "#2f6fdb", "#b8bcc4"

st.set_page_config(page_title="SockLock Quiz Recovery", page_icon="🧦", layout="wide")


@st.cache_data(show_spinner="Reading quiz events...")
def sessions_from_csv(data: bytes | str) -> pd.DataFrame:
    src = data if isinstance(data, str) else pd.io.common.BytesIO(data)
    return a.build_sessions(pd.read_csv(src, compression="infer" if isinstance(data, str) else None))


@st.cache_data(show_spinner="Generating synthetic quiz events...")
def sessions_generated(n: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    ev = generate_events(n, seed)
    return ev, a.build_sessions(ev)


def money(x: float) -> str:
    return f"${x / 1000:,.1f}k" if abs(x) >= 1000 else f"${x:,.0f}"


# ---------- sidebar: data source + API key ----------
with st.sidebar:
    st.title("🧦 Quiz Lead Recovery")
    st.caption("Finds where paid quiz traffic leaks, sizes the money in the leads we already paid for, "
               "and writes recovery emails per segment.")
    source = st.radio("Quiz events", ["Sample export (20k clicks)", "Upload CSV", "Generate new sample"])
    raw_events = None
    if source == "Upload CSV":
        up = st.file_uploader("Quiz event export (.csv or .csv.gz)", type=["csv", "gz"])
        if up is None:
            st.info("Upload a file, or switch to the sample.")
            st.stop()
        data = up.getvalue()
        if up.name.endswith(".gz"):
            import gzip
            data = gzip.decompress(data)
        try:
            sessions = sessions_from_csv(data)
        except ValueError as e:
            st.error(str(e))
            st.stop()
    elif source == "Generate new sample":
        n = st.slider("Ad clicks", 5_000, 100_000, 30_000, 5_000)
        seed = st.number_input("Random seed", value=1, step=1)
        raw_events, sessions = sessions_generated(n, int(seed))
    else:
        sessions = sessions_from_csv(str(SAMPLE))

    st.divider()
    api_key = st.text_input("Gemini API key", value=os.getenv("GEMINI_API_KEY", ""), type="password",
                            help="Without a key the Emails tab shows pre-generated demo sequences.")
    model = st.text_input("Gemini model", value=os.getenv("GEMINI_MODEL", em.DEFAULT_MODEL))

fun = a.funnel(sessions)
lead_df = a.leads(sessions)
segs = a.segments(lead_df)
n_clicks = len(sessions)
lead_share = len(lead_df) / n_clicks if n_clicks else 0.0

st.title("SockLock: recovering paid quiz leads")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Ad clicks in export", f"{n_clicks:,}")
c2.metric("Paid", f"{int(sessions['purchased'].sum()):,}", f"{sessions['purchased'].mean():.1%} of clicks",
          delta_color="off")
c3.metric("Gave email, did not pay", f"{len(lead_df):,}", f"{lead_share:.0%} of clicks", delta_color="off")
c4.metric("Leads per buyer", f"{len(lead_df) / max(int(sessions['purchased'].sum()), 1):.0f}×")

tab_f, tab_p, tab_o, tab_e, tab_x, tab_d = st.tabs(
    ["1 · Funnel", "2 · Pains", "3 · Opportunity", "4 · Emails", "5 · Experiment", "Data"])

# ---------- funnel ----------
with tab_f:
    left, right = st.columns([3, 2])
    with left:
        fig = go.Figure(go.Funnel(
            y=fun["label"], x=fun["sessions"], texttemplate="%{value:,} · %{percentInitial:.0%}",
            marker={"color": [ACCENT if s in (5, 7) else GREY for s in fun["stage"]]}))
        fig.update_layout(height=430, margin=dict(l=10, r=10, t=30, b=10),
                          title="Where paid clicks go (share of all clicks)")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Biggest leaks")
        for r in a.biggest_leaks(fun).itertuples():
            prev = stage_label(r.stage - 1) if r.stage != 7 else "Personal offer"
            st.markdown(f"**{prev} → {r.label}**: {r.lost:,} sessions lost "
                        f"({1 - r.step_conversion:.0%} of those who got there)")
        st.caption("Everyone who reached step 5 already left an email. "
                   "Those who did not pay are the leads in tabs 3 and 4.")

    st.subheader("Who drops, and where")
    labels = {s: stage_label(s) for s, _ in STAGES} | {7: "Paid"}
    cc = st.columns([2, 2, 2, 3])
    from_stage = cc[0].selectbox("From", list(labels)[:-1], index=4, format_func=labels.get)
    to_stage = cc[1].selectbox("To", [s for s in labels if s > from_stage], index=0, format_func=labels.get)
    dims = [d for d in a.DIMENSIONS if d not in a.STEP_OF or a.STEP_OF[d] < from_stage]
    dim = cc[2].selectbox("Split by", dims, index=0)
    t = a.transition_breakdown(sessions, dim, from_stage, to_stage)
    avg = t.attrs["avg_rate"]
    cc[3].metric(f"Average pass rate {labels[from_stage]} → {labels[to_stage]}", f"{avg:.1%}")
    bar = px.bar(t, x="rate", y="label", orientation="h", text=t["rate"].map("{:.1%}".format),
                 color=t["flag"].map({True: "significant gap", False: "normal"}),
                 color_discrete_map={"significant gap": ACCENT, "normal": GREY},
                 hover_data={"sessions": True, "lost": True, "z": ":.1f"})
    bar.add_vline(x=avg, line_dash="dash", annotation_text="average")
    bar.update_layout(height=60 + 40 * len(t), xaxis_tickformat=".0%", legend_title="", yaxis_title="",
                      xaxis_title="pass rate", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(bar, use_container_width=True)

    an = a.anomalies(sessions, from_stage, to_stage, dims)
    if an.empty:
        st.success("No group differs significantly from the average on this step.")
    else:
        st.markdown("**Groups that differ significantly (|z| ≥ 2), all dimensions:**")
        st.dataframe(an.assign(rate=an["rate"].map("{:.1%}".format), vs_avg_pp=an["vs_avg_pp"].round(1),
                               z=an["z"].round(1)), hide_index=True, use_container_width=True)

# ---------- pains ----------
with tab_p:
    pains = a.pain_analysis(sessions)
    st.subheader("Which pains bring clicks, and which bring buyers")
    long = pains.melt(id_vars="label", value_vars=["share_of_answers", "share_of_buyers"],
                      var_name="metric", value_name="share")
    long["metric"] = long["metric"].map({"share_of_answers": "Share of quiz answers",
                                         "share_of_buyers": "Share of buyers"})
    pf = px.bar(long, x="share", y="label", color="metric", barmode="group", orientation="h",
                text=long["share"].map("{:.0%}".format),
                color_discrete_map={"Share of quiz answers": GREY, "Share of buyers": ACCENT})
    pf.update_layout(height=380, xaxis_tickformat=".0%", yaxis_title="", xaxis_title="", legend_title="",
                     margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(pf, use_container_width=True)
    st.markdown("**Findings for the creative team**")
    for line in a.pain_insights(pains):
        st.markdown(f"- {line}")
    st.dataframe(pains.drop(columns="pain").style.format({
        "share_of_answers": "{:.1%}", "email_pass_rate": "{:.1%}", "offer_to_paid": "{:.2%}",
        "share_of_buyers": "{:.1%}", "conversion_index": "{:.2f}"}), hide_index=True, use_container_width=True)
    st.caption("Conversion index = share of buyers ÷ share of answers. Above 1 = the pain converts better than average.")

    st.subheader("Creative briefs from pains")
    st.caption("Second lever for ROMI: recovery raises revenue per click, ads built on pains that convert "
               "lower CPA. Gemini turns the table above into hooks and 15-second scripts for motion designers.")
    if "creative" not in st.session_state:
        st.session_state.creative = None
    if st.button("Write briefs with Gemini", type="primary", disabled=not api_key, key="gen_creative"):
        with st.spinner("Gemini is writing briefs..."):
            try:
                st.session_state.creative = cr.generate_pack(pains, em.get_client(api_key), model)
            except Exception as e:
                st.error(f"Gemini call failed: {e}")
    pack = st.session_state.creative or cr.load_demo()
    if pack:
        labels = dict(zip(pains["pain"], pains["label"]))
        st.markdown(f"<small>{'generated now' if st.session_state.creative else 'pre-generated demo'}</small>",
                    unsafe_allow_html=True)
        st.info(pack["summary"])
        badge = {"lead": "🟢 LEAD", "test": "🟡 TEST", "avoid": "🔴 AVOID"}
        for b in pack["briefs"]:
            with st.expander(f"{badge[b['verdict']]} · {labels.get(b['pain'], b['pain'])}",
                             expanded=b["verdict"] == "lead"):
                st.markdown(b["why"])
                if b["hooks"]:
                    st.markdown("**Hooks (first 2 seconds)**\n" + "\n".join(f"- {h}" for h in b["hooks"]))
                if b["script"]:
                    st.markdown("**15-second script**")
                    st.dataframe(pd.DataFrame(b["script"]), hide_index=True, use_container_width=True)
                if b["on_screen_text"]:
                    st.caption(f"End card: {b['on_screen_text']}")
        st.download_button("Briefs (Markdown)", cr.to_markdown(pack, labels), "creative_briefs.md", "text/markdown")
        with st.expander("Prompt sent to Gemini"):
            st.code(cr.build_prompt(pains), language="text")

# ---------- opportunity ----------
with tab_o:
    st.subheader("What the leads are worth per month")
    st.caption(f"Lead rate from this export: {lead_share:.1%} of clicks gave an email and did not pay.")
    i1, i2, i3, i4 = st.columns(4)
    spend = i1.number_input("Monthly ad spend, $", 100_000, 2_000_000, 400_000, 50_000)
    cpc = i2.number_input("CPC, $", 0.2, 5.0, 1.0, 0.05)
    ltv = i3.number_input("LTV of a recovered buyer, $", 10, 200, 60, 1,
                          help="$68 data-room LTV minus an allowance for a first-box discount")
    case = i4.radio("Today", ["A: no recovery emails", "B: generic flow exists"])
    if case.startswith("A"):
        levels, cost = {"Pessimistic": 0.003, "Base": 0.01, "Optimistic": 0.02}, 3_000
        conv_help = "Incremental orders per lead, vs a holdout"
    else:
        levels, cost = {"Pessimistic": 0.0015, "Base": 0.003, "Optimistic": 0.005}, 0
        conv_help = "Extra orders per lead on top of the generic flow"
    conv = st.slider(f"{conv_help}, %", 0.0, 3.0, levels["Base"] * 100, 0.05, format="%.2f%%") / 100
    o = a.opportunity(lead_share, spend, cpc, conv, ltv, cost)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Leads / month", f"{o['leads']:,.0f}")
    m2.metric("Recovered orders / month", f"{o['orders']:,.0f}")
    m3.metric("EGP / month", money(o["egp"]))
    m4.metric("ROMI lift", f"+{o['romi_lift_pp']:.1f} pp")

    rows = []
    for name, c in levels.items():
        for sp in (400_000, 800_000):
            r = a.opportunity(lead_share, sp, cpc, c, ltv, cost)
            rows.append({"Scenario": name, "Conversion": f"{c:.2%}", "Spend": money(sp),
                         "Orders / month": round(r["orders"]), "EGP / month": money(r["egp"]),
                         "ROMI lift": f"+{r['romi_lift_pp']:.1f} pp"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption("EGP = recovered orders × LTV − email platform cost; no extra ad spend. "
               "Model of the full $400k → $800k ramp with CPA degradation: model/egp_model.py.")

    st.subheader("Segments to recover")
    sv = segs.copy()
    sv["monthly_leads"] = sv["share"] * o["leads"]
    sv["egp_month"] = sv["monthly_leads"] * conv * ltv
    st.dataframe(sv[["label", "leads", "share", "monthly_leads", "egp_month", "top_who_for", "top_size"]].style.format(
        {"share": "{:.1%}", "monthly_leads": "{:,.0f}", "egp_month": "${:,.0f}"}),
        hide_index=True, use_container_width=True)

# ---------- emails ----------
with tab_e:
    st.subheader("Recovery sequences per segment")
    demo = em.load_demo()
    if "generated" not in st.session_state:
        st.session_state.generated = {}
    gen = st.session_state.generated

    seg_ids = segs["segment_id"].tolist()
    seg_by_id = {r["segment_id"]: r for r in segs.to_dict("records")}
    col_a, col_b = st.columns([3, 2])
    pick = col_a.selectbox("Segment", seg_ids, format_func=lambda s: f"{seg_by_id[s]['label']}  ·  {seg_by_id[s]['leads']:,} leads")
    discount = col_b.toggle("Allow 20% off in email 3", value=False)
    b1, b2, _ = st.columns([2, 2, 1])
    if b1.button("Generate with Gemini", type="primary", disabled=not api_key):
        with st.spinner("Gemini is writing 3 emails..."):
            try:
                gen[pick] = em.generate_sequence(seg_by_id[pick], em.get_client(api_key), model, discount)
            except Exception as e:  # show API errors in the UI
                st.error(f"Gemini call failed: {e}")
    if b2.button("Generate all segments", disabled=not api_key):
        bar = st.progress(0.0)
        client = em.get_client(api_key)
        for i, sid in enumerate(seg_ids, 1):
            try:
                gen[sid] = em.generate_sequence(seg_by_id[sid], client, model, discount)
            except Exception as e:
                st.error(f"{sid}: {e}")
            bar.progress(i / len(seg_ids))
    if not api_key:
        st.info("No Gemini key: showing pre-generated demo sequences. Add a key in the sidebar to write new ones.")

    seq = gen.get(pick) or demo.get(pick)
    if seq is None:
        st.warning("No sequence for this segment yet. Press Generate.")
    else:
        source_tag = "generated now" if pick in gen else "pre-generated demo"
        rep = qa.check_sequence(seq, discount)
        repairs = seq.get("repairs", 0)
        q1, q2 = st.columns([4, 1])
        q1.markdown(f"**Angle:** {seq['angle']}  \n<small>{source_tag}"
                    f"{f' · auto-repaired {repairs}×' if repairs else ''}</small>", unsafe_allow_html=True)
        q2.metric("QA score", f"{rep['score']}/100", f"{rep['errors']} errors · {rep['warnings']} warnings",
                  delta_color="off" if rep["errors"] == 0 else "inverse",
                  help="Rule checks: subject/preheader/body limits, merge fields, claims the brief does not "
                       "support, discounts, spam triggers. Errors trigger one automatic rewrite on generation.")
        for i in rep["sequence"]:
            st.error(f"{i['field']}: {i['msg']}")
        cols = st.columns(len(seq["emails"]))
        for col, e, issues in zip(cols, seq["emails"], rep["per_email"]):
            with col:
                st.markdown(f"**+{e['send_after_hours']}h** · A: {e['subject']}")
                for letter, alt in zip("BC", e.get("alt_subjects") or []):
                    st.markdown(f"<small>{letter}: {alt}</small>", unsafe_allow_html=True)
                st.caption(e["preheader"])
                if issues:
                    for i in issues:
                        (st.error if i["level"] == "error" else st.warning)(f"{i['field']}: {i['msg']}", icon=None)
                else:
                    st.success("All checks passed")
                components.html(em.render_html(e, {"size": str(seg_by_id[pick].get("top_size") or "M"),
                                                   "who_for": "you"}), height=520, scrolling=True)
        with st.expander("Prompt sent to Gemini"):
            st.code(em.build_prompt(seg_by_id[pick], discount), language="text")

    st.subheader("Export for the email platform")
    all_seqs = [gen.get(s) or demo.get(s) for s in seg_ids]
    all_seqs = [s for s in all_seqs if s]
    d1, d2, d3 = st.columns(3)
    d1.download_button("Lead profiles (CSV)", em.profiles_export(lead_df).to_csv(index=False),
                       "recovery_profiles.csv", "text/csv",
                       help="Email + segment properties, one row per lead, for a profile import")
    d2.download_button("Email sequences (CSV)", em.sequences_to_csv(all_seqs).to_csv(index=False),
                       "recovery_sequences.csv", "text/csv", disabled=not all_seqs)
    d3.download_button("Sequences (JSON)", json.dumps(all_seqs, indent=2, ensure_ascii=False),
                       "recovery_sequences.json", "application/json", disabled=not all_seqs)
    st.caption(f"{len(all_seqs)} of {len(seg_ids)} segments have a sequence. "
               "Flows branch on the segment_id profile property. Subjects A/B/C go into the platform's "
               "subject-line A/B test; it sends the winner after the test window.")

# ---------- experiment ----------
with tab_x:
    st.subheader("Did the emails make money? Holdout test readout")
    st.caption("Leads are split 50/50: treatment gets the sequences, holdout gets nothing. "
               "Incremental orders per lead = treatment rate − holdout rate. Only this number goes into EGP.")
    xs = st.radio("Test results", ["Sample 3-week test (synthetic)", "Upload CSV", "Simulate"], horizontal=True)
    if xs == "Upload CSV":
        upx = st.file_uploader("Results: email, segment_id, group, ordered (+ opened, clicked, unsubscribed, spam)",
                               type=["csv", "gz"], key="upx")
        results = pd.read_csv(upx, compression="gzip" if upx and upx.name.endswith(".gz") else None) if upx else None
    elif xs == "Simulate":
        s1, s2 = st.columns(2)
        n_test = s1.slider("Leads in test", 10_000, 200_000, 100_000, 10_000,
                           help="100k ≈ 3 weeks of leads at $400k/month")
        scale = s2.slider("True effect (1.0 = planted lifts, 0 = emails do nothing)", 0.0, 1.5, 0.7, 0.1)
        results = ex.simulate_results(segs, n_test, scale, seed=3)
    else:
        results = pd.read_csv(SAMPLE_TEST)
    if results is None:
        st.info("Upload a results file, or use the sample.")
    else:
        try:
            ro = ex.readout(results)
        except ValueError as e:
            st.error(str(e))
            st.stop()
        tot = ro[ro["segment_id"] == "TOTAL"].iloc[0]
        ltv_x = st.number_input("LTV of a recovered buyer, $", 10, 200, 60, 1, key="ltv_x")
        val = ex.value_of_lift(tot["lift"], ltv_x).set_index("spend")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Incremental orders per lead", f"{tot['lift']:.2%}",
                  f"95% CI {tot['ci_low']:.2%} … {tot['ci_high']:.2%}", delta_color="off")
        k2.metric("p-value", "< 0.001" if tot["p_value"] < 0.001 else f"{tot['p_value']:.3f}")
        k3.metric("EGP / month at $800k", money(val.loc[800_000, "egp"]))
        k4.metric("ROMI at $800k", f"{val.loc[800_000, 'romi_with_recovery']:.1%}",
                  f"{(val.loc[800_000, 'romi_with_recovery'] - val.loc[800_000, 'romi_ads_only']) * 100:+.1f} pp vs ads only")
        goal = val.loc[800_000, "meets_125"]
        (st.success if goal else st.error)(
            f"Goal {'met' if goal else 'not met'}: ROMI at $800k spend is {val.loc[800_000, 'romi_with_recovery']:.1%} "
            f"with recovery vs {val.loc[800_000, 'romi_ads_only']:.1%} from ads alone (target ≥ 125%).")
        st.markdown(f"**Decision:** {ex.overall_decision(ro)}")

        body = ro[ro["segment_id"] != "TOTAL"]
        color = {"Roll out": "#2e9e5b", "Keep testing": "#d9a521", "Stop": "#d0453a"}
        fig = go.Figure()
        for v, g in body.groupby("verdict"):
            fig.add_trace(go.Scatter(
                x=g["lift"], y=g["label"], mode="markers", name=v, marker=dict(size=11, color=color[v]),
                error_x=dict(type="data", symmetric=False, array=g["ci_high"] - g["lift"],
                             arrayminus=g["lift"] - g["ci_low"], color=color[v])))
        fig.add_vline(x=0, line_color=GREY)
        fig.add_vline(x=ex.STOP_BELOW, line_dash="dash", annotation_text="0.15% stop line")
        fig.update_layout(height=60 + 40 * len(body), xaxis_tickformat=".1%", xaxis_title="incremental orders per lead",
                          yaxis=dict(categoryorder="array", categoryarray=body["label"][::-1].tolist()),
                          margin=dict(l=10, r=10, t=10, b=10), legend_title="")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Bars = 95% interval, Bonferroni-corrected across segments so a lucky segment is not rolled out "
                   "by chance. Roll out: interval above 0 and lift ≥ 0.15%. Stop: whole interval below 0.15%.")
        show = ro[["label", "treatment_leads", "holdout_leads", "treatment_rate", "holdout_rate", "lift",
                   "ci_low", "ci_high", "p_value", "verdict", "leads_needed"]]
        st.dataframe(show.style.format({"treatment_rate": "{:.2%}", "holdout_rate": "{:.2%}", "lift": "{:+.2%}",
                                        "ci_low": "{:+.2%}", "ci_high": "{:+.2%}", "p_value": "{:.3g}",
                                        "treatment_leads": "{:,}", "holdout_leads": "{:,}", "leads_needed": "{:,}"}),
                     hide_index=True, use_container_width=True)
        st.caption("leads_needed = leads per group to detect the observed lift (or 0.3%, whichever is larger) "
                   "with 80% power.")

        fh = ex.flow_health(results)
        if not fh.empty:
            st.markdown("**Flow health (treatment)**")
            hc = st.columns(len(fh))
            for c, r in zip(hc, fh.itertuples()):
                c.metric(r.metric, f"{r.rate:.2%}", f"target {r.target}", delta_color="normal" if r.ok else "inverse")
        st.download_button("Readout (CSV)", ro.to_csv(index=False), "experiment_readout.csv", "text/csv")

# ---------- data ----------
with tab_d:
    st.markdown("Expected format: one row per quiz event, columns "
                "`session_id, ts, event, step, answer, email, device, country, creative_id`. "
                "Events: `ad_click`, `step_view` (1-5), `step_answer`, `email_submitted`, `offer_view`, `purchase`.")
    st.markdown("The bundled sample is **synthetic**, calibrated to the data-room funnel "
                "(88% → 61% → 58% → 36% → 31% → 2%).")
    st.dataframe(sessions.head(200), use_container_width=True)
    if raw_events is not None:
        st.download_button("Download generated events (CSV)", raw_events.to_csv(index=False),
                           "quiz_events.csv", "text/csv")
