"""Suspect-address cleaner. Runs after the sender. The pipeline itself is not touched.

For every email lead the pipeline held back as "suspect" (address may not belong to the business):
1. A human answer wins: 2B_suspect_review.csv (Approve = yes/no) and any 2B_answers_*.csv on Drive.
2. Otherwise only CLEAR cases are decided by the rules below; anything unclear is left blank
   for the weekly check. Nothing already answered is ever changed.
3. yes -> the lead is approved and ready in LEADS_MASTER (as the pipeline does for your answers)
   no  -> the lead moves to the phone list (as the pipeline does for your answers)
"""
import glob
import os
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

import pandas as pd

TEMPLATE_DOMAINS = {"email.com", "domain.com", "example.com", "example.org", "mysite.com", "yoursite.com",
                    "website.com", "yourdomain.com", "company.com", "test.com", "sentry.io", "wixpress.com",
                    "sentry-next.wixpress.com", "godaddy.com", "squarespace.com", "wix.com", "user.com"}
TEMPLATE_LOCALS = {"your", "you", "user", "name", "yourname", "email", "example", "test", "someone", "john.doe",
                   "firstname.lastname", "username"}
VENDOR_WORDS = ("design", "digital", "web", "media", "print", "marketing", "creative", "photograph", "agency",
                "solutions", "seo", "hosting", "booksy", "fresha", "treatwell", "phorest", "timely", "mindbody",
                "opentable", "resdiary", "squarespace", "wix", "godaddy", "salongroup", "it-", "tech")
ORG_SUFFIXES = (".gov.ie", ".gov.uk", ".gov", ".edu", ".ac.uk", ".ac.ie")
ORG_DOMAINS = {"opw.ie", "hse.ie", "setu.ie", "ul.ie", "tcd.ie", "ucd.ie", "dcu.ie", "mu.ie", "atu.ie", "mtu.ie",
               "tus.ie", "universityofgalway.ie", "nuigalway.ie", "ucc.ie", "garda.ie", "housing.gov.ie"}
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.ie", "yahoo.co.uk", "hotmail.com", "hotmail.co.uk",
             "outlook.com", "outlook.ie", "live.com", "live.ie", "icloud.com", "me.com", "aol.com", "eircom.net",
             "mail.com", "gmx.com", "protonmail.com", "msn.com"}
GENERIC = {"the", "and", "of", "at", "by", "co", "ltd", "limited", "ireland", "irish", "bar", "bars", "cafe", "caffe",
           "coffee", "restaurant", "restaurants", "hotel", "hotels", "house", "salon", "salons", "studio", "club",
           "spa", "beauty", "hair", "nails", "nail", "lodge", "inn", "pub", "bistro", "kitchen", "grill", "tavern",
           "bakery", "gym", "fitness", "health", "wellness", "clinic", "centre", "center", "room", "rooms", "tea",
           "and", "wine", "food", "group", "suites", "guest", "guesthouse", "bnb", "b&b", "family", "leisure",
           "city", "town", "street", "square", "road", "lane", "main", "new", "old", "little", "big", "best"}
PLACES = {"dublin", "cork", "galway", "limerick", "waterford", "kilkenny", "ennis", "clare", "drogheda",
          "dundalk", "bray", "greystones", "swords", "balbriggan", "navan", "naas", "newbridge", "tralee", "killarney",
          "carlow", "athlone", "mullingar", "wexford", "sligo", "letterkenny", "clonmel", "tullamore", "portlaoise",
          "castlebar", "kerry", "meath", "kildare", "louth", "wicklow", "mayo", "donegal", "tipperary", "offaly",
          "laois", "westmeath", "salthill", "tramore", "lahinch", "douglas", "ballincollig", "rathmines", "ranelagh"}
EMAIL_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")


