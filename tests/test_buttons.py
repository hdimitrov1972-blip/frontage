"""Short email text, reply buttons (reference code), button YES answered by the machine.   python tests/test_buttons.py"""
import datetime as dt
import email
import json
import os
import sys
import tempfile
import zipfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import fixreply  # noqa: E402
import replies  # noqa: E402
import shorttext  # noqa: E402
import summary  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


# ---------- short text: one real problem, nothing invented ----------
base = {"Clean_Name": "Bee Cafe", "Has_Tap_To_Call": "yes", "HTTPS": "yes", "Has_Form": "yes", "Copyright_Year": "2026.0",
        "LCP": "2.1\xa0s", "Checks_Note": ""}
check("nothing wrong found: no short email", shorttext.write(base, 2026) is None)
s, b = shorttext.write({**base, "Has_Tap_To_Call": "no"}, 2026)
check("no call button: said plainly, about 75 words, ends with the opt-out",
      "couldn't find a button to call you" in b and 55 <= len(b.split()) <= 100 and b.startswith("Hi Bee Cafe team,")
      and 'reply "no thanks"' in b and s == "Bee Cafe: quick question about your website" and "€" not in b)
check("slow only when Google measured 6 s or more", shorttext.write({**base, "LCP": "5.4 s"}, 2026) is None
      and "took about 8 seconds" in shorttext.write({**base, "LCP": "8.4 s"}, 2026)[1]
      and "took over 10 seconds" in shorttext.write({**base, "LCP": "23 s"}, 2026)[1])
check("homepage not readable: no claims about what is on the page",
      shorttext.write({**base, "Has_Tap_To_Call": "no", "Has_Form": "no", "Checks_Note": "homepage not readable (bot check)"}, 2026) is None)
check("old © year", "© 2019" in shorttext.write({**base, "Copyright_Year": "2019.0"}, 2026)[1])
home = tempfile.mkdtemp()
pd.DataFrame([{**base, "place_id": "p1", "Funnel": "email", "Status_Outreach": "pending", "Has_Form": "no"},
              {**base, "place_id": "p2", "Funnel": "email", "Status_Outreach": "pending"},
              {**base, "place_id": "p3", "Funnel": "email", "Status_Outreach": "sent", "Has_Form": "no"}]
             ).to_csv(home + "/LEADS_MASTER.csv", index=False)
n = shorttext.fill(home, dt.date(2026, 11, 12), log=lambda m: None)
m = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str, keep_default_na=False).set_index("place_id")
check("written only for pending email leads with a real problem", n == 1 and m.loc["p1", "Email_Body_S"]
      and not m.loc["p2", "Email_Body_S"] and not m.loc["p3", "Email_Body_S"])
check("second run writes nothing new", shorttext.fill(home, dt.date(2026, 11, 12), log=lambda m: None) == 0)

# ---------- button replies ----------
ref = replies.ref_of("pb")
yes = email.message_from_string(f"From: Owner <owner@gmail.com>\nTo: hello@frontage.agency\n"
                                f"Subject: YES - send the report (ref {ref})\nMessage-ID: <y1>\n\nYes, please send me the report.\n")
no = email.message_from_string(f"From: Owner <owner2@gmail.com>\nTo: hello@frontage.agency\n"
                               f"Subject: NO THANKS (ref {replies.ref_of('pc')})\nMessage-ID: <n1>\n\nNo thanks.\n")
refs = {ref: "info@bee.ie", replies.ref_of("pc"): "info@cee.ie"}
check("button YES from another address is matched by its code", replies.classify(yes, {"info@bee.ie"}, {}, {}, refs)
      == ("reply", "info@bee.ie"))
check("button NO THANKS is an opt-out for the business we wrote to", replies.classify(no, {"info@cee.ie"}, {}, {}, refs)
      == ("optout", "info@cee.ie"))
stranger = email.message_from_string("From: x@gmail.com\nSubject: YES - send the report (ref ZZZZZZ)\nMessage-ID: <s>\n\nhi\n")
check("a made-up code matches nothing", replies.classify(stranger, {"info@bee.ie"}, {}, {}, refs) == (None, None))

# ---------- a button YES is answered by the machine, with the report; a typed yes stays a draft ----------
h = tempfile.mkdtemp()
os.makedirs(h + "/latest"); os.makedirs(h + "/lighthouse_json")
with zipfile.ZipFile(h + "/latest/4A_reports.zip", "w") as z:
    z.writestr("b.pdf", b"%PDF b")
