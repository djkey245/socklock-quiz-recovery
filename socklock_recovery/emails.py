"""Recovery email sequences per segment, written by Gemini, exported for an email platform.

One sequence (3 emails) per segment, not per person: ~10-30 model calls per refresh.
Personal details (size, who the socks are for) go in as merge fields at send time.

CLI: python -m socklock_recovery.emails --csv data/quiz_events.csv.gz --out demo/sample_sequences.json
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from .email_qa import check_sequence, repair_note
from .quiz_schema import STEPS, pain_label

DEMO_PATH = Path(__file__).resolve().parent.parent / "demo" / "sample_sequences.json"
DEFAULT_MODEL = "gemini-3.8-flash"

BRAND_BRIEF = """\
Brand: SockLock (US market, plain friendly American English).
Product: magnetic socks. A small magnet in the cuffs keeps each pair together in the washer and dryer,
so pairs never get separated or lost in the laundry.
Offer: subscription, 5 pairs for $29, then a new delivery every quarter. Cancel anytime.
Where the reader came from: a Meta ad, then a 6-step quiz. They gave their email and sock size at step 4.
"""

RULES = """\
Rules:
- 3 emails: 1 hour, 24 hours and 72 hours after the drop-off.
- Speak to the reader's pain in their own words; email 1 reminds, email 2 answers the main objection,
  email 3 is a last, honest nudge.
- Subject <= 50 characters, preheader <= 90 characters, body 60-120 words, one clear call to action.
- You may use one merge field, written exactly as {{ size }} (their sock size). No other merge fields.
- No invented facts: no reviews, ratings, customer counts, guarantees or discounts unless given above.
- Only the product features and terms listed above exist. "Cancel anytime" is the only flexibility
  (no pausing, skipping or free trial). Do not claim comfort, fit, materials or durability.
- Do not claim we saved or reserved anything for them.
- No absolute promises ("never lose a sock again", "no more searching", "together forever", "always"):
  the magnet works in the washer and dryer only, and only if the pair is snapped together.
- If the pain is something the magnet does not solve (for example socks wearing out), do not pretend it does;
  be honest about what SockLock fixes.
- No emoji in subjects.
- Each email also gets 2 alternative subject lines for an A/B/C test (same limits): one curiosity,
  one plain benefit, both different from the main subject.
