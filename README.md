# SockLock: Quiz Lead Recovery

34% of SockLock's paid ad clicks leave an email and a sock size in the quiz and never pay:
about 136,000 leads a month that nobody contacts again. This tool takes a quiz event export
(CSV) and:

1. **Funnel** — shows where paid traffic leaks and which groups (device, country, creative,
   quiz answers) drop significantly more on any step.
2. **Pains** — compares each quiz pain's share of answers with its share of buyers: which pains
   convert, which leak at the email step, which ads attract people the product cannot help.
   Gemini turns this into **creative briefs**: lead / test / avoid per pain, 3 hooks and a
   15-second script for motion designers (second ROMI lever: lower CPA).
3. **Opportunity** — sizes the monthly EGP from recovering the leads (scenarios A: no flow today,
   B: a generic flow exists) and ranks recovery segments (pain × where the lead stopped).
4. **Emails** — Gemini writes a 3-email recovery sequence per segment (1 h, 24 h, 72 h) with
   3 subject lines per email for an A/B/C test. Every email is **rule-checked** (limits, merge
   fields, invented claims, discounts, spam triggers); errors trigger one automatic rewrite.
   HTML previews; exports lead profiles and sequences as CSV/JSON for an email platform (e.g. Klaviyo).
5. **Experiment** — reads the holdout test results and answers "did it make money": incremental
   orders per lead with a 95% interval per segment (Bonferroni-corrected), roll out / keep testing /
   stop per segment, flow health, and what the measured lift does to ROMI at $800k spend.

No access to SockLock's Meta, Airtable or backend is needed: input is a CSV, output is files.
The bundled exports (`data/quiz_events.csv.gz`, `data/experiment_results.csv.gz`) are **synthetic**, calibrated to the data-room funnel
(88% → 61% → 58% → 36% → 31% → 2% of clicks).

## Run

```bash
cd socklock-quiz-recovery
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # paste your GEMINI_API_KEY (optional)
streamlit run app.py        # opens http://localhost:8501
```

Without a key the Emails tab shows pre-generated sequences from `demo/sample_sequences.json`;
the key can also be pasted in the sidebar.

Other commands:

```bash
python -m socklock_recovery.generate_data --sessions 50000 --out data/my_events.csv.gz  # new synthetic export
python -m socklock_recovery.emails --csv data/quiz_events.csv.gz                       # regenerate demo emails
python -m socklock_recovery.creative --csv data/quiz_events.csv.gz                     # regenerate demo creative briefs
python -m socklock_recovery.experiment --leads 100000 --lift-scale 0.7                 # new synthetic test results
python model/egp_model.py                                                              # $400k -> $800k spend-ramp model
pytest -q                                                                              # tests
```

## Input format

One row per quiz event:

| column | example |
| --- | --- |
| `session_id` | `s0000042` (one ad click) |
| `ts` | `2026-10-03T14:22:05` |
| `event` | `ad_click`, `step_view`, `step_answer`, `email_submitted`, `offer_view`, `purchase` |
| `step` | 1–5 for quiz steps, 6 offer, 7 purchase |
| `answer` | answer key for `step_answer` (e.g. `lost_in_laundry`) |
| `email` | set on `email_submitted` |
| `device`, `country`, `creative_id` | `mobile`, `US`, `cr_03` |

Test results (Experiment tab), one row per lead in the test:

| column | example |
| --- | --- |
| `email` | `lead000042@example.com` |
| `segment_id` | `lost_in_laundry__offer` (from the profile export) |
| `group` | `treatment` or `holdout` |
| `ordered` | `1` if the lead bought during the test window |
| `opened`, `clicked`, `unsubscribed`, `spam` | optional, `0/1`, treatment only |

Quiz steps: 1 who the socks are for · 2 main sock frustration (pain) · 3 style ·
4 size + email · 5 household size · then the personal offer.

## How it works

| File | What it does |
| --- | --- |
| `socklock_recovery/quiz_schema.py` | Quiz steps, answer options, stage names |
| `socklock_recovery/generate_data.py` | Synthetic sessions → raw events. Planted patterns: mobile drops more at the email step, "sorting takes forever" drops more at the email step, "socks wear out" rarely buys |
| `socklock_recovery/analytics.py` | Events → one row per session; funnel; pass rate per group with a two-proportion z-score (\|z\| ≥ 2 flagged); pain index; leads; segments; EGP opportunity |
| `socklock_recovery/emails.py` | Prompt per segment → Gemini with a JSON schema (structured output) → QA → one repair call if needed; HTML preview; CSV exports |
| `socklock_recovery/email_qa.py` | Rule checks per email; score 0-100 (−15 per error, −5 per warning) |
| `socklock_recovery/creative.py` | Pain table → one Gemini call → lead / test / avoid briefs with hooks and 15-second scripts |
| `socklock_recovery/experiment.py` | Holdout readout: lift, interval, p-value, verdicts, sample size, flow health, ROMI at $800k; synthetic test generator |
| `app.py` | Streamlit UI over the modules above |
| `model/egp_model.py` | Spend ramp $400k → $800k with CPA degradation, scenarios A/B, ROMI ceiling |

Copy is generated **per segment, not per person** (10 segments = 10 calls, cents per refresh).
Size and "who for" go in as merge fields (`{{ size }}`) at send time.

## How we measure success

Launch on the top 3 segments with a **50/50 holdout** (leads in the holdout get no emails).

| Metric | Now | Target | When |
| --- | --- | --- | --- |
| Incremental orders per lead (treatment − holdout) | 0% | ≥ 0.3% go / no-go, 1% base case | 3 weeks / month 3 |
| Recovered orders per month | 0 | ~1,360 at $400k spend | month 3 |
| EGP from recovered orders | $0 | +$79k / month at $400k, +$143k at $800k | month 3 / month 6 |
| Blended CPA (spend ÷ all orders) | $50 | ≤ $45 | month 3 |
| Blended ROMI at $800k spend | 120.5% projected | ≥ 125% | month 6 |
| Flow health: open / click / unsubscribe / spam | — | ≥ 40% / ≥ 3% / < 0.5% / < 0.08% | weekly |
| Growth PM time per drop-off analysis | ~half a day | ~10 minutes | week 1 |

Stop rule: if after 3 weeks the incremental rate is below 0.15% on every segment, stop and
reuse the analysis for the quiz instead (fix the email step first).

## Next iteration

1. **Live connection**: push profiles and events to the email platform by API and trigger flows
   in real time from a quiz webhook, instead of CSV uploads.
2. **Learn from the test**: feed the winning subject lines and segment lifts back into the prompt,
   so the next generation starts from what worked.
3. **Second channel**: export hashed lead emails per segment as Meta Custom Audiences for
   retargeting; SMS for leads who opt in.
4. **Creative briefs → measured**: tag new ads with the brief's pain and read CPA per pain in the
   Experiment tab the same way.
5. **DE / FR**: the same pipeline writes localised sequences for the European tests.
6. **Prioritise by value**: score leads by predicted LTV (household size, who for) and send the
   richer sequence to the top tier.