def _base(domain):
    """'www.Rive-Gauche.ie' -> 'rivegauche' (name part of a domain, no www, no TLD, no dashes)."""
    d = (domain or "").lower().strip().removeprefix("www.")
    parts = d.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac"):
        parts = parts[:-2]
    elif len(parts) >= 2:
        parts = parts[:-1]
    return re.sub(r"[^a-z0-9]", "", parts[-1] if parts else "")


def _tokens(name):
    words = re.findall(r"[a-z0-9]+", re.sub(r"['’`]", "", (name or "").lower()))
    return [w for w in words if len(w) >= 4 and w not in GENERIC and w not in PLACES]


def _initials(name):
    """Two spellings: every word ('Tower Hotel Waterford' -> thw) and distinctive words only
    ('Treacy's West County Hotel' -> twc)."""
    words = [w for w in re.findall(r"[a-z0-9]+", re.sub(r"['’`]", "", (name or "").lower())) if w != "the"]
    return {"".join(w[0] for w in words), "".join(w[0] for w in words if w not in GENERIC)}


def _common(a, b):
    m = SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b))
    return m.size


def decide(name, website, email, city=""):
    """('yes'|'no'|'', reason). '' = unclear, left for a person."""
    e = (email or "").strip().lower()
    if not EMAIL_RE.match(e):
        return "no", "not a real email address"
    local, dom = e.split("@", 1)
    site = urlparse(website if "://" in str(website) else "http://" + str(website or "")).netloc.lower()
    ebase, sbase = _base(dom), _base(site)
    name_tokens = _tokens(name)

    if dom in TEMPLATE_DOMAINS or local in TEMPLATE_LOCALS or dom.endswith(".wixpress.com"):
        return "no", "template / placeholder address"
    if dom in ORG_DOMAINS or dom.endswith(ORG_SUFFIXES) or re.search(r"coco\.ie$|council\.ie$", dom):
        return "no", "staff address at a public body, not the business"
    if any(t in ebase for t in name_tokens) or (dom in FREE_MAIL and any(t in local.replace(".", "") for t in name_tokens)):
        named = True
    else:
        named = False
    if any(w in ebase for w in VENDOR_WORDS) and not named:
        return "no", "web designer / booking system / supplier address"

    if dom in FREE_MAIL:
        return ("yes", "business name in the address") if named else ("", "free-mail address without the name")
    # a town in the email that the business name doesn't have -> probably another branch
    home_town = (city or "").lower()
    other_town = next((p for p in PLACES if p in ebase and p not in (name or "").lower() and p not in sbase
                       and p != home_town), None)
    if sbase and ebase == sbase:
        return "yes", "same domain as the website"
    if (sbase and 0 < _edit_distance(ebase, sbase) <= 2 and len(sbase) >= 6
            and ebase not in sbase and sbase not in ebase):          # 'rivegauche' + 'kk' is not a typo
        return "", "address looks like a typo of the website domain (could bounce)"
    if other_town:
        return "", f"address mentions {other_town.title()} — maybe another branch"
    if named:
        return "yes", "business name in the address"
    if any(len(i) >= 3 and ebase.startswith(i) for i in _initials(name)):
        return "yes", "business initials in the address"
    if sbase and _common(ebase, sbase) >= 6:
        return "yes", "address shares the website's name"
    return "", "no clear link between the address and the business"


def _edit_distance(a, b):
    if abs(len(a) - len(b)) > 2:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _read(path):
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


def human_answers(home):
    """place_id -> 'yes'/'no' from 2B_suspect_review.csv and any 2B_answers_*.csv (later files win)."""
    out = {}
    files = [os.path.join(home, "2B_suspect_review.csv")] + sorted(glob.glob(os.path.join(home, "2B_answers_*.csv")))
    for f in files:
        d = _read(f)
        if d.empty or "place_id" not in d.columns or "Approve" not in d.columns:
            continue
        for _, r in d.iterrows():
            a = str(r["Approve"]).strip().lower()
            if a in ("yes", "y", "no", "n") and "decided by rules" not in str(r.get("Hint", "")):
                out[str(r["place_id"])] = "yes" if a.startswith("y") else "no"
    return out


