from socklock_recovery import emails as e

SEG = {"segment_id": "wear_out__offer", "pain": "wear_out", "drop_stage": "offer", "leads": 120,
       "top_who_for": "kids", "top_size": "kids"}


def test_prompt_carries_segment_and_rules():
    p = e.build_prompt(SEG)
    assert "Socks wear out too fast" in p and "personal offer" in p and "My kids" in p
    assert "Do not offer any discount" in p
    assert "20% off" in e.build_prompt(SEG, include_discount=True)


def test_render_and_exports():
    seq = {"segment_id": "x", "emails": [{"send_after_hours": 1, "subject": "S", "preheader": "P",
                                          "body": "Hi <b>\n\nYour {{ size }} pair", "cta_text": "Go"}]}
    h = e.render_html(seq["emails"][0])
    assert "&lt;b&gt;" in h and "Your M pair" in h
    assert len(e.sequences_to_csv([seq])) == 1
