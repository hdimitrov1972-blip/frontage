"""12 Nov 2026 fixes: own test presses ignored, one answer per business, short names.   python tests/test_reliability.py"""
import datetime as dt
import email
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import fixreply  # noqa: E402
import names  # noqa: E402
import replies  # noqa: E402

OWNER = "anzhel.test@gmail.com"


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


# ------------------------------------------------------------------ short names
for full, short in [("The Gateway Hotel • Dundalk", "The Gateway Hotel"), ("Jungle Berry Açaí - Bray", "Jungle Berry Açaí"),
                    ("Lifegym Personal Training | Online Personal Training", "Lifegym Personal Training"),
                    ("Butlers Chocolate Café (Bray)", "Butlers Chocolate Café"), ("Café – Main St", "Café"),
                    ("COCONUT & MOO MOO: Kitchen", "COCONUT & MOO MOO: Kitchen"), ("Salon-X", "Salon-X"),
                    ("Point A Hotel Dublin, The Liberties", "Point A Hotel Dublin, The Liberties"), ("A - B", "A - B"),
                    ("Eleven", "Eleven"), ("", "")]:
    check(f"short name: {full!r} -> {short!r}", names.short_name(full) == short)

home = tempfile.mkdtemp()
pd.DataFrame([
    {"Status_Outreach": "pending", "Email_Subject": "The Gateway Hotel • Dundalk website on a phone",
     "Email_Body": "Hi The Gateway Hotel • Dundalk team,\n\nThe Gateway Hotel • Dundalk scored 39.",
     "Email_Subject_S": "The Gateway Hotel • Dundalk: quick question about your website",
     "Email_Body_S": "Hi The Gateway Hotel • Dundalk team,\n\nI had a look"},
    {"Status_Outreach": "sent", "Email_Subject": "Old • Town website on a phone", "Email_Body": "Hi Old • Town team,",
     "Email_Subject_S": "", "Email_Body_S": ""},
    {"Status_Outreach": "pending", "Email_Subject": "Eleven website on a phone", "Email_Body": "Hi Eleven team,",
     "Email_Subject_S": "", "Email_Body_S": ""},
]).to_csv(home + "/LEADS_MASTER.csv", index=False)
check("polish changes the 2 waiting Gateway emails only", names.polish(home) == 2)
m = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str, keep_default_na=False)
check("long email: subject and body shortened", m.at[0, "Email_Subject"] == "The Gateway Hotel website on a phone"
      and "•" not in m.at[0, "Email_Body"] and m.at[0, "Email_Body"].startswith("Hi The Gateway Hotel team,"))
check("short email shortened too", m.at[0, "Email_Subject_S"].startswith("The Gateway Hotel: quick question"))
check("already-sent rows untouched", m.at[1, "Email_Body"] == "Hi Old • Town team,")
check("second polish changes nothing", names.polish(home) == 0)


# ------------------------------------------------------------------ own test presses are not a business's reply
def mail(frm, subject, body, mid):
    return email.message_from_string(f"From: {frm}\nTo: hello@frontage.agency\nSubject: {subject}\n"
                                     f"Message-ID: <{mid}>\nDate: Thu, 12 Nov 2026 12:25:00 +0000\n\n{body}\n")


ref = replies.ref_of("ChIJ_gateway")
sent = {"reservations@gatewayhotel.ie"}
for subj, body in [(f"YES - send the report (ref {ref})", "Yes, please send me the report."),
                   (f"NO THANKS (ref {ref})", "No thanks.")]:
    kind, _ = replies.classify(mail(f"Anzhel <{OWNER}>", subj, body, "t"), sent, {}, None,
                               {ref: "reservations@gatewayhotel.ie"}, ignore={OWNER})
    check(f"own press '{subj[:9]}' ignored", kind is None)
kind, hit = replies.classify(mail("Front desk <frontdesk.gateway@gmail.com>", f"YES - send the report (ref {ref})",
                                  "Yes", "b"), sent, {}, None, {ref: "reservations@gatewayhotel.ie"}, ignore={OWNER})
