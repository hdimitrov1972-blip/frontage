"""Short, natural business names in every email.

Google Maps names often carry the town or a slogan: "The Gateway Hotel • Dundalk", "Jungle Berry Açaí - Bray",
"Lifegym Personal Training | Online Personal Training | Nutrition". An owner never writes his own name like
that, so "Hi The Gateway Hotel • Dundalk team" reads like a machine. This keeps the first part only.

polish(home) fixes the texts already written for businesses still waiting to be emailed (long and short
versions, subject and body), so the pipeline notebook itself does not need to change.
"""
import os
import re

import pandas as pd

# a separator with a space before it: " • ", " · ", " | ", " - ", " – ", " — ", " (" , " :" is NOT cut
_CUT = re.compile(r"\s+(?:[•·|–—(]|-(?=\s))")
_GREETING = re.compile(r"^Hi (?P<name>.+?) team,", re.M)
TEXT_COLS = [("Email_Subject", "Email_Body"), ("Email_Subject_S", "Email_Body_S")]


def short_name(name):
    """'The Gateway Hotel • Dundalk' -> 'The Gateway Hotel'. Never returns less than 3 characters of name."""
    full = re.sub(r"\s+", " ", str(name or "")).strip()
    first = _CUT.split(full)[0].strip(" ,.;:-") if full else ""
    return first if len(first) >= 3 else full


def fix_text(subject, body):
    """(subject, body, changed): the long name replaced by the short one everywhere in this email."""
    m = _GREETING.search(str(body or ""))
    if not m:
        return subject, body, False
    long_name = m.group("name")
    short = short_name(long_name)
    if short == long_name:
        return subject, body, False
    return str(subject).replace(long_name, short), str(body).replace(long_name, short), True


def polish(home, log=print):
    """Shortens the names in the waiting emails. Returns how many emails changed."""
    path = os.path.join(home, "LEADS_MASTER.csv")
    if not os.path.exists(path):
        return 0
    m = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "Status_Outreach" not in m.columns:
        return 0
    waiting = m["Status_Outreach"].str.lower() == "pending"
    n = 0
    for subj_col, body_col in TEXT_COLS:
        if subj_col not in m.columns or body_col not in m.columns:
            continue
        for i in m.index[waiting & (m[body_col] != "")]:
            s, b, changed = fix_text(m.at[i, subj_col], m.at[i, body_col])
            if changed:
                m.at[i, subj_col], m.at[i, body_col] = s, b
                n += 1
    if n:
        m.to_csv(path, index=False)
    return n
