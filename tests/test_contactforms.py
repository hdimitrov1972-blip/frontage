"""Contact-form list with fake websites and a fake speed test.   python tests/test_contactforms.py"""
import datetime as dt
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import contactforms as cf  # noqa: E402

TODAY = dt.date(2026, 11, 9)


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


class Resp:
    def __init__(self, url, text, code=200, ctype="text/html; charset=utf-8"):
        self.url, self.text, self.status_code, self.headers = url, text, code, {"Content-Type": ctype}


SITES = {
    # slow café: contact page with a WPForms form and reCAPTCHA
    "https://slowcafe.ie/": '<a href="/contact-us/">Contact</a><a href="tel:+353">Call</a> © 2025',
    "https://slowcafe.ie/contact-us/": '<form class="wpforms-form"><textarea></textarea></form>'
                                       '<div class="g-recaptcha"></div>',
    # fast salon with no call button, form on the home page, no robot check
    "https://fastsalon.ie/": '<form action="/send"><input name="n"><textarea name="m"></textarea></form>',
    # fast pub with everything fine -> no clear problem -> not listed
    "https://finepub.ie/": '<a href="/get-in-touch">Get in touch</a><a href="tel:061">Call</a> © 2026',
    "https://finepub.ie/get-in-touch": '<form><textarea></textarea></form>',
    # http site, contact page without a detectable form (built by script)
    "http://oldhotel.ie/": '<a href="contact.html">Enquiries</a><a href="tel:1">x</a> &copy; 2012 Old Hotel',
    "http://oldhotel.ie/contact.html": '<div id="app"></div>',
    # a gym that is on do-not-contact by domain
    "https://blockedgym.ie/": '<form><textarea></textarea></form>',
    # tea rooms run by the state
    "https://castletea.ie/": '<form><textarea></textarea></form> © 2026 Office of Public Works',
}
SPEED = {"https://slowcafe.ie/": (0.31, 7400), "https://fastsalon.ie/": (0.92, 1800),
         "https://finepub.ie/": (0.95, 1500), "http://oldhotel.ie/": (0.88, 2100)}
calls = {"get": [], "speed": []}


def fake_get(url, **k):
    calls["get"].append(url)
    if url.startswith("https://down.ie"):
        raise ConnectionError("down")
    if url not in SITES:
        return Resp(url, "", 404)
    return Resp(url, SITES[url])


def fake_speed(url):
    calls["speed"].append(url)
    score, lcp = SPEED[url]
    return {"lighthouseResult": {"categories": {"performance": {"score": score}},
                                 "audits": {"largest-contentful-paint": {"numericValue": lcp}}}}


def lead(pid, name, site, cat="cafes", city="Kilkenny", rating="4.8", reviews="130", funnel="phone", form="yes",
         social="False", score="5"):
    return {"place_id": pid, "name": name, "Clean_Name": name, "website": site, "Website": site, "city": city,
            "search_category": cat, "rating": rating, "user_ratings_total": reviews, "Funnel": funnel,
            "Has_Form": form, "Has_Social_Only": social, "Lead_Score": score, "Do_Not_Contact": ""}


home = tempfile.mkdtemp()
pd.DataFrame([
    lead("p1", "Slow Café", "https://slowcafe.ie/", score="9"),
    lead("p2", "Fast Salon", "https://fastsalon.ie/", cat="salons", city="Ennis", rating="4.1", reviews="300"),
    lead("p3", "Fine Pub", "https://finepub.ie/", cat="pubs"),
    lead("p4", "Old Hotel", "http://oldhotel.ie/", cat="hotels", city="Waterford", reviews="12"),
    lead("p5", "Blocked Gym", "https://blockedgym.ie/", cat="gyms"),
    lead("p6", "Down Bakery", "https://down.ie/", cat="bakeries"),
    lead("p7", "Emailed Spa", "https://emailedspa.ie/", cat="spas"),
    lead("p8", "Email lead", "https://emaillead.ie/", funnel="email"),
    lead("p9", "Facebook only", "https://facebook.com/x", social="True"),
    lead("p10", "No form", "https://noform.ie/", form="no"),
    lead("p11", "Castle tea rooms", "https://castletea.ie/"),
]).to_csv(home + "/LEADS_MASTER.csv", index=False)
open(home + "/0_do_not_contact.csv", "w").write("email_or_domain\n@blockedgym.ie\n")
pd.DataFrame([{"sent_at": "2026-11-02T09:00:00", "place_id": "p7", "email": "info@emailedspa.ie"}]).to_csv(
    home + "/0_sent_log.csv", index=False)

c = cf.run(home, "key", today=TODAY, get=fake_get, speed=fake_speed, log=lambda m: None)
chk = pd.read_csv(home + "/0_contact_forms_checked.csv", dtype=str).fillna("").set_index("place_id")
lst = pd.read_excel(home + "/" + cf.LIST_NAME, dtype=str).fillna("")