"""

DROP_CONTEXT = {
    "step_5": "They left right after giving their email, before seeing their personal offer.",
    "offer": "They finished the quiz and saw their personal offer (5 pairs for $29) but did not pay.",
}


class Email(BaseModel):
    send_after_hours: int = Field(description="1, 24 or 72")
    subject: str
    alt_subjects: list[str] = Field(description="2 alternative subject lines for an A/B/C test")
    preheader: str
    body: str = Field(description="Plain text, paragraphs separated by blank lines")
    cta_text: str


class Sequence(BaseModel):
    angle: str = Field(description="One sentence: the persuasion angle of this sequence")
    emails: list[Email]


def build_prompt(segment: dict, include_discount: bool = False) -> str:
    who = STEPS[1]["options"].get(segment.get("top_who_for") or "", "themselves")
    offer_line = "You may offer 20% off the first box in email 3 only." if include_discount else "Do not offer any discount."
    return (
        f"{BRAND_BRIEF}\n"
        f"Segment: {segment['leads']:,} leads.\n"
        f"Their biggest sock frustration (quiz answer): \"{pain_label(segment['pain'])}\".\n"
        f"Where they stopped: {DROP_CONTEXT[segment['drop_stage']]}\n"
        f"Most of them buy for: {who}. Most common size: {segment.get('top_size') or 'unknown'}.\n\n"
        f"{RULES}- {offer_line}\n\n"
        "Write the 3-email recovery sequence."
    )


def get_client(api_key: str | None = None):
    from google import genai
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=key)


def _call(client, model: str, prompt: str) -> dict:
    from google.genai import types
    resp = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=Sequence, temperature=0.8),
    )
    seq = resp.parsed if resp.parsed is not None else Sequence.model_validate_json(resp.text)
    return seq.model_dump()


def generate_sequence(segment: dict, client=None, model: str | None = None,
                      include_discount: bool = False, max_repairs: int = 1) -> dict:
    """Generate, check with email_qa, and send the errors back for up to `max_repairs` rewrites."""
    client = client or get_client()
    model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    prompt = build_prompt(segment, include_discount)
    seq = _call(client, model, prompt)
    repairs = 0
    report = check_sequence(seq, include_discount)
    while report["errors"] and repairs < max_repairs:
        repairs += 1
        fix = (f"{prompt}\n\nYour previous draft:\n{json.dumps(seq, ensure_ascii=False)}\n\n"
               f"It broke these rules:\n{repair_note(report)}\nRewrite the sequence and fix every one of them.")
        seq = _call(client, model, fix)
        report = check_sequence(seq, include_discount)
    return {"segment_id": segment["segment_id"], "pain": segment["pain"], "drop_stage": segment["drop_stage"],
            "leads": int(segment["leads"]), **seq, "repairs": repairs, "qa_score": report["score"]}


def load_demo() -> dict:
    if not DEMO_PATH.exists():
        return {}
    return {s["segment_id"]: s for s in json.loads(DEMO_PATH.read_text())}


def render_html(email: dict, sample: dict | None = None) -> str:
    """Simple branded preview; merge fields filled with sample values."""
    sample = sample or {"size": "M", "who_for": "you"}
    text = email["body"]
    for k, v in sample.items():
        text = text.replace("{{ " + k + " }}", v).replace("{{" + k + "}}", v)
    paras = "".join(f"<p style='margin:0 0 14px'>{html.escape(p).replace(chr(10), '<br>')}</p>"
                    for p in text.split("\n\n") if p.strip())
    return f"""<div style="font-family:Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;border:1px solid #e5e5e5;border-radius:10px;overflow:hidden;background:#fff;color:#1f2328">
<div style="background:#1f3a5f;color:#fff;padding:14px 22px;font-weight:700;letter-spacing:.5px">SockLock</div>
<div style="padding:22px;font-size:15px;line-height:1.55">{paras}
<a style="display:inline-block;background:#e8613c;color:#fff;text-decoration:none;padding:12px 22px;border-radius:6px;font-weight:600">{html.escape(email['cta_text'])}</a></div>
<div style="padding:10px 22px 18px;font-size:11px;color:#8a8f98">You got this because you took the SockLock quiz. Unsubscribe anytime.</div></div>"""


def sequences_to_csv(sequences: list[dict]) -> pd.DataFrame:
    rows = []
    for s in sequences:
        for i, e in enumerate(s["emails"], 1):
            rows.append({"segment_id": s["segment_id"], "email_no": i, "send_after_hours": e["send_after_hours"],
                         "subject": e["subject"],
                         **{f"subject_{c}": v for c, v in zip("bc", e.get("alt_subjects") or [])},
                         "preheader": e["preheader"], "body": e["body"],
                         "cta_text": e["cta_text"]})
    return pd.DataFrame(rows)


def profiles_export(lead_df: pd.DataFrame) -> pd.DataFrame:
    """Profile import file: email + custom properties the flows branch on."""
    out = lead_df[["email", "pain", "drop_stage", "who_for", "size", "household", "device", "country"]].copy()
    out["segment_id"] = out["pain"] + "__" + out["drop_stage"]
    out["quiz_dropoff_at"] = lead_df["ts"]
    return out.rename(columns={"email": "Email"})


def main() -> None:
    from dotenv import load_dotenv

    from . import analytics as a
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default="data/quiz_events.csv.gz")
    ap.add_argument("--out", default=str(DEMO_PATH))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    segs = a.segments(a.leads(a.build_sessions(pd.read_csv(args.csv))))
    client = get_client()
    out = []
    for seg in segs.head(args.limit).to_dict("records") if args.limit else segs.to_dict("records"):
        print(f"generating {seg['segment_id']} ...", flush=True)
        out.append(generate_sequence(seg, client))
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"{len(out)} sequences -> {args.out}")


if __name__ == "__main__":
    main()
