"""Rule checks for generated emails: format limits, merge fields, invented claims, spam triggers.

The prompt asks Gemini to follow the rules; this module checks that it did. Errors trigger one
automatic repair call in emails.generate_sequence; the UI shows the score per email.
"""
from __future__ import annotations

import re

SEND_HOURS = [1, 24, 72]
ALLOWED_MERGE = {"size"}

# claims the brief does not support (see emails.RULES)
BANNED = {
    r"\bpaus(e|ing)\b|\bskip(ping)? (a |the |any |your )?(next )?(deliver|box|shipment|month|order|quarter)|free trial":"flexibility we do not offer (only 'cancel anytime')",
    r"\bguarantee": "guarantee",
    r"\breviews?\b|\brated\b|\b\d(\.\d)? stars?\b|\bcustomers? (love|say)|\bthousands of\b": "social proof we do not have",
    r"\bsaved\b.*\bfor you\b|\breserved\b|\bheld for you\b|\bwaiting for you\b": "claims we saved something for them",
    r"\bcomfort|\bsoft(est|er)?\b|\bdurab|\blasts? longer\b|\bholds? up\b|\bwears? well\b|\bbreathab|\bcotton\b|\bmerino\b": "comfort / material / durability claim",
}
DISCOUNT = r"\d+\s?% off|\bdiscount|\bcoupon|\bpromo code|\bsale\b"
SPAM = r"\bfree\b|\bact now\b|\blimited time\b|\burgent\b|\b100%|\$\$|!!|\bclick here\b|\bbuy now\b"
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def _merge_fields(text: str) -> set[str]:
    return {m.strip() for m in re.findall(r"\{\{\s*([^}]+?)\s*\}\}", text)}


def check_email(email: dict, allow_discount: bool = False, index: int | None = None) -> list[dict]:
    """List of {level: error|warn, field, msg}."""
    issues = []

    def add(level, field, msg):
        issues.append({"level": level, "field": field, "msg": msg})

    subjects = [email.get("subject", "")] + list(email.get("alt_subjects") or [])
    for i, subj in enumerate(subjects):
        name = "subject" if i == 0 else f"alt subject {i}"
        if len(subj) > 50:
            add("error", name, f"{len(subj)} characters, max 50")
        if EMOJI.search(subj):
            add("error", name, "emoji in subject")
        if re.search(r"\b[A-Z]{4,}\b", subj.replace("SockLock", "")):
            add("warn", name, "ALL CAPS word")
    if len(email.get("preheader", "")) > 90:
        add("error", "preheader", f"{len(email['preheader'])} characters, max 90")

    words = len(re.findall(r"\b\w+\b", email.get("body", "")))
    if words < 60 or words > 120:
        add("error" if words < 50 or words > 135 else "warn", "body", f"{words} words, target 60-120")

    text = " ".join([*subjects, email.get("preheader", ""), email.get("body", ""), email.get("cta_text", "")])
    low = text.lower()
    bad_fields = _merge_fields(text) - ALLOWED_MERGE
    if bad_fields:
        add("error", "merge", f"unknown merge field(s): {', '.join(sorted(bad_fields))}")
    for pattern, what in BANNED.items():
        m = re.search(pattern, low)
        if m:
            add("error", "claim", f"{what}: \"{m.group(0)}\"")
    if not allow_discount and re.search(DISCOUNT, low):
        add("error", "claim", "mentions a discount, but discounts are off")
    if allow_discount and index is not None and index < 2 and re.search(DISCOUNT, low):
        add("error", "claim", "discount allowed in email 3 only")
    for m in set(re.findall(SPAM, low)):
        add("warn", "spam", f"spam-filter trigger: \"{m}\"")
    if len(email.get("cta_text", "").split()) > 5:
        add("warn", "cta", "call to action longer than 5 words")
    return issues


def check_sequence(seq: dict, allow_discount: bool = False) -> dict:
    """{score 0-100, per_email: [issues...], sequence: [issues...]}."""
    emails = seq.get("emails", [])
    seq_issues = []
    hours = [e.get("send_after_hours") for e in emails]
    if hours != SEND_HOURS:
        seq_issues.append({"level": "error", "field": "timing", "msg": f"send times {hours}, expected {SEND_HOURS}"})
    per_email = [check_email(e, allow_discount, i) for i, e in enumerate(emails)]
    all_issues = seq_issues + [i for lst in per_email for i in lst]
    errors = sum(i["level"] == "error" for i in all_issues)
    warns = len(all_issues) - errors
    return {"score": max(0, 100 - 15 * errors - 5 * warns), "errors": errors, "warnings": warns,
            "per_email": per_email, "sequence": seq_issues}


def repair_note(report: dict) -> str:
    """Feedback for a repair call, listing only the errors."""
    lines = [f"- {i['field']}: {i['msg']}" for i in report["sequence"] if i["level"] == "error"]
    for n, issues in enumerate(report["per_email"], 1):
        lines += [f"- email {n}, {i['field']}: {i['msg']}" for i in issues if i["level"] == "error"]
    return "\n".join(lines)
