"""SockLock quiz definition: 6 steps, then the personal offer and checkout.

Step 2 is the pain question used for segmentation and email personalisation.
"""

STEPS = {
    1: {"key": "who_for", "question": "Who are the socks for?",
        "options": {"me": "Me", "partner": "My partner", "kids": "My kids", "family": "The whole family"}},
    2: {"key": "pain", "question": "What frustrates you most about socks?",
        "options": {
            "lost_in_laundry": "Socks disappear in the laundry",
            "mismatched": "I can never find a matching pair",
            "sorting_time": "Sorting and pairing takes forever",
            "kids_lose": "My kids lose socks constantly",
            "wear_out": "Socks wear out too fast",
        }},
    3: {"key": "style", "question": "What style do you wear most?",
        "options": {"casual": "Casual", "athletic": "Athletic", "dress": "Dress", "mix": "A mix"}},
    4: {"key": "size", "question": "Your size and email for your personal plan",
        "options": {"kids": "Kids", "S": "S", "M": "M", "L": "L", "XL": "XL"}},
    5: {"key": "household", "question": "How many people live in your home?",
        "options": {"1": "Just me", "2": "Two", "3-4": "3-4", "5+": "5 or more"}},
}

# Stage = how far a session got. 6 = saw the personal offer.
STAGES = [
    (0, "Clicked ad"),
    (1, "Opened quiz"),
    (2, "Step 2: pain"),
    (3, "Step 3: style"),
    (4, "Step 4: size + email"),
    (5, "Step 5: household"),
    (6, "Personal offer"),
]
PAID_STAGE = 7
EMAIL_STEP = 4

ANSWER_KEYS = [s["key"] for s in STEPS.values()]


def pain_label(key: str) -> str:
    return STEPS[2]["options"].get(key, key)


def stage_label(stage: int) -> str:
    if stage == PAID_STAGE:
        return "Paid"
    return dict(STAGES).get(stage, str(stage))
