from socklock_recovery import creative as cr
from socklock_recovery import email_qa as q
from socklock_recovery import emails as em

BODY = " ".join(["word"] * 80)
GOOD = {"send_after_hours": 1, "subject": "Socks gone missing again?", "alt_subjects": ["Where do they go?", "Pairs stay together"],
        "preheader": "Magnets keep pairs together.", "body": f"Your {{{{ size }}}} pairs. {BODY}", "cta_text": "Build my box"}


def _email(**kw):
    return {**GOOD, **kw}


def test_clean_email_passes():
    assert q.check_email(GOOD) == []


def test_catches_invented_claims_and_fields():
    issues = q.check_email(_email(body=f"Pause anytime. Soft cotton. {{{{ who_for }}}} {BODY}"))
    msgs = " ".join(i["msg"] for i in issues)
    assert "flexibility" in msgs and "comfort" in msgs and "who_for" in msgs
    assert all(i["level"] == "error" for i in issues if i["field"] in ("claim", "merge"))


def test_limits_and_discount():
    issues = q.check_email(_email(subject="x" * 60, alt_subjects=["Get 20% off 🧦"]))
    fields = {i["field"] for i in issues}
    assert {"subject", "alt subject 1", "claim"} <= fields
    assert not any(i["field"] == "claim" for i in q.check_email(_email(body=f"20% off. {BODY}"), True, 2))
    assert any(i["field"] == "claim" for i in q.check_email(_email(body=f"20% off. {BODY}"), True, 0))


def test_absolute_promises_flagged_but_pain_quotes_pass():
    issues = q.check_email(_email(alt_subjects=["Never lose a sock again", "Pairs together forever"]))
    assert sum("absolute promise" in i["msg"] for i in issues) == 1  # one hit per rule, both subjects joined
    ok = f"You said you can never find a match and sorting takes forever. {BODY}"
    assert q.check_email(_email(body=ok)) == []


def test_skip_in_plain_english_is_fine():
    assert q.check_email(_email(body=f"You can skip this email. {BODY}")) == []


def test_sequence_score_and_repair_note():
    seq = {"emails": [GOOD, _email(send_after_hours=24, body="too short"), _email(send_after_hours=72)]}
    r = q.check_sequence(seq)
    assert r["errors"] == 1 and r["score"] == 85
    assert "email 2, body" in q.repair_note(r)
    assert q.check_sequence({"emails": [GOOD]})["sequence"]


def test_demo_sequences_pass_qa():
    for s in em.load_demo().values():
        assert q.check_sequence(s)["errors"] == 0, s["segment_id"]


def test_csv_has_subject_variants():
    df = em.sequences_to_csv([{"segment_id": "x", "emails": [GOOD]}])
    assert list(df[["subject", "subject_b", "subject_c"]].iloc[0]) == [GOOD["subject"], *GOOD["alt_subjects"]]


def test_creative_demo_and_markdown():
    pack = cr.load_demo()
    assert {b["verdict"] for b in pack["briefs"]} <= {"lead", "test", "avoid"}
    for b in pack["briefs"]:
        if b["verdict"] == "avoid":
            assert not b["hooks"]
        else:
            assert len(b["hooks"]) == 3 and all(len(h.split()) <= 12 for h in b["hooks"])
    md = cr.to_markdown(pack, {})
    assert md.startswith("# SockLock creative briefs") and "| sec |" in md