check("only phone leads with a form, not social-only, not emailed, not on do-not-contact",
      set(chk.index) == {"p1", "p2", "p3", "p4", "p6", "p11"})
check("run by the state (OPW / council) -> not listed, no speed test", chk.loc["p11", "result"] == "public body"
      and "https://castletea.ie/" not in calls["speed"])
check("best lead first in the list", lst["place_id"].iloc[0] == "p1")
check("slow site: real seconds", chk.loc["p1", "problem"] == "it takes about 7 seconds to open")
check("form found on the contact page, robot check seen", chk.loc["p1", "form_url"] == "https://slowcafe.ie/contact-us/"
      and chk.loc["p1", "robot_check"] == "yes")
check("fast site without a call button", chk.loc["p2", "problem"] == "there's no button to call you straight from the phone"
      and chk.loc["p2", "robot_check"] == "no" and chk.loc["p2", "form_url"] == "https://fastsalon.ie/")
check("nothing wrong found -> not listed", chk.loc["p3", "result"] == "no clear problem" and "p3" not in set(lst["place_id"]))
check("http site -> 'Not secure'; contact page without a visible form still linked",
      "Not secure" in chk.loc["p4", "problem"] and chk.loc["p4", "form_kind"] == "contact page"
      and chk.loc["p4", "robot_check"] == "?")
check("site down is recorded, not listed", chk.loc["p6", "result"] == "site down" and "p6" not in set(lst["place_id"]))
check("speed test saved for the fix note", os.path.exists(home + "/lighthouse_json/p1.json"))

m1 = chk.loc["p1", "message"]
check("message = approved text with this business's details",
      m1.startswith("Hi Slow Café team,\n\nI came across Slow Café while looking at cafés in Kilkenny. "
                    "130 Google reviews at 4.8★ is a great reputation.")
      and "noticed it takes about 7 seconds to open. That's usually the moment" in m1
      and "Just reply to hello@frontage.agency." in m1 and "I won't contact you again." in m1
      and m1.endswith("Anzhel\nFrontage · frontage.agency"))
check("no praise for a 4.1★ rating or only 12 reviews",
      "reputation" not in chk.loc["p2", "message"] and "reputation" not in chk.loc["p4", "message"]
      and "looking at hair and beauty salons in Ennis." in chk.loc["p2", "message"])
check("no prices in any message", not any("€" in x for x in chk["message"]))
check("counts", c["listed_new"] == 3 and c["no_problem"] == 1 and c["site_down"] == 1 and c["in_list"] == 3
      and c["left_to_check"] == 0)

# second run: nothing is looked at twice
calls["get"].clear(); calls["speed"].clear()
c2 = cf.run(home, "key", today=TODAY, get=fake_get, speed=fake_speed, log=lambda m: None)
check("second run: no website or speed test repeated", calls["get"] == [] and calls["speed"] == [] and c2["in_list"] == 3)

# Anzhel ticks two rows on his phone: one x, one skip
from openpyxl import load_workbook  # noqa: E402
wb = load_workbook(home + "/" + cf.LIST_NAME)
ws = wb.worksheets[0]
for row in ws.iter_rows(min_row=2):
    if row[9].value == "p1":
        row[0].value = "x"
    if row[9].value == "p4":
        row[0].value = "Skip"
wb.save(home + "/" + cf.LIST_NAME)
c3 = cf.run(home, "key", today=TODAY + dt.timedelta(days=1), get=fake_get, speed=fake_speed, log=lambda m: None)
sent = pd.read_csv(home + "/0_contact_forms_sent.csv", dtype=str).set_index("place_id")
lst3 = pd.read_excel(home + "/" + cf.LIST_NAME, dtype=str).fillna("")
check("ticked rows move to the sent list with what was typed", c3["moved_to_sent"] == 2
      and sent.loc["p1", "mark"] == "x" and sent.loc["p4", "mark"] == "skip" and sent.loc["p1", "domain"] == "slowcafe.ie")
check("ticked rows leave the list for good", list(lst3["place_id"]) == ["p2"])
c4 = cf.run(home, "key", today=TODAY + dt.timedelta(days=2), get=fake_get, speed=fake_speed, log=lambda m: None)
check("no double counting on later runs", c4["moved_to_sent"] == 0 and len(pd.read_csv(home + "/0_contact_forms_sent.csv")) == 2)

# a 'no thanks' later puts the domain on do-not-contact -> it leaves the list
open(home + "/0_do_not_contact.csv", "a").write("@fastsalon.ie\n")
c5 = cf.run(home, "key", today=TODAY + dt.timedelta(days=2), get=fake_get, speed=fake_speed, log=lambda m: None)
check("do-not-contact wins over the list", c5["in_list"] == 0)

# the site that was down is tried again after 14 days
calls["get"].clear()
cf.run(home, "key", today=TODAY + dt.timedelta(days=15), get=fake_get, speed=fake_speed, log=lambda m: None)
check("site down: tried again after 14 days", any(u.startswith("https://down.ie") for u in calls["get"]))