pd.DataFrame([{"place_id": "pb", "Template": "outbox_v2_short_btn", "Report_File": "b.pdf", "Attachment_Name": "Bee.pdf"},
              {"place_id": "pd", "Template": "outbox_v1_nopdf_btn", "Report_File": "b.pdf", "Attachment_Name": "Dee.pdf"}]
             ).to_csv(h + "/LEADS_MASTER.csv", index=False)
pd.DataFrame([{"sent_at": "x", "place_id": "pb", "email": "info@bee.ie", "name": "Bee"},
              {"sent_at": "x", "place_id": "pd", "email": "info@dee.ie", "name": "Dee"}]).to_csv(h + "/0_sent_log.csv", index=False)
pd.DataFrame([{"message_id": "<y1>", "kind": "reply", "matched_email": "info@bee.ie", "from": "owner@gmail.com",
               "subject": f"YES - send the report (ref {ref})", "first_lines": ""},
              {"message_id": "<y2>", "kind": "reply", "matched_email": "info@dee.ie", "from": "info@dee.ie",
               "subject": "Re: Dee website", "first_lines": "Yes please"}]).to_csv(h + "/0_replies.csv", index=False)
open(h + "/fix_guide.json", "w").write("{}")
for p in ("pb", "pd"):
    open(f"{h}/lighthouse_json/{p}.json", "w").write('{"lighthouseResult": {"audits": {"x": {}}}}')
sent, drafts, notes = [], [], []
fixreply.compose = lambda name, a, g: f"Hi {name} team,\nhere are the fixes"
fixreply.send_reply = lambda msg, to, pw, smtp=None: sent.append((to, msg))
fixreply.save_draft = lambda msg, pw, imap: drafts.append(msg) or True
fixreply.notify = lambda text, subj, pw, to, smtp=None: notes.append(subj)
c = fixreply.run(h, "pw", "me@x", today=dt.date(2026, 11, 13), log=lambda m: None, auto_send=True)
check("button YES: reply sent by the machine to the person who pressed it, with the PDF",
      c["sent_auto"] == 1 and sent[0][0] == "owner@gmail.com" and len(list(sent[0][1].iter_attachments())) == 1
      and "As promised" in sent[0][1].get_body().get_content())
check("typed yes: stays a draft for Anzhel", c["drafted"] == 1 and drafts[0]["To"] == "info@dee.ie"
      and len(list(drafts[0].iter_attachments())) == 1)
check("Anzhel is told about both", any("report sent" in x for x in notes) and any("Drafts" in x for x in notes))
c2 = fixreply.run(h, "pw", "me@x", today=dt.date(2026, 11, 13), log=lambda m: None, auto_send=True)
check("never answered twice", c2["yes_replies"] == 0 and len(sent) == 1)
check("all no-PDF versions count as 'report promised'; the old one doesn't",
      fixreply.promised_report("outbox_v2_short_btn") and fixreply.promised_report("outbox_v1_nopdf")
      and not fixreply.promised_report("outbox_v1") and not fixreply.promised_report(""))

# ---------- weekly summary per version ----------
h2 = tempfile.mkdtemp()
pd.DataFrame([{"place_id": "a", "Template": "outbox_v1"}, {"place_id": "l", "Template": "outbox_v1_nopdf"},
              {"place_id": "l2", "Template": "outbox_v1_nopdf_btn"}, {"place_id": "s", "Template": "outbox_v2_short_btn"}]
             ).to_csv(h2 + "/0_sent_leads.csv", index=False)
snt = pd.DataFrame([{"sent_at": "2026-11-09T09:00", "place_id": "a", "email": "a@a.ie"},
                    {"sent_at": "2026-11-11T09:00", "place_id": "l", "email": "l@l.ie"},
                    {"sent_at": "2026-11-13T09:00", "place_id": "l2", "email": "l2@l.ie"},
                    {"sent_at": "2026-11-13T09:01", "place_id": "s", "email": "s@s.ie"}])
rp = pd.DataFrame([{"kind": "reply", "matched_email": "s@s.ie"}, {"kind": "optout", "matched_email": "l2@l.ie"},
                   {"kind": "reply", "matched_email": "l@l.ie"}])
r = summary.split_test(h2, snt, rp)
check("summary counts long vs short from the day the short email began",
      r == {"since": "2026-11-13", "short email": {"sent": 1, "replies": 1, "no_thanks": 0},
            "long email": {"sent": 1, "replies": 0, "no_thanks": 1}})
print("\nALL BUTTON TESTS PASSED")
