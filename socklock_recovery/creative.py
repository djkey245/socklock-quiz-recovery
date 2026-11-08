"""Creative briefs from the pain analysis: which pains to lead ads with, hooks, a 15-second script.

The pain index says which quiz answers turn into buyers. Ads built on high-index pains buy
clicks that convert (lower CPA); ads that attract low-index pains waste spend.
One Gemini call per refresh.

CLI: python -m socklock_recovery.creative --csv data/quiz_events.csv.gz
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from .emails import BRAND_BRIEF, DEFAULT_MODEL, get_client

DEMO_PATH = Path(__file__).resolve().parent.parent / "demo" / "sample_creative_briefs.json"

CREATIVE_RULES = """\
Rules:
- Meta video ads, 9:16, US audience, plain friendly American English.
- verdict: "lead" for pains with conversion index >= 1.1, "test" for 0.8-1.1, "avoid" below 0.8.
  Exception: if the magnet does solve the pain and the low index comes from a weak email-step pass rate,
  use "test" and say the leak is in the quiz, not in the angle.
- For "avoid" pains: no hooks and no script; explain in why what spend to cut and what NOT to say in ads.
- Hooks: 3 per pain, each <= 12 words, spoken in the first 2 seconds, in the customer's own words.
  Each hook takes a different angle (question, confession, bold statement).
- Script: 4-5 shots that fit 15 seconds; each shot = what we see + what is said or shown as text.
- The magnet works in the washer and dryer only. Do not promise anything outside laundry
  (kids losing socks at school, drawers, etc.) and no absolutes like "never", "zero" or "completely".
- Only the product facts above exist. No reviews, ratings, customer counts, guarantees, discounts,
  comfort, materials or durability claims.
- Shoots must be cheap: phone footage, home setting, one actor, the product, a washer.
"""


class Shot(BaseModel):
    seconds: str = Field(description="e.g. 0-2")
    visual: str
    voice_or_text: str


class PainBrief(BaseModel):
    pain: str = Field(description="The pain key exactly as given")
    verdict: Literal["lead", "test", "avoid"]
    why: str = Field(description="One or two sentences citing the numbers")
    hooks: list[str]
    script: list[Shot]
    on_screen_text: str = Field(description="Short overlay text for the end card, empty for avoid")


class CreativePack(BaseModel):
    summary: str = Field(description="Three sentences for the creative lead: what to make next and what to stop")
    briefs: list[PainBrief]


def build_prompt(pains: pd.DataFrame) -> str:
    lines = []
    for r in pains.itertuples():
        lines.append(
            f"- key={r.pain}, \"{r.label}\": {r.share_of_answers:.0%} of quiz answers, {r.share_of_buyers:.0%} of buyers, "
            f"conversion index {r.conversion_index:.2f}, {r.email_pass_rate:.0%} pass the email step")
    return (
        f"{BRAND_BRIEF}\n"
        "Quiz data: answers to 'What frustrates you most about socks?' and how each group converts.\n"
        + "\n".join(lines) + "\n\n"
        f"{CREATIVE_RULES}\n"
        "Write one brief per pain, in the order given."
    )


def generate_pack(pains: pd.DataFrame, client=None, model: str | None = None) -> dict:
    from google.genai import types
    client = client or get_client()
    resp = client.models.generate_content(
        model=model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        contents=build_prompt(pains),
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=CreativePack, temperature=0.9),
    )
    pack = resp.parsed if resp.parsed is not None else CreativePack.model_validate_json(resp.text)
    return pack.model_dump()


def load_demo() -> dict | None:
    return json.loads(DEMO_PATH.read_text()) if DEMO_PATH.exists() else None


def to_markdown(pack: dict, labels: dict[str, str]) -> str:
    out = ["# SockLock creative briefs from quiz pains", "", pack["summary"], ""]
    for b in pack["briefs"]:
        out += [f"## {labels.get(b['pain'], b['pain'])} — {b['verdict'].upper()}", "", b["why"], ""]
        if b["hooks"]:
            out += ["**Hooks**", ""] + [f"- {h}" for h in b["hooks"]] + [""]
        if b["script"]:
            out += ["**15-second script**", "", "| sec | visual | voice / text |", "| --- | --- | --- |"]
            out += [f"| {s['seconds']} | {s['visual']} | {s['voice_or_text']} |" for s in b["script"]] + [""]
        if b["on_screen_text"]:
            out += [f"End card: {b['on_screen_text']}", ""]
    return "\n".join(out)


def main() -> None:
    from dotenv import load_dotenv

    from . import analytics as a
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default="data/quiz_events.csv.gz")
    ap.add_argument("--out", default=str(DEMO_PATH))
    args = ap.parse_args()
    pains = a.pain_analysis(a.build_sessions(pd.read_csv(args.csv)))
    pack = generate_pack(pains)
    Path(args.out).write_text(json.dumps(pack, indent=2, ensure_ascii=False))
    print(f"{len(pack['briefs'])} briefs -> {args.out}")


if __name__ == "__main__":
    main()
