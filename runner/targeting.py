"""Targeting (Anzhel's decision, 17 Nov 2026): small owner-run places first, big ones second.

Hotels, chains and big venues are NOT dropped: they move to the back of the email queue
(Target_Tier 2), so every small place ready that day is emailed before them. Small B&Bs and guest
houses stay in front. The sender (v2.6) sorts by Target_Tier, then Lead_Score.

A waiting email lead goes to the back (Target_Tier "2", Target_Reason says why) when:
- hotel:  the name or the address says hotel / resort / conference centre / golf links, or it is in the
          'hotels' search and has more than BIG_HOTEL_REVIEWS Google reviews (a small B&B stays in front)
- chain:  its email domain is used by 2 or more different places in LEADS_MASTER (fusegym.ie for Bray
          and Waterford), or the address says group / collection / hotels
- big:    more than BIG_REVIEWS Google reviews, or a shopping centre / retail park / airport / arena
- wrong:  a jobs or accounts address (careers@, accounts@...)
Everyone else: Target_Tier "1". Nothing is blocked or deleted.
"small_first": false in config/frontage.json clears the tiers (one queue again).
"""
import os
import re

import pandas as pd

BIG_REVIEWS = 3000
BIG_HOTEL_REVIEWS = 1000
HOTEL = re.compile(r"\bhotels?\b|\bresort\b|conference cent|golf links|golf resort", re.I)
BIG_PLACE = re.compile(r"shopping cent|retail park|\bairport\b|\bterminal \d|\barena\b|\bstadium\b", re.I)
GROUP_WORDS = re.compile(r"group|collection|hotels", re.I)
WRONG_LOCAL = {"career", "careers", "jobs", "hr", "recruitment", "accounts", "invoices", "payroll"}


def _reviews(m):
    out = pd.Series(0.0, index=m.index)
    for c in ("user_ratings_total", "Reviews"):
        if c in m.columns:
            out = out.combine(pd.to_numeric(m[c], errors="coerce").fillna(0), max)
    return out


def reason(row, reviews, domain_places):
    name = f"{row.get('name', '')} {row.get('Name', '')} {row.get('Clean_Name', '')}"
    email = str(row.get("Best_Email", "")).strip().lower()
    local, _, dom = email.rpartition("@")
    if HOTEL.search(name) or "hotel" in dom:
        return "hotel"
    if str(row.get("search_category", "")).lower() == "hotels" and reviews > BIG_HOTEL_REVIEWS:
        return "hotel"
    if dom and domain_places.get(dom, 0) >= 2:
        return "chain (same email domain as other places)"
    if GROUP_WORDS.search(dom) or GROUP_WORDS.search(local):
        return "chain (group address)"
    if reviews > BIG_REVIEWS or BIG_PLACE.search(name):
        return "big venue"
    if local in WRONG_LOCAL:
        return "jobs / accounts address"
    return ""


def run(home, enabled=True, log=print):
    """Returns {"front": tier 1, "back": tier 2, "changed": rows whose tier changed}."""
    path = os.path.join(home, "LEADS_MASTER.csv")
    out = {"front": 0, "back": 0, "changed": 0}
    if not os.path.exists(path):
        return out
    m = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in ("Funnel", "Status_Outreach", "Best_Email", "place_id", "name", "Name", "Clean_Name",
              "search_category", "Target_Tier", "Target_Reason"):
        if c not in m.columns:
            m[c] = ""
    pending = (m["Funnel"] == "email") & (m["Status_Outreach"].str.lower() == "pending")
    tier, why_col = m["Target_Tier"].copy(), m["Target_Reason"].copy()
    if not enabled:
        tier[pending], why_col[pending] = "", ""
    else:
        doms = m["Best_Email"].str.strip().str.lower().str.rpartition("@")[2]
        domain_places = m.assign(_d=doms)[doms != ""].groupby("_d")["place_id"].nunique().to_dict()
        reviews = _reviews(m)
        for i in m.index[pending]:
            why = reason(m.loc[i], reviews[i], domain_places)
            tier[i], why_col[i] = ("2", why) if why else ("1", "")
    changed = (tier != m["Target_Tier"]) | (why_col != m["Target_Reason"])
    out["changed"] = int(changed.sum())
    out["front"] = int((pending & (tier == "1")).sum())
    out["back"] = int((pending & (tier == "2")).sum())
    if out["changed"]:
        m["Target_Tier"], m["Target_Reason"] = tier, why_col
        tmp = path + ".tmp"
        m.to_csv(tmp, index=False)
        os.replace(tmp, path)
        log(f"[targeting] waiting email leads: {out['front']} small places first, {out['back']} hotels / chains / "
            f"big venues after them ({out['changed']} changed today)")
    return out