check("a business's own button press from another address still counts", kind == "reply"
      and hit == "reservations@gatewayhotel.ie")

home = tempfile.mkdtemp()
pd.DataFrame([{"sent_at": "2026-11-12T15:20:00", "place_id": "ChIJ_gateway", "email": "reservations@gatewayhotel.ie",
               "name": "The Gateway Hotel • Dundalk", "mailbox": "hello@frontage.agency"}]).to_csv(
    home + "/0_sent_log.csv", index=False)
pd.DataFrame([{"seen_at": "2026-11-12", "received": "2026-11-12", "mailbox": "hello@frontage.agency",
               "message_id": "<old-test>", "kind": "optout", "from": OWNER,
               "matched_email": "reservations@gatewayhotel.ie", "subject": f"NO THANKS (ref {ref})",
               "first_lines": "No thanks."}]).to_csv(home + "/0_replies.csv", index=False)
open(home + "/0_do_not_contact.csv", "w").write("email_or_domain\n")
boxes = {"hello@frontage.agency": [mail(OWNER, f"NO THANKS (ref {ref})", "No thanks.", "n2"),
                                   mail(OWNER, f"YES - send the report (ref {ref})", "Yes", "y2")]}
c = replies.run(home, {"hello@frontage.agency": "pw"}, today=dt.date(2026, 11, 12),
                fetch=lambda a, p, s: iter(boxes.get(a, [])), log=lambda m: None, ignore={OWNER})
dnc = open(home + "/0_do_not_contact.csv").read()
check("own presses not recorded", c["reply"] == 0 and c["optout"] == 0)
check("an older own 'no thanks' row does not put the business on do-not-contact",
      "gatewayhotel" not in dnc and c["added_to_do_not_contact"] == 0)


# ------------------------------------------------------------------ one answer per business
home = tempfile.mkdtemp()
open(home + "/fix_guide.json", "w").write("{}")
pd.DataFrame([{"sent_at": "2026-11-12T15:20:00", "place_id": "ChIJ_gateway", "email": "reservations@gatewayhotel.ie",
               "name": "The Gateway Hotel • Dundalk", "mailbox": "hello@frontage.agency"}]).to_csv(
    home + "/0_sent_log.csv", index=False)
rows = [{"seen_at": "2026-11-12", "received": "2026-11-12", "mailbox": "hello@frontage.agency", "message_id": f"<y{i}>",
         "kind": "reply", "from": "reservations@gatewayhotel.ie", "matched_email": "reservations@gatewayhotel.ie",
         "subject": f"YES - send the report (ref {ref})", "first_lines": "Yes, please send me the report."}
        for i in range(3)]
rows.append(dict(rows[0], message_id="<own>", **{"from": OWNER}))
pd.DataFrame(rows).to_csv(home + "/0_replies.csv", index=False)
SENT, NOTES = [], []
fixreply.load_audit = lambda h, pid: {"ok": 1}
fixreply.compose = lambda name, audits, guide: f"Hi {name} team,\n\nThree fixes."
fixreply.report_for_no_pdf_email = lambda h, pid: None
fixreply.send_reply = lambda msg, to, pw, smtp=None: SENT.append((to, msg))
fixreply.notify = lambda text, subject, pw, to, smtp=None: NOTES.append(subject)
c = fixreply.run(home, "pw", OWNER, today=dt.date(2026, 11, 12), log=lambda m: None, auto_send=True)
check("3 presses by the same business -> 1 answer", len(SENT) == 1 and c["sent_auto"] == 1)
check("own test press never answered", all(to != OWNER for to, _ in SENT))
check("greeting uses the short name", "Hi The Gateway Hotel team," in SENT[0][1].get_content()
      and "•" not in NOTES[0])
log = pd.read_csv(home + "/0_fix_replies.csv", dtype=str)
check("extra presses logged as already answered", sorted(log["status"]) == ["already_answered", "already_answered", "sent"])
c = fixreply.run(home, "pw", OWNER, today=dt.date(2026, 11, 13), log=lambda m: None, auto_send=True)
check("next run sends nothing more", len(SENT) == 1)

print("\nALL RELIABILITY TESTS PASSED")