# tick made on the phone while a run was busy is kept when saving
home2 = tempfile.mkdtemp()
rows = [{"place_id": "a", "name": "A", "city": "X", "form_url": "u", "message": "m", "robot_check": "no", "problem": "p"},
        {"place_id": "b", "name": "B", "city": "X", "form_url": "u", "message": "m", "robot_check": "no", "problem": "p"}]
cf.write_list(home2 + "/local.xlsx", rows)
cf.write_list(home2 + "/latest.xlsx", rows)
wb = load_workbook(home2 + "/latest.xlsx"); wb.worksheets[0]["A3"] = "x"; wb.save(home2 + "/latest.xlsx")
n = cf.merge_done(home2 + "/latest.xlsx", home2 + "/local.xlsx")
check("phone tick during a run is kept", n == 1 and cf.read_done(home2 + "/local.xlsx") == {"b": "x"})
check("merge with no Drive copy yet: nothing breaks", cf.merge_done(home2 + "/missing.xlsx", home2 + "/local.xlsx") == 0)

# problem wording
f = {"tel": True, "https": True, "year": 2026}
check("over 10 seconds", cf.choose_problem(20, 12500 / 1000, f, 2026) == "it takes over 10 seconds to open")
check("low phone score", cf.choose_problem(38, 3.1, f, 2026) == "Google's own phone test scores it 38 out of 100")
check("old © year", "© 2019" in cf.choose_problem(90, 2.0, {"tel": True, "https": True, "year": 2019}, 2026))
check("speed test failed and page fine -> nothing invented", cf.choose_problem(None, None, f, 2026) is None)

# Replies from a business contacted through its form: matched by domain, 'no thanks' -> do-not-contact,
# 'yes' -> the free fix note is prepared from the speed test saved for it
import email  # noqa: E402
import replies  # noqa: E402
import fixreply  # noqa: E402
import summary  # noqa: E402
home3 = tempfile.mkdtemp()
pd.DataFrame([{"place_id": "pa", "done_on": "2026-11-09", "mark": "x", "name": "Slow Café", "city": "Kilkenny",
               "domain": "slowcafe.ie", "form_url": "u"},
              {"place_id": "pb", "done_on": "2026-11-09", "mark": "x", "name": "Quiet Pub", "city": "Ennis",
               "domain": "quietpub.ie", "form_url": "u"}]).to_csv(home3 + "/0_contact_forms_sent.csv", index=False)


def mail(frm, subject, body, mid):
    return email.message_from_string(f"From: {frm}\nTo: hello@frontage.agency\nSubject: {subject}\n"
                                     f"Message-ID: <{mid}>\nDate: Tue, 10 Nov 2026 10:00:00 +0000\n\n{body}\n")


BOX = {"hello@frontage.agency": [mail("Mary <mary@slowcafe.ie>", "Website enquiry", "Yes please, send it over.", "y1"),
                                 mail("Pub <info@quietpub.ie>", "Re: your message", "No thanks.", "n1")]}
pw = {f"{b}@frontage.agency": "x" for b in replies.BOXES}
rc = replies.run(home3, pw, today=dt.date(2026, 11, 10), fetch=lambda a, p, s: iter(BOX.get(a, [])), log=lambda m: None)
dnc = open(home3 + "/0_do_not_contact.csv").read().split()
check("form business 'no thanks' -> whole domain on do-not-contact", "@quietpub.ie" in dnc and rc["optout"] == 1)
check("form business 'yes' is seen as a reply, not blocked", rc["reply"] == 1 and "@slowcafe.ie" not in dnc)
open(home3 + "/fix_guide.json", "w").write("{}")
os.makedirs(home3 + "/lighthouse_json")
open(home3 + "/lighthouse_json/pa.json", "w").write('{"lighthouseResult": {"audits": {"x": {}}}}')
got = {}
fixreply.compose = lambda name, audits, guide: f"Hi {name} team, here are your 3 fixes"
fixreply.save_draft = lambda msg, pw, imap: got.setdefault("draft", msg) is not None
fixreply.notify = lambda body, subj, pw, to, smtp: got.setdefault("subj", subj)
fc = fixreply.run(home3, "pw", "me@x", today=dt.date(2026, 11, 10), log=lambda m: None)
check("'yes' from a form business -> fix note drafted with its own speed test and name",
      fc["drafted"] == 1 and "Slow Café" in got["subj"] and got["draft"]["To"] == "mary@slowcafe.ie")

# weekly summary shows the contact-form numbers
n = summary.week_numbers(home, TODAY + dt.timedelta(days=2), 100)
t = summary.text(n, TODAY + dt.timedelta(days=2))
check("weekly summary: forms you sent this week + waiting in the list",
      "Contact forms you sent this week: 2" in t and "Waiting in Contact_forms_to_send.xlsx:" in t)
print("\nALL CONTACT FORM TESTS PASSED")
