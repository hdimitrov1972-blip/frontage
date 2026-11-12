"""The short first email (split test from 12 Nov 2026: half the businesses get it, half get the long one).

About 70 words, ONE problem, and only a problem that was really found on their site. The text is written into
LEADS_MASTER.csv (Email_Subject_S / Email_Body_S); the sender picks it for the "short" half.
A business with no clear problem gets no short text, and so gets the long email.
"""
import datetime as dt
import os
import re

import pandas as pd

OLD_YEARS = 3          # © year this many years old or more
SLOW_SECONDS = 6       # Google's phone test: seconds until the main content shows


def _num(v):
    m = re.search(r"\d+(\.\d+)?", str(v).replace(",", "."))
    return float(m.group(0)) if m else None


def short_name(name):
    from names import short_name as _short
    return _short(name) or "there"


def problem(row, this_year):
    """A clause that follows "I had a look at your website and ", or None."""
    readable = "not readable" not in str(row.get("Checks_Note", "")).lower()
    if readable and str(row.get("Has_Tap_To_Call", "")).lower() == "no":
        return ("couldn't find a button to call you straight from a phone. People have to copy the number by hand, "
                "and many just pick the next place.")
    if str(row.get("HTTPS", "")).upper() == "NO":
        return ("the browser shows a \"Not secure\" warning on it. That makes people think twice before getting "
                "in touch.")
    if readable and str(row.get("Has_Form", "")).lower() == "no":
        return "couldn't find a way to send you a message from it, so some enquiries probably go elsewhere."
    year = _num(row.get("Copyright_Year", ""))
    if readable and year and 1995 <= year <= this_year - OLD_YEARS:
        return (f"noticed the bottom of the page still says © {int(year)}. A small thing, but it can make people "
                "wonder if you're still open.")
    lcp = _num(row.get("LCP", ""))
    if lcp and lcp >= SLOW_SECONDS:
        secs = "over 10" if lcp >= 10.5 else f"about {round(lcp)}"
        return (f"ran it through Google's phone test: it took {secs} seconds to show up. Most people give up "
                "after three or four.")
    return None


def write(row, this_year):
    """(subject, body) or None when no clear problem was found."""
    p = problem(row, this_year)
    if not p:
        return None
    name = short_name(row.get("Clean_Name") or row.get("Name") or row.get("name") or "")
    body = "\n".join([
        f"Hi {name} team,", "",
        f"I had a look at your website and {p}", "",
        "I fix small things like this for local businesses, and I've made a short free report on your website. "
        "Would you like me to send it? Just reply \"yes\".", "",
        "Anzhel", "Frontage · frontage.agency", "",
        "Not interested? Just reply \"no thanks\" and I won't write again."])
    return f"{name}: quick question about your website", body


def fill(home, today=None, log=print):
    today = today or dt.date.today()
    path = os.path.join(home, "LEADS_MASTER.csv")
    if not os.path.exists(path):
        return 0
    m = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in ("Funnel", "Status_Outreach", "Email_Subject_S", "Email_Body_S"):
        if c not in m.columns:
            m[c] = ""
    need = (m["Funnel"] == "email") & (m["Status_Outreach"].str.lower() == "pending") & (m["Email_Body_S"] == "")
    n = 0
    for i in m.index[need]:
        got = write(m.loc[i], today.year)
        if got:
            m.at[i, "Email_Subject_S"], m.at[i, "Email_Body_S"] = got
            n += 1
    if n:
        m.to_csv(path, index=False)
    return n
