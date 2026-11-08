"""SockLock: spend-ramp model, $400k -> $800k over 6 months.

Simplified homework formula: EGP = Spend x (ROMI - 100%).
Every assumption is a named constant below.
"""

BASE_SPEND = 400_000
BASE_ROMI = 1.35            # blended, data room
CPC = 1.00                  # data room (US)
LEAD_RATE = 0.36 - 0.02     # reached step 5 (email given) minus buyers
DEGRADATION_AT_2X = 0.12    # assumption: CPA/CPC +12% when spend doubles
LTV_EMAIL = 60              # assumption: $68 LTV minus first-box discount
ESP_COST = 3_000            # assumption: ESP for ~150-300k active profiles / month
RAMP = [400, 467, 533, 600, 667, 733, 800]  # $k, month 0..6
EFFECT_SHARE = [0, 0, 0.5, 1, 1, 1, 1]      # month 1 build, month 2 50% holdout test

import math
K = math.log(1 + DEGRADATION_AT_2X) / math.log(2)

SCENARIOS = {
    "A: no flow":       {"pess": 0.003, "base": 0.010, "opt": 0.020, "esp": ESP_COST},
    "B: generic flow":  {"pess": 0.0015, "base": 0.003, "opt": 0.005, "esp": 0},
}


def degr(spend):
    return (spend / BASE_SPEND) ** K


def ads(spend):
    romi = BASE_ROMI / degr(spend)
    return romi, spend * (romi - 1)


def leads(spend):
    return spend / (CPC * degr(spend)) * LEAD_RATE


def email(spend, conv, esp):
    buyers = leads(spend) * conv
    return buyers, buyers * LTV_EMAIL - esp


def max_spend(extra_romi_per_dollar=0.0):
    # solve (BASE_ROMI + extra) / degr(S) >= 1.25
    return BASE_SPEND * ((BASE_ROMI + extra_romi_per_dollar) / 1.25) ** (1 / K)


if __name__ == "__main__":
    print(f"K={K:.4f}")
    print("\nMonth | spend | ROMI ads | EGP ads | leads | A-base buyers | EGP email A-base | total ROMI A-base")
    for m, s_k in enumerate(RAMP):
        s = s_k * 1000
        romi, egp = ads(s)
        b, e = email(s, 0.010, ESP_COST)
        e *= EFFECT_SHARE[m]; b *= EFFECT_SHARE[m]
        tot_romi = (s * romi + b * LTV_EMAIL) / (s + (ESP_COST if EFFECT_SHARE[m] else 0))
        print(f"{m} | {s_k}k | {romi:.1%} | {egp/1e3:.1f}k | {leads(s)/1e3:.1f}k | {b:.0f} | {e/1e3:.1f}k | {tot_romi:.1%}")

    for spend in (400_000, 800_000):
        print(f"\nAt spend {spend/1e3:.0f}k: ads ROMI {ads(spend)[0]:.1%}, EGP ads {ads(spend)[1]/1e3:.1f}k, leads {leads(spend)/1e3:.1f}k")
        for name, sc in SCENARIOS.items():
            for lvl in ("pess", "base", "opt"):
                b, e = email(spend, sc[lvl], sc["esp"])
                romi_total = (spend * ads(spend)[0] + b * LTV_EMAIL) / (spend + sc["esp"])
                e68 = b * 68 - sc["esp"]
                print(f"  {name:16s} {lvl:4s} conv {sc[lvl]:.2%}: buyers {b:6.0f}, EGP {e/1e3:6.1f}k (LTV68: {e68/1e3:6.1f}k), total ROMI {romi_total:.1%}")

    print(f"\nMax spend at ROMI>=125% without flow: {max_spend()/1e3:.0f}k")
    for name, sc in SCENARIOS.items():
        for lvl in ("pess", "base", "opt"):
            extra = LEAD_RATE / CPC * sc[lvl] * LTV_EMAIL
            print(f"Max spend with {name} {lvl}: {max_spend(extra)/1e3:.0f}k (+{extra:.1%} ROMI)")
    # 6-month cumulative EGP from email, scenario A base
    cum = sum(email(s*1000, 0.010, ESP_COST)[1] * EFFECT_SHARE[m] for m, s in enumerate(RAMP))
    print(f"\n6-month cumulative email EGP A-base: {cum/1e3:.0f}k")
