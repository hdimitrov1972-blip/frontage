"""Dead-domain check with a fake DNS.   python tests/test_domaincheck.py"""
import datetime as dt
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import domaincheck  # noqa: E402

TODAY = dt.date(2026, 11, 6)


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


DNS = {"google.com": ("ok", ""), "gmail.com": ("ok", ""), "outlook.com": ("ok", ""), "alive.ie": ("ok", "MX mx.alive.ie"), "gone.ie": ("dead", "domain does not exist"),
       "slow.ie": ("unknown", "Timeout"), "nomx.ie": ("dead", "no MX and no A record")}
asked = []


def fake(dom):
    if dom in ("google.com", "gmail.com", "outlook.com"):
        return DNS[dom]
    asked.append(dom)
    return DNS[dom]


home = tempfile.mkdtemp()
pd.DataFrame([
    {"Funnel": "email", "Status_Outreach": "pending", "Best_Email": "info@alive.ie"},
    {"Funnel": "email", "Status_Outreach": "pending", "Best_Email": "mailto%20info@gone.ie"},
    {"Funnel": "email", "Status_Outreach": "pending", "Best_Email": "book@slow.ie"},
    {"Funnel": "email", "Status_Outreach": "pending", "Best_Email": "hi@nomx.ie"},
    {"Funnel": "email", "Status_Outreach": "pending", "Best_Email": "someone@gmail.com"},
    {"Funnel": "email", "Status_Outreach": "sent", "Best_Email": "old@gone2.ie"},
]).to_csv(home + "/LEADS_MASTER.csv", index=False)
open(home + "/0_do_not_contact.csv", "w").write("email_or_domain\nhi@nomx.ie\n")

c = domaincheck.run(home, today=TODAY, resolve=fake, log=lambda m: None)
dnc = open(home + "/0_do_not_contact.csv").read().split()
check("Gmail addresses and already-sent leads are not looked up", "gmail.com" not in asked and "gone2.ie" not in asked)
check("dead domain added (clean address)", "info@gone.ie" in dnc)
check("live domain and timeout are NOT blocked", "info@alive.ie" not in dnc and "book@slow.ie" not in dnc)
check("no duplicates on do-not-contact", dnc.count("hi@nomx.ie") == 1)
check("counts", c == {"checked": 4, "dead_domains": 2, "added_to_do_not_contact": 1, "unknown": 1, "skipped": ""})

asked.clear()
c2 = domaincheck.run(home, today=TODAY + dt.timedelta(days=1), resolve=fake, log=lambda m: None)
check("next day: only the 'no answer' domain is asked again", asked == ["slow.ie"] and c2["added_to_do_not_contact"] == 0)
asked.clear()
domaincheck.run(home, today=TODAY + dt.timedelta(days=31), resolve=fake, log=lambda m: None)
check("after 30 days every domain is checked again", sorted(asked) == ["alive.ie", "gone.ie", "nomx.ie", "slow.ie"])

home2 = tempfile.mkdtemp()
pd.DataFrame([{"Funnel": "email", "Status_Outreach": "pending", "Best_Email": f"info@shop{i}.ie"} for i in range(12)]
             ).to_csv(home2 + "/LEADS_MASTER.csv", index=False)
c3 = domaincheck.run(home2, today=TODAY, resolve=lambda d: ("dead", "NXDOMAIN"), log=lambda m: None)
check("broken DNS (google.com 'dead'): skipped, nobody blocked",
      c3["skipped"] and not os.path.exists(home2 + "/0_do_not_contact.csv"))
c4 = domaincheck.run(home2, today=TODAY, resolve=lambda d: ("ok", "") if d in DNS else ("dead", "x"), log=lambda m: None)
check("12 of 12 shop domains dead: looks wrong, nobody blocked, nothing cached",
      c4["skipped"] and not os.path.exists(home2 + "/0_domain_check.csv")
      and "@" not in open(home2 + "/0_do_not_contact.csv").read() if os.path.exists(home2 + "/0_do_not_contact.csv") else c4["skipped"])
print("\nALL DOMAIN CHECK TESTS PASSED")