def run(home, log=print):
    mpath = os.path.join(home, "LEADS_MASTER.csv")
    m = _read(mpath)
    counts = {"suspects": 0, "yes": 0, "no": 0, "unclear": 0}
    if m.empty:
        return counts
    for c in ("Funnel", "Email_Approved", "Status_Outreach", "Send_Ready", "Send_Block_Reason", "Review_Note",
              "Call_Status", "Website", "Best_Email", "Clean_Name", "Name", "place_id"):
        if c not in m.columns:
            m[c] = ""
    sus = m[(m["Funnel"] == "email") & ~m["Email_Approved"].str.lower().isin(["true", "1", "yes"])
            & (m["Status_Outreach"].str.lower().isin(["pending", ""]))]
    counts["suspects"] = len(sus)
    if sus.empty:
        return counts
    answers = human_answers(home)
    rpath = os.path.join(home, "2B_suspect_review.csv")
    review = _read(rpath)
    if review.empty:
        review = pd.DataFrame(columns=["place_id", "Clean_Name", "Website", "Best_Email", "Approve", "Hint"])
    known = set(review["place_id"])
    new_rows = []
    for idx, r in sus.iterrows():
        pid = str(r["place_id"])
        name = r["Clean_Name"] or r["Name"]
        rule_verdict, rule_why = decide(name, r["Website"], r["Best_Email"], r.get("city", ""))
        changed = review[(review["place_id"] == pid) & review["Hint"].str.startswith("decided by rules")
                         & (review["Approve"].str.strip().str.lower() != rule_verdict)]
        if pid in answers:
            verdict, why, by = answers[pid], "your answer", "you"
        elif len(changed) and changed["Approve"].iloc[0].strip().lower()[:1] in ("y", "n"):
            verdict = "yes" if changed["Approve"].iloc[0].strip().lower().startswith("y") else "no"
            why, by = "your answer", "you"            # a person changed a rules answer in the file
        else:
            verdict, why, by = rule_verdict, rule_why, "rules"
        if pid not in known:
            new_rows.append({"place_id": pid, "Clean_Name": name, "Website": r["Website"], "Best_Email": r["Best_Email"],
                             "Approve": verdict, "Hint": (f"decided by rules: {why}" if verdict else f"weekly check: {why}")})
            known.add(pid)
        if verdict == "yes":
            m.at[idx, "Email_Approved"] = "True"
            if not str(r["Status_Outreach"]).strip():
                m.at[idx, "Status_Outreach"] = "pending"
            if (str(r["Send_Block_Reason"]).startswith("email address not approved")
                    or (not str(r["Send_Block_Reason"]).strip() and str(r.get("Report_File", "")).strip())):
                m.at[idx, "Send_Ready"] = "True"
                m.at[idx, "Send_Block_Reason"] = ""
            m.at[idx, "Review_Note"] = "approved by you" if by == "you" else f"approved by rules: {why}"
            counts["yes"] += 1
        elif verdict == "no":
            m.at[idx, "Funnel"] = "phone"
            m.at[idx, "Email_Approved"] = "False"
            m.at[idx, "Send_Ready"] = "False"
            m.at[idx, "Status_Outreach"] = ""
            m.at[idx, "Call_Status"] = "pending"
            m.at[idx, "Review_Note"] = ("moved to phone: you rejected the email" if by == "you"
                                        else f"moved to phone by rules: {why}")
            counts["no"] += 1
        else:
            counts["unclear"] += 1
    if new_rows:
        review = pd.concat([review, pd.DataFrame(new_rows)], ignore_index=True)
        review.to_csv(rpath, index=False)
    if counts["yes"] or counts["no"]:
        m.to_csv(mpath, index=False)
        if os.path.isdir(os.path.join(home, "latest")):
            m.to_csv(os.path.join(home, "latest", "LEADS_MASTER.csv"), index=False)
    return counts
